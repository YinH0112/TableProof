"""Evidence-preserving table edits on JSON projects.

Grid boundaries and character ``displayBbox`` use pdfplumber's display space.
Source references always retain original PDF user-space coordinates.  Operations
return a deep copy; storage owns the project version and save timestamp.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


class OperationError(ValueError):
    """An edit cannot be applied without losing evidence or grid validity."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def snapshot_project(project: dict[str, Any]) -> dict[str, Any]:
    """Capture editable state; PDF pages and original character data are immutable."""
    return deepcopy({"name": project.get("name", ""), "tables": project.get("tables", [])})


def _changes(before: dict, after: dict) -> list[dict]:
    result = []
    if before.get("name") != after.get("name"):
        result.append({"entity": "name", "before": before.get("name"), "after": after.get("name")})
    before_tables = {t["id"]: t for t in before.get("tables", [])}
    after_tables = {t["id"]: t for t in after.get("tables", [])}
    for table_id in dict.fromkeys([*before_tables, *after_tables]):
        old, new = before_tables.get(table_id), after_tables.get(table_id)
        if old is None or new is None:
            result.append({"entity": "table", "tableId": table_id, "before": old, "after": new})
            continue
        old_meta = {k: v for k, v in old.items() if k not in ("cells", "contexts")}
        new_meta = {k: v for k, v in new.items() if k not in ("cells", "contexts")}
        if old_meta != new_meta:
            result.append({"entity": "table", "tableId": table_id, "before": old_meta, "after": new_meta})
        for key, entity, id_key in (("cells", "cell", "cellId"), ("contexts", "context", "contextId")):
            old_items = {c["id"]: c for c in old.get(key, [])}
            new_items = {c["id"]: c for c in new.get(key, [])}
            for item_id in dict.fromkeys([*old_items, *new_items]):
                left, right = old_items.get(item_id), new_items.get(item_id)
                if left != right:
                    result.append({"entity": entity, "tableId": table_id, id_key: item_id,
                                   "before": left, "after": right})
    return deepcopy(result)


def _audit(project: dict, action: dict, before: dict, after: dict) -> dict:
    record = {"id": str(uuid4()), "type": action.get("type", "change"),
              "action": deepcopy(action), "createdAt": _now(),
              "version": project.get("version", 0) + 1,
              "changes": _changes(before, after)}
    project.setdefault("history", []).append(record)
    return record


def record_change(project: dict, action: dict | str, before_snapshot: dict) -> dict:
    """Record an already-applied change, including extraction, on ``project``.

    The caller takes ``snapshot_project`` before mutation, then calls this helper.
    It does not increment the version. No-op changes leave history and stacks alone.
    """
    if isinstance(action, str):
        action = {"type": action}
    before, after = deepcopy(before_snapshot), snapshot_project(project)
    if before == after:
        return project
    record = _audit(project, action, before, after)
    project.setdefault("undoStack", []).append({"historyId": record["id"], "action": deepcopy(action),
                                               "before": before, "after": after})
    project["redoStack"] = []
    return project


def _table(project: dict, table_id: Any) -> dict:
    for table in project.get("tables", []):
        if table.get("id") == table_id:
            return table
    raise OperationError("Table not found.")


def _cell(table: dict, cell_id: Any) -> dict:
    for cell in table.get("cells", []):
        if cell.get("id") == cell_id:
            return cell
    raise OperationError("Cell not found.")


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise OperationError(f"{label} must be a string.")
    return value


def _indices(cell: dict) -> tuple[int, int, int, int]:
    values = [cell.get(k) for k in ("row", "col", "rowSpan", "colSpan")]
    if any(not isinstance(v, int) or isinstance(v, bool) for v in values):
        raise OperationError("Cell grid coordinates must be integers.")
    row, col, rows, cols = values
    if min(row, col) < 0 or min(rows, cols) < 1:
        raise OperationError("Cell grid coordinates are invalid.")
    return row, col, row + rows, col + cols


def _slots(cell: dict) -> set[tuple[int, int]]:
    r0, c0, r1, c1 = _indices(cell)
    return {(r, c) for r in range(r0, r1) for c in range(c0, c1)}


def _display_bbox(table: dict, cell: dict) -> list[float]:
    r0, c0, r1, c1 = _indices(cell)
    rows, cols = table.get("rowBoundaries"), table.get("colBoundaries")
    for boundaries, size in ((rows, table.get("rowCount")), (cols, table.get("colCount"))):
        if not isinstance(boundaries, list) or len(boundaries) != size + 1:
            raise OperationError("This table has no complete grid boundaries for splitting.")
        if any(not isinstance(x, (int, float)) or isinstance(x, bool) for x in boundaries):
            raise OperationError("Grid boundaries must be numbers.")
        if any(a >= b for a, b in zip(boundaries, boundaries[1:])):
            raise OperationError("Grid boundaries must be strictly increasing.")
    if r1 > table["rowCount"] or c1 > table["colCount"]:
        raise OperationError("Cell is outside the table grid.")
    return [cols[c0], rows[r0], cols[c1], rows[r1]]


