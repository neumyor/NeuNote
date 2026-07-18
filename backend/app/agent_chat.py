from __future__ import annotations

import asyncio
import base64
import json
import queue
import shutil
import subprocess
import tempfile
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pypdf import PdfReader

from .kb import (
    append_session_message,
    list_papers,
    load_paper,
    load_session,
    now_iso,
    save_paper,
)

READ_PREFIXES = (
    "AGENT.md",
    "papers/",
    "logs/",
)
WRITE_PREFIXES = (
    "papers/",
    "logs/",
)
PDF_PREFIX = "originals/papers/"
AGENT_GUIDE_PATH = "AGENT.md"


def safe_rel_path(value: str) -> str:
    rel = value.strip().lstrip("/")
    if not rel or ".." in Path(rel).parts:
        raise ValueError("Path must be a relative path inside the knowledge base.")
    return rel


def assert_allowed_read(rel: str) -> None:
    if rel.startswith(PDF_PREFIX):
        raise ValueError("Use the PDF tools for source PDFs.")
    if not any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in READ_PREFIXES):
        raise ValueError(f"Read denied for `{rel}`. Allowed: AGENT.md, papers/, logs/.")


def assert_allowed_write(rel: str) -> None:
    if rel.startswith(PDF_PREFIX):
        raise ValueError("Writes to originals/papers are forbidden.")
    if not any(rel.startswith(prefix) for prefix in WRITE_PREFIXES):
        raise ValueError(f"Write denied for `{rel}`. Allowed: papers/, logs/.")


def safe_join(root: Path, rel: str) -> Path:
    path = (root / rel).resolve()
    if root.resolve() not in path.parents and path != root.resolve():
        raise ValueError("Path escapes knowledge root.")
    return path


def paper_pdf_path(root: Path, paper_id: str) -> Path:
    paper = load_paper(root, paper_id)
    source = paper.get("source_pdf")
    if not source or not str(source).startswith(PDF_PREFIX):
        raise ValueError(f"Paper has no allowed source PDF: {paper_id}")
    path = safe_join(root, source)
    if not path.exists():
        raise ValueError(f"Source PDF does not exist: {source}")
    return path


