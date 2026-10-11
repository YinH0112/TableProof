"""Coordinates are checked against known PDF drawing instructions, not round trips alone."""

import hashlib
import io
import json
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

from tableproof.pdf import (extract_table, parse_pdf, select_context,
                            text_from_chars, transform_bbox, transform_point, _grid)

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
MANIFEST = json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))


def load_fixture(fixture):
    path = SAMPLES / fixture["filename"]
    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, file_hash, parse_pdf(path, file_hash)


@pytest.mark.parametrize("fixture", MANIFEST["fixtures"], ids=lambda f: f["id"])
def test_original_glyph_coordinates_and_boxes(fixture):
    _, _, pages = load_fixture(fixture)
    page = pages[0]
    assert page["number"] == 1
    assert page["rotation"] == fixture["rotation"]
    assert page["mediaBox"] == fixture["mediaBox"]
    assert page["cropBox"] == fixture["cropBox"]
    expected_bbox = fixture["expected"]["anchor"]["bbox"]
    # First A was drawn at this literal x/baseline in all fixture PDFs.
    anchor = next(c for c in page["chars"] if c["text"] == "A")
    assert anchor["bbox"] == pytest.approx(expected_bbox, abs=0.015)
    assert transform_bbox(page["transform"], anchor["bbox"]) == pytest.approx(anchor["displayBbox"])
    assert transform_bbox(page["inverseTransform"], anchor["displayBbox"]) == pytest.approx(expected_bbox, abs=0.015)
    assert [c["id"] for c in page["chars"]] == [f"p1-c{i}" for i in range(len(page["chars"]))]
    assert all(len(c["bbox"]) == 4 for c in page["chars"])
    assert page["mappingReliable"]


@pytest.mark.parametrize("fixture_id", ["ruled", "multiheader", "unicode_science", "crop_nonzero"])
def test_ruled_geometry_and_source_characters(fixture_id):
    fixture = next(f for f in MANIFEST["fixtures"] if f["id"] == fixture_id)
    path, file_hash, pages = load_fixture(fixture)
    table = extract_table(path, pages, file_hash, 1, fixture["tableBbox"])
    assert table["rowCount"] == fixture["expected"]["rows"]
    assert table["colCount"] == fixture["expected"]["cols"]
    assert table["extractionStrategy"] == "lines"
    assert not table["warnings"]
    for expected in fixture["expected"]["mergedCells"]:
        cell = next(c for c in table["cells"] if c["row"] == expected["row"] and c["col"] == expected["col"])
        assert cell["colSpan"] == expected["colSpan"]
    all_text = "\n".join(c["value"] for c in table["cells"])
    for text in fixture["expected"]["contains"]:
        assert text in all_text
    char_lookup = {c["id"]: c for c in pages[0]["chars"]}
    seen = set()
    for cell in table["cells"]:
        assert not cell["reviewed"]
        ref = cell["sourceRefs"][0]
        assert ref["fileHash"] == file_hash
        assert ref["page"] == 1
        assert not seen.intersection(ref["charIds"])
        seen.update(ref["charIds"])
        assert cell["originalText"] == text_from_chars(char_lookup[i] for i in ref["charIds"])
        assert transform_bbox(pages[0]["transform"], ref["bbox"]) == pytest.approx(cell["displayBbox"])


def test_caption_note_unit_are_separate_regions():
    fixture = MANIFEST["fixtures"][0]
    _, file_hash, pages = load_fixture(fixture)
    for kind in ["caption", "note", "unit"]:
        region = select_context(pages, file_hash, 1, fixture["expected"][kind + "Bbox"], kind)
        assert region["kind"] == kind
        assert region["text"]
        assert region["sourceRefs"][0]["charIds"]
    assert "invented values" in select_context(pages, file_hash, 1, fixture["expected"]["noteBbox"], "note")["text"]


