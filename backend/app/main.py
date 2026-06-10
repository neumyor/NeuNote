from __future__ import annotations

import concurrent.futures
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .agent_chat import run_agent_answer_sync
from .kb import (
    append_session_message,
    cancel_job,
    cleanup_duplicates,
    create_job,
    create_session,
    delete_job,
    delete_paper,
    enrich_paper,
    ensure_kb,
    find_duplicates,
    ingest_pdf,
    library_stats,
    list_jobs,
    list_papers,
    list_sessions,
    load_app_config,
    load_job,
    load_paper,
    load_session,
    log,
    now_iso,
    run_enrichment_job,
    save_app_config,
    save_paper,
    save_session,
    update_job,
)
from .translate import translate_paper_summary

APP_CONFIG = Path(".kb_app_config.yaml")
DEFAULT_ROOT = Path(os.environ.get("KB_DEFAULT_ROOT", Path.cwd())).resolve()

app = FastAPI(title="NeuNote")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── parallel job executor ─────────────────────────────────────────────

_executor: concurrent.futures.ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


def _get_executor(max_workers: int = 4) -> concurrent.futures.ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None or _executor._max_workers != max_workers:
            if _executor is not None:
                _executor.shutdown(wait=False)
            _executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        return _executor


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


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    root = DEFAULT_ROOT
    if APP_CONFIG.exists():
        import yaml
        data = yaml.safe_load(APP_CONFIG.read_text(encoding="utf-8")) or {}
        if data.get("root"):
            root = Path(data["root"]).expanduser().resolve()
    ensure_kb(root)
    cfg = load_app_config(root)
    return {"root": str(root), **cfg}


@app.post("/api/config")
def set_config(config: RootConfig) -> dict[str, Any]:
    import yaml
    root = Path(config.root).expanduser().resolve()
    ensure_kb(root)
    APP_CONFIG.write_text(yaml.safe_dump({"root": str(root)}, sort_keys=False), encoding="utf-8")
    cfg = save_app_config(root, config.model_dump(exclude={"root"}, exclude_none=True))
    # Recreate executor if concurrency changed
    _get_executor(cfg.get("max_concurrency", 4))
    return {"root": str(root), **cfg}


# ── papers ────────────────────────────────────────────────────────────

@app.get("/api/papers")
def api_list_papers(root: str | None = None) -> dict[str, Any]:
    kb_root = resolve_root(root)
    papers = list_papers(kb_root)
    stats = library_stats(kb_root)
    return {"root": str(kb_root), "papers": papers, "stats": stats}


@app.get("/api/papers/{paper_id}")
def api_get_paper(paper_id: str, root: str | None = None) -> dict[str, Any]:
    kb_root = resolve_root(root)
    try:
        paper = load_paper(kb_root, paper_id)
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
    review_note: str | None = None
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

    if update.review_note:
        paper.setdefault("review_notes", []).append(update.review_note)

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
    if not source:
        raise HTTPException(status_code=404, detail="No source PDF.")
    pdf_path = (kb_root / source).resolve()
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file unavailable.")
    return FileResponse(pdf_path, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{pdf_path.name}"'})


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
        executor = _get_executor(cfg.get("max_concurrency", 4))
        executor.submit(run_enrichment_job, kb_root, paper["id"], job["id"], cfg)

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

    cfg = load_app_config(kb_root)
    # Skip if already has a running/queued job
    existing = [j for j in list_jobs(kb_root)
                if j.get("paper_id") == paper_id and j.get("status") in {"queued", "running"}]
    if existing:
        return {"root": str(kb_root), "paper": paper, "job": existing[0]}

    job = create_job(kb_root, paper_id, paper.get("title", paper_id))
    executor = _get_executor(cfg.get("max_concurrency", 4))
    executor.submit(run_enrichment_job, kb_root, paper_id, job["id"], cfg)
    return {"root": str(kb_root), "paper": paper, "job": job}


@app.post("/api/papers/enrich-all")
def api_enrich_all(background_tasks: BackgroundTasks, config: RootConfig) -> dict[str, Any]:
    kb_root = resolve_root(config.root)
    cfg = load_app_config(kb_root)
    papers = list_papers(kb_root)
    executor = _get_executor(cfg.get("max_concurrency", 4))
    jobs = []
    for paper in papers:
        pid = paper["id"]
        # Skip if already has a running/queued job
        existing = [j for j in list_jobs(kb_root)
                    if j.get("paper_id") == pid and j.get("status") in {"queued", "running"}]
        if existing:
            jobs.append(existing[0])
            continue
        job = create_job(kb_root, pid, paper.get("title", pid))
        executor.submit(run_enrichment_job, kb_root, pid, job["id"], cfg)
        jobs.append(job)
    return {"root": str(kb_root), "jobs": jobs, "queued": len(jobs)}


# ── jobs ──────────────────────────────────────────────────────────────

@app.get("/api/jobs")
def api_list_jobs(root: str | None = None) -> dict[str, Any]:
    kb_root = resolve_root(root)
    return {"root": str(kb_root), "jobs": list_jobs(kb_root)}


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
    """Translate the summary fields of a paper to Chinese using offline Argos Translate."""
    kb_root = resolve_root(config.root)
    try:
        paper = load_paper(kb_root, paper_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    translations = translate_paper_summary(paper)
    # Cache translations in the paper YAML
    paper["translations"] = translations
    save_paper(kb_root, paper)
    return {"root": str(kb_root), "translations": translations}


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


# ── chat ──────────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    question: str
    root: str | None = None
    session_id: str | None = None
    claude_api_key: str | None = None
    claude_endpoint: str | None = None
    claude_model: str | None = None
    temperature: float = 0.2
    max_context_files: int = Field(default=8, ge=1, le=20)


@app.post("/api/ask")
def api_ask(request: AskRequest) -> dict[str, Any]:
    kb_root = resolve_root(request.root)
    parts: list[str] = []
    final_session = None
    for payload in run_agent_answer_sync(kb_root, request.question,
                                          request.session_id, request.model_dump()):
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

    def event(payload: dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def generate():
        for payload in run_agent_answer_sync(kb_root, request.question,
                                              request.session_id, request.model_dump()):
            yield event(payload)

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── health ────────────────────────────────────────────────────────────

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
