from __future__ import annotations

import concurrent.futures
import json
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .agent_chat import run_agent_answer_sync
from .librarian import (
    create_action,
    pdf_archive_path,
    import_action,
    load_action,
    merge_metadata,
    normalize_venues,
    run_librarian_job,
    search_fulltext,
)
from .git_sync import GitSyncError, git_sync_status, normalize_remote_url, sync_with_git
from .kb import (
    append_session_message,
    cancel_job,
    cleanup_duplicates,
    create_job,
    create_session,
    delete_job,
    delete_paper,
    delete_session,
    enrich_paper,
    ensure_kb,
    find_duplicates,
    ingest_pdf,
    library_stats,
    list_jobs,
    list_papers,
    list_paper_summaries,
    list_sessions,
    load_app_config,
    load_job,
    load_paper,
    load_session,
    mark_paper_viewed,
    log,
    now_iso,
    pause_job,
    resume_job,
    retry_job,
    run_enrichment_job,
    save_app_config,
    save_job,
    save_paper,
    save_session,
    update_job,
)
from .translate import translate_paper_summary, translate_paper_summary_llm

APP_CONFIG = Path(".kb_app_config.yaml")
DEFAULT_ROOT = Path(os.environ.get("KB_DEFAULT_ROOT", Path.home() / ".neunote")).expanduser().resolve()

_auto_sync_lock = threading.Lock()
_auto_sync_wake = threading.Event()
_auto_sync_stop = threading.Event()
_auto_sync_signature: tuple[Any, ...] | None = None
_auto_sync_next_due: float | None = None
_auto_sync_state: dict[str, Any] = {
    "running": False,
    "last_attempt_at": None,
    "last_success_at": None,
    "last_error": None,
    "next_sync_at": None,
}
_translation_preload_lock = threading.Lock()
_translation_preload_started = False