def _source_union(cells: list[dict]) -> list[dict]:
    refs = []
    for cell in cells:
        for ref in cell.get("sourceRefs", []):
            if ref not in refs:
                refs.append(deepcopy(ref))
    return refs


def _joined(cells: list[dict], key: str) -> str:
    lines: dict[int, list[str]] = {}
    for cell in sorted(cells, key=lambda c: (c["row"], c["col"])):
        lines.setdefault(cell["row"], []).append(cell.get(key, ""))
    return "\n".join("\t".join(line) for line in lines.values())


def _merge(table: dict, operation: dict) -> None:
    ids = operation.get("cellIds")
    if (not isinstance(ids, list) or len(ids) < 2 or any(not isinstance(i, str) for i in ids)
            or len(set(ids)) != len(ids)):
        raise OperationError("Select at least two distinct cells to merge.")
    selected = [_cell(table, cell_id) for cell_id in ids]
    bounds = [_indices(c) for c in selected]
    r0, c0 = min(b[0] for b in bounds), min(b[1] for b in bounds)
    r1, c1 = max(b[2] for b in bounds), max(b[3] for b in bounds)
    expected = {(r, c) for r in range(r0, r1) for c in range(c0, c1)}
    covered: set[tuple[int, int]] = set()
    for cell in selected:
        slots = _slots(cell)
        if covered & slots:
            raise OperationError("Selected cells overlap.")
        covered |= slots
    if covered != expected:
        raise OperationError("Merged cells must fill a complete rectangle.")
    for cell in table["cells"]:
        if cell["id"] not in ids and _slots(cell) & expected:
            raise OperationError("Merge includes an unselected cell.")
    if r1 > table["rowCount"] or c1 > table["colCount"]:
        raise OperationError("Merge is outside the table grid.")
    merged = {"id": str(uuid4()), "row": r0, "col": c0, "rowSpan": r1 - r0, "colSpan": c1 - c0,
              "originalText": _joined(selected, "originalText"), "value": _joined(selected, "value"),
              "sourceRefs": _source_union(selected), "reviewed": False}
    if table.get("rowBoundaries") and table.get("colBoundaries"):
        merged["displayBbox"] = _display_bbox(table, merged)
    table["cells"] = sorted([c for c in table["cells"] if c["id"] not in ids] + [merged],
                            key=lambda c: (c["row"], c["col"]))


def _bbox_union(chars: list[dict]) -> list[float]:
    return [min(c["bbox"][0] for c in chars), min(c["bbox"][1] for c in chars),
            max(c["bbox"][2] for c in chars), max(c["bbox"][3] for c in chars)]


def _partition_sources(project: dict, cell: dict, axis: str, cut: float) -> tuple[list[list[dict]], list[list[dict]]]:
    pages = {p["number"]: {c["id"]: c for c in p.get("chars", [])} for p in project.get("pages", [])}
    refs: list[list[dict]] = [[], []]
    source_chars: list[list[dict]] = [[], []]
    seen = [set(), set()]
    for ref in cell.get("sourceRefs", []):
        chars_by_id = pages.get(ref.get("page"), {})
        grouped: list[list[dict]] = [[], []]
        for char_id in ref.get("charIds", []):
            char = chars_by_id.get(char_id)
            if char is None or len(char.get("displayBbox", [])) != 4:
                raise OperationError("Source characters are unavailable for this split.")
            bbox = char["displayBbox"]
            center = (bbox[1] + bbox[3]) / 2 if axis == "row" else (bbox[0] + bbox[2]) / 2
            side = 0 if center < cut else 1
            grouped[side].append(char)
            identity = (ref.get("fileHash"), ref.get("page"), char_id)
            if identity not in seen[side]:
                source_chars[side].append(char)
                seen[side].add(identity)
        for side, chars in enumerate(grouped):
            if chars:
                new_ref = deepcopy(ref)
                new_ref["bbox"] = _bbox_union(chars)
                new_ref["charIds"] = list(dict.fromkeys(c["id"] for c in chars))
                refs[side].append(new_ref)
    if cell.get("originalText") and not any(source_chars):
        raise OperationError("This cell has no source characters to split.")
    return refs, source_chars


