# Contributing

Use Python 3.13 and Node 24. Install lockfiles and run README's checks.

Keep original PDFs, originalText, character IDs and raw coordinates intact. All edits use the operation engine and a project-version check. Storage acknowledges success only after atomic replacement.

Bug reports should include page, region, expected and observed result. Share synthetic or redistributable samples; keep confidential papers out of public issues.

Tests assert coordinate alignment, source retention, valid grids, persisted undo/redo, conflicts, save failure and literal XLSX values. Do not use extraction output as its own accuracy ground truth.

Paper references come from publisher JATS XML and are kept separate from PDF observations. Known automatic-grid limitations use visible xfail cases; preserve these checks until the behavior improves. Trial tasks still need independent human rubric review.

Frontend changes must work offline in both languages, with keyboard access and visible errors/busy state. Bundle workers, fonts and character maps locally.

Run the portable release checklist before publication. The trial's 30% target is not a claim until measured.
