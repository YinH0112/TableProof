"""Generate redistributable, synthetic research PDFs and known coordinates.

Run ``python scripts/generate_samples.py``.  These are invented measurements,
not copied papers.  Vera is the ReportLab-distributed Bitstream font; Chinese
uses ReportLab's standard STSong-Light CID font without bundling a font file.
"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import reportlab
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
BOX = [50, 510, 550, 710]


def register_fonts() -> None:
    if "TPVera" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("TPVera", str(Path(reportlab.__file__).parent / "fonts" / "Vera.ttf")))
    if "STSong-Light" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))


def ruled_table(c: canvas.Canvas, *, scientific: bool = False, merged: bool = False) -> dict:
    xs = [50, 190, 310, 430, 550]
    ys = [710, 670, 630, 590, 550, 510]
    c.setLineWidth(0.7)
    for y in ys:
        c.line(xs[0], y, xs[-1], y)
    for x in xs:
        # Two independently merged groups in the top header, established by
        # missing vertical segments, not by empty extracted cell values.
        c.line(x, ys[-1], x, ys[1] if merged and x in {190, 430} else ys[0])
    c.setFont("Helvetica", 10)
    if merged:
        c.drawString(65, 685, "Aqueous group")
        c.drawString(325, 685, "Solid group")
        for index, value in enumerate(["Analyte", "Dose", "Analyte", "Dose"]):
            c.drawString(xs[index] + 12, 645, value)
    else:
        for index, value in enumerate(["Analyte", "Dose", "Mean", "Unit"]):
            c.drawString(xs[index] + 12, 685, value)
        for index, value in enumerate(["A", "00123", "1.20", "mg/L"]):
            c.drawString(xs[index] + 12, 645, value)
    data = [["B", "00007", "2.40", "mg/L"],
            ["C", "=literal", "3.60", "mg/L"],
            ["D", "10-3", "4.80", "mg/L"]]
    for row, values in enumerate(data):
        for col, value in enumerate(values):
            if scientific and row == 0 and col < 3:
                continue
            c.drawString(xs[col] + 12, 605 - row * 40, value)
    if scientific:
        c.setFont("STSong-Light", 10)
        c.drawString(62, 605, "μm ± 0.03")
        c.setFont("TPVera", 10)
        c.drawString(202, 605, "10^-3 cm²")
        c.setFont("STSong-Light", 10)
        c.drawString(322, 605, "样本甲")
    c.setFont("Helvetica", 10)
    c.drawString(50, 747, "Table 1. Synthetic measurements")
    c.drawString(50, 487, "Note: invented values; uncertainty is one standard deviation.")
    c.drawString(50, 470, "Units: dose in mg/L; no numeric conversion applied.")
    return {"rows": 5, "cols": 4,
            "mergedCells": [{"row": 0, "col": 0, "colSpan": 2},
                            {"row": 0, "col": 2, "colSpan": 2}] if merged else [],
            "anchor": {"text": "A", "baseline": [65, 685] if merged else [62, 685],
                       "bbox": [65 if merged else 62, 682.93, 71.67 if merged else 68.67, 692.93]},
            "contains": ["Aqueous group", "Solid group"] if merged else ["00123", "=literal"],
            "captionBbox": [48, 740, 400, 762], "noteBbox": [48, 480, 550, 500],
            "unitBbox": [48, 465, 550, 480]}


def borderless_table(c: canvas.Canvas) -> dict:
    xs = [62, 202, 322, 442]
    rows = [["Analyte", "Dose", "Mean", "Unit"],
            ["A", "00123", "1.20", "mg/L"],
            ["B", "00007", "2.40", "mg/L"],
            ["C", "=literal", "3.60", "mg/L"],
            ["D", "10-3", "4.80", "mg/L"]]
    c.setFont("Helvetica", 10)
    for row, values in enumerate(rows):
        for x, value in zip(xs, values):
            c.drawString(x, 685 - row * 40, value)
    c.drawString(50, 747, "Table 2. Borderless synthetic measurements")
    return {"rows": 5, "cols": 4, "mergedCells": [], "contains": ["00123", "=literal"],
            "anchor": {"text": "A", "baseline": [62, 685], "bbox": [62, 682.93, 68.67, 692.93]},
            "columnLinesRaw": [190, 310, 430]}


def generate_samples(output: Path = SAMPLES) -> dict:
    register_fonts()
    output.mkdir(parents=True, exist_ok=True)
    definitions = [
        ("ruled", "Ruled table, literal leading zero and equals", 0, None, None, False, False, False),
        ("multiheader", "Two real spanning header cells", 0, None, None, True, False, False),
        ("borderless", "Borderless table with explicit optional columns", 0, None, None, False, False, True),
        ("unicode_science", "Chinese and scientific Unicode strings", 0, None, None, True, True, False),
        ("rotated_90", "90 degree page rotation", 90, None, None, False, False, False),
        ("rotated_180", "180 degree page rotation", 180, None, None, False, False, False),
        ("crop_nonzero", "Nonzero MediaBox and smaller CropBox", 0, [20, 30, 620, 830], [40, 40, 580, 760], False, False, False),
        ("rotated_270_crop", "270 degree rotation with nonzero MediaBox and CropBox", 270, [20, 30, 620, 830], [40, 40, 580, 760], False, False, False),
    ]
    fixtures = []
    for name, scenario, rotation, media, crop, merged, scientific, borderless in definitions:
        stream = io.BytesIO()
        c = canvas.Canvas(stream, pagesize=(600, 800), invariant=1)
        c.setTitle(f"TableProof synthetic fixture: {name}")
        expected = borderless_table(c) if borderless else ruled_table(c, scientific=scientific, merged=merged)
        c.showPage()
        c.save()
        reader = PdfReader(io.BytesIO(stream.getvalue()))
        page = reader.pages[0]
        if media:
            page.mediabox = RectangleObject(media)
        if crop:
            page.cropbox = RectangleObject(crop)
        if rotation:
            page.rotate(rotation)
        writer = PdfWriter()
        writer.add_page(page)
        writer.add_metadata({"/Title": f"TableProof synthetic fixture: {name}"})
        filename = f"{name}.pdf"
        with (output / filename).open("wb") as handle:
            writer.write(handle)
        if scientific:
            expected["contains"] += ["μm ± 0.03", "10^-3 cm²", "样本甲"]
        fixtures.append({"id": name, "filename": filename, "scenario": scenario,
                         "page": 1, "rotation": rotation, "mediaBox": media or [0, 0, 600, 800],
                         "cropBox": crop or media or [0, 0, 600, 800], "tableBbox": BOX,
                         "expected": expected})
    manifest = {"schemaVersion": 1, "synthetic": True,
                "coordinateSpace": "original unrotated PDF user space (points)",
                "fontNotes": "Helvetica; ReportLab-distributed Bitstream Vera; standard STSong-Light CID font. No external font files distributed.",
                "fixtures": fixtures}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(output / "multiheader.pdf", output / "demo.pdf")
    return manifest


if __name__ == "__main__":
    result = generate_samples()
    print(f"Generated {len(result['fixtures'])} synthetic PDFs in {SAMPLES}")