def _compact(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[truncated]"


def _compact_json(value: Any, limit: int = 700) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "... [truncated]"


def _parse_page_spec(spec: str | None, page_count: int, *, default_count: int = 3, max_pages: int = 12) -> list[int]:
    if page_count < 1:
        return []
    raw = (spec or "").strip().lower()
    if not raw:
        return list(range(1, min(page_count, default_count) + 1))
    selected: list[int] = []
    if raw in {"all", "*"}:
        selected = list(range(1, page_count + 1))
    else:
        for token in raw.replace("，", ",").split(","):
            part = token.strip()
            if not part:
                continue
            if "-" in part:
                start_raw, end_raw = part.split("-", 1)
                start = int(start_raw) if start_raw.strip() else 1
                end = int(end_raw) if end_raw.strip() else page_count
                if start > end:
                    start, end = end, start
                selected.extend(range(start, end + 1))
            else:
                selected.append(int(part))
    deduped: list[int] = []
    seen: set[int] = set()
    for page in selected:
        if page < 1 or page > page_count or page in seen:
            continue
        deduped.append(page)
        seen.add(page)
        if len(deduped) >= max_pages:
            break
    return deduped


def _pdf_page_count(path: Path) -> int:
    reader = PdfReader(str(path))
    return len(reader.pages)


def _intend_schema(description: str) -> dict[str, str]:
    return {
        "type": "string",
        "description": f"{description} Write in the user's language, under 24 Chinese characters or 12 English words.",
    }


def _tool_error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _describe_exception(exc: BaseException) -> str:
    chain = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    cause = exc.__cause__ or exc.__context__
    if cause:
        return f"{chain}\nCaused by: {_describe_exception(cause)}"
    return chain


async def run_agent_answer(root: Path, question: str,
                           session_id: str | None,
                           config: dict[str, Any] | None = None,
                           paper_id: str | None = None,
                           paper_ids: list[str] | None = None) -> Iterable[dict[str, Any]]:
    try:
        from claude_code_sdk import (
            AssistantMessage,
            ClaudeCodeOptions,
            ClaudeSDKClient,
            ResultMessage,
            TextBlock,
            ToolResultBlock,
            ToolUseBlock,
            UserMessage,
            create_sdk_mcp_server,
            tool,
        )
    except Exception as exc:
        yield {"type": "error", "detail": f"Claude Code SDK is unavailable: {exc}"}
        return

    # ── tools ─────────────────────────────────────────────────────────

    @tool(
        name="kb_list",
        description="List paper YAML files in the knowledge base.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "intend": _intend_schema("Explain why you are listing this directory for the user."),
            },
            "required": ["path", "intend"],
        },
    )
    async def kb_list(args: dict) -> dict:
        try:
            rel = safe_rel_path(args["path"])
            if not any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in ("papers/", "logs/")):
                return _tool_error("Can only list papers/ or logs/.")
            path = safe_join(root, rel)
            if not path.exists() or not path.is_dir():
                return _tool_error("Directory not found.")
            files = sorted(str(item.relative_to(root)) for item in path.rglob("*") if item.is_file())
            return {"content": [{"type": "text", "text": "\n".join(files[:200])}]}
        except Exception as exc:
            return _tool_error(str(exc))

    @tool(
        name="kb_read",
        description="Read a paper YAML, AGENT.md, or log file.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "intend": _intend_schema("Explain what information you are reading for the user."),
            },
            "required": ["path", "intend"],
        },
    )
    async def kb_read(args: dict) -> dict:
        try:
            rel = safe_rel_path(args["path"])
            assert_allowed_read(rel)
            path = safe_join(root, rel)
            if not path.exists() or not path.is_file():
                return _tool_error("File not found.")
            return {"content": [{"type": "text", "text": _compact(path.read_text(encoding="utf-8", errors="ignore"))}]}
        except Exception as exc:
            return _tool_error(str(exc))

    @tool(
        name="kb_write",
        description="Write to a paper YAML file. Only papers/ paths and logs/ are allowed.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "intend": _intend_schema("Explain what verified correction you are writing for the user."),
            },
            "required": ["path", "content", "intend"],
        },
    )
    async def kb_write(args: dict) -> dict:
        try:
            rel = safe_rel_path(args["path"])
            assert_allowed_write(rel)
            path = safe_join(root, rel)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args["content"], encoding="utf-8")
            return {"content": [{"type": "text", "text": f"Wrote {rel}"}]}
        except Exception as exc:
            return _tool_error(str(exc))

    @tool(
        name="kb_pdf_info",
        description="Inspect the source PDF metadata for a paper, including total page count and source path.",
        input_schema={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string"},
                "intend": _intend_schema("Explain why you are checking PDF metadata for the user."),
            },
            "required": ["paper_id", "intend"],
        },
    )
    async def kb_pdf_info(args: dict) -> dict:
        try:
            paper = load_paper(root, args["paper_id"])
            path = paper_pdf_path(root, args["paper_id"])
            info = {
                "paper_id": args["paper_id"],
                "title": paper.get("title"),
                "source_pdf": paper.get("source_pdf"),
                "page_count": _pdf_page_count(path),
            }
            return {"content": [{"type": "text", "text": json.dumps(info, ensure_ascii=False, indent=2)}]}
        except Exception as exc:
            return _tool_error(str(exc))

    @tool(
        name="kb_read_pdf_pages",
        description=(
            "Extract text from specific 1-based PDF pages for a paper. "
            "Use pages like '1,3-5,10-' instead of broad max-page reads."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string"},
                "pages": {
                    "type": "string",
                    "description": "1-based page selector, e.g. '1', '2-4', '1,5,9-11', '10-', or 'all'.",
                },
                "char_limit_per_page": {"type": "integer", "minimum": 1000, "maximum": 16000},
                "intend": _intend_schema("Explain what evidence you expect to read from these PDF pages."),
            },
            "required": ["paper_id", "pages", "intend"],
        },
    )
    async def kb_read_pdf_pages(args: dict) -> dict:
        try:
            path = paper_pdf_path(root, args["paper_id"])
            reader = PdfReader(str(path))
            pages = _parse_page_spec(str(args.get("pages") or ""), len(reader.pages), max_pages=12)
            if not pages:
                return _tool_error("No valid pages selected.")
            char_limit = min(max(int(args.get("char_limit_per_page") or 8000), 1000), 16000)
            blocks = [
                f"PDF: {path.name}",
                f"page_count: {len(reader.pages)}",
                f"selected_pages: {', '.join(str(page) for page in pages)}",
            ]
            for page_number in pages:
                text = reader.pages[page_number - 1].extract_text() or ""
                blocks.append(f"\n--- page {page_number} ---\n{_compact(text.strip(), limit=char_limit)}")
            return {"content": [{"type": "text", "text": "\n".join(blocks)}]}
        except Exception as exc:
            return _tool_error(str(exc))

    @tool(
        name="kb_render_pdf_pages",
        description=(
            "Render specific PDF pages as images for visual inspection of figures, tables, equations, or layout. "
            "Use after kb_pdf_info/kb_read_pdf_pages when the text extraction is insufficient."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string"},
                "pages": {
                    "type": "string",
                    "description": "1-based page selector, e.g. '4', '6-7', or '2,9'. Up to 4 pages per call.",
                },
                "dpi": {"type": "integer", "minimum": 72, "maximum": 180},
                "intend": _intend_schema("Explain what visual evidence you are checking on these PDF pages."),
            },
            "required": ["paper_id", "pages", "intend"],
        },
    )
    async def kb_render_pdf_pages(args: dict) -> dict:
        try:
            renderer = shutil.which("pdftoppm")
            if not renderer:
                return _tool_error("PDF page rendering is unavailable because pdftoppm is not installed.")
            path = paper_pdf_path(root, args["paper_id"])
            page_count = _pdf_page_count(path)
            pages = _parse_page_spec(str(args.get("pages") or ""), page_count, max_pages=4)
            if not pages:
                return _tool_error("No valid pages selected.")
            dpi = min(max(int(args.get("dpi") or 144), 72), 180)
            content: list[dict[str, Any]] = [{
                "type": "text",
                "text": (
                    f"Rendered {path.name} at {dpi} dpi. "
                    f"page_count: {page_count}; selected_pages: {', '.join(str(page) for page in pages)}"
                ),
            }]
            with tempfile.TemporaryDirectory(prefix="neunote-pdf-pages-") as temp_dir:
                temp_path = Path(temp_dir)
                for page_number in pages:
                    output_prefix = temp_path / f"page-{page_number}"
                    subprocess.run(
                        [
                            renderer,
                            "-png",
                            "-singlefile",
                            "-f",
                            str(page_number),
                            "-l",
                            str(page_number),
                            "-r",
                            str(dpi),
                            str(path),
                            str(output_prefix),
                        ],
                        check=True,
                        capture_output=True,
                    )
                    image_path = output_prefix.with_suffix(".png")
                    data = base64.b64encode(image_path.read_bytes()).decode("ascii")
                    content.append({"type": "text", "text": f"page {page_number}"})
                    content.append({"type": "image", "data": data, "mimeType": "image/png"})
            return {"content": content}
        except Exception as exc:
            return _tool_error(str(exc))

    server = create_sdk_mcp_server(
        name="neunote",
        version="1.0.0",
        tools=[kb_list, kb_read, kb_write, kb_pdf_info, kb_read_pdf_pages, kb_render_pdf_pages],
    )

    session = load_session(root, session_id)
    history = "\n".join(
        f"{m.get('role')}: {m.get('content')}"
        for m in (session.get("messages") or [])[-8:]
    )
    mentioned_ids: list[str] = []
    for value in [paper_id, *(paper_ids or [])]:
        if value and value not in mentioned_ids:
            mentioned_ids.append(value)

    paper_scope = ""
    if mentioned_ids:
        lines = ["Mentioned papers:"]
        for mentioned_id in mentioned_ids:
            try:
                scoped_paper = load_paper(root, mentioned_id)
                lines.append(f"- id: {scoped_paper.get('id')}; title: {scoped_paper.get('title') or mentioned_id}")
            except Exception:
                lines.append(f"- id: {mentioned_id}; title: unavailable")
        paper_scope = "\n".join(lines) + "\n\nFor this chat, start from the mentioned paper YAML files. Compare across mentioned papers when the user asks, and only broaden to the full library when explicitly requested.\n\n"
    else:
        paper_scope = "No papers are mentioned for this turn. Ask a general library question, or list papers/ when you need to discover relevant papers.\n\n"

    prompt = f"""Question:
{question}

{paper_scope}\
Recent chat history:
{history}

Workflow:
1. Read AGENT.md for rules.
2. If papers are mentioned, read each mentioned paper YAML first. Otherwise list papers/ only when the question requires discovering relevant papers.
3. If critical evidence is missing from a mentioned or discovered paper YAML, use kb_pdf_info and then kb_read_pdf_pages with precise pages or page ranges.
4. Use kb_render_pdf_pages for figures, tables, equations, screenshots, or layout-sensitive claims that text extraction cannot verify.
5. Answer strictly from paper YAML content and verified PDF evidence. Do not add outside knowledge.
6. Separate evidence from inference: if a claim is explicitly stated by the paper, say so with the paper ID; if you infer it from paper content, label it as your inference; if the paper does not provide enough evidence, say that the paper does not explicitly state it.
7. Answer with citations to paper IDs and mention when PDF text or visual verification was used.
8. Only write paper updates when correcting verified errors.

Tool UI:
- Every tool call requires an `intend` field. This string is shown directly to the user as the tool status.
- Keep `intend` short, concrete, and user-facing, for example: "正在读取论文摘要", "正在查看第 4 页图表", "正在保存修正".
- Do not put raw tool names, file paths only, JSON, or private chain-of-thought in `intend`.
"""

    config = config or {}
    env = {}
    if config.get("claude_api_key"):
        env["ANTHROPIC_API_KEY"] = config["claude_api_key"]
    if config.get("claude_endpoint"):
        env["ANTHROPIC_BASE_URL"] = config["claude_endpoint"]

    stderr_temp = tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=True)
    options = ClaudeCodeOptions(
        cwd=str(root),
        max_turns=12,
        model=config.get("claude_model") or "sonnet",
        env=env,
        permission_mode="default",
        allowed_tools=[
            "mcp__neunote__kb_list",
            "mcp__neunote__kb_read",
            "mcp__neunote__kb_write",
            "mcp__neunote__kb_pdf_info",
            "mcp__neunote__kb_read_pdf_pages",
            "mcp__neunote__kb_render_pdf_pages",
        ],
        disallowed_tools=["Read", "Write", "Edit", "MultiEdit", "Bash", "Grep", "Glob", "LS", "WebFetch", "WebSearch"],
        mcp_servers={"neunote": server},
        extra_args={"debug-to-stderr": None},
        debug_stderr=stderr_temp,
        system_prompt=(
            "You are a paper knowledge-base agent. Use only the neunote tools. "
            "Answer strictly according to the paper YAML files and source PDF evidence available through those tools. "
            "Do not use outside knowledge, guesses, or unstated background facts as if they came from the paper. "
            "When the original paper explicitly states something, attribute it to the paper ID. "
            "When you make a necessary inference from paper content, clearly label it as inference. "
            "When the paper does not explicitly state the answer or evidence is insufficient, say so directly. "
            "Never claim you read PDF text unless you called kb_read_pdf_pages. "
            "Never claim you visually inspected a PDF page, figure, table, or equation unless you called kb_render_pdf_pages. "
            "Prefer paper YAML files before PDF extraction. "
            "When using PDFs, choose specific 1-based pages or page ranges rather than broad reads. "
            "Every tool call must include a short user-facing `intend` field explaining the immediate action. "
            "Only write paper updates when correcting verified errors; never modify originals/papers."
        ),
    )

    answer_parts: list[str] = []
    agent_steps: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []

    def attach_tool_result(tool_id: str, detail: str, is_error: bool) -> None:
        for segment in reversed(segments):
            if segment.get("type") == "tool" and segment.get("id") == tool_id:
                segment["result"] = detail
                segment["is_error"] = is_error
                return

    yield {"type": "session", "session": session}

    start_step = {
        "kind": "progress",
        "title": "Scanning paper YAML files",
        "detail": "The agent starts by reading AGENT.md and listing papers/ directory.",
    }
    agent_steps.append(start_step)
    segments.append({"type": "progress", **start_step})
    yield {"type": "progress", **start_step}

    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            answer_parts.append(block.text)
                            if segments and segments[-1].get("type") == "text":
                                segments[-1]["content"] = f"{segments[-1].get('content', '')}{block.text}"
                            else:
                                segments.append({"type": "text", "content": block.text})
                            yield {"type": "delta", "delta": block.text}
                        elif isinstance(block, ToolUseBlock):
                            tool_input = getattr(block, "input", None)
                            step = {
                                "id": block.id,
                                "kind": "tool",
                                "title": block.name,
                                "detail": _compact_json(tool_input) if tool_input is not None else "",
                            }
                            agent_steps.append(step)
                            segments.append({"type": "tool", **step})
                            yield {"type": "tool", "id": block.id, "name": block.name, "input": tool_input, "detail": step["detail"]}
                        elif isinstance(block, ToolResultBlock):
                            tool_result = getattr(block, "content", None)
                            detail = _compact_json(tool_result, limit=1400)
                            attach_tool_result(block.tool_use_id, detail, bool(block.is_error))
                            yield {
                                "type": "tool_result",
                                "tool_use_id": block.tool_use_id,
                                "result": tool_result,
                                "detail": detail,
                                "is_error": bool(block.is_error),
                            }
                elif isinstance(message, UserMessage):
                    content = message.content
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, ToolResultBlock):
                                tool_result = getattr(block, "content", None)
                                detail = _compact_json(tool_result, limit=1400)
                                attach_tool_result(block.tool_use_id, detail, bool(block.is_error))
                                yield {
                                    "type": "tool_result",
                                    "tool_use_id": block.tool_use_id,
                                    "result": tool_result,
                                    "detail": detail,
                                    "is_error": bool(block.is_error),
                                }
                elif isinstance(message, ResultMessage):
                    if message.is_error:
                        yield {"type": "error", "detail": f"Claude Code ended with error: {message.subtype}"}
                        return
        answer = "".join(answer_parts).strip()
        append_session_message(root, session, "user", question, paper_ids=mentioned_ids)
        append_session_message(root, session, "assistant", answer, agent_steps=agent_steps, segments=segments)
        yield {"type": "done", "answer": answer, "session": session}
    except Exception as exc:
        stderr_temp.flush()
        stderr_temp.seek(0)
        stderr_tail = stderr_temp.read()[-12000:].strip()
        detail = f"Claude Code agent failed:\n{_describe_exception(exc)}"
        if stderr_tail:
            detail += f"\n\nClaude CLI stderr:\n{stderr_tail}"
        yield {"type": "error", "detail": detail}
    finally:
        stderr_temp.close()


