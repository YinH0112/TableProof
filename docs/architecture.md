# Architecture and evidence contract

FastAPI hosts React and PDF.js on the same loopback origin. Two import workers report progress and check cancellation between pages. Extraction uses one page. No external API or model is involved.

Each project contains immutable source.pdf and atomically replaced project.json: SHA-256, stable character IDs, geometry, tables, contexts, audit and undo/redo. RLock serializes read/check/mutate/save within one process. Only one server may use a data directory; no cross-process lock is implemented.

## Coordinates and edits

- Source/character/table bbox and API selections use original PDF user space, before rotation.
- displayBbox, rowBoundaries/colBoundaries and columnLines use pdfplumber absolute top-left space, including MediaBox offset.
- page.transform maps raw PDF to display space using pdfminer's actual page CTM. PDF.js viewport maps raw points to CSS; transform four corners, including crop, rotation and zoom.
- Mapping reliability is explicit. Empty cells get grid-region sources, never fabricated character IDs.

Cells own stable ID, zero-based row/col, positive spans, originalText, value, sourceRefs and reviewed. Geometry determines spans; None alone never proves a merge. Merge requires complete rectangular coverage without cutting a span. Split only at existing grid boundaries; chars partition by center. Edited splits require both new values. Edits invalidate review.

Re-extraction adds a table with supersedes linking the old one; old edits remain. Undo/redo restores editable snapshots and appends audit. Version increases only after a saved mutation.

## API

| Route | Contract |
|---|---|
| POST /api/projects | multipart file →202 {jobId} |
| GET /api/demo | sample import →202 {jobId} |
| GET /api/jobs/{id} | status/progress/projectId/error |
| DELETE /api/jobs/{id} | cooperative cancel |
| GET /api/projects | saved summaries |
| GET /api/projects/{id} | project JSON |
| GET …/source | original PDF |
| POST …/tables | {version,page,bbox,columnLines?,supersedes?} |
| POST …/operations | {version,operation} |
| GET …/export.xlsx | literal-string workbook |

Operations: edit, review, merge, split, context, rename, undo, redo. Split: axis row/col, at absolute grid boundary, optional values [first,second]. Context: kind caption/note/unit, page/bbox. Old version→409; invalid input→422; unknown project/job→404.

Excel has a sheet per table version, anchor comments, Sources/Changes/Metadata. All values are explicit strings, including zeros and formula prefixes.
