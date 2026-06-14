from __future__ import annotations

import json
import os
import re
import shutil
import tempfile as tempfile_mod
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pypdf import PdfReader


# ── helpers ───────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def job_debug_log(root: Path, job_id: str, message: str) -> None:
    """Append a timestamped line to a job-specific debug log."""
    debug_dir = root / "logs/debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    path = debug_dir / f"{job_id}.log"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"
    with path.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")


def slugify(value: str, fallback: str = "paper") -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or fallback


def unique_id(existing_ids: set[str], base_id: str) -> str:
    if base_id not in existing_ids:
        return base_id
    for idx in range(2, 1000):
        candidate = f"{base_id}_{idx}"
        if candidate not in existing_ids:
            return candidate
    raise ValueError(f"could not create unique paper id for {base_id}")


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for idx in range(2, 1000):
        candidate = path.with_name(f"{stem}_{idx}{suffix}")
        if not candidate.exists():
            return candidate
    raise ValueError(f"could not create unique path for {path}")


# ── directory scaffolding ─────────────────────────────────────────────

REQUIRED_DIRS = [
    "papers",
    "originals/papers",
    "metadata",
    "logs",
    "logs/chat_sessions",
    "logs/jobs",
    "logs/debug",
]


def ensure_kb(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for rel in REQUIRED_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)
    _ensure_text(root / "AGENT.md", AGENT_MD)
    _ensure_text(root / "logs/ingest_log.md", "# Ingest Log\n")
    _ensure_text(root / "logs/update_log.md", "# Update Log\n")


AGENT_MD = """\
# Agent Guide

One YAML file per paper under `papers/`.  Source PDFs live in `originals/papers/`.

## Read path

1. List papers: scan `papers/` directory.
2. Read one paper: open `papers/<paper_id>.yaml`.
3. Evidence check only: open `originals/papers/<paper>.pdf`.

## Write rules

- Create / update / delete **only** `papers/<paper_id>.yaml`.
- Never write to `originals/papers/` except during upload.
- Log significant changes to `logs/update_log.md`.
"""


def _ensure_text(path: Path, default: str) -> None:
    if not path.exists():
        path.write_text(default, encoding="utf-8")


def _ensure_yaml(path: Path, default: dict[str, Any]) -> None:
    if not path.exists():
        path.write_text(yaml.safe_dump(default, sort_keys=False, allow_unicode=True), encoding="utf-8")


# ── paper CRUD ────────────────────────────────────────────────────────

def papers_dir(root: Path) -> Path:
    ensure_kb(root)
    return root / "papers"


def paper_path(root: Path, paper_id: str) -> Path:
    return papers_dir(root) / f"{paper_id}.yaml"