def run_agent_answer_sync(root: Path, question: str, session_id: str | None,
                          config: dict[str, Any] | None = None,
                          paper_id: str | None = None,
                          paper_ids: list[str] | None = None) -> Iterable[dict[str, Any]]:
    output: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def worker() -> None:
        async def produce() -> None:
            async for item in run_agent_answer(root, question, session_id, config, paper_id, paper_ids):
                output.put(item)
            output.put(None)

        asyncio.run(produce())

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    while True:
        item = output.get()
        if item is None:
            break
        yield item


# ── agent paper review (used by enrichment job) ─────────────────────

PAPER_REVIEW_SYSTEM_PROMPT = """\
You are a precise academic paper reviewer. Your task is to review a paper's \
metadata extracted by an automated pipeline and correct any errors or fill in \
missing fields by examining the provided PDF text.

Rules:
- Only fill a field when the PDF text provides clear evidence.
- If evidence is ambiguous or absent, leave the field as null in your patch.
- Never invent authors, venues, DOIs, arXiv IDs, or years.
- Citations in the references section are NOT the paper's own venue.
- Keep method/experiment/limitation entries as concise, factual bullet points.
- author_affiliations should list the paper authors' teams, labs, companies,
  universities, or institutions when they are explicitly visible in the PDF.
  Prefer team/institution names over postal addresses or email domains.
- core_concepts should contain 5-8 central concepts needed to understand this
  paper. Each explanation must be plain, accessible, and specific to how the
  paper uses the concept.
- key_figures should identify the 1-3 most important figures/pages for
  understanding the paper. Use the page markers in the PDF text to find
  candidate figures, then use the available PDF figure tools to visually inspect
  the page and save a readable crop of the actual figure area. Do not output a
  key_figure unless you have either reused an existing image_path or saved a new
  crop with save_figure_crop. Include the exact figure label when visible, for
  example "Figure 2" or "Fig. 3".
- In fast_pillow mode, figure candidates are already provided in the prompt.
  Do not call visual tools; choose from those candidates and copy image_path,
  crop, and crop_method exactly. In agent_pymupdf mode, use the figure tools.
- During re-enrichment, prefer newly extracted figure assets over existing
  image_path values. Reuse old image_path only when the prompt explicitly says
  no new figure extraction was performed.
- Figure crops must tightly cover the figure graphic and optional caption only.
  Do not save whole pages, page headers, author blocks, unrelated body text, or
  neighboring tables. Use normalized top-left page coordinates from the rendered
  page. After save_figure_crop returns, copy its image_path, crop, and crop_method
  fields into the matching key_figures item in your final JSON.
- Prefer list_figure_candidates and save_figure_candidate when available. These
  tools use PDF drawing geometry near the caption and usually produce tighter
  crops than manual coordinates. Use preview_figure_crop before saving a manual
  crop. Use manual save_figure_crop only when no suitable candidate exists.
- Write one_sentence, problem, contributions, method, experiments, and
  limitations in a readable, self-contained style. Avoid vague fragments:
  include the key object, action, mechanism, evidence, or tradeoff needed for a
  reader to understand the point without rereading the PDF text.
- contributions should be specific claims from the paper, not generic descriptions.
- The one_sentence should be a single sentence summary of the core contribution,
  not just a restatement of the title.
- For title: only provide it when the current title is clearly wrong (e.g. it looks \
  like a PDF filename slug, contains garbled text, or is a section heading). \
  Do NOT change a title that is merely imperfectly formatted.\n  The corrected title must be in Title Case (capitalize first letter of each\n  major word), never ALL CAPS. For example "MY PAPER TITLE" → "My Paper Title".
- For tags: review the current tags and the known-tags list provided in the prompt.\
  Keep tags that still apply, remove any that don't, and add NEW tags only when the\
  paper clearly covers a topic not represented by any existing tag. Be conservative:\
  do NOT create tags that are synonyms of existing ones (e.g. don't add \"llms\" if\
  \"llm\" exists). Use lowercase, underscore_separated names.

Output ONLY a valid JSON object with this schema:
{
  "title": "string" | null,
  "authors": ["string"] | null,
  "author_affiliations": ["string"] | null,
  "year": number | null,
  "venue": "string" | null,
  "doi": "string" | null,
  "arxiv_id": "string" | null,
  "abstract": "string" | null,
  "core_concepts": [{"concept": "string", "explanation": "string"}] | null,
  "key_figures": [{"label": "string", "title": "string", "page": number, "caption": "string", "reason": "string", "image_path": "string", "crop": {"x0": number, "y0": number, "x1": number, "y1": number}, "crop_method": "string"}] | null,
  "one_sentence": "string" | null,
  "problem": "string" | null,
  "contributions": ["string"] | null,
  "method": ["string"] | null,
  "experiments": ["string"] | null,
  "limitations": ["string"] | null,
  "tags": ["string"] | null,
  "review_notes": ["string"]
}

For tags: provide the COMPLETE list of tags that should be on this paper (keep + remove + add).
Include review_notes explaining what you changed and what remains unknown.
"""