def test_borderless_extraction_is_explicitly_approximate():
    fixture = next(f for f in MANIFEST["fixtures"] if f["id"] == "borderless")
    path, file_hash, pages = load_fixture(fixture)
    table = extract_table(path, pages, file_hash, 1, fixture["tableBbox"], [190, 310, 430])
    assert table["colCount"] == 4
    assert table["extractionStrategy"] in {"text", "fallback", "manual"}
    assert not table["mappingReliable"]
    assert table["warnings"]
    assert all(c["colSpan"] == c["rowSpan"] == 1 for c in table["cells"])
    assert "00123" in "\n".join(c["value"] for c in table["cells"])


def test_known_rotated_crop_corner_mapping():
    # Verify expected independently from the inverse helper. The original
    # media is (20,30,620,830), /Rotate 270. pdfminer's layout=(830-y,x-20),
    # pdfplumber display=(layout_x+30,600-layout_y-20).
    fixture = next(f for f in MANIFEST["fixtures"] if f["id"] == "rotated_270_crop")
    _, _, pages = load_fixture(fixture)
    page = pages[0]
    assert transform_point(page["transform"], 50, 710) == pytest.approx([150, 550])
    assert page["displayCropBox"] == pytest.approx([100, 20, 820, 560])


@pytest.mark.parametrize("fixture_id", ["rotated_90", "rotated_180", "rotated_270_crop"])
def test_rotated_table_does_not_reverse_cell_text(fixture_id):
    fixture = next(f for f in MANIFEST["fixtures"] if f["id"] == fixture_id)
    path, file_hash, pages = load_fixture(fixture)
    table = extract_table(path, pages, file_hash, 1, fixture["tableBbox"])
    values = [c["value"] for c in table["cells"]]
    assert "Analyte" in values
    assert "00123" in values
    assert "=literal" in values
    assert all(c["rowSpan"] == c["colSpan"] == 1 for c in table["cells"])


def test_progress_cancellation_and_stability():
    path = SAMPLES / "ruled.pdf"
    events = []
    first = parse_pdf(path, "hash", lambda done, total: events.append((done, total)))
    second = parse_pdf(path, "hash")
    assert events == [(1, 1)]
    assert first == second
    with pytest.raises(ValueError, match="^CANCELLED"):
        parse_pdf(path, "hash", cancelled=lambda: True)


def test_reject_encrypted_damaged_and_image_only(tmp_path):
    encrypted = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_page(PdfReader(SAMPLES / "ruled.pdf").pages[0])
    writer.encrypt("secret")
    with encrypted.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(ValueError, match="^ENCRYPTED_PDF"):
        parse_pdf(encrypted, "hash")
    empty_password = tmp_path / "empty_password.pdf"
    writer = PdfWriter()
    writer.add_page(PdfReader(SAMPLES / "ruled.pdf").pages[0])
    writer.encrypt("")
    with empty_password.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(ValueError, match="^ENCRYPTED_PDF"):
        parse_pdf(empty_password, "hash")
    damaged = tmp_path / "damaged.pdf"
    damaged.write_bytes(b"%PDF-1.7\nmissing catalog")
    with pytest.raises(ValueError, match="^INVALID_PDF"):
        parse_pdf(damaged, "hash")
    blank = tmp_path / "blank.pdf"
    c = canvas.Canvas(str(blank), pagesize=(600, 800))
    c.rect(40, 40, 400, 400, fill=1)
    c.showPage()
    c.save()
    with pytest.raises(ValueError, match="^NO_TEXT"):
        parse_pdf(blank, "hash")


def test_invalid_and_empty_regions():
    fixture = MANIFEST["fixtures"][0]
    path, file_hash, pages = load_fixture(fixture)
    with pytest.raises(ValueError, match="^EMPTY_REGION"):
        extract_table(path, pages, file_hash, 1, [10, 10, 30, 30])
    with pytest.raises(ValueError, match="^INVALID_REGION"):
        extract_table(path, pages, file_hash, 1, [-100, 0, 30, 30])
    with pytest.raises(ValueError, match="^INVALID_PAGE"):
        select_context(pages, file_hash, 2, [10, 10, 30, 30], "note")


def test_missing_grid_cell_is_not_a_merge():
    rows, cols, cells = _grid([[0, 0, 10, 10], [10, 0, 20, 10], [0, 10, 10, 20]])
    assert rows == cols == [0, 10, 20]
    assert len(cells) == 4
    assert all(c["rowSpan"] == c["colSpan"] == 1 for c in cells)
    missing = next(c for c in cells if c["row"] == c["col"] == 1)
    assert missing["inferredEmpty"]