def list_papers(root: Path) -> list[dict[str, Any]]:
    """Return all papers sorted alphabetically by title."""
    ensure_kb(root)
    papers = []
    for path in sorted(papers_dir(root).glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if data.get("id"):
                papers.append(data)
        except yaml.YAMLError:
            continue
    papers.sort(key=lambda p: (p.get("title") or p.get("id") or "").lower())
    return papers


def load_paper(root: Path, paper_id: str) -> dict[str, Any]:
    path = paper_path(root, paper_id)
    if not path.exists():
        raise FileNotFoundError(f"Paper not found: {paper_id}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def save_paper(root: Path, paper: dict[str, Any]) -> None:
    paper_id = paper.get("id")
    if not paper_id:
        raise ValueError("Paper requires an id.")
    paper["updated_at"] = now_iso()
    content = yaml.safe_dump(paper, sort_keys=False, allow_unicode=True)
    path = paper_path(root, paper_id)
    # Atomic write via temp file
    tmp_fd, tmp_path = tempfile_mod.mkstemp(suffix=".yaml", prefix=".paper_", dir=str(path.parent))
    closed = False
    try:
        os.write(tmp_fd, content.encode("utf-8"))
        os.fsync(tmp_fd)
        os.close(tmp_fd)
        closed = True
        os.replace(tmp_path, str(path))
    except Exception:
        # Only close the fd if the try block didn't get a chance to.
        if not closed:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def delete_paper(root: Path, paper_id: str) -> dict[str, Any]:
    path = paper_path(root, paper_id)
    if not path.exists():
        raise FileNotFoundError(f"Paper not found: {paper_id}")
    paper = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    # Delete source PDF
    source = paper.get("source_pdf")
    deleted = []
    if source:
        pdf_path = (root / source).resolve()
        if pdf_path.exists() and root.resolve() in pdf_path.parents:
            pdf_path.unlink()
            deleted.append(source)
    # Delete paper yaml
    path.unlink()
    deleted.append(f"papers/{paper_id}.yaml")
    log(root, "update_log.md", f"Deleted paper `{paper_id}`. Removed: {', '.join(deleted)}.")
    return {"paper_id": paper_id, "deleted_files": deleted}


# ── PDF ingestion ─────────────────────────────────────────────────────

def extract_pdf_info(path: Path) -> tuple[str, int, str]:
    reader = PdfReader(str(path))
    pages = len(reader.pages)
    metadata_title = ""
    if reader.metadata:
        metadata_title = " ".join((reader.metadata.title or "").split())
    text_parts = []
    for page in reader.pages[:2]:
        text_parts.append(page.extract_text() or "")
    text = "\n".join(text_parts)
    title = metadata_title if metadata_title and len(metadata_title) > 4 else _infer_title(text, path.stem)
    return title, pages, text


def extract_pdf_text(path: Path, max_pages: int = 8) -> str:
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages[:max_pages]:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _infer_title(text: str, fallback: str) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    skip = re.compile(r"^(published|proceedings|arxiv|abstract|copyright)", re.I)
    for i, line in enumerate(lines[:30]):
        if skip.search(line):
            continue
        if re.search(r"[A-Za-z]", line):
            title = line
            if i + 1 < len(lines) and len(lines[i + 1]) < 110:
                title += " " + lines[i + 1]
            return title
    return fallback.replace("_", " ").title()


def _known_tags(root: Path) -> list[str]:
    """Collect all unique tags from existing papers."""
    tags: set[str] = set()
    for paper in list_papers(root):
        for t in paper.get("tags", []):
            tags.add(t)
    return sorted(tags)


def _infer_tags(root: Path, title: str, text: str) -> list[str]:
    """Infer initial tags from text using existing vocabulary."""
    haystack = f"{title}\n{text}".lower()
    tags: list[str] = []
    # Check against known tags from existing papers
    for tag in _known_tags(root):
        tag_phrase = tag.replace("_", " ")
        if tag_phrase in haystack or tag in haystack:
            tags.append(tag)
    # Always add time_series if temporal content mentioned
    if ("time series" in haystack or "temporal" in haystack) and "time_series" not in tags:
        tags.append("time_series")
    # Fallback
    return sorted(set(tags)) or ["paper"]


def _compact_abstract(text: str) -> str:
    normalized = " ".join(text.split())
    match = re.search(r"\babstract\b(.{80,700})", normalized, re.I)
    if match:
        return match.group(1).strip(" :-")
    return normalized[:500].strip()


def _split_sentences(text: str) -> list[str]:
    normalized = " ".join(text.split())
    chunks = re.split(r"(?<=[.!?])\s+", normalized)
    return [chunk.strip() for chunk in chunks if 60 <= len(chunk.strip()) <= 360]


def _first_sentence(sentences: list[str], needles: list[str]) -> str:
    for sentence in sentences:
        lower = sentence.lower()
        if any(needle in lower for needle in needles):
            return sentence
    return ""


def ingest_pdf(root: Path, temp_pdf: Path, original_name: str) -> dict[str, Any]:
    """Copy PDF, create paper YAML entry, return paper dict."""
    ensure_kb(root)

    safe_name = f"{slugify(Path(original_name).stem)}.pdf"
    dest = unique_path(root / "originals/papers" / safe_name)
    shutil.move(str(temp_pdf), dest)

    title, pages, text = extract_pdf_info(dest)
    existing = {p.get("id") for p in list_papers(root)}
    paper_id = unique_id(existing, slugify(title)[:80].strip("_"))

    tags = _infer_tags(root, title, text)
    sentences = _split_sentences(text)
    abstract = _compact_abstract(text)
    problem = _first_sentence(sentences, ["problem", "challenge", "difficult", "lack", "however"]) or abstract
    core = _first_sentence(sentences, ["introduce", "propose", "present", "develop", "framework", "method"]) or abstract
    method_notes = [s for s in sentences if any(w in s.lower() for w in ["agent", "tool", "retrieval", "benchmark", "model", "framework", "rule"])][:5]

    paper = {
        "id": paper_id,
        "title": title,
        "authors": [],
        "year": None,
        "venue": "",
        "doi": "",
        "arxiv_id": "",
        "source_pdf": str(dest.relative_to(root)),
        "pages": pages,
        "tags": tags,
        "status": "summarized",
        "confidence": "medium",
        "reading_status": "unread",
        "priority": "normal",
        "needs_review": True,
        "abstract": abstract,
        "one_sentence": abstract or "First-pass summary from PDF text.",
        "problem": problem,
        "contributions": [],
        "method": method_notes,
        "experiments": [],
        "limitations": [],
        "notes": _render_initial_notes(paper_id, title, tags, abstract, dest.relative_to(root), pages),
        "review_notes": [],
        "agent_reviews": [],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }

    save_paper(root, paper)
    log(root, "ingest_log.md", f"Added `{paper_id}` from `{original_name}`.")
    log(root, "update_log.md", f"Created paper entry for `{paper_id}`.")
    return paper


def _render_initial_notes(paper_id: str, title: str, tags: list[str], abstract: str, pdf_rel: Path, pages: int) -> str:
    return f"""# Reading Notes

*Use this space for your own notes while reading the paper. The structured summary is available in the Summary section.*

## Key takeaways

- 

## Questions

- 

## Connections to other papers

- 
"""


# ── enrichment ────────────────────────────────────────────────────────

def _is_auto_text(value: Any) -> bool:
    """Check if a text value looks auto-generated (regex filler)."""
    if not value:
        return True
    s = str(value).strip()
    if not s:
        return True
    markers = ("TODO", "First-pass", "Not extracted", "No abstract",
               "Review source PDF", "Verify in PDF", "review source")
    low = s.lower()
    return any(m.lower() in low for m in markers)


def _is_auto_list(value: Any) -> bool:
    """Check if a list field looks auto-generated."""
    if not value or len(value) == 0:
        return True
    joined = " ".join(str(v) for v in value).lower()
    markers = ("first-pass", "review source", "verify", "todo")
    return any(m in joined for m in markers)


def _text_is_english(text: str) -> bool:
    """Check if text is primarily English (not Chinese)."""
    if not text:
        return False
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff')
    return cjk < len(text) * 0.05  # < 5% CJK → English


def enrich_paper(root: Path, paper_id: str, max_pages: int = 8, job_id: str | None = None) -> dict[str, Any]:
    """Extract text from PDF and fill missing/auto-generated fields only."""
    def _dbg(msg: str) -> None:
        if job_id:
            job_debug_log(root, job_id, msg)

    paper = load_paper(root, paper_id)
    source = paper.get("source_pdf")
    if not source:
        raise ValueError(f"Paper `{paper_id}` has no source PDF.")

    pdf_path = root / source
    if not pdf_path.exists():
        raise ValueError(f"Source PDF missing: {source}")

    _dbg(f"enrich_paper: reading '{source}' (max {max_pages} pages)")
    text = extract_pdf_text(pdf_path, max_pages=max_pages)
    sentences = _split_sentences(text)
    abstract = _compact_abstract(text)
    _dbg(f"enrich_paper: extracted {len(text)} chars, {len(sentences)} sentences, abstract={len(abstract)} chars")

    # ── only fill missing/auto-generated fields ──
    filled = []
    skipped = []
    if _is_auto_text(paper.get("abstract")):
        paper["abstract"] = abstract or paper.get("abstract", "")
        filled.append("abstract")
    else:
        skipped.append("abstract")
    if _is_auto_text(paper.get("one_sentence")):
        paper["one_sentence"] = abstract or paper.get("one_sentence", "")
        filled.append("one_sentence")
    else:
        skipped.append("one_sentence")
    if _is_auto_text(paper.get("problem")):
        found = _first_sentence(sentences, ["problem", "challenge", "difficult", "lack", "however"])
        if found:
            paper["problem"] = found
            filled.append("problem")
        else:
            skipped.append("problem (no match)")
    else:
        skipped.append("problem")
    if _is_auto_list(paper.get("method")):
        method = [s for s in sentences if any(w in s.lower() for w in ["agent", "tool", "retrieval", "benchmark", "model", "framework", "rule"])][:6]
        if method:
            paper["method"] = method
            filled.append(f"method ({len(method)} items)")
        else:
            skipped.append("method (no match)")
    else:
        skipped.append("method")
    if _is_auto_list(paper.get("experiments")):
        exp = [s for s in sentences if any(w in s.lower() for w in ["dataset", "benchmark", "metric", "baseline", "experiment", "evaluation"])][:5]
        if exp:
            paper["experiments"] = exp
            filled.append(f"experiments ({len(exp)} items)")
        else:
            skipped.append("experiments (no match)")
    else:
        skipped.append("experiments")
    if _is_auto_list(paper.get("limitations")):
        lim = [s for s in sentences if any(w in s.lower() for w in ["limitation", "future work", "fail", "challenge", "however"])][:4]
        if lim:
            paper["limitations"] = lim
            filled.append(f"limitations ({len(lim)} items)")
        else:
            skipped.append("limitations (no match)")
    else:
        skipped.append("limitations")

    _dbg(f"enrich_paper: filled=[{', '.join(filled) or 'none'}] skipped=[{', '.join(skipped)}]")

    # ── status bump, but never overwrite notes ──
    paper["status"] = "profiled"
    paper["confidence"] = "medium"

    # ── only generate notes if current are auto-generated or empty ──
    current_notes = paper.get("notes", "")
    is_old_template = current_notes.startswith(f"# {paper.get('title', '')}")
    if _is_auto_text(current_notes) or is_old_template:
        paper["notes"] = """# Reading Notes

*Use this space for your own notes while reading the paper. The structured summary is available in the Summary section.*

## Key takeaways

- 

## Questions

- 

## Connections to other papers

- 
"""
        _dbg("enrich_paper: notes replaced (was auto-generated)")
    else:
        _dbg("enrich_paper: notes preserved (user content)")

    save_paper(root, paper)
    log(root, "update_log.md", f"Enriched paper `{paper_id}` from source PDF.")
    _dbg("enrich_paper: saved")
    return paper


# ── jobs ──────────────────────────────────────────────────────────────

def job_path(root: Path, job_id: str) -> Path:
    return root / "logs/jobs" / f"{job_id}.json"


def create_job(root: Path, paper_id: str, title: str) -> dict[str, Any]:
    created = now_iso()
    job = {
        "id": uuid.uuid4().hex,
        "paper_id": paper_id,
        "title": title,
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "created_at": created,
        "updated_at": created,
        "started_at": None,
        "completed_at": None,
        "events": [{"time": created, "message": "Queued."}],
    }
    save_job(root, job)
    return job


def save_job(root: Path, job: dict[str, Any]) -> None:
    job["updated_at"] = now_iso()
    path = job_path(root, job["id"])
    path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")


def load_job(root: Path, job_id: str) -> dict[str, Any]:
    path = job_path(root, job_id)
    if not path.exists():
        raise FileNotFoundError(f"Job not found: {job_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_jobs(root: Path) -> list[dict[str, Any]]:
    jobs_dir = root / "logs/jobs"
    if not jobs_dir.exists():
        return []
    jobs = []
    for path in sorted(jobs_dir.glob("*.json")):
        try:
            jobs.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    jobs.sort(key=lambda j: j.get("updated_at") or "", reverse=True)
    return jobs


def update_job(root: Path, job_id: str, *, status: str | None = None,
               stage: str | None = None, progress: int | None = None,
               message: str | None = None) -> dict[str, Any]:
    job = load_job(root, job_id)
    if status is not None:
        if status == "running" and not job.get("started_at"):
            job["started_at"] = now_iso()
        if status in {"completed", "failed", "cancelled"} and not job.get("completed_at"):
            job["completed_at"] = now_iso()
        job["status"] = status
    if stage is not None:
        job["stage"] = stage
    if progress is not None:
        job["progress"] = progress
    if message:
        job.setdefault("events", []).append({"time": now_iso(), "message": message})
    save_job(root, job)
    return job


def cancel_job(root: Path, job_id: str) -> dict[str, Any]:
    job = load_job(root, job_id)
    if job.get("status") in {"completed", "failed", "cancelled"}:
        return job
    job["status"] = "cancelled"
    job["stage"] = "cancelled"
    job["completed_at"] = now_iso()
    job.setdefault("events", []).append({"time": now_iso(), "message": "Cancelled."})
    save_job(root, job)
    return job


def delete_job(root: Path, job_id: str) -> None:
    path = job_path(root, job_id)
    if path.exists():
        path.unlink()


def run_enrichment_job(root: Path, paper_id: str, job_id: str, config: dict[str, Any] | None = None) -> None:
    """Background enrichment job: regex extraction + optional agent review."""
    job_debug_log(root, job_id, f"=== Job started: paper_id={paper_id} ===")
    try:
        job = load_job(root, job_id)
        if job.get("status") == "cancelled":
            job_debug_log(root, job_id, "Job was cancelled before start, exiting")
            return

        paper = load_paper(root, paper_id)
        job_debug_log(root, job_id, f"Paper: '{paper.get('title')}', source={paper.get('source_pdf')}, pages={paper.get('pages')}")

        update_job(root, job_id, status="running", stage="extracting",
                   progress=15, message="Extracting text from PDF.")
        job_debug_log(root, job_id, "Stage: extracting")
        job = load_job(root, job_id)
        if job.get("status") == "cancelled":
            job_debug_log(root, job_id, "Cancelled during extracting")
            return

        update_job(root, job_id, stage="enriching",
                   progress=35, message="Running keyword extraction.")
        job_debug_log(root, job_id, "Stage: enriching (regex)")
        job = load_job(root, job_id)
        if job.get("status") == "cancelled":
            job_debug_log(root, job_id, "Cancelled during enriching")
            return

        enrich_paper(root, paper_id, job_id=job_id)

        # ── Agent review (if API key configured) ──
        config = config or load_app_config(root)
        if config.get("claude_api_key"):
            update_job(root, job_id, stage="agent_review",
                       progress=60, message="AI agent reviewing metadata.")
            job_debug_log(root, job_id, f"Stage: agent_review (model={config.get('claude_model', 'sonnet')})")
            job = load_job(root, job_id)
            if job.get("status") == "cancelled":
                job_debug_log(root, job_id, "Cancelled before agent review")
                return

            try:
                from .agent_chat import run_agent_paper_review_sync
                t0 = datetime.now(timezone.utc)
                result = run_agent_paper_review_sync(root, paper_id, job_id, config)
                elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
                job_debug_log(root, job_id, f"Agent review completed in {elapsed:.1f}s, status={result.get('status')}")
                if result.get("status") == "ok":
                    notes_count = len(result.get("notes", []))
                    job_debug_log(root, job_id, f"Agent corrections ({notes_count}):")
                    for note in result.get("notes", []):
                        job_debug_log(root, job_id, f"  - {note}")
                    update_job(root, job_id, stage="agent_review", progress=90,
                               message=f"Agent reviewed: {notes_count} corrections.")
                else:
                    reason = result.get('reason', result.get('detail', 'unknown'))
                    job_debug_log(root, job_id, f"Agent review skipped/failed: {reason}")
                    update_job(root, job_id, stage="agent_review", progress=90,
                               message=f"Agent review skipped: {reason}")
            except Exception as exc:
                job_debug_log(root, job_id, f"Agent review exception: {exc}")
                import traceback as _tb
                job_debug_log(root, job_id, _tb.format_exc())
                update_job(root, job_id, stage="agent_review", progress=90,
                           message=f"Agent review failed: {exc}")
        else:
            job_debug_log(root, job_id, "Agent review skipped: no API key")
            update_job(root, job_id, stage="agent_review", progress=85,
                       message="Agent review skipped: no API key configured.")

        # ── Translation (after enrichment, if paper is in English) ──
        try:
            from .translate import translate_paper_summary, translate_paper_summary_llm
            paper = load_paper(root, paper_id)
            if not paper.get("translations") and _text_is_english(paper.get("abstract", "")):
                engine = (config.get("translation_engine") or "local").lower()
                if engine == "llm" and not (config.get("claude_api_key") or "").strip():
                    job_debug_log(root, job_id,
                                  "Translation engine='llm' but no API key configured; "
                                  "falling back to local Argos.")
                    engine = "local"

                engine_label = "LLM (Claude)" if engine == "llm" else "Argos (offline)"
                update_job(root, job_id, stage="translating", progress=92,
                           message=f"Translating summary to Chinese ({engine_label}).")
                job_debug_log(root, job_id, f"Stage: translating (engine={engine}, model={config.get('claude_model', 'sonnet') if engine == 'llm' else 'n/a'})")
                job = load_job(root, job_id)
                if job.get("status") == "cancelled":
                    return

                if engine == "llm":
                    translations = translate_paper_summary_llm(paper, config)
                    # If the LLM returned nothing usable (parse failure, no
                    # fields translated), fall back to local so the user
                    # still gets *something* rather than an empty card.
                    if not translations:
                        job_debug_log(root, job_id,
                                      "LLM translation returned no fields; "
                                      "falling back to local Argos.")
                        translations = translate_paper_summary(paper)
                else:
                    translations = translate_paper_summary(paper)

                paper["translations"] = translations
                save_paper(root, paper)
                field_count = len(translations)
                job_debug_log(root, job_id, f"Translation complete: {field_count} fields")
                update_job(root, job_id, stage="translating", progress=96,
                           message=f"Translated {field_count} summary fields via {engine_label}.")
            else:
                job_debug_log(root, job_id, "Translation skipped (already translated or non-English)")
        except Exception as exc:
            job_debug_log(root, job_id, f"Translation failed (non-fatal): {exc}")

        update_job(root, job_id, status="completed", stage="completed",
                   progress=100, message="Enrichment completed.")
        log(root, "update_log.md", f"Background enrichment completed for `{paper_id}`.")
        job_debug_log(root, job_id, "=== Job completed successfully ===")
    except Exception as exc:
        job_debug_log(root, job_id, f"=== Job FAILED: {exc} ===")
        import traceback as _tb
        job_debug_log(root, job_id, _tb.format_exc())
        update_job(root, job_id, status="failed", stage="failed",
                   progress=100, message=str(exc))


# ── sessions ──────────────────────────────────────────────────────────

def session_path(root: Path, session_id: str) -> Path:
    safe = slugify(session_id, "session")
    return root / "logs/chat_sessions" / f"{safe}.json"


def create_session(root: Path, title: str | None = None) -> dict[str, Any]:
    created = now_iso()
    session = {
        "id": uuid.uuid4().hex,
        "title": title or "New chat",
        "created_at": created,
        "updated_at": created,
        "messages": [],
    }
    save_session(root, session)
    return session


def load_session(root: Path, session_id: str | None) -> dict[str, Any]:
    """Load a session by id, or create a new one if id is missing.

    If an id is provided but no such session file exists, return an empty
    stub *without* creating a file on disk — silently materialising a
    session for an unknown id would fill logs/chat_sessions/ with garbage.
    Callers that want a persisted session for an unknown id should call
    create_session() explicitly.
    """
    if not session_id:
        return create_session(root)
    path = session_path(root, session_id)
    if not path.exists():
        return {"id": session_id, "title": "Unknown", "messages": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_session(root: Path, session: dict[str, Any]) -> None:
    session["updated_at"] = now_iso()
    session_path(root, session["id"]).write_text(
        json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")


def list_sessions(root: Path) -> list[dict[str, Any]]:
    sessions_dir = root / "logs/chat_sessions"
    if not sessions_dir.exists():
        return []
    sessions = []
    for path in sorted(sessions_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        sessions.append({
            "id": data.get("id"),
            "title": data.get("title") or "New chat",
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "message_count": len(data.get("messages") or []),
        })
    sessions.sort(key=lambda s: s.get("updated_at") or "", reverse=True)
    return sessions


def append_session_message(root: Path, session: dict[str, Any],
                           role: str, content: str,
                           contexts: list[dict[str, str]] | None = None,
                           agent_steps: list[dict[str, Any]] | None = None,
                           segments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"role": role, "content": content, "created_at": now_iso()}
    if contexts:
        message["contexts"] = [{"path": c["path"]} for c in contexts]
    if agent_steps:
        message["agent_steps"] = agent_steps
    if segments:
        message["segments"] = segments
    session.setdefault("messages", []).append(message)
    if session.get("title") == "New chat" and role == "user":
        compact = " ".join(content.split())
        session["title"] = compact[:48] + ("..." if len(compact) > 48 else "")
    save_session(root, session)
    return message


# ── config ────────────────────────────────────────────────────────────

def load_app_config(root: Path) -> dict[str, Any]:
    ensure_kb(root)
    path = root / "metadata/app_config.yaml"
    if not path.exists():
        default = {
            "claude_api_key": "",
            "claude_endpoint": "",
            "claude_model": "sonnet",
            "max_concurrency": 4,
            "translation_engine": "llm",
        }
        path.write_text(yaml.safe_dump(default, sort_keys=False, allow_unicode=True))
        return default
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        "claude_api_key": data.get("claude_api_key") or "",
        "claude_endpoint": data.get("claude_endpoint") or "",
        "claude_model": data.get("claude_model") or "sonnet",
        "max_concurrency": data.get("max_concurrency", 4),
        "translation_engine": data.get("translation_engine") or "llm",
    }


def save_app_config(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    ensure_kb(root)
    current = load_app_config(root)
    for key in ("claude_api_key", "claude_endpoint", "claude_model",
                "max_concurrency", "translation_engine"):
        if key in config and config[key] is not None:
            current[key] = config[key]
    (root / "metadata/app_config.yaml").write_text(
        yaml.safe_dump(current, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return current


# ── context retrieval (for agent chat) ────────────────────────────────

def retrieve_context(root: Path, query: str, limit: int = 8) -> list[dict[str, str]]:
    """Search papers for relevant context."""
    papers = list_papers(root)
    terms = [t for t in re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]+", query.lower()) if len(t) > 1]
    scored = []
    for paper in papers:
        text = yaml.safe_dump(paper, sort_keys=False, allow_unicode=True)
        lower = text.lower()
        score = sum(lower.count(term) for term in terms)
        if score > 0:
            scored.append((score, paper))
    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for _, paper in scored[:limit]:
        results.append({
            "path": f"papers/{paper['id']}.yaml",
            "content": yaml.safe_dump(paper, sort_keys=False, allow_unicode=True)[:5000],
        })
    return results


# ── duplicate detection ───────────────────────────────────────────────

def _normalize_title(title: str) -> set[str]:
    """Normalize title to a set of lowercase alphanumeric words for comparison."""
    return set(re.findall(r"[a-z0-9]+", title.lower()))


def _jaccard(set_a: set[str], set_b: set[str]) -> float:
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def find_duplicates(root: Path) -> list[dict[str, Any]]:
    """Detect potential duplicate papers using deterministic rules.

    Rules (in priority order):
    1. Same DOI (non-empty) → confirmed duplicate
    2. Same arXiv ID (non-empty) → confirmed duplicate
    3. Title Jaccard similarity ≥ 0.65 → potential duplicate

    Returns a list of duplicate groups, each containing the papers in the group
    and a 'keep_id' pointing to the recommended paper to retain (most recently updated).
    """
    papers = list_papers(root)
    n = len(papers)
    if n < 2:
        return []

    # Build index maps
    doi_map: dict[str, list[int]] = {}
    arxiv_map: dict[str, list[int]] = {}
    for i, p in enumerate(papers):
        doi = (p.get("doi") or "").strip().lower()
        arxiv = (p.get("arxiv_id") or "").strip().lower()
        if doi:
            doi_map.setdefault(doi, []).append(i)
        if arxiv:
            arxiv_map.setdefault(arxiv, []).append(i)

    # Union-Find for clustering
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # Rule 1 & 2: exact identifier matches
    for idx_map in (doi_map, arxiv_map):
        for indices in idx_map.values():
            if len(indices) > 1:
                for j in range(1, len(indices)):
                    union(indices[0], indices[j])

    # Rule 3: title similarity
    title_words = [_normalize_title(p.get("title") or "") for p in papers]
    for i in range(n):
        for j in range(i + 1, n):
            if find(i) == find(j):
                continue
            sim = _jaccard(title_words[i], title_words[j])
            if sim >= 0.65:
                union(i, j)

    # Build groups
    groups_map: dict[int, list[int]] = {}
    for i in range(n):
        root_idx = find(i)
        groups_map.setdefault(root_idx, []).append(i)

    result: list[dict[str, Any]] = []
    for indices in groups_map.values():
        if len(indices) < 2:
            continue
        group_papers = [papers[i] for i in indices]
        # Find keep_id: most recently updated paper
        best = max(group_papers, key=lambda p: p.get("updated_at") or "")
        duplicate_count = len(group_papers) - 1
        result.append({
            "papers": group_papers,
            "keep_id": best["id"],
            "duplicate_count": duplicate_count,
        })

    # Sort by number of duplicates descending
    result.sort(key=lambda g: g["duplicate_count"], reverse=True)
    return result


def cleanup_duplicates(root: Path) -> dict[str, Any]:
    """Delete all duplicate papers, keeping only the newest in each group."""
    groups = find_duplicates(root)
    deleted_ids: list[str] = []
    for group in groups:
        keep_id = group["keep_id"]
        for paper in group["papers"]:
            if paper["id"] == keep_id:
                continue
            delete_paper(root, paper["id"])
            deleted_ids.append(paper["id"])
    return {
        "groups_processed": len(groups),
        "deleted_count": len(deleted_ids),
        "deleted_ids": deleted_ids,
    }


# ── stats ─────────────────────────────────────────────────────────────

def library_stats(root: Path) -> dict[str, Any]:
    papers = list_papers(root)
    tags = set()
    for p in papers:
        for t in p.get("tags", []):
            tags.add(t)
    # Note: duplicate counts live in /api/duplicates, called on demand.
    # They were intentionally removed from here because find_duplicates is
    # O(n^2) in title comparisons and was being recomputed on every
    # /api/papers call (page load). The frontend never read stats.duplicate_*.
    return {
        "papers": len(papers),
        "needs_review": sum(1 for p in papers if p.get("needs_review")),
        "profiled": sum(1 for p in papers if p.get("status") == "profiled"),
        "tags": len(tags),
    }


# ── logging ───────────────────────────────────────────────────────────

def log(root: Path, filename: str, message: str) -> None:
    ensure_kb(root)
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    path = root / "logs" / filename
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n- {today}: {message}\n")
