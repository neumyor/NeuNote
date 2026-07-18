from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

from .kb import load_paper, slugify


def _fitz() -> Any:
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - depends on optional runtime dep
        raise RuntimeError("PyMuPDF is not installed. Run `uv sync` in backend/ first.") from exc
    return fitz


def _pillow() -> Any:
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - depends on optional runtime dep
        raise RuntimeError("Pillow is not installed. Run `uv sync` in backend/ first.") from exc
    return Image


def _paper_pdf_path(root: Path, paper_id: str) -> Path:
    paper = load_paper(root, paper_id)
    source = paper.get("source_pdf")
    if not isinstance(source, str):
        raise ValueError(f"Paper has no source_pdf: {paper_id}")
    path = (root / source).resolve()
    path.relative_to(root.resolve())
    if not path.exists():
        raise FileNotFoundError(f"Source PDF not found: {source}")
    return path


def render_pdf_page(root: Path, paper_id: str, page_number: int, dpi: int = 120) -> dict[str, Any]:
    fitz = _fitz()
    path = _paper_pdf_path(root, paper_id)
    dpi = min(max(int(dpi), 72), 180)
    with fitz.open(path) as doc:
        if page_number < 1 or page_number > doc.page_count:
            raise ValueError(f"Page {page_number} out of range 1-{doc.page_count}.")
        page = doc.load_page(page_number - 1)
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
        png = pix.tobytes("png")
        rect = page.rect
        return {
            "paper_id": paper_id,
            "page": page_number,
            "page_count": doc.page_count,
            "dpi": dpi,
            "width": round(rect.width, 2),
            "height": round(rect.height, 2),
            "image_base64": base64.b64encode(png).decode("ascii"),
        }


def _norm_rect(page_rect: Any, rect: Any) -> dict[str, float]:
    return {
        "x0": round(rect.x0 / page_rect.width, 4),
        "y0": round(rect.y0 / page_rect.height, 4),
        "x1": round(rect.x1 / page_rect.width, 4),
        "y1": round(rect.y1 / page_rect.height, 4),
    }


def _denorm_rect(fitz: Any, page_rect: Any, crop: dict[str, Any]) -> Any:
    x0 = float(crop["x0"])
    y0 = float(crop["y0"])
    x1 = float(crop["x1"])
    y1 = float(crop["y1"])
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError("Crop coordinates must be normalized numbers in [0, 1] with x0 < x1 and y0 < y1.")
    return fitz.Rect(x0 * page_rect.width, y0 * page_rect.height, x1 * page_rect.width, y1 * page_rect.height)


def _padded_rect(fitz: Any, page_rect: Any, rect: Any, x_pad: float = 10,
                 y_pad: float = 8, bottom_pad: float = 2) -> Any:
    return fitz.Rect(
        max(0, rect.x0 - x_pad),
        max(0, rect.y0 - y_pad),
        min(page_rect.width, rect.x1 + x_pad),
        min(page_rect.height, rect.y1 + bottom_pad),
    )


def _caption_blocks(page: Any) -> list[dict[str, Any]]:
    captions: list[dict[str, Any]] = []
    for block in page.get_text("blocks"):
        x0, y0, x1, y1, text, *_ = block
        compact = " ".join(str(text).split())
        match = re.search(r"\bFigure\s+(\d+[a-zA-Z]?)\s*:\s*(.+)", compact)
        if not match:
            continue
        caption = match.group(0)
        section_match = re.search(r"\s+\d+\s+[A-Z][A-Za-z ]{3,}$", caption)
        if section_match:
            caption = caption[:section_match.start()].rstrip()
        captions.append({
            "label": f"Figure {match.group(1)}",
            "caption": caption,
            "rect": page.rect.__class__(x0, y0, x1, y1),
        })
    return captions


