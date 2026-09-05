from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .kb import slugify


class MinerUExtractionError(RuntimeError):
    """Raised when MinerU cannot produce a usable parsed document."""


def _now_token() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _find_largest(paths: list[Path]) -> Path | None:
    return max(paths, key=lambda path: path.stat().st_size, default=None)


def _asset_pages(value: Any) -> dict[str, int]:
    """Best-effort page lookup across MinerU JSON variants."""
    pages: dict[str, int] = {}

    def visit(item: Any) -> None:
        if isinstance(item, list):
            for child in item:
                visit(child)
            return
        if not isinstance(item, dict):
            return
        raw_page = next((item.get(key) for key in ("page", "page_no", "page_num", "page_number") if item.get(key) is not None), None)
        page: int | None = None
        try:
            if raw_page is not None:
                page = int(raw_page)
                if page == 0:
                    page = 1
        except (TypeError, ValueError):
            pass
        for key in ("image_path", "img_path", "path", "file_path"):
            value = item.get(key)
            if page and isinstance(value, str) and value:
                pages[Path(value).name] = page
        for child in item.values():
            visit(child)

    visit(value)
    return pages


def _referenced_image_names(markdown: str) -> list[str]:
    names: list[str] = []
    for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", markdown):
        raw = match.group(1).strip().strip("<>").split(" ", 1)[0]
        name = Path(raw).name
        if name and name not in names:
            names.append(name)
    return names


def extract_paper_with_mineru(
    root: Path,
    paper_id: str,
    source_pdf: Path,
    config: dict[str, Any],
    *,
    debug: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Parse a local PDF with MinerU and retain its structured result in logs/.

    Precision mode is used whenever a token is configured.  Flash mode is a
    deliberately explicit no-token fallback; it never falls back to the old
    Pillow or PyMuPDF extraction paths.
    """
    def log(message: str) -> None:
        if debug:
            debug(f"mineru: {message}")

    binary = str(config.get("mineru_command") or "mineru-open-api")
    if not shutil.which(binary):
        raise MinerUExtractionError("MinerU CLI is unavailable. Install mineru-open-api before enriching papers.")
    if not source_pdf.exists():
        raise MinerUExtractionError(f"Source PDF is missing: {source_pdf}")
    if not bool(config.get("mineru_allow_remote", True)):
        raise MinerUExtractionError("MinerU remote processing is disabled in settings.")

    token = str(config.get("mineru_api_token") or os.environ.get("MINERU_TOKEN") or "").strip()
    requested_mode = str(config.get("mineru_extraction_mode") or "auto")
    mode = "precision" if requested_mode == "precision" or (requested_mode == "auto" and token) else "flash"
    if mode == "precision" and not token:
        raise MinerUExtractionError("MinerU precision mode requires a MinerU API token.")

    output_dir = root / "logs" / "mineru" / slugify(paper_id) / _now_token()
    output_dir.mkdir(parents=True, exist_ok=False)
    timeout = max(60, min(int(config.get("mineru_timeout_seconds") or 900), 1800))
    command = [binary, "extract" if mode == "precision" else "flash-extract", str(source_pdf), "--output", str(output_dir), "--language", "en", "--timeout", str(timeout)]
    if mode == "precision":
        command.extend(["--format", "md,json", "--model", str(config.get("mineru_model") or "vlm"), "--ocr"])
        command.extend(["--token", token])

    log(f"starting {mode} extraction for {source_pdf.name}")
    try:
        completed = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=timeout + 30, check=False)
    except subprocess.TimeoutExpired as exc:
        raise MinerUExtractionError(f"MinerU timed out after {timeout}s.") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown MinerU failure").strip()
        raise MinerUExtractionError(f"MinerU {mode} extraction failed (exit {completed.returncode}): {detail[:800]}")

    markdown_path = _find_largest(list(output_dir.rglob("*.md")))
    markdown = markdown_path.read_text(encoding="utf-8", errors="ignore") if markdown_path else completed.stdout.strip()
    if not markdown:
        raise MinerUExtractionError("MinerU completed but produced no Markdown content.")
    if not markdown_path:
        markdown_path = output_dir / "parsed.md"
        markdown_path.write_text(markdown, encoding="utf-8")

    json_path = _find_largest(list(output_dir.rglob("*.json")))
    parsed_json: Any = None
    if json_path:
        try:
            parsed_json = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log("JSON output could not be decoded; continuing with Markdown")
    page_by_name = _asset_pages(parsed_json)
    referenced = _referenced_image_names(markdown)
    image_extensions = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    available = [path for path in output_dir.rglob("*") if path.is_file() and path.suffix.lower() in image_extensions]
    by_name = {path.name: path for path in available}
    selected = [by_name[name] for name in referenced if name in by_name]
    if not selected:
        selected = available

    asset_dir = root / "assets" / "paper_figures"
    asset_dir.mkdir(parents=True, exist_ok=True)
    assets: list[dict[str, Any]] = []
    for index, source in enumerate(selected[:12], start=1):
        destination = asset_dir / f"{slugify(paper_id)}_mineru_{index}{source.suffix.lower()}"
        shutil.copy2(source, destination)
        item: dict[str, Any] = {
            "candidate_id": f"mineru-{index}",
            "image_path": str(destination.relative_to(root)),
            "source_name": source.name,
        }
        if source.name in page_by_name:
            item["page"] = page_by_name[source.name]
        assets.append(item)

    log(f"completed {mode} extraction: {len(markdown)} Markdown chars, {len(assets)} extracted image assets")
    return {
        "mode": mode,
        "markdown": markdown,
        "markdown_path": str(markdown_path.relative_to(root)),
        "json_path": str(json_path.relative_to(root)) if json_path else "",
        "assets": assets,
    }