def _build_review_prompt(
    paper: dict[str, Any],
    pdf_text: str,
    known_tags: list[str] | None = None,
    figure_candidates: list[dict[str, Any]] | None = None,
    figure_mode: str = "agent_pymupdf",
) -> str:
    identity = f"""\
Current paper metadata:
- id: {paper.get('id')}
- title: {paper.get('title')}
- authors: {json.dumps(paper.get('authors', []))}
- author_affiliations: {json.dumps(paper.get('author_affiliations', []))}
- year: {paper.get('year')}
- venue: {paper.get('venue')}
- doi: {paper.get('doi')}
- arxiv_id: {paper.get('arxiv_id')}
- pages: {paper.get('pages')}
- tags: {json.dumps(paper.get('tags', []))}
- status: {paper.get('status')}
"""
    summary = f"""\
Current extracted content:
- one_sentence: {paper.get('one_sentence', '')}
- problem: {paper.get('problem', '')}
- abstract: {paper.get('abstract', '')[:300]}
- core_concepts: {json.dumps(paper.get('core_concepts', []), ensure_ascii=False)}
- key_figures: {json.dumps(paper.get('key_figures', []), ensure_ascii=False)}
- contributions: {json.dumps(paper.get('contributions', []))}
- method: {json.dumps(paper.get('method', []))}
- experiments: {json.dumps(paper.get('experiments', []))}
- limitations: {json.dumps(paper.get('limitations', []))}
"""
    tags_info = ""
    if known_tags:
        tags_info = f"""\
Known tags across the library (avoid duplicates/synonyms):
{json.dumps(sorted(known_tags))}

"""
    figure_info = ""
    if figure_mode == "fast_pillow":
        figure_info = f"""\
Fast figure extraction candidates:
{json.dumps(figure_candidates or [], ensure_ascii=False, indent=2)}

For key_figures, choose the most important 1-3 items from this candidate list.
Do not call visual figure tools in fast_pillow mode. Copy image_path, crop, and
crop_method exactly from the selected candidate. You may improve title, caption,
and reason using the PDF text.

"""
    pdf_snippet = pdf_text[:16000]
    return f"""\
Review this paper's metadata against the source PDF text and output corrections.

{identity}

{summary}

{tags_info}{figure_info}Source PDF text (first pages with 1-based page markers):
---
{pdf_snippet}
---

Output ONLY the JSON patch object as specified.
"""