def _drawing_candidates_for_caption(fitz: Any, page: Any, caption_rect: Any, lower_y: float = 0.0) -> list[Any]:
    page_rect = page.rect
    min_area = page_rect.width * page_rect.height * 0.004
    rects = []
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if not rect:
            continue
        area = rect.width * rect.height
        if area < min_area:
            continue
        if rect.y0 < lower_y:
            continue
        if rect.y1 > caption_rect.y0 + page_rect.height * 0.02:
            continue
        if caption_rect.y0 - rect.y1 > page_rect.height * 0.36:
            continue
        overlap = max(0, min(rect.x1, caption_rect.x1) - max(rect.x0, caption_rect.x0))
        caption_width = max(caption_rect.width, 1)
        if overlap / caption_width < 0.08 and rect.width < page_rect.width * 0.55:
            continue
        rects.append(rect)
    if not rects:
        return []
    rects.sort(key=lambda r: (r.width * r.height, -abs(caption_rect.y0 - r.y1)), reverse=True)
    seed = rects[0]
    seed_area = seed.width * seed.height
    selected = [
        r for r in rects
        if (
            r.width * r.height >= seed_area * 0.08
            and r.y0 >= seed.y0 - page_rect.height * 0.08
            and r.y1 <= seed.y1 + page_rect.height * 0.08
        )
    ]
    union = selected[0]
    for rect in selected[1:]:
        union |= rect
    return [_padded_rect(fitz, page_rect, union)]


def list_figure_candidates(root: Path, paper_id: str, pages: list[int] | None = None) -> dict[str, Any]:
    fitz = _fitz()
    path = _paper_pdf_path(root, paper_id)
    candidates: list[dict[str, Any]] = []
    with fitz.open(path) as doc:
        selected_pages = pages or list(range(1, min(doc.page_count, 12) + 1))
        for page_number in selected_pages:
            if page_number < 1 or page_number > doc.page_count:
                continue
            page = doc.load_page(page_number - 1)
            captions = sorted(_caption_blocks(page), key=lambda item: item["rect"].y0)
            for idx, caption in enumerate(captions):
                lower_y = captions[idx - 1]["rect"].y1 if idx > 0 else 0.0
                rects = _drawing_candidates_for_caption(fitz, page, caption["rect"], lower_y)
                if not rects:
                    continue
                for idx, rect in enumerate(rects, start=1):
                    candidate_id = f"p{page_number}-{slugify(caption['label'])}-{idx}"
                    crop = _norm_rect(page.rect, rect)
                    caption_crop = _norm_rect(page.rect, rect | caption["rect"])
                    candidates.append({
                        "candidate_id": candidate_id,
                        "label": caption["label"],
                        "page": page_number,
                        "caption": caption["caption"],
                        "crop": crop,
                        "crop_with_caption": caption_crop,
                    })
    return {"paper_id": paper_id, "candidates": candidates}


def preview_figure_crop(
    root: Path,
    paper_id: str,
    page_number: int,
    crop: dict[str, Any],
    dpi: int = 120,
) -> dict[str, Any]:
    fitz = _fitz()
    path = _paper_pdf_path(root, paper_id)
    dpi = min(max(int(dpi), 72), 180)
    with fitz.open(path) as doc:
        if page_number < 1 or page_number > doc.page_count:
            raise ValueError(f"Page {page_number} out of range 1-{doc.page_count}.")
        page = doc.load_page(page_number - 1)
        clip = _denorm_rect(fitz, page.rect, crop)
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=clip, alpha=False)
        png = pix.tobytes("png")
        return {
            "paper_id": paper_id,
            "page": page_number,
            "dpi": dpi,
            "crop": {k: round(float(v), 4) for k, v in crop.items()},
            "image_base64": base64.b64encode(png).decode("ascii"),
        }


