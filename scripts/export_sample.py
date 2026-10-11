"""Create a complete evidence workbook for manual office-app verification."""
import hashlib
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tableproof.export import export_xlsx
from tableproof.operations import apply_operation, record_change, snapshot_project
from tableproof.pdf import extract_table, parse_pdf, select_context
from tableproof.storage import timestamp


def main():
    path = ROOT / "samples" / "demo.pdf"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    pages = parse_pdf(path, digest)
    now = timestamp()
    project = {"id": uuid.uuid4().hex, "name": "Demonstration", "version": 1, "fileHash": digest,
               "pages": pages, "tables": [], "history": [], "undoStack": [], "redoStack": [],
               "createdAt": now, "updatedAt": now}
    before = snapshot_project(project)
    table = extract_table(path, pages, digest, 1, [50, 510, 550, 710])
    project["tables"].append(table)
    record_change(project, {"type": "extract", "tableId": table["id"]}, before)
    project["version"] += 1
    for kind, box in [("caption", [48, 740, 550, 762]), ("note", [48, 480, 550, 500]), ("unit", [48, 465, 550, 480])]:
        context = select_context(pages, digest, 1, box, kind)
        project = apply_operation(project, {"type": "context", "tableId": table["id"], "context": context})
        project["version"] += 1
    target = next(c for c in table["cells"] if c["value"] == "=literal")
    project = apply_operation(project, {"type": "edit", "tableId": table["id"], "cellId": target["id"], "value": "=00123"})
    project["version"] += 1
    project = apply_operation(project, {"type": "review", "tableId": table["id"], "cellIds": [target["id"]], "reviewed": True})
    project["version"] += 1
    output = ROOT / "output" / "playwright" / "demo.xlsx"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(export_xlsx(project))
    print(output)


if __name__ == "__main__":
    main()