def _title_looks_bad(title: str) -> bool:
    """Check if the title is likely auto-generated garbage or a conference header."""
    import re as _re
    t = title.strip()
    if not t or len(t) < 10:
        return True
    # Filename slug (underscores, no spaces)
    if "_" in t and " " not in t:
        return True
    # Generic fallback values
    if t.lower() in {"paper", "untitled", "unknown", "pdf", "document"}:
        return True
    if t.lower().endswith(".pdf"):
        return True
    # Just numbers/dots
    if _re.match(r"^[\d.]+$", t):
        return True
    # Low alpha ratio (garbled text)
    alpha_ratio = sum(1 for c in t if c.isalpha() or c.isspace()) / max(len(t), 1)
    if alpha_ratio < 0.5:
        return True
    # ── conference / journal header patterns ──
    low = t.lower()
    if _re.search(r"proceedings of|findings of|conference on|workshop on|symposium on", low):
        return True
    if _re.search(r"association for|society for|international (conference|joint)", low):
        return True
    if _re.search(r"pages?\s*\d+", low):  # "pages 14510"
        return True
    if _re.search(r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b", low):
        return True  # month names in title → likely a header
    if "©" in t or "&copy;" in t:
        return True
    return False


def _titles_differ_substantially(current: str, suggested: str) -> bool:
    """Check if the agent's title is a substantially different correction."""
    import re as _re
    # Tokenize: lowercase words, remove punctuation
    def words(s: str) -> set[str]:
        return set(_re.findall(r"[a-z0-9]{3,}", s.lower()))
    curr_words = words(current)
    sugg_words = words(suggested)
    if not curr_words or not sugg_words:
        return False
    # Jaccard similarity: intersection / union
    overlap = curr_words & sugg_words
    similarity = len(overlap) / max(len(curr_words | sugg_words), 1)
    # If <30% of words overlap, the titles are substantially different
    return similarity < 0.3


def _merge_review_patch(
    paper: dict[str, Any],
    patch: dict[str, Any],
    *,
    preserve_existing_figures: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    """Merge agent corrections into paper. Returns (paper, notes)."""
    notes: list[str] = []

    # ── title: only correct if current looks bad OR substantially different ──
    title = patch.get("title")
    if title and title != paper.get("title", ""):
        current = paper.get("title", "")
        if _title_looks_bad(current) or _titles_differ_substantially(current, title):
            paper["title"] = title
            notes.append(f"title: '{_brief(current)}' → '{_brief(title)}'")

    # ── identity fields: if agent provides a value, apply it ──
    for key in ("authors", "author_affiliations", "year", "venue", "doi", "arxiv_id"):
        value = patch.get(key)
        if value is not None and value != "" and value != []:
            old = paper.get(key)
            paper[key] = value
            notes.append(f"{key}: {_brief(old)} → {_brief(value)}")

    # ── text fields: if agent provides a value, apply it ──
    for key in ("abstract", "one_sentence", "problem"):
        value = patch.get(key)
        if value and value != paper.get(key, ""):
            old = str(paper.get(key, ""))[:60]
            paper[key] = value
            notes.append(f"{key}: updated (was: '{old}...')")

    # ── structured concept definitions: keep only well-formed items ──
    core_concepts = patch.get("core_concepts")
    if isinstance(core_concepts, list):
        normalized_concepts = []
        for item in core_concepts:
            if not isinstance(item, dict):
                continue
            concept = str(item.get("concept") or "").strip()
            explanation = str(item.get("explanation") or "").strip()
            if concept and explanation:
                normalized_concepts.append({"concept": concept, "explanation": explanation})
        if normalized_concepts:
            current = paper.get("core_concepts") or []
            paper["core_concepts"] = normalized_concepts[:8]
            notes.append(f"core_concepts: replaced {len(current)} items → {len(paper['core_concepts'])} items")

    # ── selected key figures: backend renders images after merge ──
    key_figures = patch.get("key_figures")
    if isinstance(key_figures, list):
        normalized_figures = []
        current_figures = [f for f in (paper.get("key_figures") or []) if isinstance(f, dict)]

        def existing_figure_asset(page: int, label: str, title: str) -> dict[str, Any]:
            label_low = label.lower()
            title_low = title.lower()
            for current in current_figures:
                try:
                    current_page = int(current.get("page") or 0)
                except (TypeError, ValueError):
                    continue
                if current_page != page:
                    continue
                current_label = str(current.get("label") or "").lower()
                current_title = str(current.get("title") or "").lower()
                if label_low and current_label == label_low:
                    return current
                if title_low and current_title == title_low:
                    return current
                if not label_low and not title_low:
                    return current
            return {}

        for item in key_figures:
            if not isinstance(item, dict):
                continue
            try:
                page = int(item.get("page") or 0)
            except (TypeError, ValueError):
                continue
            title = str(item.get("title") or "").strip()
            label = str(item.get("label") or "").strip()
            caption = str(item.get("caption") or "").strip()
            reason = str(item.get("reason") or "").strip()
            if page >= 1 and (label or title or caption):
                normalized = {
                    "label": label,
                    "title": title or f"Figure on page {page}",
                    "page": page,
                    "caption": caption,
                    "reason": reason,
                }
                existing = existing_figure_asset(page, label, title) if preserve_existing_figures else {}
                for asset_key in ("image_path", "crop", "crop_method"):
                    if item.get(asset_key):
                        normalized[asset_key] = item[asset_key]
                    elif existing.get(asset_key):
                        normalized[asset_key] = existing[asset_key]
                normalized_figures.append(normalized)
        if normalized_figures:
            current = paper.get("key_figures") or []
            paper["key_figures"] = normalized_figures[:3]
            notes.append(f"key_figures: replaced {len(current)} items → {len(paper['key_figures'])} items")

    # ── list fields: if agent provides a list, apply it ──
    for key in ("contributions", "method", "experiments", "limitations"):
        value = patch.get(key)
        if value and len(value) > 0:
            current = paper.get(key) or []
            paper[key] = value
            notes.append(f"{key}: replaced {len(current)} items → {len(value)} items")

    # ── tags: if agent provides tags, use them (agent decides keep/remove/add) ──
    new_tags = patch.get("tags")
    if new_tags is not None and isinstance(new_tags, list):
        old_tags = set(paper.get("tags", []))
        new_set = set(new_tags)
        added = new_set - old_tags
        removed = old_tags - new_set
        paper["tags"] = sorted(new_set)
        if added:
            notes.append(f"tags: added {sorted(added)}")
        if removed:
            notes.append(f"tags: removed {sorted(removed)}")

    return paper, notes


def _brief(value: Any) -> str:
    s = str(value)
    return (s[:60] + "...") if len(s) > 60 else s


PAPER_REVIEW_TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_figure_candidates",
        "description": (
            "List candidate figure crops detected from PDF captions and drawing geometry. "
            "Prefer these candidates over manually guessed coordinates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "paper_id": {"type": "string"},
                "pages": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                    "description": "Optional 1-based pages to inspect. Omit to scan the first 12 pages.",
                },
            },
            "required": ["paper_id"],
        },
    },
    {
        "name": "render_pdf_page",
        "description": (
            "Render one source PDF page as an image for visual inspection. "
            "Use this before choosing crop coordinates for key figures."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "paper_id": {"type": "string"},
                "page": {"type": "integer", "minimum": 1},
                "dpi": {"type": "integer", "minimum": 72, "maximum": 180},
            },
            "required": ["paper_id", "page"],
        },
    },
    {
        "name": "preview_figure_crop",
        "description": (
            "Preview a proposed normalized crop before saving it. Use this for manual crops "
            "to ensure body text or unrelated tables are not included."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "paper_id": {"type": "string"},
                "page": {"type": "integer", "minimum": 1},
                "crop": {
                    "type": "object",
                    "properties": {
                        "x0": {"type": "number", "minimum": 0, "maximum": 1},
                        "y0": {"type": "number", "minimum": 0, "maximum": 1},
                        "x1": {"type": "number", "minimum": 0, "maximum": 1},
                        "y1": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["x0", "y0", "x1", "y1"],
                },
                "dpi": {"type": "integer", "minimum": 72, "maximum": 180},
            },
            "required": ["paper_id", "page", "crop"],
        },
    },
    {
        "name": "save_figure_candidate",
        "description": (
            "Save a detected figure candidate as a cropped PNG. Use candidate_id from "
            "list_figure_candidates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "paper_id": {"type": "string"},
                "candidate_id": {"type": "string"},
                "figure_index": {"type": "integer", "minimum": 1, "maximum": 3},
                "include_caption": {"type": "boolean"},
                "dpi": {"type": "integer", "minimum": 120, "maximum": 240},
            },
            "required": ["paper_id", "candidate_id", "figure_index"],
        },
    },
    {
        "name": "save_figure_crop",
        "description": (
            "Save a cropped PNG for a key paper figure. Coordinates are normalized "
            "page coordinates in [0, 1], measured from the top-left of the rendered page."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "paper_id": {"type": "string"},
                "page": {"type": "integer", "minimum": 1},
                "figure_index": {"type": "integer", "minimum": 1, "maximum": 3},
                "crop": {
                    "type": "object",
                    "properties": {
                        "x0": {"type": "number", "minimum": 0, "maximum": 1},
                        "y0": {"type": "number", "minimum": 0, "maximum": 1},
                        "x1": {"type": "number", "minimum": 0, "maximum": 1},
                        "y1": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["x0", "y0", "x1", "y1"],
                },
                "dpi": {"type": "integer", "minimum": 120, "maximum": 240},
            },
            "required": ["paper_id", "page", "figure_index", "crop"],
        },
    },
]