app = FastAPI(title="NeuNote")
app.add_middleware(
    CORSMiddleware,
    # NOTE: allow_origins=["*"] with allow_credentials=True is rejected by
    # browsers per the CORS spec (it implies sending cookies cross-origin
    # with no allow-list). The frontend never sends cookies anyway — all
    # auth is body-borne — so we drop credentials and keep a wide open
    # origin list for the localhost dev case.
    allow_origins=os.environ.get("KB_ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── startup: warm the local translation cache only when it is selected ──

def _preload_translation_model() -> None:
    """Download Argos en→zh model in background. Idempotent & best-effort.

    Argos model download is hundreds of MB and synchronous. Without this
    preload, the first /api/papers/{id}/translate request hangs for as
    long as it takes, which most clients will time out on. We try once at
    boot in a daemon thread; the real /translate handler still calls
    _ensure_model() so a failed preload is recovered on the next call.
    """
    import logging
    from .translate import _ensure_model
    try:
        _ensure_model()
    except Exception as exc:  # noqa: BLE001 — best effort, log and move on
        logging.getLogger("neunote.translate").warning(
            "Translation model preload failed (will retry on first use): %s", exc)


def _start_local_translation_preload(config: dict[str, Any]) -> None:
    """Avoid loading Argos (and monopolizing CPU) for LLM translation users."""
    global _translation_preload_started
    if str(config.get("translation_engine") or "llm").lower() != "local":
        return
    with _translation_preload_lock:
        if _translation_preload_started:
            return
        _translation_preload_started = True
    threading.Thread(target=_preload_translation_model, daemon=True).start()


def _configured_root() -> Path:
    root = DEFAULT_ROOT
    if APP_CONFIG.exists():
        import yaml
        data = yaml.safe_load(APP_CONFIG.read_text(encoding="utf-8")) or {}
        if data.get("root"):
            root = Path(data["root"]).expanduser().resolve()
    return root


def _reset_auto_sync_schedule() -> None:
    global _auto_sync_signature, _auto_sync_next_due
    with _auto_sync_lock:
        _auto_sync_signature = None
        _auto_sync_next_due = None
    _auto_sync_wake.set()


def _auto_sync_status(config: dict[str, Any]) -> dict[str, Any]:
    with _auto_sync_lock:
        state = dict(_auto_sync_state)
    state.update({
        "enabled": config.get("sync_mode") == "git" and bool(config.get("git_auto_sync")),
        "interval_minutes": int(config.get("git_sync_interval_minutes", 10)),
    })
    return state


def _auto_sync_loop() -> None:
    global _auto_sync_signature, _auto_sync_next_due
    while not _auto_sync_stop.is_set():
        wait_seconds = 5.0
        try:
            root = _configured_root()
            config = load_app_config(root)
            enabled = config.get("sync_mode") == "git" and bool(config.get("git_auto_sync"))
            interval_minutes = max(1, min(1440, int(config.get("git_sync_interval_minutes", 10))))
            signature = (
                str(root), enabled, interval_minutes, config.get("git_remote"),
                config.get("git_remote_url"), config.get("git_branch"),
                config.get("git_sync_pdfs"), config.get("git_sync_chats"),
            )
            now_monotonic = time.monotonic()
            with _auto_sync_lock:
                if signature != _auto_sync_signature:
                    _auto_sync_signature = signature
                    _auto_sync_next_due = now_monotonic + interval_minutes * 60 if enabled else None
                    _auto_sync_state.update({
                        "running": False,
                        "last_error": None,
                        "next_sync_at": (
                            datetime.now(timezone.utc) + timedelta(minutes=interval_minutes)
                        ).isoformat() if enabled else None,
                    })
                due = enabled and _auto_sync_next_due is not None and now_monotonic >= _auto_sync_next_due

            if due:
                attempted_at = datetime.now(timezone.utc).isoformat()
                with _auto_sync_lock:
                    _auto_sync_state.update({"running": True, "last_attempt_at": attempted_at})
                try:
                    sync_with_git(root, config)
                    with _auto_sync_lock:
                        _auto_sync_state.update({"last_success_at": datetime.now(timezone.utc).isoformat(),
                                                 "last_error": None})
                except Exception as exc:  # noqa: BLE001 - scheduler must remain alive
                    with _auto_sync_lock:
                        _auto_sync_state["last_error"] = str(exc)
                finally:
                    with _auto_sync_lock:
                        _auto_sync_state["running"] = False
                        _auto_sync_next_due = time.monotonic() + interval_minutes * 60
                        _auto_sync_state["next_sync_at"] = (
                            datetime.now(timezone.utc) + timedelta(minutes=interval_minutes)
                        ).isoformat()

            with _auto_sync_lock:
                if enabled and _auto_sync_next_due is not None:
                    wait_seconds = max(0.25, min(5.0, _auto_sync_next_due - time.monotonic()))
        except Exception as exc:  # noqa: BLE001 - keep scheduler alive on config errors
            with _auto_sync_lock:
                _auto_sync_state.update({"running": False, "last_error": str(exc), "next_sync_at": None})
        _auto_sync_wake.wait(wait_seconds)
        _auto_sync_wake.clear()


@app.on_event("startup")
def _on_startup() -> None:
    _start_local_translation_preload(load_app_config(_configured_root()))
    _auto_sync_stop.clear()
    threading.Thread(target=_auto_sync_loop, daemon=True, name="neunote-git-auto-sync").start()


@app.on_event("shutdown")
def _on_shutdown() -> None:
    _auto_sync_stop.set()
    _auto_sync_wake.set()

# ── enrichment job scheduler ──────────────────────────────────────────

_executor: concurrent.futures.ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()
_scheduler_lock = threading.Lock()
_scheduler_roots: dict[str, dict[str, Any]] = {}
_running_futures: dict[str, concurrent.futures.Future[Any]] = {}
_future_roots: dict[str, str] = {}


def _get_executor(max_workers: int = 4) -> concurrent.futures.ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None or _executor._max_workers != max_workers:
            if _executor is not None:
                _executor.shutdown(wait=False)
            _executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        return _executor


def _queue_state_path(root: Path) -> Path:
    return root / "logs/job_queue_state.json"


def _load_queue_state(root: Path) -> dict[str, Any]:
    path = _queue_state_path(root)
    if not path.exists():
        return {"paused": False, "updated_at": now_iso()}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"paused": False, "updated_at": now_iso()}
    return {"paused": bool(data.get("paused", False)), "updated_at": data.get("updated_at") or now_iso()}


def _save_queue_state(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    state = {"paused": bool(state.get("paused", False)), "updated_at": now_iso()}
    path = _queue_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def _schedule_enrichment(root: Path, config: dict[str, Any]) -> None:
    ensure_kb(root)
    root_key = str(root.resolve())
    with _scheduler_lock:
        _scheduler_roots[root_key] = {"root": root, "config": config}
    _drain_enrichment_queue(root)


def _drain_enrichment_queue(root: Path) -> None:
    root_key = str(root.resolve())
    with _scheduler_lock:
        entry = _scheduler_roots.get(root_key)
        if not entry:
            entry = {"root": root, "config": load_app_config(root)}
            _scheduler_roots[root_key] = entry
        config = dict(entry["config"])
        max_workers = max(1, int(config.get("max_concurrency", 4) or 4))
        for job_id, future in list(_running_futures.items()):
            if future.done():
                _running_futures.pop(job_id, None)
                _future_roots.pop(job_id, None)
                continue
        active = sum(
            1 for job_id, future in _running_futures.items()
            if not future.done() and _future_roots.get(job_id) == root_key
        )
        if _load_queue_state(root).get("paused"):
            return
        slots = max(0, max_workers - active)
        if slots <= 0:
            return
        queued = [job for job in list_jobs(root) if job.get("status") == "queued"]
        queued.sort(key=lambda item: item.get("created_at") or "")
        executor = _get_executor(max_workers)
        for job in queued[:slots]:
            job_id = str(job["id"])
            if job_id in _running_futures and not _running_futures[job_id].done():
                continue
            job["attempts"] = int(job.get("attempts") or 0) + 1
            job.setdefault("events", []).append({"time": now_iso(), "message": "Scheduled for execution."})
            save_job(root, job)
            future = executor.submit(_run_scheduled_job, root, job, job_id, config)
            _running_futures[job_id] = future
            _future_roots[job_id] = root_key


def _run_scheduled_job(root: Path, job: dict[str, Any], job_id: str, config: dict[str, Any]) -> None:
    try:
        if (job.get("kind") or "enrichment") == "enrichment":
            run_enrichment_job(root, str(job["paper_id"]), job_id, config)
        else:
            run_librarian_job(root, job_id, Path(__file__).resolve().parents[2])
    finally:
        with _scheduler_lock:
            _running_futures.pop(job_id, None)
            _future_roots.pop(job_id, None)
        _drain_enrichment_queue(root)


def _queue_status(root: Path) -> dict[str, Any]:
    jobs = list_jobs(root)
    counts: dict[str, int] = {}
    for job in jobs:
        status = str(job.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    running_ids = [
        job_id for job_id, future in _running_futures.items()
        if not future.done() and _future_roots.get(job_id) == str(root.resolve())
    ]
    return {
        **_load_queue_state(root),
        "counts": counts,
        "running_job_ids": running_ids,
    }


# ── helpers ───────────────────────────────────────────────────────────

def resolve_root(root: str | None = None) -> Path:
    selected = Path(root).expanduser().resolve() if root else DEFAULT_ROOT
    ensure_kb(selected)
    return selected


# ── config ────────────────────────────────────────────────────────────

class RootConfig(BaseModel):
    root: str
    claude_api_key: str | None = None
    claude_endpoint: str | None = None
    claude_model: str | None = None
    max_concurrency: int | None = Field(default=None, ge=1, le=20)
    translation_engine: str | None = Field(default=None, pattern=r"^(local|llm)$")
    default_summary_language: str | None = Field(default=None, pattern=r"^(en|zh)$")
    mineru_api_token: str | None = None
    mineru_extraction_mode: str | None = Field(default=None, pattern=r"^(auto|precision|flash)$")
    mineru_model: str | None = Field(default=None, pattern=r"^(vlm|pipeline)$")
    mineru_timeout_seconds: int | None = Field(default=None, ge=60, le=1800)
    mineru_allow_remote: bool | None = None
    sync_mode: str | None = Field(default=None, pattern=r"^(local|git)$")
    git_remote: str | None = None
    git_remote_url: str | None = None
    git_branch: str | None = None
    git_sync_pdfs: bool | None = None
    git_sync_chats: bool | None = None
    git_auto_sync: bool | None = None
    git_sync_interval_minutes: int | None = Field(default=None, ge=1, le=1440)


class PaperBatchRequest(RootConfig):
    paper_ids: list[str] = Field(default_factory=list)


class JobBatchRequest(RootConfig):
    job_ids: list[str] = Field(default_factory=list)


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    root = _configured_root()
    ensure_kb(root)
    cfg = load_app_config(root)
    return {"root": str(root), **cfg}


@app.post("/api/config")
def set_config(config: RootConfig) -> dict[str, Any]:
    import yaml
    root = Path(config.root).expanduser().resolve()
    ensure_kb(root)
    APP_CONFIG.write_text(yaml.safe_dump({"root": str(root)}, sort_keys=False), encoding="utf-8")
    updates = config.model_dump(exclude={"root"}, exclude_none=True)
    if "git_remote_url" in updates:
        updates["git_remote_url"] = normalize_remote_url(updates["git_remote_url"])
    cfg = save_app_config(root, updates)
    # Recreate executor if concurrency changed
    _get_executor(cfg.get("max_concurrency", 4))
    _start_local_translation_preload(cfg)
    _reset_auto_sync_schedule()
    return {"root": str(root), **cfg}


class GitSyncRequest(BaseModel):
    root: str | None = None


@app.get("/api/sync/status")
def api_sync_status(root: str | None = None) -> dict[str, Any]:
    kb_root = resolve_root(root)
    config = load_app_config(kb_root)
    return {**git_sync_status(kb_root, config), "auto_sync": _auto_sync_status(config)}


@app.post("/api/sync")
def api_sync(request: GitSyncRequest) -> dict[str, Any]:
    kb_root = resolve_root(request.root)
    try:
        result = sync_with_git(kb_root, load_app_config(kb_root))
        _reset_auto_sync_schedule()
        return result
    except GitSyncError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ── papers ────────────────────────────────────────────────────────────

@app.get("/api/papers")
def api_list_papers(root: str | None = None) -> dict[str, Any]:
    kb_root = resolve_root(root)
    papers = list_paper_summaries(kb_root)
    stats = library_stats(kb_root, papers)
    return {"root": str(kb_root), "papers": papers, "stats": stats}


@app.get("/api/papers/{paper_id}")
def api_get_paper(paper_id: str, root: str | None = None) -> dict[str, Any]:
    kb_root = resolve_root(root)
    try:
        paper = load_paper(kb_root, paper_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"root": str(kb_root), "paper": paper}


@app.post("/api/papers/{paper_id}/viewed")
def api_mark_paper_viewed(paper_id: str, config: RootConfig) -> dict[str, Any]:
    kb_root = resolve_root(config.root)
    try:
        paper = mark_paper_viewed(kb_root, paper_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"root": str(kb_root), "paper": paper}


class PaperUpdate(BaseModel):
    root: str | None = None
    title: str | None = None
    authors: list[str] | None = None
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    tags: list[str] | None = None
    reading_status: str | None = None
    priority: str | None = None
    needs_review: bool | None = None
    review_note: str | None = None  # legacy: appends a string entry
    review_notes: list[dict[str, Any]] | None = None  # canonical: replaces the whole list
    notes: str | None = None


@app.patch("/api/papers/{paper_id}")
def api_update_paper(paper_id: str, update: PaperUpdate) -> dict[str, Any]:
    kb_root = resolve_root(update.root)
    try:
        paper = load_paper(kb_root, paper_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    for key in ("title", "authors", "year", "venue", "doi", "arxiv_id",
                "tags", "reading_status", "priority", "needs_review", "notes"):
        value = getattr(update, key)
        if value is not None:
            paper[key] = value

    # review_notes canonical form: list of {text, created_at} dicts.
    # The legacy `review_note` (singular str) field is kept for backward
    # compatibility with any older callers; it now appends a dict so the
    # canonical shape is preserved.
    if update.review_notes is not None:
        paper["review_notes"] = update.review_notes
    elif update.review_note:
        paper.setdefault("review_notes", []).append({
            "text": update.review_note,
            "created_at": now_iso(),
        })

    save_paper(kb_root, paper)
    return {"root": str(kb_root), "paper": paper}


@app.delete("/api/papers/{paper_id}")
def api_delete_paper(paper_id: str, root: str | None = None) -> dict[str, Any]:
    kb_root = resolve_root(root)
    try:
        result = delete_paper(kb_root, paper_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"root": str(kb_root), **result}


@app.get("/api/papers/{paper_id}/pdf")
def api_paper_pdf(paper_id: str, root: str | None = None) -> FileResponse:
    kb_root = resolve_root(root)
    try:
        paper = load_paper(kb_root, paper_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    source = paper.get("source_pdf")
    if not source or not isinstance(source, str):
        raise HTTPException(status_code=404, detail="No source PDF.")
    # Defence in depth: a paper YAML can be hand-edited, so source_pdf
    # could in principle point anywhere. Containment check guards against
    # serving files outside the knowledge base.
    pdf_path = (kb_root / source).resolve()
    try:
        pdf_path.relative_to(kb_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid PDF path.")
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file unavailable.")
    # Sanitize the filename for the Content-Disposition header to avoid
    # header injection via embedded quotes / newlines in the path name.
    safe_name = pdf_path.name.replace('"', "").replace("\r", "").replace("\n", "")
    return FileResponse(pdf_path, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{safe_name}"'})


@app.get("/api/librarian/archives/{archive_id}/download")
def api_librarian_archive_download(archive_id: str, root: str | None = None) -> FileResponse:
    """Download an archive created by the librarian's local PDF packaging tool."""
    kb_root = resolve_root(root)
    try:
        archive = pdf_archive_path(kb_root, archive_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not archive.is_file():
        raise HTTPException(status_code=404, detail="PDF archive is unavailable.")
    filename = f"neunote-papers-{archive_id[:8]}.zip"
    return FileResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/papers/{paper_id}/figures/{figure_index}")
def api_paper_figure(paper_id: str, figure_index: int, root: str | None = None) -> FileResponse:
    kb_root = resolve_root(root)
    try:
        paper = load_paper(kb_root, paper_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    figures = paper.get("key_figures") or []
    if figure_index < 0 or figure_index >= len(figures):
        raise HTTPException(status_code=404, detail="Figure not found.")
    figure = figures[figure_index]
    if not isinstance(figure, dict) or not isinstance(figure.get("image_path"), str):
        raise HTTPException(status_code=404, detail="Figure image unavailable.")

    image_path = (kb_root / figure["image_path"]).resolve()
    try:
        image_path.relative_to(kb_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid figure path.")
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Figure image unavailable.")
    return FileResponse(image_path, media_type="image/png")


# ── upload ────────────────────────────────────────────────────────────

@app.post("/api/papers/upload")
async def api_upload_paper(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    root: str | None = Form(default=None),
    auto_enrich: bool = Form(default=True),
) -> dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported.")
    kb_root = resolve_root(root)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as handle:
        temp_path = Path(handle.name)
        while chunk := await file.read(1024 * 1024):
            handle.write(chunk)

    try:
        paper = ingest_pdf(kb_root, temp_path, file.filename)
    except Exception as exc:
        if temp_path.exists():
            temp_path.unlink()
        raise HTTPException(status_code=500, detail=str(exc))

    job = None
    if auto_enrich:
        cfg = load_app_config(kb_root)
        job = create_job(kb_root, paper["id"], paper["title"])
        _schedule_enrichment(kb_root, cfg)

    return {"root": str(kb_root), "paper": paper, "job": job}


# ── enrichment ────────────────────────────────────────────────────────

@app.post("/api/papers/{paper_id}/enrich")
def api_enrich_paper(paper_id: str, config: RootConfig) -> dict[str, Any]:
    """Enqueue a background enrichment job for a single paper."""
    kb_root = resolve_root(config.root)
    try:
        paper = load_paper(kb_root, paper_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if paper.get("download_status") != "downloaded" or not paper.get("source_pdf"):
        raise HTTPException(status_code=409, detail="Download the PDF before enrichment.")
    cfg = load_app_config(kb_root)
    # Skip if already has an active job
    existing = [j for j in list_jobs(kb_root)
                if j.get("paper_id") == paper_id and j.get("status") in {"queued", "running", "paused"}]
    if existing:
        return {"root": str(kb_root), "paper": paper, "job": existing[0]}

    job = create_job(kb_root, paper_id, paper.get("title", paper_id))
    _schedule_enrichment(kb_root, cfg)
    return {"root": str(kb_root), "paper": paper, "job": job}


@app.post("/api/papers/enrich-all")
def api_enrich_all(background_tasks: BackgroundTasks, config: RootConfig) -> dict[str, Any]:
    kb_root = resolve_root(config.root)
    cfg = load_app_config(kb_root)
    papers = list_papers(kb_root)
    jobs = []
    for paper in papers:
        if paper.get("download_status") != "downloaded" or not paper.get("source_pdf"):
            continue
        pid = paper["id"]
        # Skip if already has an active job
        existing = [j for j in list_jobs(kb_root)
                    if j.get("paper_id") == pid and j.get("status") in {"queued", "running", "paused"}]
        if existing:
            jobs.append(existing[0])
            continue
        job = create_job(kb_root, pid, paper.get("title", pid))
        jobs.append(job)
    _schedule_enrichment(kb_root, cfg)
    return {"root": str(kb_root), "jobs": jobs, "queued": len(jobs)}


@app.post("/api/papers/enrich-batch")
def api_enrich_batch(config: PaperBatchRequest) -> dict[str, Any]:
    kb_root = resolve_root(config.root)
    cfg = load_app_config(kb_root)
    paper_ids = [paper_id for paper_id in config.paper_ids if paper_id]
    jobs = []
    for paper_id in paper_ids:
        try:
            paper = load_paper(kb_root, paper_id)
        except FileNotFoundError:
            continue
        if paper.get("download_status") != "downloaded" or not paper.get("source_pdf"):
            continue
        existing = [j for j in list_jobs(kb_root)
                    if j.get("paper_id") == paper_id and j.get("status") in {"queued", "running", "paused"}]
        if existing:
            jobs.append(existing[0])
            continue
        jobs.append(create_job(kb_root, paper_id, paper.get("title", paper_id)))
    _schedule_enrichment(kb_root, cfg)
    return {"root": str(kb_root), "jobs": jobs, "queued": len(jobs)}


# ── jobs ──────────────────────────────────────────────────────────────

@app.get("/api/jobs")
def api_list_jobs(root: str | None = None) -> dict[str, Any]:
    kb_root = resolve_root(root)
    _drain_enrichment_queue(kb_root)
    return {"root": str(kb_root), "jobs": list_jobs(kb_root), "queue": _queue_status(kb_root)}


@app.post("/api/jobs/pause")
def api_pause_queue(config: RootConfig) -> dict[str, Any]:
    kb_root = resolve_root(config.root)
    state = _save_queue_state(kb_root, {"paused": True})
    for job in list_jobs(kb_root):
        if job.get("status") in {"queued", "running"}:
            pause_job(kb_root, job["id"], reason="queue")
    return {"root": str(kb_root), "queue": {**_queue_status(kb_root), **state}, "jobs": list_jobs(kb_root)}


@app.post("/api/jobs/resume")
def api_resume_queue(config: RootConfig) -> dict[str, Any]:
    kb_root = resolve_root(config.root)
    state = _save_queue_state(kb_root, {"paused": False})
    for job in list_jobs(kb_root):
        if job.get("status") == "paused" and job.get("pause_reason") == "queue":
            resume_job(kb_root, job["id"], reason="queue")
    _schedule_enrichment(kb_root, load_app_config(kb_root))
    return {"root": str(kb_root), "queue": {**_queue_status(kb_root), **state}, "jobs": list_jobs(kb_root)}


@app.post("/api/jobs/cancel-all")
def api_cancel_all_jobs(config: RootConfig) -> dict[str, Any]:
    kb_root = resolve_root(config.root)
    cancelled = []
    for job in list_jobs(kb_root):
        if job.get("status") in {"queued", "running", "paused"}:
            cancel_job(kb_root, job["id"])
            cancelled.append(job["id"])
    return {"root": str(kb_root), "cancelled": len(cancelled), "jobs": list_jobs(kb_root)}


@app.post("/api/jobs/batch/cancel")
def api_cancel_jobs_batch(config: JobBatchRequest) -> dict[str, Any]:
    kb_root = resolve_root(config.root)
    changed = []
    for job_id in config.job_ids:
        try:
            changed.append(cancel_job(kb_root, job_id)["id"])
        except FileNotFoundError:
            continue
    return {"root": str(kb_root), "changed": changed, "jobs": list_jobs(kb_root), "queue": _queue_status(kb_root)}


@app.post("/api/jobs/batch/pause")
def api_pause_jobs_batch(config: JobBatchRequest) -> dict[str, Any]:
    kb_root = resolve_root(config.root)
    changed = []
    for job_id in config.job_ids:
        try:
            changed.append(pause_job(kb_root, job_id)["id"])
        except FileNotFoundError:
            continue
    return {"root": str(kb_root), "changed": changed, "jobs": list_jobs(kb_root), "queue": _queue_status(kb_root)}


@app.post("/api/jobs/batch/resume")
def api_resume_jobs_batch(config: JobBatchRequest) -> dict[str, Any]:
    kb_root = resolve_root(config.root)
    changed = []
    for job_id in config.job_ids:
        try:
            changed.append(resume_job(kb_root, job_id)["id"])
        except FileNotFoundError:
            continue
    _schedule_enrichment(kb_root, load_app_config(kb_root))
    return {"root": str(kb_root), "changed": changed, "jobs": list_jobs(kb_root), "queue": _queue_status(kb_root)}


@app.post("/api/jobs/batch/retry")
def api_retry_jobs_batch(config: JobBatchRequest) -> dict[str, Any]:
    kb_root = resolve_root(config.root)
    changed = []
    for job_id in config.job_ids:
        try:
            changed.append(retry_job(kb_root, job_id)["id"])
        except FileNotFoundError:
            continue
    _schedule_enrichment(kb_root, load_app_config(kb_root))
    return {"root": str(kb_root), "changed": changed, "jobs": list_jobs(kb_root), "queue": _queue_status(kb_root)}


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str, root: str | None = None) -> dict[str, Any]:
    kb_root = resolve_root(root)
    try:
        job = load_job(kb_root, job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"root": str(kb_root), "job": job}


@app.post("/api/jobs/{job_id}/cancel")
def api_cancel_job(job_id: str, config: RootConfig) -> dict[str, Any]:
    kb_root = resolve_root(config.root)
    try:
        job = cancel_job(kb_root, job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"root": str(kb_root), "job": job}


@app.post("/api/jobs/{job_id}/pause")
def api_pause_job(job_id: str, config: RootConfig) -> dict[str, Any]:
    kb_root = resolve_root(config.root)
    try:
        job = pause_job(kb_root, job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"root": str(kb_root), "job": job}


@app.post("/api/jobs/{job_id}/resume")
def api_resume_job(job_id: str, config: RootConfig) -> dict[str, Any]:
    kb_root = resolve_root(config.root)
    try:
        job = resume_job(kb_root, job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    _schedule_enrichment(kb_root, load_app_config(kb_root))
    return {"root": str(kb_root), "job": job}


@app.post("/api/jobs/{job_id}/retry")
def api_retry_job(job_id: str, config: RootConfig) -> dict[str, Any]:
    kb_root = resolve_root(config.root)
    try:
        job = retry_job(kb_root, job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    _schedule_enrichment(kb_root, load_app_config(kb_root))
    return {"root": str(kb_root), "job": job}


@app.delete("/api/jobs/cleanup")
def api_cleanup_jobs(root: str | None = None) -> dict[str, Any]:
    """Delete all completed, failed, and cancelled jobs."""
    kb_root = resolve_root(root)
    removed = []
    for job in list_jobs(kb_root):
        if job.get("status") in {"completed", "failed", "cancelled"}:
            delete_job(kb_root, job["id"])
            removed.append(job["id"])
    return {"root": str(kb_root), "removed": len(removed), "jobs": list_jobs(kb_root)}


@app.delete("/api/jobs/{job_id}")
def api_delete_job(job_id: str, root: str | None = None) -> dict[str, Any]:
    kb_root = resolve_root(root)
    try:
        cancel_job(kb_root, job_id)
    except FileNotFoundError:
        pass
    delete_job(kb_root, job_id)
    return {"root": str(kb_root), "deleted": job_id, "jobs": list_jobs(kb_root)}


# ── duplicates ────────────────────────────────────────────────────────

@app.get("/api/duplicates")
def api_get_duplicates(root: str | None = None) -> dict[str, Any]:
    """Return groups of potential duplicate papers."""
    kb_root = resolve_root(root)
    groups = find_duplicates(kb_root)
    return {"root": str(kb_root), "groups": groups}


@app.post("/api/duplicates/cleanup")
def api_cleanup_duplicates(root: str | None = None) -> dict[str, Any]:
    """Delete all duplicate papers, keeping only the newest in each group."""
    kb_root = resolve_root(root)
    result = cleanup_duplicates(kb_root)
    return {"root": str(kb_root), **result}


# ── translation ───────────────────────────────────────────────────────

@app.post("/api/papers/{paper_id}/translate")
def api_translate_paper(paper_id: str, config: RootConfig) -> dict[str, Any]:
    """Translate the summary fields of a paper to Chinese using the configured engine."""
    kb_root = resolve_root(config.root)
    try:
        paper = load_paper(kb_root, paper_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    saved_config = load_app_config(kb_root)
    request_config = config.model_dump(exclude={"root"}, exclude_none=True)
    effective_config = {**saved_config, **request_config}
    engine = (effective_config.get("translation_engine") or "local").lower()
    if engine == "llm":
        try:
            translations = translate_paper_summary_llm(paper, effective_config)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM translation failed: {exc}") from exc
    else:
        translations = translate_paper_summary(paper)

    # Cache translations in the paper YAML
    existing = paper.get("translations") if isinstance(paper.get("translations"), dict) else {}
    paper["translations"] = {**existing, **translations}
    paper["translation_meta"] = {
        "engine": engine,
        "model": effective_config.get("claude_model") if engine == "llm" else None,
        "updated_at": now_iso(),
    }
    save_paper(kb_root, paper)
    return {"root": str(kb_root), "paper": paper, "translations": paper["translations"], "translation_meta": paper["translation_meta"]}


# ── sessions ──────────────────────────────────────────────────────────

@app.get("/api/sessions")
def api_list_sessions(root: str | None = None) -> dict[str, Any]:
    kb_root = resolve_root(root)
    return {"root": str(kb_root), "sessions": list_sessions(kb_root)}


@app.post("/api/sessions")
def api_create_session(config: RootConfig) -> dict[str, Any]:
    kb_root = resolve_root(config.root)
    session = create_session(kb_root)
    return {"root": str(kb_root), "session": session}


@app.get("/api/sessions/{session_id}")
def api_get_session(session_id: str, root: str | None = None) -> dict[str, Any]:
    kb_root = resolve_root(root)
    return {"root": str(kb_root), "session": load_session(kb_root, session_id)}


@app.delete("/api/sessions/{session_id}")
def api_delete_session(session_id: str, root: str | None = None) -> dict[str, Any]:
    kb_root = resolve_root(root)
    try:
        delete_session(kb_root, session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"root": str(kb_root), "deleted": session_id, "sessions": list_sessions(kb_root)}


# ── chat ──────────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    question: str
    root: str | None = None
    session_id: str | None = None
    paper_id: str | None = None
    paper_ids: list[str] = Field(default_factory=list)
    tag_mentions: list[str] = Field(default_factory=list)
    claude_api_key: str | None = None
    claude_endpoint: str | None = None
    claude_model: str | None = None
    temperature: float = 0.2
    max_context_files: int = Field(default=8, ge=1, le=20)


class MetadataSearchRequest(BaseModel):
    root: str
    conferences: list[str] = Field(default_factory=list)
    years: list[int] = Field(default_factory=list)
    query: str = "*"
    session_id: str | None = None


class MetadataCandidatesRequest(BaseModel):
    root: str
    items: list[dict[str, Any]] = Field(min_length=1, max_length=1000)
    session_id: str | None = None


class ActionConfirmRequest(BaseModel):
    root: str
    selected: list[int] | None = None


class DownloadProposalRequest(BaseModel):
    root: str
    paper_ids: list[str] = Field(min_length=1, max_length=200)
    urls: dict[str, str] = Field(default_factory=dict)
    session_id: str | None = None


class FulltextSearchRequest(BaseModel):
    root: str
    query: str = Field(min_length=1)
    paper_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=12, ge=1, le=50)


@app.post("/api/librarian/search")
def api_librarian_search(request: MetadataSearchRequest) -> dict[str, Any]:
    root = resolve_root(request.root)
    try:
        conferences = normalize_venues(request.conferences) if request.conferences else []
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    job = create_job(root, "", f"检索 {','.join(request.conferences)}", kind="metadata_search", payload={
        "conferences": conferences,
        "years": request.years, "query": request.query or "*", "session_id": request.session_id,
    })
    _schedule_enrichment(root, load_app_config(root))
    return {"root": str(root), "job": job}


@app.post("/api/librarian/import/propose")
def api_librarian_import_propose(request: MetadataCandidatesRequest) -> dict[str, Any]:
    root = resolve_root(request.root)
    action = create_action(root, "metadata_import", request.items, session_id=request.session_id)
    return {"root": str(root), "action": action}


@app.get("/api/librarian/actions/{action_id}")
def api_librarian_action(action_id: str, root: str | None = None) -> dict[str, Any]:
    kb_root = resolve_root(root)
    try:
        action = load_action(kb_root, action_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"root": str(kb_root), "action": action}


@app.post("/api/librarian/actions/{action_id}/confirm-import")
def api_librarian_confirm_import(action_id: str, request: ActionConfirmRequest) -> dict[str, Any]:
    root = resolve_root(request.root)
    try:
        action = import_action(root, action_id, request.selected)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"root": str(root), "action": action, "papers": list_papers(root)}


@app.post("/api/librarian/download/propose")
def api_librarian_download_propose(request: DownloadProposalRequest) -> dict[str, Any]:
    root = resolve_root(request.root)
    items = []
    for paper_id in request.paper_ids:
        try:
            paper = load_paper(root, paper_id)
        except FileNotFoundError:
            continue
        url = request.urls.get(paper_id) or paper.get("pdf_url")
        if url:
            items.append({"paper_id": paper_id, "title": paper.get("title"), "url": url})
    if not items:
        raise HTTPException(status_code=400, detail="No selected paper has a PDF URL.")
    action = create_action(root, "pdf_download", items, session_id=request.session_id)
    return {"root": str(root), "action": action}


@app.post("/api/librarian/actions/{action_id}/confirm-download")
def api_librarian_confirm_download(action_id: str, request: ActionConfirmRequest) -> dict[str, Any]:
    root = resolve_root(request.root)
    try:
        action = load_action(root, action_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if action.get("kind") != "pdf_download" or action.get("status") not in {"pending", "completed"}:
        raise HTTPException(status_code=409, detail="Download action is unavailable.")
    if action.get("status") == "completed":
        return {"root": str(root), "action": action, "jobs": action.get("jobs", [])}
    indexes = request.selected if request.selected is not None else list(range(len(action["items"])))
    jobs = []
    for index in indexes:
        if not 0 <= index < len(action["items"]):
            continue
        item = action["items"][index]
        paper_id = item.get("paper_id")
        if not paper_id:
            imported = merge_metadata(root, {"title": item.get("title") or Path(str(item["url"])).stem or "Downloaded paper", "pdf_url": item["url"], "metadata_source": "direct_url"})
            if imported.get("status") == "conflict":
                continue
            paper_id = imported["paper"]["id"]
        jobs.append(create_job(root, paper_id, item.get("title") or paper_id, kind="pdf_download", payload={"url": item["url"], "paper_id": paper_id}))
    action.update({"status": "completed", "completed_at": now_iso(), "jobs": jobs})
    from .librarian import save_action
    save_action(root, action)
    _schedule_enrichment(root, load_app_config(root))
    return {"root": str(root), "action": action, "jobs": jobs}


@app.post("/api/librarian/fulltext/search")
def api_librarian_fulltext_search(request: FulltextSearchRequest) -> dict[str, Any]:
    root = resolve_root(request.root)
    return {"root": str(root), "results": search_fulltext(root, request.query, request.paper_ids or None, request.limit)}


@app.post("/api/papers/{paper_id}/index")
def api_index_paper(paper_id: str, config: RootConfig) -> dict[str, Any]:
    root = resolve_root(config.root)
    paper = load_paper(root, paper_id)
    if paper.get("download_status") != "downloaded" or not paper.get("source_pdf"):
        raise HTTPException(status_code=409, detail="Paper PDF is not downloaded.")
    job = create_job(root, paper_id, paper.get("title") or paper_id, kind="fulltext_index")
    _schedule_enrichment(root, load_app_config(root))
    return {"root": str(root), "job": job}


def _paper_ids_for_tags(kb_root: Path, tags: list[str]) -> list[str]:
    selected_tags = [tag.strip() for tag in tags if tag and tag.strip()]
    if not selected_tags:
        return []
    selected = {tag.lower() for tag in selected_tags}
    matches: list[str] = []
    for paper in list_papers(kb_root):
        paper_tags = {str(tag).lower() for tag in paper.get("tags", [])}
        if selected.issubset(paper_tags) and paper.get("id"):
            matches.append(str(paper["id"]))
    return matches


def _expand_mentioned_paper_ids(kb_root: Path, request: AskRequest) -> list[str]:
    paper_ids: list[str] = []
    for paper_id in [request.paper_id, *request.paper_ids]:
        if paper_id and paper_id not in paper_ids:
            paper_ids.append(paper_id)
    for paper_id in _paper_ids_for_tags(kb_root, request.tag_mentions):
        if paper_id not in paper_ids:
            paper_ids.append(paper_id)
    return paper_ids


@app.post("/api/ask")
def api_ask(request: AskRequest) -> dict[str, Any]:
    kb_root = resolve_root(request.root)
    paper_ids = _expand_mentioned_paper_ids(kb_root, request)
    parts: list[str] = []
    final_session = None
    for payload in run_agent_answer_sync(kb_root, request.question,
                                          request.session_id, request.model_dump(),
                                          paper_ids=paper_ids):
        if payload.get("type") == "delta":
            parts.append(payload.get("delta", ""))
        elif payload.get("type") in ("session", "done"):
            final_session = payload.get("session")
        elif payload.get("type") == "error":
            raise HTTPException(status_code=502, detail=payload.get("detail", "Agent failed."))
    return {"answer": "".join(parts), "root": str(kb_root), "session": final_session}


@app.post("/api/chat/stream")
def api_chat_stream(request: AskRequest) -> StreamingResponse:
    kb_root = resolve_root(request.root)
    paper_ids = _expand_mentioned_paper_ids(kb_root, request)

    def event(payload: dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def generate():
        for payload in run_agent_answer_sync(kb_root, request.question,
                                              request.session_id, request.model_dump(),
                                              paper_ids=paper_ids):
            yield event(payload)

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── health ────────────────────────────────────────────────────────────

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