def _split(project: dict, table: dict, operation: dict) -> None:
    cell = _cell(table, operation.get("cellId"))
    axis, at = operation.get("axis"), operation.get("at")
    if axis not in ("row", "col") or not isinstance(at, int) or isinstance(at, bool):
        raise OperationError("Split needs a row/col axis and an integer grid boundary.")
    r0, c0, r1, c1 = _indices(cell)
    start, end = (r0, r1) if axis == "row" else (c0, c1)
    if not start < at < end:
        raise OperationError("Split must lie inside the cell at an existing grid boundary.")
    _display_bbox(table, cell)
    values = operation.get("values")
    if values is not None and (not isinstance(values, list) or len(values) != 2 or
                               any(not isinstance(v, str) for v in values)):
        raise OperationError("Split values must be an explicit pair of strings.")
    if cell.get("value") != cell.get("originalText") and values is None:
        raise OperationError("Provide both split values for an edited cell.")
    boundary = table["rowBoundaries" if axis == "row" else "colBoundaries"][at]
    refs, chars = _partition_sources(project, cell, axis, boundary)
    from .pdf import text_from_chars

    children = []
    for side in range(2):
        child = {"id": str(uuid4()), "row": r0, "col": c0, "rowSpan": r1 - r0, "colSpan": c1 - c0,
                 "sourceRefs": refs[side], "originalText": text_from_chars(chars[side]), "reviewed": False}
        if axis == "row":
            child["row"] = r0 if side == 0 else at
            child["rowSpan"] = at - r0 if side == 0 else r1 - at
        else:
            child["col"] = c0 if side == 0 else at
            child["colSpan"] = at - c0 if side == 0 else c1 - at
        child["value"] = values[side] if values is not None else child["originalText"]
        child["displayBbox"] = _display_bbox(table, child)
        children.append(child)
    table["cells"] = sorted([c for c in table["cells"] if c["id"] != cell["id"]] + children,
                            key=lambda c: (c["row"], c["col"]))


def apply_operation(project: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    """Validate and apply an operation without changing the input project."""
    result = deepcopy(project)
    if not isinstance(operation, dict):
        raise OperationError("Operation must be an object.")
    kind = operation.get("type")
    before = snapshot_project(result)
    if kind in ("undo", "redo"):
        source = "undoStack" if kind == "undo" else "redoStack"
        destination = "redoStack" if kind == "undo" else "undoStack"
        if not result.get(source):
            return result
        entry = result[source].pop()
        snapshot = deepcopy(entry["before" if kind == "undo" else "after"])
        result.update(snapshot)
        result.setdefault(destination, []).append(entry)
        _audit(result, {"type": kind, "targetHistoryId": entry["historyId"]}, before, snapshot_project(result))
        return result
    if kind == "rename":
        name = _string(operation.get("name"), "Project name").strip()
        if not name:
            raise OperationError("Project name cannot be empty.")
        result["name"] = name
    elif kind in ("edit", "review", "merge", "split", "context"):
        table = _table(result, operation.get("tableId"))
        if kind == "edit":
            cell = _cell(table, operation.get("cellId"))
            value = _string(operation.get("value"), "Cell value")
            if cell.get("value") != value:
                cell["value"], cell["reviewed"] = value, False
        elif kind == "review":
            ids, reviewed = operation.get("cellIds"), operation.get("reviewed")
            if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids):
                raise OperationError("Review needs one or more cell IDs.")
            if not isinstance(reviewed, bool):
                raise OperationError("Reviewed must be a boolean.")
            cells = [_cell(table, cell_id) for cell_id in ids]
            for cell in cells:
                cell["reviewed"] = reviewed
        elif kind == "merge":
            _merge(table, operation)
        elif kind == "split":
            _split(result, table, operation)
        else:
            context = deepcopy(operation.get("context"))
            if not isinstance(context, dict):
                raise OperationError("Context must be an object.")
            context_id = context.get("id") or str(uuid4())
            context["id"] = _string(context_id, "Context ID")
            _string(context.get("kind"), "Context kind")
            _string(context.get("text"), "Context text")
            if not isinstance(context.get("sourceRefs", []), list):
                raise OperationError("Context source references must be a list.")
            contexts = table.setdefault("contexts", [])
            existing = next((c for c in contexts if c["id"] == context_id), None)
            if existing is not None:
                # A textual correction cannot erase its captured PDF evidence.
                context = {**deepcopy(existing), **context}
                context["sourceRefs"] = deepcopy(existing.get("sourceRefs", []))
                contexts[contexts.index(existing)] = context
            else:
                context.setdefault("sourceRefs", [])
                contexts.append(context)
    else:
        raise OperationError("Unknown operation type.")
    return record_change(result, operation, before)