def _image_tool_result(tool_use_id: str, text: str, image_base64: str) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": [
            {"type": "text", "text": text},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image_base64,
                },
            },
        ],
    }


def _text_tool_result(tool_use_id: str, text: str, *, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": [{"type": "text", "text": text}],
    }
    if is_error:
        result["is_error"] = True
    return result


def _execute_paper_review_tool(root: Path, tool_use: dict[str, Any]) -> dict[str, Any]:
    from .figure_tools import (
        list_figure_candidates,
        preview_figure_crop,
        render_pdf_page,
        save_figure_candidate,
        save_figure_crop,
    )

    tool_id = str(tool_use.get("id") or "")
    name = str(tool_use.get("name") or "")
    args = tool_use.get("input") if isinstance(tool_use.get("input"), dict) else {}
    try:
        if name == "list_figure_candidates":
            pages = args.get("pages")
            result = list_figure_candidates(
                root,
                str(args["paper_id"]),
                [int(page) for page in pages] if isinstance(pages, list) else None,
            )
            return _text_tool_result(tool_id, json.dumps(result, ensure_ascii=False, indent=2))
        if name == "render_pdf_page":
            result = render_pdf_page(
                root,
                str(args["paper_id"]),
                int(args["page"]),
                int(args.get("dpi") or 120),
            )
            text = json.dumps({k: v for k, v in result.items() if k != "image_base64"}, ensure_ascii=False, indent=2)
            return _image_tool_result(tool_id, text, result["image_base64"])
        if name == "preview_figure_crop":
            result = preview_figure_crop(
                root,
                str(args["paper_id"]),
                int(args["page"]),
                args["crop"],
                int(args.get("dpi") or 120),
            )
            text = json.dumps({k: v for k, v in result.items() if k != "image_base64"}, ensure_ascii=False, indent=2)
            return _image_tool_result(tool_id, text, result["image_base64"])
        if name == "save_figure_candidate":
            result = save_figure_candidate(
                root,
                str(args["paper_id"]),
                str(args["candidate_id"]),
                int(args["figure_index"]),
                bool(args.get("include_caption") or False),
                int(args.get("dpi") or 180),
            )
            return _text_tool_result(tool_id, json.dumps(result, ensure_ascii=False, indent=2))
        if name == "save_figure_crop":
            result = save_figure_crop(
                root,
                str(args["paper_id"]),
                int(args["page"]),
                int(args["figure_index"]),
                args["crop"],
                int(args.get("dpi") or 180),
            )
            return _text_tool_result(tool_id, json.dumps(result, ensure_ascii=False, indent=2))
        return _text_tool_result(tool_id, f"Unknown tool: {name}", is_error=True)
    except Exception as exc:
        return _text_tool_result(tool_id, str(exc), is_error=True)


