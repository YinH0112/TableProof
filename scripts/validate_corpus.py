"""Compare real PDF regions with independently sourced publisher JATS tables.

--refresh-reference fetches only the two publisher XML documents. Default runs
offline using reference.json. References never use PDF extraction or the seeded
cells in manifest.json. Observations are kept separate, including failures; this
small corpus is not a general extraction-accuracy benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "samples" / "papers"
sys.path.insert(0, str(ROOT / "src"))

from tableproof.pdf import chars_in_bbox, extract_table, parse_pdf, text_from_chars, transform_bbox

KEY_COORDINATES = {
    "womack-2015-table-1": [(1, 1), (1, 2), (1, 3), (10, 4)],
    "womack-2015-table-2": [(1, 1), (1, 2), (1, 3), (10, 4)],
    "womack-2015-table-3": [(1, 1), (1, 2), (1, 3), (10, 4)],
    "womack-2015-table-4": [(1, 1), (1, 2), (1, 3), (10, 4)],
    "womack-2015-table-5": [(1, 1), (1, 2), (11, 2), (11, 3)],
    "womack-2015-table-6": [(1, 1), (1, 2), (11, 2), (11, 3)],
    "womack-2015-table-7": [(1, 1), (1, 2), (11, 2), (11, 3)],
    "womack-2015-table-8": [(1, 1), (1, 2), (11, 2), (11, 3)],
    "womack-2015-table-9": [(1, 0), (1, 1), (1, 3), (5, 5)],
    "womack-2015-table-10": [(1, 0), (1, 1), (3, 3), (5, 4)],
    "womack-2015-table-11": [(1, 0), (1, 1), (2, 1), (16, 5)],
    "giofre-2017-table-2": [(0, 1), (0, 4), (2, 0), (2, 1), (7, 6), (11, 6)],
}
GIOFRE_GUIDES = [142, 214, 287, 359, 432, 504]
VISUALLY_REVIEWED_HASHES = {
    "womack-2015": "72f10b89d475137aaca8b0c6daa497e871f8cbf8a07009c268d305ef6b3de73e",
    "giofre-2017": "bf046efa2f8e85ea5923233a64ec4682e9bcb69a28d7df0700605dc407a31f12",
}


def compact(text: str) -> str:
    """Remove whitespace only; do not alter digits, punctuation, or Unicode."""
    return re.sub(r"\s+", "", text)


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _math_text(element: ET.Element) -> str:
    tag = _tag(element)
    children = [_math_text(child) for child in element]
    if tag == "mspace":
        return " "
    if tag == "mfrac" and len(children) == 2:
        return f"({children[0]})/({children[1]})"
    if tag == "msub" and len(children) == 2:
        return f"{children[0]}_{{{children[1]}}}"
    if tag == "msup" and len(children) == 2:
        return f"{children[0]}^{{{children[1]}}}"
    if tag == "mover" and len(children) == 2:
        return f"over({children[0]},{children[1]})"
    direct = element.text if element.text and element.text.strip() else ""
    return direct + "".join(children)


def _xml_text(element: ET.Element) -> str:
    if _tag(element) == "math":
        return _math_text(element)
    result = element.text if element.text and element.text.strip() else ""
    for child in element:
        result += _xml_text(child)
        if child.tail and child.tail.strip():
            result += child.tail
    return re.sub(r"\s+", " ", result).strip()


def reference_table(wrap: ET.Element, paper_id: str, number: int) -> dict:
    table = next(element for element in wrap.iter() if _tag(element) == "table")
    rows = [element for element in table.iter() if _tag(element) == "tr"]
    thead = table.find("thead")
    header_count = len(thead.findall("tr")) if thead is not None else 0
    occupied = set()
    cells = []
    col_count = 0
    for row_index, row in enumerate(rows):
        col_index = 0
        for cell in row:
            if _tag(cell) not in {"td", "th"}:
                continue
            while (row_index, col_index) in occupied:
                col_index += 1
            rowspan, colspan = int(cell.get("rowspan", 1)), int(cell.get("colspan", 1))
            has_formula = any(_tag(e) == "math" for e in cell.iter())
            cells.append({"row": row_index, "col": col_index, "rowSpan": rowspan,
                          "colSpan": colspan, "text": _xml_text(cell),
                          "section": "header" if row_index < header_count else "body",
                          "textComparisonEligible": not has_formula,
                          **({"mathML": [ET.tostring(e, encoding="unicode") for e in cell.iter()
                                        if _tag(e) == "math"]} if has_formula else {})})
            occupied.update((r, c) for r in range(row_index, row_index + rowspan)
                            for c in range(col_index, col_index + colspan))
            col_index += colspan
            col_count = max(col_count, col_index)
    identifier = f"{paper_id}-table-{number}"
    keys = []
    for row, col in KEY_COORDINATES[identifier]:
        cell = next(c for c in cells if c["row"] == row and c["col"] == col)
        keys.append({"row": row, "col": col, "text": cell["text"]})
    return {"id": identifier, "paperId": paper_id, "tableNumber": number,
            "jatsId": wrap.get("id"), "label": _xml_text(wrap.find("label")),
            "caption": _xml_text(wrap.find("caption")), "rowCount": len(rows),
            "colCount": col_count, "headerRowCount": header_count,
            "cells": cells, "keyValues": keys,
            "spans": [{k: c[k] for k in ("row", "col", "rowSpan", "colSpan")}
                      for c in cells if c["rowSpan"] > 1 or c["colSpan"] > 1]}


def fetch_references(manifest: dict) -> dict:
    references = []
    papers = []
    for paper in manifest["papers"]:
        url = f"https://journals.plos.org/plosone/article/file?id={paper['doi']}&type=manuscript"
        with urlopen(url, timeout=30) as response:
            xml_bytes = response.read()
        article = ET.fromstring(xml_bytes)
        papers.append({"id": paper["id"], "doi": paper["doi"], "sourceUrl": paper["source"],
                       "xmlUrl": url, "xmlSha256": hashlib.sha256(xml_bytes).hexdigest(),
                       "title": paper["title"], "authors": paper["authors"],
                       "license": paper["license"], "licenseUrl": paper["licenseUrl"]})
        for number in paper["tables"]:
            wrap = next(t for t in article.iter("table-wrap")
                        if compact(_xml_text(t.find("label"))) == f"Table{number}")
            references.append(reference_table(wrap, paper["id"], number))
    return {"schemaVersion": 1, "referenceMethod": "Independent publisher JATS table cells, row/col spans and captions; no PDF extractor outputs used as truth.",
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "textComparison": "Whitespace removed only. MathML linearizations excluded from literal cell matching; original MathML retained.",
            "limitations": "Twelve regions from two PLOS articles are a development corpus, not a representative accuracy benchmark. Automatic, manual-guide, and blocked results are separate.",
            "papers": papers, "tables": references}


def compare_table(reference: dict, table: dict | None) -> dict:
    if table is None:
        return {"shapeMatch": False, "spansMatch": False, "exactCellTextMatches": 0,
                "eligibleReferenceCellCount": sum(c["textComparisonEligible"] for c in reference["cells"])}
    lookup = {(c["row"], c["col"]): c for c in table["cells"]}
    exact = 0
    mismatches = []
    for expected in reference["cells"]:
        if not expected["textComparisonEligible"]:
            continue
        actual = lookup.get((expected["row"], expected["col"]))
        matches = actual is not None and compact(actual["value"]) == compact(expected["text"])
        if matches:
            exact += 1
        else:
            mismatches.append({"row": expected["row"], "col": expected["col"], "expected": expected["text"],
                               "actual": actual["value"] if actual is not None else None})
    spans = [{k: c[k] for k in ("row", "col", "rowSpan", "colSpan")}
             for c in table["cells"] if c["rowSpan"] > 1 or c["colSpan"] > 1]
    return {"actualShape": [table["rowCount"], table["colCount"]],
            "shapeMatch": [table["rowCount"], table["colCount"]] == [reference["rowCount"], reference["colCount"]],
            "spansMatch": spans == reference["spans"], "exactCellTextMatches": exact,
            "eligibleReferenceCellCount": sum(c["textComparisonEligible"] for c in reference["cells"]),
            "cellMismatches": mismatches, "warnings": table.get("warnings", []),
            "omittedText": table.get("omittedText", {}).get("text") if table.get("omittedText") else None}


def manual_giofre(path: Path, pages: list, file_hash: str, region: dict) -> dict:
    """Exercise the actual merge operation after user-provided guide columns."""
    from tableproof.operations import apply_operation
    table = extract_table(path, pages, file_hash, region["page"], region["bbox"], GIOFRE_GUIDES)
    project = {"tables": [table], "pages": pages, "history": [], "undoStack": [], "redoStack": [], "version": 1}
    for cols in [(1, 2, 3), (4, 5, 6)]:
        cell_ids = [c["id"] for c in table["cells"] if c["row"] == 0 and c["col"] in cols]
        project = apply_operation(project, {"type": "merge", "tableId": table["id"], "cellIds": cell_ids})
        table = project["tables"][0]
    return table


def validate(manifest: dict, references: dict) -> dict:
    parsed = {}
    results = []
    for paper in manifest["papers"]:
        path = CORPUS / paper["file"]
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if file_hash != paper["sha256"]:
            raise ValueError(f"CORPUS_HASH_CHANGED: {paper['id']}")
        parsed[paper["id"]] = (path, file_hash, parse_pdf(path, file_hash))
    for region in manifest["tables"]:
        reference = next(t for t in references["tables"] if t["id"] == region["id"])
        path, file_hash, pages = parsed[region["paperId"]]
        page = pages[region["page"] - 1]
        selected = chars_in_bbox(page["chars"], transform_bbox(page["transform"], region["bbox"]))
        region_text = text_from_chars(selected)
        key_checks = [{**key, "presentInRegion": compact(key["text"]) in compact(region_text)}
                      for key in reference["keyValues"]]
        automatic = None
        error = None
        try:
            automatic = extract_table(path, pages, file_hash, region["page"], region["bbox"])
        except ValueError as exc:
            error = str(exc)
        result = {"id": region["id"], "page": region["page"], "bbox": region["bbox"],
                  "referenceShape": [reference["rowCount"], reference["colCount"]],
                  "selectedRegionKeyChecks": key_checks,
                  "regionIdentityVerified": all(k["presentInRegion"] for k in key_checks),
                  "mappingReliable": page["mappingReliable"], "automaticError": error,
                  "visualRegionReview": {"status": "reviewed" if VISUALLY_REVIEWED_HASHES.get(region["paperId"]) == file_hash else "not reviewed",
                                         "date": "2026-10-11", "pdfSha256": file_hash,
                                         "method": "Agent visually inspected all 12 complete regions rendered at 120 dpi, matching header, first/last rows and key values to publisher XML. Not a full manual transcription."},
                  "automatic": compare_table(reference, automatic)}
        if region["id"] == "giofre-2017-table-2":
            manual = manual_giofre(path, pages, file_hash, region)
            result["manual"] = {"columnLines": GIOFRE_GUIDES,
                                "operations": "merge row0 columns1-3; merge row0 columns4-6",
                                **compare_table(reference, manual)}
        results.append(result)
    return {"validatedAt": datetime.now(timezone.utc).isoformat(),
            "summary": {"regions": len(results),
                        "regionIdentityVerified": sum(r["regionIdentityVerified"] for r in results),
                        "automaticShapeMatches": sum(r["automatic"]["shapeMatch"] for r in results),
                        "blockedUnreliableMapping": sum(bool(r["automaticError"] and r["automaticError"].startswith("UNRELIABLE_MAPPING")) for r in results)},
            "findings": ["All regions repaired to include table header and full width, using PDF boundary edges. Old seed regions excluded headers and, for Giofre, outside columns.",
                         "Automatic detection of partial ruled tables remains incomplete; omitted source text is retained separately with provenance.",
                         "Manual guides cover the complete selection, followed by explicit grouped-header merges. This requires user correction and is not counted as automatic extraction.",
                         "Womack Table9 and Table11 are blocked by unmapped glyphs on their pages; independent XML references remain available."],
            "results": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-reference", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    reference_path = CORPUS / "reference.json"
    references = fetch_references(manifest) if args.refresh_reference else json.loads(reference_path.read_text(encoding="utf-8"))
    references["validation"] = validate(manifest, references)
    reference_path.write_text(json.dumps(references, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(references["validation"]["summary"]))


if __name__ == "__main__":
    main()
