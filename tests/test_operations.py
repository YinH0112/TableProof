from copy import deepcopy
import json

import pytest

from tableproof.operations import OperationError, apply_operation, record_change, snapshot_project


def project():
    chars, cells = [], []
    for row in range(2):
        for col in range(2):
            index = row * 2 + col
            text = "ABCD"[index]
            display = [110 + 50 * col, 220 + 30 * row, 116 + 50 * col, 230 + 30 * row]
            original = [display[0], 800 - display[3], display[2], 800 - display[1]]
            chars.append({"id": f"p1-c{index}", "text": text, "bbox": original, "displayBbox": display})
            cells.append({"id": f"cell-{index}", "row": row, "col": col, "rowSpan": 1, "colSpan": 1,
                          "originalText": text, "value": text, "reviewed": True,
                          "sourceRefs": [{"fileHash": "sha", "page": 1, "bbox": original,
                                          "charIds": [f"p1-c{index}"]}]})
    return {"id": "project", "name": "Paper", "fileHash": "sha", "version": 7,
            "pages": [{"number": 1, "chars": list(reversed(chars))}],
            "tables": [{"id": "table", "page": 1, "bbox": [100, 510, 200, 590],
                        "displayBbox": [100, 210, 200, 290], "rowCount": 2, "colCount": 2,
                        "rowBoundaries": [210, 245, 290], "colBoundaries": [100, 150, 200],
                        "cells": cells, "contexts": [], "supersedes": None}],
            "history": [], "undoStack": [], "redoStack": [],
            "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-01-01T00:00:00Z"}


def test_edit_persistence_undo_redo_keep_original_evidence_and_audit():
    initial = project()
    frozen = deepcopy(initial)
    edited = apply_operation(initial, {"type": "edit", "tableId": "table", "cellId": "cell-0", "value": "0012"})
    assert initial == frozen
    assert edited["version"] == 7
    changed = edited["tables"][0]["cells"][0]
    assert changed["value"] == "0012" and changed["originalText"] == "A"
    assert changed["reviewed"] is False
    assert changed["sourceRefs"] == initial["tables"][0]["cells"][0]["sourceRefs"]
    # Persist/reload the same JSON shape that storage uses; snapshots cannot rely
    # on Python identity or undo removing earlier audit entries.
    loaded = json.loads(json.dumps(edited))
    undone = apply_operation(loaded, {"type": "undo"})
    assert undone["tables"] == initial["tables"]
    assert [h["type"] for h in undone["history"]] == ["edit", "undo"]
    assert undone["history"][0]["changes"][0]["before"]["sourceRefs"] == changed["sourceRefs"]
    redone = apply_operation(json.loads(json.dumps(undone)), {"type": "redo"})
    assert redone["tables"] == edited["tables"]
    assert [h["type"] for h in redone["history"]] == ["edit", "undo", "redo"]
    assert redone["pages"] == initial["pages"]


def test_new_edit_after_undo_invalidates_redo_but_not_audit():
    edited = apply_operation(project(), {"type": "rename", "name": "Changed"})
    undone = apply_operation(edited, {"type": "undo"})
    renamed = apply_operation(undone, {"type": "rename", "name": "Another"})
    assert renamed["redoStack"] == []
    assert [h["type"] for h in renamed["history"]] == ["rename", "undo", "rename"]
    assert apply_operation(renamed, {"type": "redo"}) == renamed


def test_noop_does_not_reset_review_or_create_history():
    initial = project()
    assert apply_operation(initial, {"type": "edit", "tableId": "table", "cellId": "cell-0", "value": "A"}) == initial


@pytest.mark.parametrize("ids", [["cell-0", "cell-3"], ["cell-0", "cell-1", "cell-2"], ["cell-0", "cell-0"]])
def test_merge_rejects_incomplete_rectangle_without_mutating_project(ids):
    initial = project()
    frozen = deepcopy(initial)
    with pytest.raises(OperationError):
        apply_operation(initial, {"type": "merge", "tableId": "table", "cellIds": ids})
    assert initial == frozen


def test_merge_pending_keeps_all_chars_and_undo_restores_original_ids():
    initial = project()
    merged = apply_operation(initial, {"type": "merge", "tableId": "table", "cellIds": ["cell-0", "cell-1"]})
    cell = merged["tables"][0]["cells"][0]
    assert (cell["rowSpan"], cell["colSpan"]) == (1, 2)
    assert cell["value"] == "A\tB" and cell["originalText"] == "A\tB"
    assert cell["reviewed"] is False
    assert [c for ref in cell["sourceRefs"] for c in ref["charIds"]] == ["p1-c0", "p1-c1"]
    assert cell["displayBbox"] == [100, 210, 200, 245]
    assert apply_operation(merged, {"type": "undo"})["tables"] == initial["tables"]


