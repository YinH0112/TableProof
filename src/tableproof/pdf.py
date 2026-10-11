"""Text PDF extraction with immutable, original-coordinate provenance.

Coordinate contract
-------------------
``bbox`` in a sourceRef, character, table, or context is an axis-aligned box in
the PDF's *original*, unrotated user space, in PDF points (not screen pixels).
``displayBbox``, ``rowBoundaries`` and ``colBoundaries`` use pdfplumber's
absolute top-left coordinates, including its MediaBox origin offsets.  A page's
``transform`` maps original points to this display space.  PDF.js should use
its own viewport conversion on the original source bbox when drawing highlights.

The original characters remain in content-stream order so their IDs are stable.
Only text reconstruction reorders them.  Empty grid positions never imply a
merge: spans are derived from an actual detected cell's geometry.
"""

from __future__ import annotations

import math
import statistics
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import pdfplumber
from pdfplumber.utils import extract_text

BBox = Sequence[float]
TOLERANCE = 0.75


def _box(values: Sequence[Any]) -> list[float]:
    if len(values) != 4:
        raise ValueError("INVALID_REGION: expected four coordinates")
    result = [float(value) for value in values]
    if not all(math.isfinite(value) for value in result):
        raise ValueError("INVALID_REGION: coordinates must be finite")
    return [min(result[0], result[2]), min(result[1], result[3]),
            max(result[0], result[2]), max(result[1], result[3])]


def transform_point(transform: Sequence[float], x: float, y: float) -> list[float]:
    """Apply PDF affine matrix [a,b,c,d,e,f] to an original/display point."""
    a, b, c, d, e, f = transform
    return [a * x + c * y + e, b * x + d * y + f]


def transform_bbox(transform: Sequence[float], bbox: BBox) -> list[float]:
    x0, y0, x1, y1 = _box(bbox)
    points = [transform_point(transform, x, y)
              for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
    return [min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points)]


def _inverse(transform: Sequence[float]) -> list[float]:
    a, b, c, d, e, f = transform
    det = a * d - b * c
    if abs(det) < 1e-12:
        raise ValueError("INVALID_PDF: singular page transform")
    return [d / det, -b / det, -c / det, a / det,
            (c * f - d * e) / det, (b * e - a * f) / det]


def _page_transform(page: Any) -> list[float]:
    # Match PDFPageInterpreter.process_page in pdfminer.six, then compose
    # Page.process_object's x offset and y inversion in pdfplumber.  In
    # particular, a nonzero MediaBox is not equivalent to height - raw_y.
    x0, y0, x1, y1 = [float(v) for v in page.page_obj.mediabox]
    rotation = page.rotation
    if rotation == 90:
        ctm = [0, -1, 1, 0, -y0, x1]
    elif rotation == 180:
        ctm = [-1, 0, 0, -1, x1, y1]
    elif rotation == 270:
        ctm = [0, 1, -1, 0, y1, -x0]
    elif rotation == 0:
        ctm = [1, 0, 0, 1, -x0, -y0]
    else:
        raise ValueError("UNSUPPORTED_ROTATION: page rotation must be a multiple of 90")
    a, b, c, d, e, f = ctm
    mb_x0, mb_top = page.mediabox[:2]
    return [float(a), float(-b), float(c), float(-d),
            float(e + mb_x0), float(page.height - f + mb_top)]


def _encrypted_error(exc: BaseException) -> bool:
    pending: list[Any] = [exc]
    seen: set[int] = set()
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if "Password" in type(item).__name__ or "Encryption" in type(item).__name__:
            return True
        if isinstance(item, BaseException):
            pending.extend(v for v in item.args if isinstance(v, BaseException))
            pending.extend(v for v in (item.__cause__, item.__context__) if v is not None)
    return False