async def run_agent_paper_review(root: Path, paper_id: str,
                                  config: dict[str, Any] | None = None,
                                  job_id: str | None = None) -> dict[str, Any]:
    """Run a Claude agent to review and correct paper metadata."""
    from .kb import _known_tags, extract_pdf_text, job_debug_log, load_paper, now_iso, save_paper

    def _dbg(msg: str) -> None:
        if job_id:
            job_debug_log(root, job_id, msg)

    paper = load_paper(root, paper_id)
    source = paper.get("source_pdf")
    if not source or not (root / source).exists():
        _dbg("agent_review: no source PDF, skipping")
        return {"status": "skipped", "reason": "no source pdf"}

    _dbg(f"agent_review: reading PDF '{source}' (max 12 pages)")
    pdf_text = extract_pdf_text(root / source, max_pages=12, include_page_markers=True)
    if not pdf_text.strip():
        _dbg("agent_review: empty PDF text, skipping")
        return {"status": "skipped", "reason": "empty pdf text"}
    _dbg(f"agent_review: PDF text {len(pdf_text)} chars")

    config = config or {}
    api_key = config.get("claude_api_key", "")
    endpoint = config.get("claude_endpoint", "")
    model = config.get("claude_model", "sonnet")
    figure_mode = config.get("figure_extraction_mode") or "fast_pillow"
    reextract_figures = bool(config.get("figure_reextract_on_enrich", True))

    if not api_key:
        _dbg("agent_review: no API key, skipping")
        return {"status": "skipped", "reason": "no api key configured"}

    figure_candidates: list[dict[str, Any]] = []
    if figure_mode == "fast_pillow" and reextract_figures:
        try:
            from .figure_tools import extract_fast_pillow_figures
            figure_candidates = extract_fast_pillow_figures(root, paper_id, max_pages=12)
            _dbg(f"agent_review: fast_pillow extracted {len(figure_candidates)} figure candidates")
        except Exception as exc:
            _dbg(f"agent_review: fast_pillow figure extraction failed: {exc}")

    known_tags = _known_tags(root)
    prompt = _build_review_prompt(paper, pdf_text, known_tags, figure_candidates, figure_mode)
    _dbg(f"agent_review: calling {model} at {endpoint or 'default'}, prompt {len(prompt)} chars")

    import httpx

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    base_url = endpoint.rstrip("/") if endpoint else "https://api.anthropic.com"
    url = f"{base_url}/v1/messages"

    body = {
        "model": model,
        "max_tokens": 8192,
        "temperature": 0.1,
        "system": PAPER_REVIEW_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }
    if figure_mode == "agent_pymupdf":
        body["tools"] = PAPER_REVIEW_TOOLS

    async with httpx.AsyncClient(timeout=120) as client:
        t0 = datetime.now(timezone.utc)
        data: dict[str, Any] = {}
        max_tool_turns = 8
        for turn in range(1, max_tool_turns + 1):
            resp = await client.post(url, headers=headers, json=body)
            elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
            _dbg(f"agent_review: API response {resp.status_code} on turn {turn} in {elapsed:.1f}s")
            if resp.status_code != 200:
                _dbg(f"agent_review: API error body: {resp.text[:300]}")
                return {"status": "error", "detail": f"API error {resp.status_code}: {resp.text[:500]}"}
            data = resp.json()
            content = data.get("content", [])
            tool_uses = [block for block in content if isinstance(block, dict) and block.get("type") == "tool_use"]
            if not tool_uses:
                break

            body["messages"].append({"role": "assistant", "content": content})
            tool_results = []
            for tool_use in tool_uses:
                _dbg(f"agent_review: tool {tool_use.get('name')} input={_compact_json(tool_use.get('input'), 500)}")
                result_block = _execute_paper_review_tool(root, tool_use)
                tool_results.append(result_block)
                result_text = result_block.get("content", [{}])[0].get("text", "")
                _dbg(f"agent_review: tool {tool_use.get('name')} result={_compact(str(result_text), 500)}")
            body["messages"].append({"role": "user", "content": tool_results})

            if turn == max_tool_turns:
                _dbg("agent_review: tool turn limit reached; requesting final JSON without further tool use")
                final_body = dict(body)
                final_body.pop("tools", None)
                final_body["messages"] = [
                    *body["messages"],
                    {
                        "role": "user",
                        "content": (
                            "Tool-use budget is exhausted. Do not call any more tools. "
                            "Return the final JSON patch now, reusing the image_path, crop, "
                            "and crop_method values already returned by save_figure_crop."
                        ),
                    },
                ]
                resp = await client.post(url, headers=headers, json=final_body)
                elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
                _dbg(f"agent_review: final JSON response {resp.status_code} in {elapsed:.1f}s")
                if resp.status_code != 200:
                    _dbg(f"agent_review: final JSON API error body: {resp.text[:300]}")
                    return {"status": "error", "detail": f"API error {resp.status_code}: {resp.text[:500]}"}
                data = resp.json()
                break
        else:
            return {"status": "error", "detail": "agent review exceeded tool-use turn limit"}

    content = data.get("content", [])
    text_output = ""
    for block in content:
        if block.get("type") == "text":
            text_output += block.get("text", "")
    _dbg(f"agent_review: response {len(text_output)} chars, usage={data.get('usage', {})}")

    # Parse JSON from response
    patch = _parse_json_block(text_output)
    if not patch:
        _dbg(f"agent_review: failed to parse JSON, raw: {text_output[:200]}")
        return {"status": "error", "detail": "could not parse JSON from agent response", "raw": text_output[:500]}

    _dbg(f"agent_review: parsed patch keys={list(patch.keys())}")

    # Merge corrections
    review_notes = patch.get("review_notes", [])
    paper, merge_notes = _merge_review_patch(
        paper,
        patch,
        preserve_existing_figures=not reextract_figures,
    )
    all_notes = merge_notes + review_notes
    _dbg(f"agent_review: merge produced {len(all_notes)} notes")
    for note in all_notes:
        _dbg(f"agent_review:   {note}")

    # Store review record
    paper.setdefault("agent_reviews", []).append({
        "time": now_iso(),
        "model": model,
        "notes": all_notes,
    })
    paper["agent_reviewed_at"] = now_iso()
    paper["needs_review"] = False

    save_paper(root, paper)
    return {"status": "ok", "notes": all_notes}


def _parse_json_block(text: str) -> dict[str, Any] | None:
    """Extract JSON object from agent response text."""
    import re

    # Try to find JSON between ```json ... ```
    match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find bare JSON object
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def run_agent_paper_review_sync(root: Path, paper_id: str,
                                 job_id: str | None = None,
                                 config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Sync wrapper for ThreadPoolExecutor usage."""
    result: dict[str, Any] = {"status": "error", "detail": "review did not complete"}

    def worker() -> None:
        nonlocal result
        async def run() -> None:
            nonlocal result
            result = await run_agent_paper_review(root, paper_id, config, job_id)
        asyncio.run(run())

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=180)  # 3-minute timeout to prevent infinite blocking
    if thread.is_alive():
        return {"status": "error", "detail": "agent review timed out after 180s"}
    return result
