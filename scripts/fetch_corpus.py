"""Download two CC BY papers and materialize twelve table annotations.

Regions include the complete header/body bounded by PDF table edges. Generated
cells are observations, not reference truth; official JATS reference annotations
and validation findings live separately in reference.json.
"""

import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.request import urlopen

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "samples" / "papers"
PAPERS = [
    {"id": "womack-2015", "doi": "10.1371/journal.pone.0143460",
     "title": "Research Data in Core Journals in Biology, Chemistry, Mathematics, and Physics",
     "authors": ["Ryan P. Womack"], "tables": list(range(1, 12))},
    {"id": "giofre-2017", "doi": "10.1371/journal.pone.0175583",
     "title": "The influence of journal submission guidelines on authors' reporting of statistics and use of open research practices",
     "authors": ["David Giofrè", "Geoff Cumming", "Luca Fresc", "Ingrid Boedker", "Patrizio Tressoldi"], "tables": [2]},
]


def main():
    sys.path.insert(0, str(ROOT / "src"))
    from tableproof.pdf import parse_pdf, extract_table
    CORPUS.mkdir(parents=True, exist_ok=True)
    manifest = {"description": "Twelve single-page research tables; PDF files unchanged.", "papers": [], "tables": []}
    for paper in PAPERS:
        url = f"https://journals.plos.org/plosone/article/file?id={paper['doi']}&type=printable"
        path = CORPUS / f"{paper['id']}.pdf"
        if not path.exists():
            with urlopen(url, timeout=60) as response:
                path.write_bytes(response.read())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest["papers"].append({**paper, "file": path.name, "sha256": digest, "downloadUrl": url,
                                   "source": f"https://journals.plos.org/plosone/article?id={paper['doi']}",
                                   "license": "CC BY 4.0", "licenseUrl": "https://creativecommons.org/licenses/by/4.0/",
                                   "modifications": "None to PDF. Regions and extracted-text annotations added separately."})
        pages = parse_pdf(path, digest)
        with pdfplumber.open(path) as pdf:
            for number in paper["tables"]:
                found = False
                for index, page in enumerate(pdf.pages):
                    matches = page.search(rf"Table\s*{number}\.\s*", regex=True)
                    if not matches:
                        continue
                    caption = matches[0]
                    candidates = [t for t in page.find_tables() if t.bbox[1] >= caption["top"] and t.bbox[1] <= caption["bottom"] + 70]
                    if not candidates:
                        continue
                    candidate = max(candidates, key=lambda t: (t.bbox[2]-t.bbox[0])*(t.bbox[3]-t.bbox[1]))
                    # find_tables may recognize only interior/body cells. Use
                    # the table's horizontal rectangle edges to include the
                    # full width and the header between caption and body.
                    # This repair is corpus-specific; it is not an automatic
                    # extraction claim or a coordinate-transform correction.
                    edges = [e for e in page.edges if e["orientation"] == "h"
                             and e["top"] >= caption["bottom"]
                             and e["top"] <= candidate.bbox[3] + 3
                             and e["x1"] - e["x0"] > 15]
                    if not edges:
                        raise RuntimeError(f"Missing complete table edges for {paper['id']} Table {number}")
                    b = [min(e["x0"] for e in edges), min(e["top"] for e in edges),
                         max(e["x1"] for e in edges), max(e["bottom"] for e in edges)]
                    bbox = [b[0]-1, page.height-b[3]-1, b[2]+1, page.height-b[1]+1]
                    extraction_error = None
                    try:
                        table = extract_table(path, pages, digest, index+1, bbox)
                    except ValueError as exc:
                        if not str(exc).startswith("UNRELIABLE_MAPPING"):
                            raise
                        extraction_error = str(exc)
                        table = {"rowCount": None, "colCount": None, "cells": [],
                                 "warnings": pages[index]["warnings"]}
                    manifest["tables"].append({"id": f"{paper['id']}-table-{number}", "paperId": paper["id"],
                                               "tableNumber": number, "page": index+1, "bbox": bbox,
                                               "rowCount": table["rowCount"], "colCount": table["colCount"],
                                               "cells": table["cells"], "warnings": table["warnings"],
                                               "extractionError": extraction_error,
                                               "annotationStatus": "extractor observation; independent official JATS reference in reference.json",
                                               "regionStatus": "complete header/body region; caption and footnotes excluded",
                                               "sourceCoordinateCheck": "PDF boundary-edge region repair; original PDF coordinates unchanged"})
                    found = True
                    break
                if not found:
                    raise RuntimeError(f"Could not locate {paper['id']} Table {number}")
    (CORPUS / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Prepared {len(manifest['tables'])} paper table regions.")


if __name__ == "__main__":
    main()