def test_split_uses_display_space_and_source_reading_order():
    merged = apply_operation(project(), {"type": "merge", "tableId": "table", "cellIds": [f"cell-{i}" for i in range(4)]})
    parent = merged["tables"][0]["cells"][0]
    result = apply_operation(merged, {"type": "split", "tableId": "table", "cellId": parent["id"], "axis": "col", "at": 1})
    left, right = result["tables"][0]["cells"]
    assert left["originalText"] == left["value"] == "A\nC"
    assert right["originalText"] == right["value"] == "B\nD"
    assert left["displayBbox"] == [100, 210, 150, 290]
    assert [c for ref in left["sourceRefs"] for c in ref["charIds"]] == ["p1-c0", "p1-c2"]
    assert [c for ref in right["sourceRefs"] for c in ref["charIds"]] == ["p1-c1", "p1-c3"]
    assert left["sourceRefs"][0]["bbox"] == [110, 570, 116, 580]
    assert left["reviewed"] is right["reviewed"] is False
    assert result["pages"] == merged["pages"]


def test_split_edited_value_requires_explicit_pair_and_preserves_original_text():
    merged = apply_operation(project(), {"type": "merge", "tableId": "table", "cellIds": ["cell-0", "cell-1"]})
    cell_id = merged["tables"][0]["cells"][0]["id"]
    edited = apply_operation(merged, {"type": "edit", "tableId": "table", "cellId": cell_id, "value": "corrected"})
    split = {"type": "split", "tableId": "table", "cellId": cell_id, "axis": "col", "at": 1}
    with pytest.raises(OperationError, match="both split values"):
        apply_operation(edited, split)
    result = apply_operation(edited, {**split, "values": ["001", "=1+2"]})
    assert [c["value"] for c in result["tables"][0]["cells"][:2]] == ["001", "=1+2"]
    assert [c["originalText"] for c in result["tables"][0]["cells"][:2]] == ["A", "B"]


def test_row_split_partitions_by_display_y_not_inverted_original_y():
    merged = apply_operation(project(), {"type": "merge", "tableId": "table", "cellIds": ["cell-0", "cell-2"]})
    parent = merged["tables"][0]["cells"][0]
    result = apply_operation(merged, {"type": "split", "tableId": "table", "cellId": parent["id"], "axis": "row", "at": 1})
    children = [c for c in result["tables"][0]["cells"] if c["col"] == 0]
    assert [c["value"] for c in children] == ["A", "C"]
    assert [c["displayBbox"] for c in children] == [[100, 210, 150, 245], [100, 245, 150, 290]]
    assert children[0]["sourceRefs"][0]["bbox"][1] > children[1]["sourceRefs"][0]["bbox"][1]


@pytest.mark.parametrize("axis,at", [("col", 0), ("col", 2), ("row", 1), ("col", 0.5)])
def test_split_rejects_outside_span_or_non_grid_boundary(axis, at):
    merged = apply_operation(project(), {"type": "merge", "tableId": "table", "cellIds": ["cell-0", "cell-1"]})
    with pytest.raises(OperationError):
        apply_operation(merged, {"type": "split", "tableId": "table", "cellId": merged["tables"][0]["cells"][0]["id"], "axis": axis, "at": at})


def test_split_empty_grid_child_gets_no_invented_source():
    initial = project()
    table = initial["tables"][0]
    table["cells"] = [table["cells"][0]]
    table["cells"][0]["colSpan"] = 2
    result = apply_operation(initial, {"type": "split", "tableId": "table", "cellId": "cell-0", "axis": "col", "at": 1})
    assert result["tables"][0]["cells"][1]["originalText"] == ""
    assert result["tables"][0]["cells"][1]["sourceRefs"] == []


def test_context_correction_retains_evidence_and_record_change_supports_extraction():
    initial = project()
    context = {"id": "ctx", "kind": "unit", "text": "mg", "bbox": [110, 570, 116, 580], "sourceRefs": deepcopy(initial["tables"][0]["cells"][0]["sourceRefs"])}
    added = apply_operation(initial, {"type": "context", "tableId": "table", "context": context})
    corrected = apply_operation(added, {"type": "context", "tableId": "table", "context": {"id": "ctx", "kind": "unit", "text": "μg", "sourceRefs": []}})
    assert corrected["tables"][0]["contexts"][0]["sourceRefs"] == context["sourceRefs"]
    assert corrected["tables"][0]["contexts"][0]["bbox"] == context["bbox"]
    snapshot = snapshot_project(initial)
    initial["tables"].append({**deepcopy(initial["tables"][0]), "id": "new"})
    record_change(initial, {"type": "extract", "tableId": "new"}, snapshot)
    assert initial["version"] == 7
    undone = apply_operation(initial, {"type": "undo"})
    assert undone["tables"] == snapshot["tables"]
    assert apply_operation(undone, {"type": "redo"})["tables"] == initial["tables"]


def test_partial_review_error_does_not_mutate_valid_selected_cells():
    initial = project()
    with pytest.raises(OperationError):
        apply_operation(initial, {"type": "review", "tableId": "table", "cellIds": ["cell-0", "missing"], "reviewed": False})
    assert initial["tables"][0]["cells"][0]["reviewed"] is True
