# Local preview verification

Recorded on **2026-10-11**, Windows x64, Python 3.13.2 and an isolated Node 24.21.0 toolchain. This is evidence for a local v0.1 preview; publication and the researcher trial are still pending.

## Checks and results

| Check | Result | Scope |
| --- | --- | --- |
| `pytest -q` | 80 passed, 12 expected failures | PDF parsing and coordinates, project persistence, revisions, structural operations, API, literal-string export and independent paper references |
| Playwright | 9 passed | Import, selection, extraction, source lookup, editing, review, save/reopen, export, undo/redo, merge/split, context selection, extraction versions, errors, cancellation and draft protection; the main workflow blocks non-loopback network requests |
| Frontend build | Passed | TypeScript and production Vite bundle; PDF.js worker, CMaps, standard fonts and WASM are local resources |
| Portable smoke | Passed | Executable started from a temporary directory with Python/Node absent from PATH; served frontend, parsed the bundled demo, extracted, edited, persisted and exported |
| Microsoft Excel | Passed | Export opened without a repair prompt; `=00123` was text rather than a formula, `00007` retained zeros, merged headers and evidence worksheets remained present |
| LibreOffice | Not checked | Not installed on the verification machine |
| GitHub CI | Prepared, not executed | Windows/Ubuntu workflow is supplied; no remote run is claimed |
| Five-person trial | Not started | Protocol and blank results sheet supplied; no time-saving claim is supported yet |

Reproduce Python and browser checks with the commands in the README. Portable and Excel checks use `scripts/smoke_portable.py`, `scripts/export_sample.py` and `scripts/check-excel.ps1`.

## Source coordinates

Eight generated PDFs cover ruled/borderless tables, grouped headers, Chinese and scientific symbols, all four page rotations, CropBox and a nonzero page origin. Backend coordinates are original, unrotated PDF user-space coordinates; the frontend transforms them through the actual PDF.js viewport.

Five browser geometry cases independently compare known drawing anchors with rendered highlights at device pixel ratio 2 and after zooming. Each assertion requires at most **1 CSS pixel** error. Unmapped glyphs or unreliable source geometry block extraction instead of guessing a location.

## Real paper corpus

The corpus contains 12 table regions from two attributed CC BY 4.0 PLOS papers. PDF hashes, DOI, authors, licenses and region changes are in `samples/papers/manifest.json`. Independent table references in `samples/papers/reference.json` come from publisher JATS XML, with XML URLs and hashes. They are separate from pdfplumber extraction observations. All 12 regions were rendered and checked against distinct official values to verify that the selection covers the intended table.

**All 12 automatic full-structure checks currently fail.** Ten regions produce partial or incorrect grids; two Womack regions (Tables 9 and 11) are blocked because their pages contain unmapped glyphs. The tests report these as expected failures, not successful extraction. Text outside a detected grid is retained with source references and exported separately, so a partial grid does not silently discard that text.

| Region | Independent shape | Automatic result |
| --- | --- | --- |
| Womack Tables 1–4 | 11 × 5 each | 10 × 3; 10 × 3; 10 × 1; 10 × 4 |
| Womack Tables 5–8 | 12 × 4 each | 11 × 1; 11 × 1; 11 × 1; 11 × 3 |
| Womack Table 9 | 6 × 6 | Blocked: unreliable mapping |
| Womack Table 10 | 6 × 5 | 5 × 1 |
| Womack Table 11 | 17 × 6 | Blocked: unreliable mapping |
| Giofrè Table 2 | 12 × 7 | 14 × 5 |

For **Giofrè Table 2, page 9**, six manually supplied column guides and two header merges recover the correct 12 × 7 structure. All **80 anchor cells** and header spans match the independent XML reference; text comparisons normalize whitespace only. XLSX reopening also checks all 80 values and the `B1:D1` / `E1:G1` merges. A separate API test runs import → manual extraction → merges → edit → caption selection → save/reopen → XLSX export against this real paper.

This demonstrates a correction workflow on one real research table. It does not establish general extraction accuracy or reliable handling of every scientific notation/font.

## Data and failure behavior

Tests cover atomic replacement failures, stale-version conflicts, immutable source text, review reset after edits, rectangular merge constraints, explicit values when splitting edited cells, history retention through undo/redo, and preserved extraction versions. Browser tests verify that failed saves retain the draft and do not proceed to export; version conflicts preserve attempted edits for retry.

All spreadsheet cell values are written as literal strings. Export rejects unsupported Excel control characters or overlong cells with an explicit error. Scanned, damaged, encrypted or unmappable documents produce actionable errors. Cancellation is checked between pages; a complex page can delay cancellation.

## Release status

The portable package and source are ready for local evaluation. The 30% median time-saving target remains unvalidated. Broader extraction quality, LibreOffice interoperability, unfamiliar-user installation and the five-person trial remain release work. Public release, promotion and recruitment have not been performed.