def parse_pdf(
    path: str | Path,
    file_hash: str,
    progress_callback: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    """Parse all characters once; callback receives completed page count/total.

    A blank page is allowed inside a text document.  All-blank/image-only PDFs,
    encrypted documents (including empty-password ones), and unreadable PDFs
    raise explicit ValueError codes.  Cancellation is checked between pages.
    """
    pages: list[dict[str, Any]] = []
    try:
        with pdfplumber.open(path) as pdf:
            if pdf.doc.encryption is not None:
                raise ValueError("ENCRYPTED_PDF: encrypted documents are unsupported")
            total = len(pdf.pages)
            if not total:
                raise ValueError("INVALID_PDF: document has no pages")
            for page in pdf.pages:
                if cancelled is not None and cancelled():
                    raise ValueError("CANCELLED: parsing cancelled")
                transform = _page_transform(page)
                inverse = _inverse(transform)
                chars: list[dict[str, Any]] = []
                warnings: list[str] = []
                for index, char in enumerate(page.chars):
                    display_bbox = _box([char["x0"], char["top"], char["x1"], char["bottom"]])
                    raw_bbox = transform_bbox(inverse, display_bbox)
                    text = char.get("text", "")
                    matrix = char.get("matrix", (1, 0, 0, 1, 0, 0))
                    # Glyph baseline direction in original user space. Page
                    # /Rotate must not reverse text reconstruction (180/270).
                    direction = [inverse[0] * matrix[0] - inverse[2] * matrix[1],
                                 inverse[1] * matrix[0] - inverse[3] * matrix[1]]
                    chars.append({
                        "id": f"p{page.page_number}-c{index}",
                        "text": text,
                        "bbox": raw_bbox,
                        "displayBbox": display_bbox,
                        "fontName": str(char.get("fontname", "")),
                        "fontSize": float(char.get("size", 0)),
                        "upright": bool(char.get("upright", True)),
                        "textDirection": direction,
                    })
                if not chars:
                    warnings.append("NO_PAGE_TEXT")
                if any(not c["text"] or "(cid:" in c["text"] or "\ufffd" in c["text"]
                       or "\x00" in c["text"] for c in chars):
                    warnings.append("UNMAPPED_GLYPHS")
                media_box = _box(page.page_obj.mediabox)
                crop_box = _box(page.page_obj.cropbox)
                pages.append({
                    "number": page.page_number,
                    "width": float(page.width),
                    "height": float(page.height),
                    "rotation": int(page.rotation),
                    "mediaBox": media_box,
                    "cropBox": crop_box,
                    "displayMediaBox": [float(v) for v in page.mediabox],
                    "displayCropBox": transform_bbox(transform, crop_box),
                    "transform": transform,
                    "inverseTransform": inverse,
                    "userUnit": float(page.page_obj.attrs.get("UserUnit", 1)),
                    "chars": chars,
                    "mappingReliable": not warnings,
                    "warnings": warnings,
                })
                if progress_callback is not None:
                    progress_callback(len(pages), total)
                page.close()
    except ValueError as exc:
        if str(exc).startswith(("INVALID_PDF:", "ENCRYPTED_PDF:", "CANCELLED:", "UNSUPPORTED_ROTATION:")):
            raise
        raise ValueError("INVALID_PDF: cannot parse document") from exc
    except Exception as exc:
        if _encrypted_error(exc):
            raise ValueError("ENCRYPTED_PDF: encrypted documents are unsupported") from exc
        raise ValueError("INVALID_PDF: cannot parse document") from exc
    if not any(c["text"].strip() for p in pages for c in p["chars"]):
        raise ValueError("NO_TEXT: document contains no extractable text; OCR is unsupported")
    return pages


def _page(pages: Sequence[dict[str, Any]], number: int) -> dict[str, Any]:
    try:
        return next(p for p in pages if p["number"] == number)
    except StopIteration as exc:
        raise ValueError("INVALID_PAGE: page does not exist") from exc


def chars_in_bbox(chars: Iterable[dict[str, Any]], bbox: BBox) -> list[dict[str, Any]]:
    """Assign characters by display-space center, with half-open right/bottom."""
    x0, top, x1, bottom = _box(bbox)
    result = []
    for char in chars:
        box = char["displayBbox"]
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        if x0 <= cx < x1 and top <= cy < bottom:
            result.append(char)
    return result


def text_from_chars(chars: Iterable[dict[str, Any]]) -> str:
    """Reconstruct readable text without changing stored glyphs or Unicode.

    This is a reading-order heuristic, not mathematical/LaTeX reconstruction.
    Callers should retain charIds so the exact source remains inspectable.
    """
    source = list(chars)
    objects = []
    # Canonicalize the dominant original glyph direction, independently of
    # page rotation. Mixed-direction typography remains reviewable by charIds.
    directions = [c.get("textDirection", [1, 0]) for c in source if c["text"].strip()]
    angles = [round(math.atan2(d[1], d[0]) / (math.pi / 2)) % 4 for d in directions]
    quarter_turn = max(set(angles), key=angles.count) if angles else 0
    canonical_transforms = ([1, 0, 0, 1, 0, 0], [0, -1, 1, 0, 0, 0],
                            [-1, 0, 0, -1, 0, 0], [0, 1, -1, 0, 0, 0])
    for char in source:
        if "bbox" in char:
            x0, y0, x1, y1 = transform_bbox(canonical_transforms[quarter_turn], char["bbox"])
            top, bottom = -y1, -y0
        else:
            x0, top, x1, bottom = char["displayBbox"]
        objects.append({"text": char["text"], "x0": x0, "top": top,
                        "x1": x1, "bottom": bottom, "doctop": top,
                        "upright": True, "size": bottom - top})
    return extract_text(objects, x_tolerance=2, y_tolerance=3).strip() if objects else ""


def _source_ref(file_hash: str, page: int, bbox: BBox,
                chars: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {"fileHash": file_hash, "page": page, "bbox": list(bbox),
            "charIds": [char["id"] for char in chars]}


def select_context(pages: Sequence[dict[str, Any]], file_hash: str,
                   page_number: int, bbox: BBox, kind: str) -> dict[str, Any]:
    if kind not in {"caption", "note", "unit", "title"}:
        raise ValueError("INVALID_CONTEXT_KIND: expected caption, note, unit, or title")
    page = _page(pages, page_number)
    if not page.get("mappingReliable", False):
        raise ValueError("UNRELIABLE_MAPPING: page glyph mapping requires review before selecting sources")
    raw_bbox = _box(bbox)
    display_bbox = transform_bbox(page["transform"], raw_bbox)
    chars = chars_in_bbox(page["chars"], display_bbox)
    if not chars:
        raise ValueError("EMPTY_REGION: selected context contains no text")
    return {"id": f"context-{uuid.uuid4().hex}", "kind": kind,
            "text": text_from_chars(chars), "bbox": raw_bbox,
            "displayBbox": display_bbox,
            "sourceRefs": [_source_ref(file_hash, page_number, raw_bbox, chars)]}


def _cluster(values: Iterable[float], tolerance: float = TOLERANCE) -> list[float]:
    groups: list[list[float]] = []
    for value in sorted(values):
        if groups and abs(value - statistics.mean(groups[-1])) <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [statistics.mean(group) for group in groups]


def _index(boundaries: Sequence[float], value: float) -> int:
    index = min(range(len(boundaries)), key=lambda i: abs(boundaries[i] - value))
    if abs(boundaries[index] - value) > TOLERANCE + 1e-6:
        raise ValueError("INVALID_GRID: detected cell does not align to boundaries")
    return index


def _grid(cells: Sequence[BBox]) -> tuple[list[float], list[float], list[dict[str, Any]]]:
    cols = _cluster(value for cell in cells for value in (cell[0], cell[2]))
    rows = _cluster(value for cell in cells for value in (cell[1], cell[3]))
    occupied: set[tuple[int, int]] = set()
    geometry = []
    for bbox in cells:
        col, end_col = _index(cols, bbox[0]), _index(cols, bbox[2])
        row, end_row = _index(rows, bbox[1]), _index(rows, bbox[3])
        if end_col <= col or end_row <= row:
            raise ValueError("INVALID_GRID: zero-size cell")
        slots = {(r, c) for r in range(row, end_row) for c in range(col, end_col)}
        if slots & occupied:
            raise ValueError("INVALID_GRID: overlapping cells")
        occupied |= slots
        geometry.append({"row": row, "col": col, "rowSpan": end_row - row,
                         "colSpan": end_col - col, "displayBbox": list(bbox)})
    expected = {(r, c) for r in range(len(rows) - 1) for c in range(len(cols) - 1)}
    # Absence of a detected cell is represented as an actual empty unit cell.
    # It is never silently promoted into a header span.
    for row, col in sorted(expected - occupied):
        geometry.append({"row": row, "col": col, "rowSpan": 1, "colSpan": 1,
                         "displayBbox": [cols[col], rows[row], cols[col + 1], rows[row + 1]],
                         "inferredEmpty": True})
    return rows, cols, sorted(geometry, key=lambda cell: (cell["row"], cell["col"]))


def _fallback_grid(chars: Sequence[dict[str, Any]], bbox: BBox,
                   column_lines: Sequence[float]) -> tuple[list[float], list[float], list[dict[str, Any]]]:
    """Conservative fallback: one column unless user supplied explicit dividers."""
    x0, top, x1, bottom = bbox
    line_centers = _cluster(((c["displayBbox"][1] + c["displayBbox"][3]) / 2
                             for c in chars if c["text"].strip()), tolerance=4)
    rows = [top] + [(a + b) / 2 for a, b in zip(line_centers, line_centers[1:])] + [bottom]
    cols = _cluster([x0, *[v for v in column_lines if x0 < v < x1], x1])
    geometry = [{"row": r, "col": c, "rowSpan": 1, "colSpan": 1,
                 "displayBbox": [cols[c], rows[r], cols[c + 1], rows[r + 1]]}
                for r in range(len(rows) - 1) for c in range(len(cols) - 1)]
    return rows, cols, geometry


def extract_table(path: str | Path, pages: Sequence[dict[str, Any]], file_hash: str,
                  page_number: int, bbox: BBox,
                  column_lines: Sequence[float] | None = None) -> dict[str, Any]:
    """Extract a selected region; column_lines are DISPLAY-space x coordinates.

    Ruled table geometry is preferred.  Borderless text detection is labelled
    approximate.  The final fallback retains all selected text and asks the
    user to supply columns, rather than inventing confident data structure.
    """
    page = _page(pages, page_number)
    if not page.get("mappingReliable", False):
        raise ValueError("UNRELIABLE_MAPPING: page glyph mapping requires review before selecting sources")
    raw_bbox = _box(bbox)
    display_bbox = transform_bbox(page["transform"], raw_bbox)
    if display_bbox[2] <= display_bbox[0] or display_bbox[3] <= display_bbox[1]:
        raise ValueError("INVALID_REGION: selection must have positive area")
    media = page["displayMediaBox"]
    if any((display_bbox[0] < media[0] - TOLERANCE,
            display_bbox[1] < media[1] - TOLERANCE,
            display_bbox[2] > media[2] + TOLERANCE,
            display_bbox[3] > media[3] + TOLERANCE)):
        raise ValueError("INVALID_REGION: selected region is outside the page")
    selected_chars = chars_in_bbox(page["chars"], display_bbox)
    if not selected_chars:
        raise ValueError("EMPTY_REGION: selected table contains no text")
    columns = [float(v) for v in (column_lines or [])]
    if not all(math.isfinite(v) for v in columns):
        raise ValueError("INVALID_GRID: column boundaries must be finite")
    if any(v < display_bbox[0] or v > display_bbox[2] for v in columns):
        raise ValueError("INVALID_GRID: column boundaries must lie inside the selection")
    warnings = list(page.get("warnings", []))
    candidates = []
    strategy = "lines"
    try:
        with pdfplumber.open(path) as pdf:
            pdf_page = pdf.pages[page_number - 1]
            cropped = pdf_page.crop(tuple(display_bbox), strict=False)
            settings: dict[str, Any] = {"snap_tolerance": 2, "join_tolerance": 2}
            if columns:
                settings.update(vertical_strategy="explicit",
                                explicit_vertical_lines=_cluster([display_bbox[0], *columns, display_bbox[2]]))
            candidates = cropped.find_tables(settings)
            if not candidates:
                strategy = "text"
                settings.update(horizontal_strategy="text", min_words_horizontal=1,
                                min_words_vertical=2)
                if not columns:
                    settings["vertical_strategy"] = "text"
                candidates = cropped.find_tables(settings)
            if candidates:
                candidate = max(candidates, key=lambda t: (len(chars_in_bbox(selected_chars, t.bbox)),
                                                          (t.bbox[2] - t.bbox[0]) * (t.bbox[3] - t.bbox[1])))
                if columns or strategy == "text":
                    # Text edges are word-height boundaries; directly using
                    # them produces artificial spacer rows and, with explicit
                    # columns, can drop the outside columns entirely. Retain
                    # the full selected region and use text only for dividers.
                    detected_cols = _cluster(v for cell in candidate.cells for v in (cell[0], cell[2]))
                    suggested_columns = columns or detected_cols[1:-1]
                    rows, cols, geometry = _fallback_grid(selected_chars, display_bbox, suggested_columns)
                    detected_box = display_bbox
                    if columns:
                        strategy = "manual"
                else:
                    rows, cols, geometry = _grid(candidate.cells)
                    detected_box = list(candidate.bbox)
                retained_ids = {c["id"] for c in chars_in_bbox(selected_chars, detected_box)}
                if any(c["text"].strip() and c["id"] not in retained_ids for c in selected_chars):
                    warnings.append("TEXT_OUTSIDE_DETECTED_GRID")
                if any(cell.get("inferredEmpty") for cell in geometry):
                    warnings.append("MISSING_GRID_CELLS")
            else:
                raise ValueError("NO_DETECTED_GRID")
    except ValueError as exc:
        if not str(exc).startswith(("NO_DETECTED_GRID", "INVALID_GRID")):
            raise
        strategy = "fallback"
        rows, cols, geometry = _fallback_grid(selected_chars, display_bbox, columns)
        detected_box = display_bbox
        warnings.append("GRID_FALLBACK: review rows and supply column boundaries")
    except Exception as exc:
        raise ValueError("INVALID_PDF: cannot inspect selected table") from exc
    if strategy == "text":
        warnings.append("TEXT_GRID_APPROXIMATE: verify all boundaries and header spans")
    elif strategy == "manual":
        warnings.append("MANUAL_GRID_APPROXIMATE: columns follow guides; verify rows and merge grouped headers")
    table_id = f"table-{uuid.uuid4().hex}"
    cells = []
    for index, cell in enumerate(geometry):
        cell_chars = chars_in_bbox(selected_chars, cell["displayBbox"])
        cell_bbox = transform_bbox(page["inverseTransform"], cell["displayBbox"])
        text = text_from_chars(cell_chars)
        cells.append({"id": f"{table_id}-c{index}", **cell,
                      "originalText": text, "value": text,
                      "sourceRefs": [_source_ref(file_hash, page_number, cell_bbox, cell_chars)],
                      "reviewed": False})
    assigned_ids = {char_id for cell in cells for ref in cell["sourceRefs"] for char_id in ref["charIds"]}
    omitted_chars = [char for char in selected_chars if char["id"] not in assigned_ids]
    omitted_text = None
    if omitted_chars:
        omitted_bbox = [min(c["bbox"][0] for c in omitted_chars), min(c["bbox"][1] for c in omitted_chars),
                        max(c["bbox"][2] for c in omitted_chars), max(c["bbox"][3] for c in omitted_chars)]
        omitted_text = {"text": text_from_chars(omitted_chars),
                        "sourceRefs": [_source_ref(file_hash, page_number, omitted_bbox, omitted_chars)]}
        if any(c["text"].strip() for c in omitted_chars):
            warnings.append("TEXT_OUTSIDE_DETECTED_GRID")
    return {"id": table_id, "page": page_number, "bbox": raw_bbox,
            "displayBbox": detected_box, "rowCount": len(rows) - 1,
            "colCount": len(cols) - 1, "rowBoundaries": rows,
            "colBoundaries": cols, "cells": cells, "contexts": [],
            "supersedes": None, "extractionStrategy": strategy,
            "omittedText": omitted_text,
            "mappingReliable": page["mappingReliable"] and not warnings,
            "warnings": list(dict.fromkeys(warnings))}
