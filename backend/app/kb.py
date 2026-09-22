from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile as tempfile_mod
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import yaml
from pypdf import PdfReader


# ── helpers ───────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def anthropic_request_options(base_url: str) -> dict[str, Any]:
    """Return provider-specific options for Anthropic-compatible endpoints."""
    hostname = (urllib.parse.urlparse(base_url).hostname or "").casefold()
    if hostname == "deepseek.com" or hostname.endswith(".deepseek.com"):
        # DeepSeek V4 defaults to thinking mode. Structured extraction and
        # translation need the final JSON, not a reasoning block that can use
        # the entire output budget before the answer is emitted.
        return {"thinking": {"type": "disabled"}}
    return {}


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
    "assets/paper_figures",
]

PAPER_SCHEMA_DEFAULTS: dict[str, Any] = {
    "author_affiliations": [],
    "core_concepts": [],
    "key_figures": [],
    "paper_url": "",
    "pdf_url": "",
    "download_status": "not_downloaded",
    "download_error": "",
    "downloaded_at": None,
    "index_status": "not_indexed",
    "index_error": "",
    "indexed_at": None,
    "index_version": None,
    "metadata_sources": [],
}


def normalize_paper_schema(paper: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with fields added by newer app versions.

    Older YAML records intentionally remain valid. Defaults are added at read
    time for API/frontend compatibility, and persisted the next time the paper
    is saved or enriched.
    """
    normalized = dict(paper)
    for key, value in PAPER_SCHEMA_DEFAULTS.items():
        if key not in normalized or normalized[key] is None:
            normalized[key] = list(value) if isinstance(value, list) else value
    # Legacy records predate explicit download state. A source path denotes a
    # downloaded file; existence is reconciled by the migration/index service.
    if paper.get("source_pdf") and "download_status" not in paper:
        normalized["download_status"] = "downloaded"
    return normalized


def ensure_kb(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for rel in REQUIRED_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)
    _ensure_text(root / "AGENT.md", AGENT_MD)
    _ensure_text(root / "logs/ingest_log.md", "# Ingest Log\n")
    _ensure_text(root / "logs/update_log.md", "# Update Log\n")
    _migrate_v12_papers(root)


def _migrate_v12_papers(root: Path) -> None:
    """Idempotently persist the record/PDF split for pre-v1.2 YAML files."""
    marker = root / "metadata/schema_version"
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == "1.2":
        return
    for path in (root / "papers").glob("*.yaml"):
        if path.name.startswith("."):
            continue
        try:
            paper = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        source = paper.get("source_pdf")
        local_exists = bool(source and (root / str(source)).is_file())
        paper.setdefault("paper_url", "")
        paper.setdefault("pdf_url", "")
        paper.setdefault("download_status", "downloaded" if local_exists else "not_downloaded")
        paper.setdefault("download_error", "")
        paper.setdefault("downloaded_at", paper.get("created_at") if local_exists else None)
        paper.setdefault("index_status", "not_indexed")
        paper.setdefault("index_error", "")
        paper.setdefault("indexed_at", None)
        paper.setdefault("index_version", None)
        paper.setdefault("metadata_sources", [])
        path.write_text(yaml.safe_dump(paper, sort_keys=False, allow_unicode=True), encoding="utf-8")
    marker.write_text("1.2\n", encoding="utf-8")


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
        if path.name.startswith("."):
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if data.get("id"):
                papers.append(normalize_paper_schema(data))
        except (FileNotFoundError, OSError):
            continue
        except yaml.YAMLError:
            continue
    papers.sort(key=lambda p: (p.get("title") or p.get("id") or "").lower())
    return papers


# Fields required by dashboards, cards, filters, and review-note search.  Full
# enrichment text, translations, figures, and agent traces are loaded only by
# GET /api/papers/{paper_id} when the reader opens a paper.
_PAPER_LIST_FIELDS = (
    "id", "title", "authors", "year", "venue", "doi", "arxiv_id",
    "source_pdf", "paper_url", "pdf_url", "download_status", "download_error",
    "downloaded_at", "index_status", "index_error", "indexed_at", "pages",
    "tags", "status", "confidence", "reading_status", "priority", "needs_review",
    "abstract", "one_sentence", "review_notes", "created_at", "updated_at",
    "last_read_at",
)

# A catalogue card only needs enough abstract text to identify a paper. Full
# abstracts remain available from the paper-detail endpoint; bounding this
# preview keeps repeated list refreshes cheap for large libraries.
_PAPER_LIST_ABSTRACT_MAX_CHARS = 1_200


def list_paper_summaries(root: Path) -> list[dict[str, Any]]:
    """Return compact records for the library list without detail-only payloads."""
    summaries = []
    for paper in list_papers(root):
        summary = {key: paper.get(key) for key in _PAPER_LIST_FIELDS}
        abstract = summary.get("abstract")
        if isinstance(abstract, str) and len(abstract) > _PAPER_LIST_ABSTRACT_MAX_CHARS:
            summary["abstract"] = abstract[:_PAPER_LIST_ABSTRACT_MAX_CHARS].rstrip() + "…"
        summaries.append(summary)
    return summaries


def load_paper(root: Path, paper_id: str) -> dict[str, Any]:
    path = paper_path(root, paper_id)
    if not path.exists():
        raise FileNotFoundError(f"Paper not found: {paper_id}")
    return normalize_paper_schema(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def save_paper(root: Path, paper: dict[str, Any]) -> None:
    paper_id = paper.get("id")
    if not paper_id:
        raise ValueError("Paper requires an id.")
    paper.update(normalize_paper_schema(paper))
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


def mark_paper_viewed(root: Path, paper_id: str) -> dict[str, Any]:
    paper = load_paper(root, paper_id)
    paper["last_read_at"] = now_iso()
    content = yaml.safe_dump(paper, sort_keys=False, allow_unicode=True)
    paper_path(root, paper_id).write_text(content, encoding="utf-8")
    return paper


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
    for figure in paper.get("key_figures") or []:
        if not isinstance(figure, dict):
            continue
        image_path = figure.get("image_path")
        if not isinstance(image_path, str):
            continue
        fig_path = (root / image_path).resolve()
        try:
            fig_path.relative_to(root)
        except ValueError:
            continue
        if fig_path.exists():
            fig_path.unlink()
            deleted.append(image_path)
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


def extract_pdf_text(path: Path, max_pages: int = 8, include_page_markers: bool = False) -> str:
    reader = PdfReader(str(path))
    parts = []
    for idx, page in enumerate(reader.pages[:max_pages], start=1):
        text = page.extract_text() or ""
        if include_page_markers:
            parts.append(f"\n--- PAGE {idx} ---\n{text}")
        else:
            parts.append(text)
    return "\n".join(parts)


def _pdf_page_size_points(path: Path, page: int) -> tuple[float, float]:
    reader = PdfReader(str(path))
    box = reader.pages[page - 1].mediabox
    return float(box.width), float(box.height)


def _pdf_page_words(path: Path, page: int) -> list[dict[str, Any]]:
    extractor = shutil.which("pdftotext")
    if not extractor:
        return []
    try:
        result = subprocess.run(
            [extractor, "-bbox", "-f", str(page), "-l", str(page), str(path), "-"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []

    try:
        root = ElementTree.fromstring(result.stdout)
    except ElementTree.ParseError:
        return []

    words = []
    for elem in root.iter():
        if not elem.tag.endswith("word"):
            continue
        text = "".join(elem.itertext()).strip()
        if not text:
            continue
        try:
            words.append({
                "text": text,
                "x_min": float(elem.attrib["xMin"]),
                "y_min": float(elem.attrib["yMin"]),
                "x_max": float(elem.attrib["xMax"]),
                "y_max": float(elem.attrib["yMax"]),
            })
        except (KeyError, ValueError):
            continue
    return words


def _line_text(line: list[dict[str, Any]]) -> str:
    return " ".join(w["text"] for w in sorted(line, key=lambda w: w["x_min"]))


def _caption_lines(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    lines: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda w: (w["y_min"], w["x_min"])):
        if not lines or abs(lines[-1][0]["y_min"] - word["y_min"]) > 3.0:
            lines.append([word])
        else:
            lines[-1].append(word)
    return lines


def _figure_number(value: str) -> str | None:
    match = re.search(r"\b(?:fig(?:ure)?\.?|figure)\s*([0-9]+[a-z]?)\b", value, re.I)
    return match.group(1).lower() if match else None


def _figure_crop_points(path: Path, page: int, figure: dict[str, Any]) -> tuple[float, float, float, float] | None:
    words = _pdf_page_words(path, page)
    if not words:
        return None

    width, height = _pdf_page_size_points(path, page)
    haystacks = [
        str(figure.get("label") or ""),
        str(figure.get("caption") or ""),
        str(figure.get("title") or ""),
    ]
    target_number = next((_figure_number(text) for text in haystacks if _figure_number(text)), None)

    caption_line: list[dict[str, Any]] | None = None
    for line in _caption_lines(words):
        text = _line_text(line)
        text_low = text.lower()
        number = _figure_number(text)
        if target_number and number == target_number:
            caption_line = line
            break
        if not target_number and re.search(r"\b(?:fig(?:ure)?\.?|figure)\s+[0-9]+", text_low):
            caption_line = line
            break
    if not caption_line:
        return None

    cap_x_min = min(w["x_min"] for w in caption_line)
    cap_x_max = max(w["x_max"] for w in caption_line)
    cap_y_min = min(w["y_min"] for w in caption_line)
    cap_center = (cap_x_min + cap_x_max) / 2
    cap_width = cap_x_max - cap_x_min

    margin = 24.0
    if cap_width < width * 0.58:
        if cap_center < width / 2:
            x0, x1 = margin, width / 2 - 8
        else:
            x0, x1 = width / 2 + 8, width - margin
    else:
        x0, x1 = margin, width - margin

    crop_height = min(height * 0.48, max(height * 0.24, cap_y_min - margin))
    y1 = max(margin + 24, cap_y_min - 6)
    y0 = max(margin, y1 - crop_height)
    if y1 <= y0 or x1 <= x0:
        return None
    return x0, y0, x1, y1


def _pdf_page_layout_lines(path: Path, page: int) -> list[str]:
    extractor = shutil.which("pdftotext")
    if not extractor:
        return []
    try:
        result = subprocess.run(
            [extractor, "-layout", "-f", str(page), "-l", str(page), str(path), "-"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []
    return [line.rstrip("\f\r\n") for line in result.stdout.splitlines()]


def _figure_layout_hint(path: Path, page: int, figure: dict[str, Any]) -> dict[str, Any] | None:
    lines = _pdf_page_layout_lines(path, page)
    if not lines:
        return None
    haystacks = [
        str(figure.get("label") or ""),
        str(figure.get("caption") or ""),
        str(figure.get("title") or ""),
    ]
    target_number = next((_figure_number(text) for text in haystacks if _figure_number(text)), None)
    max_width = max((len(line) for line in lines), default=0) or 1
    for idx, line in enumerate(lines):
        number = _figure_number(line)
        if target_number and number != target_number:
            continue
        if not target_number and not number:
            continue
        stripped = line.strip()
        if not stripped:
            continue
        return {
            "line_index": idx,
            "line_count": len(lines),
            "start_col": len(line) - len(line.lstrip()),
            "end_col": len(line.rstrip()),
            "max_width": max_width,
        }
    return None


def _figure_column_bounds_points(path: Path, page: int, figure: dict[str, Any],
                                 width: float) -> tuple[float, float]:
    hint = _figure_layout_hint(path, page, figure)
    margin = 24.0
    if not hint:
        return margin, width - margin
    start_ratio = hint["start_col"] / hint["max_width"]
    end_ratio = hint["end_col"] / hint["max_width"]
    if start_ratio > 0.43:
        return width / 2 + 8, width - margin
    if end_ratio < 0.57:
        return margin, width / 2 - 8
    return margin, width - margin


def _figure_crop_points_from_layout(path: Path, page: int, figure: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """Estimate a figure crop from `pdftotext -layout` when bbox XML fails.

    Some PDFs crash Poppler's bbox mode but still produce stable layout text.
    This fallback finds the caption line in the textual layout and maps its
    approximate row/column back to PDF coordinates.
    """
    lines = _pdf_page_layout_lines(path, page)
    if not lines:
        return None

    width, height = _pdf_page_size_points(path, page)
    haystacks = [
        str(figure.get("label") or ""),
        str(figure.get("caption") or ""),
        str(figure.get("title") or ""),
    ]
    target_number = next((_figure_number(text) for text in haystacks if _figure_number(text)), None)

    caption_idx: int | None = None
    caption_line = ""
    for idx, line in enumerate(lines):
        number = _figure_number(line)
        if target_number and number == target_number:
            caption_idx = idx
            caption_line = line
            break
        if not target_number and number:
            caption_idx = idx
            caption_line = line
            break
    if caption_idx is None:
        return None

    max_width = max(len(line) for line in lines) or 1
    start_col = len(caption_line) - len(caption_line.lstrip())
    end_col = len(caption_line.rstrip())
    cap_center_ratio = ((start_col + end_col) / 2) / max_width
    cap_width_ratio = max((end_col - start_col) / max_width, 0.0)

    margin = 24.0
    if cap_width_ratio < 0.48:
        if cap_center_ratio < 0.48:
            x0, x1 = margin, width / 2 - 8
        elif cap_center_ratio > 0.52:
            x0, x1 = width / 2 + 8, width - margin
        else:
            x0, x1 = margin, width - margin
    else:
        x0, x1 = margin, width - margin

    row_ratio = caption_idx / max(len(lines), 1)
    cap_y = min(max(height * row_ratio, margin + 48), height - margin)
    y1 = max(margin + 48, cap_y - 8)
    crop_height = min(height * 0.45, max(height * 0.22, y1 - margin))
    y0 = max(margin, y1 - crop_height)
    if y1 <= y0 or x1 <= x0:
        return None
    return x0, y0, x1, y1


def _read_ppm(path: Path) -> tuple[int, int, bytes] | None:
    data = path.read_bytes()
    idx = 0

    def token() -> bytes:
        nonlocal idx
        while idx < len(data) and chr(data[idx]).isspace():
            idx += 1
        if idx < len(data) and data[idx:idx + 1] == b"#":
            while idx < len(data) and data[idx:idx + 1] != b"\n":
                idx += 1
            return token()
        start = idx
        while idx < len(data) and not chr(data[idx]).isspace():
            idx += 1
        return data[start:idx]

    try:
        if token() != b"P6":
            return None
        width = int(token())
        height = int(token())
        max_value = int(token())
        if max_value != 255:
            return None
        while idx < len(data) and chr(data[idx]).isspace():
            idx += 1
    except (ValueError, IndexError):
        return None
    pixels = data[idx:]
    if len(pixels) < width * height * 3:
        return None
    return width, height, pixels


def _colored_components_bbox(width: int, height: int, pixels: bytes,
                             x0: int, x1: int) -> tuple[int, int, int, int] | None:
    block = 4
    max_y = int(height * 0.82)
    mask: set[tuple[int, int]] = set()
    for y in range(0, max_y, block):
        for x in range(max(0, x0), min(width, x1), block):
            hit = False
            for yy in range(y, min(y + block, height), 2):
                for xx in range(x, min(x + block, width), 2):
                    off = (yy * width + xx) * 3
                    r, g, b = pixels[off], pixels[off + 1], pixels[off + 2]
                    if min(r, g, b) < 246 and max(r, g, b) - min(r, g, b) > 12:
                        hit = True
                        break
                if hit:
                    break
            if hit:
                mask.add((x // block, y // block))

    seen: set[tuple[int, int]] = set()
    components: list[tuple[int, int, int, int, int]] = []
    for cell in list(mask):
        if cell in seen:
            continue
        queue = [cell]
        seen.add(cell)
        xs: list[int] = []
        ys: list[int] = []
        for current in queue:
            cx, cy = current
            xs.append(cx)
            ys.append(cy)
            for neighbor in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if neighbor in mask and neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        area = len(xs)
        if area >= 4:
            components.append((
                area,
                min(xs) * block,
                min(ys) * block,
                (max(xs) + 1) * block,
                (max(ys) + 1) * block,
            ))
    if not components:
        return None

    components.sort(reverse=True)
    seed_area, seed_x0, seed_y0, seed_x1, seed_y1 = components[0]
    min_area = max(5, seed_area * 0.03)
    vertical_gap = max(120, (seed_y1 - seed_y0) * 1.2)
    selected = [
        component for component in components
        if (
            component[0] >= min_area
            and component[2] <= seed_y1 + vertical_gap
            and component[4] >= seed_y0 - vertical_gap
        )
    ]
    if not selected:
        selected = [components[0]]
    return (
        min(component[1] for component in selected),
        min(component[2] for component in selected),
        max(component[3] for component in selected),
        max(component[4] for component in selected),
    )


def _figure_crop_points_from_rendered_page(path: Path, page: int, figure: dict[str, Any],
                                           renderer: str) -> tuple[float, float, float, float] | None:
    width_pt, height_pt = _pdf_page_size_points(path, page)
    column_x0_pt, column_x1_pt = _figure_column_bounds_points(path, page, figure, width_pt)
    dpi = 96
    scale = dpi / 72.0

    with tempfile_mod.TemporaryDirectory() as directory:
        output_prefix = Path(directory) / "page"
        try:
            subprocess.run(
                [renderer, "-r", str(dpi), "-f", str(page), "-l", str(page),
                 "-singlefile", str(path), str(output_prefix)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        ppm = _read_ppm(output_prefix.with_suffix(".ppm"))
        if not ppm:
            return None

    width_px, height_px, pixels = ppm
    x0_px = round(column_x0_pt * scale)
    x1_px = round(column_x1_pt * scale)
    bbox = _colored_components_bbox(width_px, height_px, pixels, x0_px, x1_px)
    if not bbox:
        return None

    bx0, by0, bx1, by1 = bbox
    x0 = bx0 / scale
    y0 = by0 / scale
    x1 = bx1 / scale
    y1 = by1 / scale
    crop_width = x1 - x0
    crop_height = y1 - y0
    is_single_column = (column_x1_pt - column_x0_pt) < width_pt * 0.55
    is_right_column = is_single_column and column_x0_pt > width_pt * 0.45
    pad_x = min(64.0, max(18.0, crop_width * 0.22))
    if is_right_column:
        pad_top = min(20.0, max(10.0, crop_height * 0.15))
        pad_bottom = min(10.0, max(6.0, crop_height * 0.08))
    else:
        pad_top = min(48.0, max(24.0, crop_height * 0.45))
        pad_bottom = min(28.0, max(12.0, crop_height * 0.15))
    return (
        max(column_x0_pt, x0 - pad_x),
        max(0.0, y0 - pad_top),
        min(column_x1_pt, x1 + pad_x),
        min(height_pt, y1 + pad_bottom),
    )


def _default_figure_crop_points(path: Path, page: int) -> tuple[float, float, float, float]:
    width, height = _pdf_page_size_points(path, page)
    margin_x = max(24.0, width * 0.05)
    y0 = max(36.0, height * 0.08)
    y1 = min(height * 0.68, height - 36.0)
    return margin_x, y0, width - margin_x, y1


def render_key_figures(root: Path, paper: dict[str, Any], job_id: str | None = None) -> list[dict[str, Any]]:
    """Render selected key figures as cropped PNG assets.

    The agent selects figure pages in `key_figures`; this function turns those
    selections into durable local images for the paper profile. It crops above
    the detected figure caption instead of rendering the full PDF page.
    """
    def _dbg(message: str) -> None:
        if job_id:
            job_debug_log(root, job_id, message)

    figures = paper.get("key_figures") or []
    if not isinstance(figures, list) or not figures:
        return []

    renderer = shutil.which("pdftoppm")
    if not renderer:
        _dbg("render_key_figures: pdftoppm unavailable; keeping figure metadata without images")
        return [f for f in figures if isinstance(f, dict)][:3]

    source = paper.get("source_pdf")
    if not isinstance(source, str):
        return []
    pdf_path = (root / source).resolve()
    if not pdf_path.exists():
        return []

    paper_id = slugify(str(paper.get("id") or "paper"))
    page_count = int(paper.get("pages") or 0)
    out_dir = root / "assets/paper_figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[dict[str, Any]] = []

    for idx, figure in enumerate(figures[:3], start=1):
        if not isinstance(figure, dict):
            continue
        try:
            page = int(figure.get("page") or 0)
        except (TypeError, ValueError):
            continue
        if page < 1 or (page_count and page > page_count):
            continue

        crop = _figure_crop_points_from_rendered_page(pdf_path, page, figure, renderer)
        crop_method = "rendered"
        if not crop:
            crop = _figure_crop_points(pdf_path, page, figure)
            crop_method = "caption"
        if not crop:
            crop = _figure_crop_points_from_layout(pdf_path, page, figure)
            crop_method = "layout"
        if not crop:
            crop = _default_figure_crop_points(pdf_path, page)
            crop_method = "fallback"
        item = dict(figure)
        item["crop_method"] = crop_method

        x0, y0, x1, y1 = crop
        dpi = 144
        scale = dpi / 72.0
        output_prefix = out_dir / f"{paper_id}_figure_{idx}_p{page}"
        try:
            subprocess.run(
                [renderer, "-png", "-singlefile", "-f", str(page), "-l", str(page),
                 "-r", str(dpi),
                 "-x", str(round(x0 * scale)),
                 "-y", str(round(y0 * scale)),
                 "-W", str(round((x1 - x0) * scale)),
                 "-H", str(round((y1 - y0) * scale)),
                 str(pdf_path), str(output_prefix)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            _dbg(f"render_key_figures: failed page {page}: {exc}")
            rendered.append(item)
            continue

        image_file = output_prefix.with_suffix(".png")
        if image_file.exists():
            item["image_path"] = str(image_file.relative_to(root))
            item["crop"] = {"x0": round(x0, 2), "y0": round(y0, 2), "x1": round(x1, 2), "y1": round(y1, 2)}
        rendered.append(item)

    return rendered


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
        "author_affiliations": [],
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
        "core_concepts": [],
        "key_figures": [],
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


def create_job(root: Path, paper_id: str, title: str, *, kind: str = "enrichment",
               payload: dict[str, Any] | None = None) -> dict[str, Any]:
    created = now_iso()
    job = {
        "id": uuid.uuid4().hex,
        "paper_id": paper_id,
        "title": title,
        "kind": kind,
        "payload": payload or {},
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "created_at": created,
        "updated_at": created,
        "started_at": None,
        "completed_at": None,
        "attempts": 0,
        "last_error": None,
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
        if status in {"queued", "paused", "running"}:
            job["completed_at"] = None
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


def pause_job(root: Path, job_id: str, reason: str = "manual") -> dict[str, Any]:
    job = load_job(root, job_id)
    if job.get("status") not in {"queued", "running"}:
        return job
    job["status"] = "paused"
    job["stage"] = "paused"
    job["pause_reason"] = reason
    job.setdefault("events", []).append({"time": now_iso(), "message": "Paused."})
    save_job(root, job)
    return job


def resume_job(root: Path, job_id: str, reason: str | None = None) -> dict[str, Any]:
    job = load_job(root, job_id)
    if job.get("status") != "paused":
        return job
    if reason and job.get("pause_reason") != reason:
        return job
    job["status"] = "queued"
    job["stage"] = "queued"
    job["completed_at"] = None
    job["pause_reason"] = None
    job.setdefault("events", []).append({"time": now_iso(), "message": "Resumed."})
    save_job(root, job)
    return job


def retry_job(root: Path, job_id: str) -> dict[str, Any]:
    job = load_job(root, job_id)
    if job.get("status") not in {"failed", "cancelled"}:
        return job
    job["status"] = "queued"
    job["stage"] = "queued"
    job["progress"] = 0
    job["started_at"] = None
    job["completed_at"] = None
    job["last_error"] = None
    job.setdefault("events", []).append({"time": now_iso(), "message": "Queued for retry."})
    save_job(root, job)
    return job


def fail_job(root: Path, job_id: str, message: str) -> dict[str, Any]:
    job = load_job(root, job_id)
    job["status"] = "failed"
    job["stage"] = "failed"
    job["progress"] = 100
    job["last_error"] = message
    if not job.get("completed_at"):
        job["completed_at"] = now_iso()
    job.setdefault("events", []).append({"time": now_iso(), "message": message})
    save_job(root, job)
    return job


def _job_should_continue(root: Path, job_id: str) -> bool:
    pause_logged = False
    while True:
        job = load_job(root, job_id)
        status = job.get("status")
        if status == "cancelled":
            return False
        if status != "paused":
            if status == "queued":
                update_job(root, job_id, status="running", message="Resumed execution.")
            return True
        if not pause_logged:
            job_debug_log(root, job_id, "Paused; waiting to resume.")
            pause_logged = True
        time.sleep(0.5)


def delete_job(root: Path, job_id: str) -> None:
    path = job_path(root, job_id)
    if path.exists():
        path.unlink()


def run_enrichment_job(root: Path, paper_id: str, job_id: str, config: dict[str, Any] | None = None) -> None:
    """Background enrichment job: MinerU parsing followed by structured AI review."""
    job_debug_log(root, job_id, f"=== Job started: paper_id={paper_id} ===")
    try:
        job = load_job(root, job_id)
        if job.get("status") in {"cancelled", "paused"} and not _job_should_continue(root, job_id):
            job_debug_log(root, job_id, "Job was cancelled before start, exiting")
            return

        paper = load_paper(root, paper_id)
        job_debug_log(root, job_id, f"Paper: '{paper.get('title')}', source={paper.get('source_pdf')}, pages={paper.get('pages')}")

        config = config or load_app_config(root)
        update_job(root, job_id, status="running", stage="extracting",
                   progress=15, message="Parsing PDF with MinerU.")
        job_debug_log(root, job_id, "Stage: extracting (MinerU)")
        if not _job_should_continue(root, job_id):
            job_debug_log(root, job_id, "Cancelled during extracting")
            return

        update_job(root, job_id, stage="agent_review",
                   progress=35, message="MinerU parsed document; filling paper profile.")
        job_debug_log(root, job_id, f"Stage: agent_review (model={config.get('claude_model', 'sonnet')})")
        if not _job_should_continue(root, job_id):
            job_debug_log(root, job_id, "Cancelled before agent review")
            return

        try:
            from .agent_chat import run_agent_paper_review_sync
            t0 = datetime.now(timezone.utc)
            result = run_agent_paper_review_sync(root, paper_id, job_id, config)
            elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
            job_debug_log(root, job_id, f"Agent review completed in {elapsed:.1f}s, status={result.get('status')}")
            if not _job_should_continue(root, job_id):
                job_debug_log(root, job_id, "Cancelled after agent review returned")
                return
            if result.get("status") == "ok":
                notes_count = len(result.get("notes", []))
                job_debug_log(root, job_id, f"Agent corrections ({notes_count}):")
                for note in result.get("notes", []):
                    job_debug_log(root, job_id, f"  - {note}")
                update_job(root, job_id, stage="agent_review", progress=90,
                           message=f"MinerU profile completed: {notes_count} corrections.")
            elif result.get("status") == "error":
                reason = result.get("detail", "unknown")
                job_debug_log(root, job_id, f"Agent review failed: {reason}")
                raise RuntimeError(f"Agent review failed: {reason}")
            else:
                reason = result.get('reason', result.get('detail', 'Claude API key is not configured'))
                job_debug_log(root, job_id, f"Agent review incomplete: {reason}")
                update_job(root, job_id, stage="agent_review", progress=90,
                           message=f"MinerU parsed; profile not filled: {reason}")
        except Exception as exc:
            job_debug_log(root, job_id, f"Agent review exception: {exc}")
            import traceback as _tb
            job_debug_log(root, job_id, _tb.format_exc())
            raise

        # ── Translation (after enrichment, if paper is in English) ──
        from .translate import translate_paper_summary, translate_paper_summary_llm
        paper = load_paper(root, paper_id)
        existing_translations = paper.get("translations") if isinstance(paper.get("translations"), dict) else {}
        missing_core_concepts_translation = (
            bool(paper.get("core_concepts"))
            and (
                not isinstance(existing_translations.get("core_concepts"), list)
                or len(existing_translations.get("core_concepts") or []) < len(paper.get("core_concepts") or [])
            )
        )
        missing_key_figures_translation = (
            bool(paper.get("key_figures"))
            and (
                not isinstance(existing_translations.get("key_figures"), list)
                or len(existing_translations.get("key_figures") or []) < len(paper.get("key_figures") or [])
            )
        )
        needs_translation = (
            _text_is_english(paper.get("abstract", ""))
            and (not existing_translations or missing_core_concepts_translation or missing_key_figures_translation)
        )
        if needs_translation:
            try:
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
                if not _job_should_continue(root, job_id):
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

                if not _job_should_continue(root, job_id):
                    job_debug_log(root, job_id, "Cancelled after translation returned")
                    return
                paper["translations"] = {**existing_translations, **translations}
                paper["translation_meta"] = {
                    "engine": engine,
                    "model": config.get("claude_model") if engine == "llm" else None,
                    "updated_at": now_iso(),
                }
                save_paper(root, paper)
                field_count = len(translations)
                job_debug_log(root, job_id, f"Translation complete: {field_count} fields")
                update_job(root, job_id, stage="translating", progress=96,
                           message=f"Translated {field_count} summary fields via {engine_label}.")
            except Exception as exc:
                job_debug_log(root, job_id, f"Translation failed: {exc}")
                raise RuntimeError(f"Translation failed: {exc}") from exc
        else:
            job_debug_log(root, job_id, "Translation skipped (already translated or non-English)")

        if not _job_should_continue(root, job_id):
            job_debug_log(root, job_id, "Cancelled before completion update")
            return
        update_job(root, job_id, status="completed", stage="completed",
                   progress=100, message="Enrichment completed.")
        log(root, "update_log.md", f"Background enrichment completed for `{paper_id}`.")
        job_debug_log(root, job_id, "=== Job completed successfully ===")
    except Exception as exc:
        job_debug_log(root, job_id, f"=== Job FAILED: {exc} ===")
        import traceback as _tb
        job_debug_log(root, job_id, _tb.format_exc())
        fail_job(root, job_id, str(exc))


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


def delete_session(root: Path, session_id: str) -> None:
    path = session_path(root, session_id)
    if not path.exists():
        raise FileNotFoundError(f"Session not found: {session_id}")
    path.unlink()


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
        paper_ids = data.get("paper_ids")
        if not isinstance(paper_ids, list):
            paper_ids = []
            for message in reversed(data.get("messages") or []):
                if isinstance(message, dict) and isinstance(message.get("paper_ids"), list):
                    paper_ids = message["paper_ids"]
                    break
        paper_ids = [paper_id for paper_id in paper_ids if isinstance(paper_id, str) and paper_id]
        sessions.append({
            "id": data.get("id"),
            "title": data.get("title") or "New chat",
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "message_count": len(data.get("messages") or []),
            "paper_ids": paper_ids,
        })
    sessions.sort(key=lambda s: s.get("updated_at") or "", reverse=True)
    return sessions


def append_session_message(root: Path, session: dict[str, Any],
                           role: str, content: str,
                           paper_ids: list[str] | None = None,
                           contexts: list[dict[str, str]] | None = None,
                           agent_steps: list[dict[str, Any]] | None = None,
                           segments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"role": role, "content": content, "created_at": now_iso()}
    if paper_ids:
        message["paper_ids"] = paper_ids
        session["paper_ids"] = paper_ids
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
            "default_summary_language": "en",
            "mineru_api_token": "",
            "mineru_extraction_mode": "auto",
            "mineru_model": "vlm",
            "mineru_timeout_seconds": 900,
            "mineru_allow_remote": True,
            "sync_mode": "local",
            "git_remote": "origin",
            "git_remote_url": "",
            "git_branch": "main",
            "git_sync_pdfs": False,
            "git_sync_chats": False,
            "git_auto_sync": False,
            "git_sync_interval_minutes": 10,
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
        "default_summary_language": data.get("default_summary_language") if data.get("default_summary_language") in {"en", "zh"} else "en",
        "mineru_api_token": data.get("mineru_api_token") or "",
        "mineru_extraction_mode": data.get("mineru_extraction_mode") if data.get("mineru_extraction_mode") in {"auto", "precision", "flash"} else "auto",
        "mineru_model": data.get("mineru_model") if data.get("mineru_model") in {"vlm", "pipeline"} else "vlm",
        "mineru_timeout_seconds": max(60, min(1800, int(data.get("mineru_timeout_seconds", 900)))),
        "mineru_allow_remote": bool(data.get("mineru_allow_remote", True)),
        "sync_mode": data.get("sync_mode") or "local",
        "git_remote": data.get("git_remote") or "origin",
        "git_remote_url": data.get("git_remote_url") or "",
        "git_branch": data.get("git_branch") or "main",
        "git_sync_pdfs": bool(data.get("git_sync_pdfs", False)),
        "git_sync_chats": bool(data.get("git_sync_chats", False)),
        "git_auto_sync": bool(data.get("git_auto_sync", False)),
        "git_sync_interval_minutes": max(1, min(1440, int(data.get("git_sync_interval_minutes", 10)))),
    }


def save_app_config(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    ensure_kb(root)
    current = load_app_config(root)
    for key in ("claude_api_key", "claude_endpoint", "claude_model",
                "max_concurrency", "translation_engine", "sync_mode",
                "default_summary_language", "mineru_api_token", "mineru_extraction_mode",
                "mineru_model", "mineru_timeout_seconds", "mineru_allow_remote",
                "git_remote", "git_remote_url", "git_branch",
                "git_sync_pdfs", "git_sync_chats", "git_auto_sync",
                "git_sync_interval_minutes"):
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

def library_stats(root: Path, papers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    papers = papers if papers is not None else list_paper_summaries(root)
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