def save_figure_crop(
    root: Path,
    paper_id: str,
    page_number: int,
    figure_index: int,
    crop: dict[str, Any],
    dpi: int = 180,
) -> dict[str, Any]:
    fitz = _fitz()
    path = _paper_pdf_path(root, paper_id)
    dpi = min(max(int(dpi), 120), 240)
    figure_index = min(max(int(figure_index), 1), 3)

    with fitz.open(path) as doc:
        if page_number < 1 or page_number > doc.page_count:
            raise ValueError(f"Page {page_number} out of range 1-{doc.page_count}.")
        page = doc.load_page(page_number - 1)
        rect = page.rect
        clip = _denorm_rect(fitz, rect, crop)
        if clip.width < rect.width * 0.05 or clip.height < rect.height * 0.04:
            raise ValueError("Crop is too small to be a readable paper figure.")

        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=clip, alpha=False)
        out_dir = root / "assets/paper_figures"
        out_dir.mkdir(parents=True, exist_ok=True)
        image_path = out_dir / f"{slugify(paper_id)}_figure_{figure_index}_p{page_number}.png"
        pix.save(image_path)

    rel = str(image_path.relative_to(root))
    return {
        "paper_id": paper_id,
        "page": page_number,
        "figure_index": figure_index,
        "image_path": rel,
        "crop": {k: round(float(crop[k]), 4) for k in ("x0", "y0", "x1", "y1")},
        "crop_method": "agent_pymupdf",
    }


def save_figure_candidate(
    root: Path,
    paper_id: str,
    candidate_id: str,
    figure_index: int,
    include_caption: bool = False,
    dpi: int = 180,
) -> dict[str, Any]:
    candidates = list_figure_candidates(root, paper_id)["candidates"]
    match = next((candidate for candidate in candidates if candidate["candidate_id"] == candidate_id), None)
    if not match:
        raise ValueError(f"Figure candidate not found: {candidate_id}")
    crop = match["crop_with_caption"] if include_caption else match["crop"]
    result = save_figure_crop(root, paper_id, int(match["page"]), figure_index, crop, dpi)
    result.update({
        "label": match["label"],
        "caption": match["caption"],
        "candidate_id": candidate_id,
        "crop_method": "agent_pymupdf_candidate",
    })
    return result