def test_real_rowspan_detected_from_drawn_geometry(tmp_path):
    path = tmp_path / "rowspan.pdf"
    c = canvas.Canvas(str(path), pagesize=(300, 300))
    for y in [100, 200]:
        c.line(50, y, 250, y)
    c.line(150, 150, 250, 150)
    for x in [50, 150, 250]:
        c.line(x, 100, x, 200)
    c.setFont("Helvetica", 10)
    c.drawString(62, 160, "Two rows")
    c.drawString(162, 175, "Header")
    c.drawString(162, 125, "Value")
    c.showPage()
    c.save()
    pages = parse_pdf(path, "hash")
    table = extract_table(path, pages, "hash", 1, [50, 100, 250, 200])
    assert table["rowCount"] == table["colCount"] == 2
    cell = next(c for c in table["cells"] if c["row"] == c["col"] == 0)
    assert cell["rowSpan"] == 2
    assert cell["colSpan"] == 1
    assert cell["value"] == "Two rows"


def test_no_detected_grid_fallback_retains_all_text(tmp_path):
    path = tmp_path / "text.pdf"
    c = canvas.Canvas(str(path), pagesize=(300, 300))
    c.setFont("Helvetica", 10)
    c.drawString(60, 175, "Single value")
    c.showPage()
    c.save()
    pages = parse_pdf(path, "hash")
    table = extract_table(path, pages, "hash", 1, [50, 100, 250, 200])
    assert table["extractionStrategy"] == "fallback"
    assert table["rowCount"] == table["colCount"] == 1
    assert table["cells"][0]["value"] == "Single value"
    assert not table["mappingReliable"]
    assert any(w.startswith("GRID_FALLBACK") for w in table["warnings"])


def test_blank_page_allowed_inside_text_document(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    writer.add_page(PdfReader(SAMPLES / "ruled.pdf").pages[0])
    path = tmp_path / "mixed.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    pages = parse_pdf(path, "hash")
    assert len(pages) == 2
    assert pages[0]["warnings"] == ["NO_PAGE_TEXT"]
    assert pages[1]["chars"][0]["id"] == "p2-c0"


def test_unreliable_glyph_mapping_cannot_create_sources():
    fixture = MANIFEST["fixtures"][0]
    path, file_hash, pages = load_fixture(fixture)
    pages[0]["mappingReliable"] = False
    with pytest.raises(ValueError, match="^UNRELIABLE_MAPPING"):
        extract_table(path, pages, file_hash, 1, fixture["tableBbox"])
    with pytest.raises(ValueError, match="^UNRELIABLE_MAPPING"):
        select_context(pages, file_hash, 1, fixture["expected"]["captionBbox"], "caption")


def test_manual_columns_keep_entire_selected_header_and_caption():
    fixture = MANIFEST["fixtures"][0]
    path, file_hash, pages = load_fixture(fixture)
    table = extract_table(path, pages, file_hash, 1, [48, 510, 552, 762], [190, 310, 430])
    values = "\n".join(c["value"] for c in table["cells"])
    # Explicit guides apply to the whole selected region. Including a caption
    # is the user's choice; it must not disappear silently outside ruled edges.
    assert "Table 1." in values
    assert "Analyte" in values
    assert table["displayBbox"] == pytest.approx(transform_bbox(pages[0]["transform"], table["bbox"]))
    assert table["omittedText"] is None
    assert table["extractionStrategy"] == "manual"


def test_automatic_omitted_text_has_immutable_provenance():
    fixture = MANIFEST["fixtures"][0]
    path, file_hash, pages = load_fixture(fixture)
    table = extract_table(path, pages, file_hash, 1, [48, 510, 552, 762])
    assert "TEXT_OUTSIDE_DETECTED_GRID" in table["warnings"]
    assert "Table 1." in table["omittedText"]["text"]
    assert table["omittedText"]["sourceRefs"][0]["fileHash"] == file_hash
    assert table["omittedText"]["sourceRefs"][0]["charIds"]