def _colored_component_rects(image: Any) -> list[tuple[int, int, int, int, int]]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    block = 5
    pixels = rgb.load()
    mask: set[tuple[int, int]] = set()
    for y in range(0, int(height * 0.86), block):
        for x in range(0, width, block):
            hit = False
            for yy in range(y, min(y + block, height), 2):
                for xx in range(x, min(x + block, width), 2):
                    r, g, b = pixels[xx, yy]
                    if min(r, g, b) < 248 and max(r, g, b) - min(r, g, b) > 16:
                        hit = True
                        break
                if hit:
                    break
            if hit:
                mask.add((x // block, y // block))

    seen: set[tuple[int, int]] = set()
    rects: list[tuple[int, int, int, int, int]] = []
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
        if area >= 10:
            rects.append((area, min(xs) * block, min(ys) * block, (max(xs) + 1) * block, (max(ys) + 1) * block))
    rects.sort(reverse=True)
    return rects


def _union_nearby_rects(rects: list[tuple[int, int, int, int, int]]) -> tuple[int, int, int, int] | None:
    if not rects:
        return None
    seed = rects[0]
    _, sx0, sy0, sx1, sy1 = seed
    seed_area = max(seed[0], 1)
    selected = []
    for area, x0, y0, x1, y1 in rects:
        vertical_overlap = min(y1, sy1 + 100) - max(y0, sy0 - 100)
        if area >= seed_area * 0.03 and vertical_overlap > 0:
            selected.append((x0, y0, x1, y1))
    if not selected:
        selected = [(sx0, sy0, sx1, sy1)]
    return (
        min(r[0] for r in selected),
        min(r[1] for r in selected),
        max(r[2] for r in selected),
        max(r[3] for r in selected),
    )


def _looks_like_axis_chart(image: Any, bbox: tuple[int, int, int, int]) -> bool:
    """Heuristically detect charts where black axis labels/ticks need padding."""
    rgb = image.convert("RGB")
    pixels = rgb.load()
    width, height = rgb.size
    x0, y0, x1, y1 = bbox
    w = max(x1 - x0, 1)
    h = max(y1 - y0, 1)
    if w > width * 0.68 and h > height * 0.18:
        return False

    # Axis plots often have long dark horizontal/vertical strokes near the
    # bottom/left of the colored marks. Diagram figures usually do not.
    dark_horizontal = 0
    for y in range(max(0, y0 - 8), min(height, y1 + 18)):
        run = 0
        best = 0
        for x in range(max(0, x0 - 24), min(width, x1 + 24), 2):
            r, g, b = pixels[x, y]
            if max(r, g, b) < 110:
                run += 2
                best = max(best, run)
            else:
                run = 0
        dark_horizontal = max(dark_horizontal, best)

    dark_vertical = 0
    for x in range(max(0, x0 - 24), min(width, x1 + 18)):
        run = 0
        best = 0
        for y in range(max(0, y0 - 16), min(height, y1 + 16), 2):
            r, g, b = pixels[x, y]
            if max(r, g, b) < 110:
                run += 2
                best = max(best, run)
            else:
                run = 0
        dark_vertical = max(dark_vertical, best)

    # Axis labels are usually dark text just outside the colored region.
    label_dark_pixels = 0
    sample_pixels = 0
    label_regions = [
        (max(0, x0 - 90), max(0, y0 - 12), min(width, x0 + 18), min(height, y1 + 32)),
        (max(0, x0 - 20), max(0, y1 - 6), min(width, x1 + 70), min(height, y1 + 72)),
    ]
    for rx0, ry0, rx1, ry1 in label_regions:
        for y in range(ry0, ry1, 3):
            for x in range(rx0, rx1, 3):
                r, g, b = pixels[x, y]
                sample_pixels += 1
                if max(r, g, b) < 145 and max(r, g, b) - min(r, g, b) < 45:
                    label_dark_pixels += 1

    long_axes = dark_horizontal > w * 0.28 and dark_vertical > h * 0.28
    label_density = sample_pixels > 0 and label_dark_pixels / sample_pixels > 0.018
    return label_density and (long_axes or (dark_horizontal > w * 0.18 and dark_vertical > h * 0.18))


def _rect_overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _expand_bbox_with_page_geometry(
    page: Any,
    bbox: tuple[int, int, int, int],
    scale: float,
    lower_y: float,
    upper_y: float,
) -> tuple[int, int, int, int]:
    """Grow a color-core bbox to include nearby non-color figure elements.

    Fast Pillow detection intentionally keys off color, but paper figures often
    contain essential black/gray labels, axes, dashed boxes, and captions inside
    the graphic. We only expand within the caption-bounded figure band and near
    the color core so colored citation markers in surrounding prose cannot pull
    the crop into body text.
    """
    page_rect = page.rect
    x0, y0, x1, y1 = bbox
    core_pt = (x0 / scale, y0 / scale, x1 / scale, y1 / scale)
    min_y = max(lower_y, page_rect.height * 0.065)
    max_y = min(upper_y, page_rect.height * 0.92)
    search = (
        max(0.0, core_pt[0] - page_rect.width * 0.12),
        max(min_y, core_pt[1] - page_rect.height * 0.08),
        min(page_rect.width, core_pt[2] + page_rect.width * 0.12),
        min(max_y, core_pt[3] + page_rect.height * 0.10),
    )
    selected: list[tuple[float, float, float, float]] = [core_pt]

    for block in page.get_text("blocks"):
        bx0, by0, bx1, by1, text, *_ = block
        compact = " ".join(str(text).split())
        if not compact:
            continue
        if by0 < min_y or by1 > max_y:
            continue
        rect = (float(bx0), float(by0), float(bx1), float(by1))
        if _rect_overlaps(rect, search):
            selected.append(rect)

    min_area = page_rect.width * page_rect.height * 0.000015
    for drawing in page.get_drawings():
        rect_obj = drawing.get("rect")
        if not rect_obj:
            continue
        if rect_obj.y0 < min_y or rect_obj.y1 > max_y:
            continue
        if rect_obj.width * rect_obj.height < min_area:
            continue
        rect = (float(rect_obj.x0), float(rect_obj.y0), float(rect_obj.x1), float(rect_obj.y1))
        if _rect_overlaps(rect, search):
            selected.append(rect)

    expanded = (
        min(r[0] for r in selected),
        min(r[1] for r in selected),
        max(r[2] for r in selected),
        max(r[3] for r in selected),
    )
    return (
        int(expanded[0] * scale),
        int(expanded[1] * scale),
        int(expanded[2] * scale),
        int(expanded[3] * scale),
    )


def extract_fast_pillow_figures(root: Path, paper_id: str, max_pages: int = 12) -> list[dict[str, Any]]:
    """Extract colorful figure candidates quickly and persist PNG assets.

    This is intentionally deterministic and cheap: it finds captions with
    PyMuPDF text extraction, renders each caption page once, then uses Pillow to
    locate colored connected components between adjacent captions.
    """
    fitz = _fitz()
    Image = _pillow()
    path = _paper_pdf_path(root, paper_id)
    out_dir = root / "assets/paper_figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[dict[str, Any]] = []
    dpi = 180

    with fitz.open(path) as doc:
        for page_number in range(1, min(doc.page_count, max_pages) + 1):
            page = doc.load_page(page_number - 1)
            captions = sorted(_caption_blocks(page), key=lambda item: item["rect"].y0)
            if not captions:
                continue
            pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            scale = dpi / 72.0
            for idx, caption in enumerate(captions):
                lower = captions[idx - 1]["rect"].y1 if idx > 0 else 0.0
                upper = caption["rect"].y0
                region_rects = []
                for rect in _colored_component_rects(image):
                    area, x0, y0, x1, y1 = rect
                    y0_pt = y0 / scale
                    y1_pt = y1 / scale
                    if y0_pt < lower or y1_pt > upper + page.rect.height * 0.025:
                        continue
                    if upper - y1_pt > page.rect.height * 0.45:
                        continue
                    region_rects.append(rect)
                bbox = _union_nearby_rects(region_rects)
                if not bbox:
                    continue
                is_axis_chart = _looks_like_axis_chart(image, bbox)
                bbox = _expand_bbox_with_page_geometry(page, bbox, scale, lower, upper)
                x0, y0, x1, y1 = bbox
                if is_axis_chart:
                    left_pad = 95
                    top_pad = 24
                    right_pad = 90
                    bottom_pad = 52
                else:
                    left_pad = right_pad = 46
                    top_pad = 14
                    bottom_pad = 4
                x0 = max(0, x0 - left_pad)
                y0 = max(0, y0 - top_pad)
                x1 = min(image.width, x1 + right_pad)
                y1 = min(image.height, y1 + bottom_pad)
                if (x1 - x0) < image.width * 0.12 or (y1 - y0) < image.height * 0.06:
                    continue
                figure_index = len(saved) + 1
                image_path = out_dir / f"{slugify(paper_id)}_figure_{figure_index}_p{page_number}.png"
                image.crop((x0, y0, x1, y1)).save(image_path)
                crop = {
                    "x0": round((x0 / scale) / page.rect.width, 4),
                    "y0": round((y0 / scale) / page.rect.height, 4),
                    "x1": round((x1 / scale) / page.rect.width, 4),
                    "y1": round((y1 / scale) / page.rect.height, 4),
                }
                saved.append({
                    "label": caption["label"],
                    "title": caption["label"],
                    "page": page_number,
                    "caption": caption["caption"],
                    "reason": "",
                    "image_path": str(image_path.relative_to(root)),
                    "crop": crop,
                    "crop_method": "fast_pillow_axis" if is_axis_chart else "fast_pillow_color",
                })
                if len(saved) >= 8:
                    return saved
    return saved
