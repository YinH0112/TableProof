# TableProof Research

**Review research PDF tables with the original evidence beside every cell.**

[中文文档](README.zh-CN.md) · [Verification](docs/verification.md) · [Contributing](CONTRIBUTING.md)

TableProof is a local web workspace for researchers turning paper tables into spreadsheets. Select a table, inspect each cell in the PDF, correct its text or structure, and export the result with source references and revision history.

**Open a paper → select a table → check the source → correct and review → export Excel.**

![PDF source and table review side by side](docs/images/workbench.png)

**Status: v0.1 local preview.** The correction workflow is implemented and tested. Automatic grid detection still needs manual checking; see [current limitations](#current-limitations). The researcher trial and public release are pending.

## What you can do

| Task | Support |
| --- | --- |
| Extract a table | Select a region on one text-layer PDF page; add manual column guides when needed |
| Check a value | Click a cell to highlight its original source and compare original text with the current value |
| Correct structure | Merge a complete rectangular group; split spanning cells along existing grid boundaries |
| Track review | Mark cells reviewed; editing or structural changes reset affected review states |
| Preserve context | Select the table caption, notes and units from the PDF |
| Continue later | Save projects locally, reopen them, undo/redo and inspect earlier extraction versions |
| Export evidence | XLSX with table sheets, sources, changes and document/context information |

The interface supports Chinese and English. FastAPI serves the built frontend on `127.0.0.1`; PDF.js workers, fonts and character maps are bundled. Daily use needs no internet connection or model key. Your documents stay in the local project directory.

## Quick start

### Windows portable package

Use `TableProof-0.1.0-windows-x64.zip` when you have the local preview package. Python and Node.js are not required.

1. Extract the **entire ZIP**, keeping the `TableProof` folder and its `_internal` directory together.
2. Double-click `TableProof/Start.cmd`.
3. Your browser opens [http://127.0.0.1:8765](http://127.0.0.1:8765). Open it manually if it does not launch automatically.
4. Choose the built-in demo to try the workflow, or import your own text-layer PDF.

Keep the console window open while working. Closing it stops the service. If port 8765 is occupied, run this from the extracted `TableProof` folder:

```powershell
.\TableProof.exe --port 8766
```

The portable package includes the demo PDF. The full geometry fixtures and paper corpus are in the source checkout. ZIPs are build outputs under `dist/`, not tracked source files; if you only have the source, use the next section.

### Run from source

Prerequisites: **Python 3.13**, **Node.js 24** and [uv](https://docs.astral.sh/uv/). Initial dependency installation requires internet access; the built application runs locally afterward. Exact versions are recorded in `uv.lock` and `frontend/package-lock.json`.

Run these commands from the **repository root** in Windows PowerShell:

```powershell
uv sync --frozen --cache-dir .tools/uv-cache
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
uv run --frozen --cache-dir .tools/uv-cache tableproof
```

For a Bash shell on Linux/macOS, use `npm` in place of `npm.cmd`:

```bash
uv sync --frozen --cache-dir .tools/uv-cache
npm --prefix frontend ci
npm --prefix frontend run build
uv run --frozen --cache-dir .tools/uv-cache tableproof
```

The local verification run covered Windows. The supplied CI workflow targets Windows and Ubuntu but has not yet run remotely.

Launch options:

```powershell
uv run --frozen --cache-dir .tools/uv-cache tableproof --port 8766 --data-dir ./local-projects --no-browser
```

`--port` changes the loopback port, `--data-dir` chooses the project directory, and `--no-browser` keeps startup from opening a browser.

## Review your first table

1. **Import and select.** Open the demo or import a PDF with selectable text. Choose a page, select Table mode, drag around the complete table and click **Extract this region**. Import progress and cancellation are available after upload.
2. **Check the source.** Click a cell. The PDF highlights its source, and Cell evidence shows both Original extraction and Current value. Empty cells use a region reference rather than a character reference.
3. **Save a correction.** Edit Current value, then click **Save value**. Typing alone creates an unsaved draft. Changing cells, switching projects or exporting prompts you to save, discard or keep editing. A failed save retains the draft.
4. **Fix the structure.** Tick the cell checkboxes to select a complete adjacent rectangle for merging. To split, select one spanning cell and choose an existing row/column boundary. If its text has been edited, enter both resulting values explicitly.
5. **Add context and review.** Choose Caption, Note or Unit mode, select the corresponding PDF text and attach it. Mark checked cells reviewed. Editing a value resets its review state.
6. **Export.** Click **Export Excel**. Review is recorded per cell; pending cells can also be exported. Reopen a saved project through Open a project when you return.

If columns are wrong, choose **Re-extract table**, enable **Column guides**, and click inside the selected region to add separators. Click a guide again to remove it, then extract. This creates a new table version from the PDF. Earlier values and review states remain in the old version; they are not copied into the new extraction. Enable **Show earlier versions** to inspect them.

Text selected outside the detected grid appears separately for review with its source references. Check the region or add column guides before treating a partial extraction as a complete table.

## What is in the Excel file?

| Worksheet | Contents |
| --- | --- |
| `Table 1`, `Table 2`, … | Every table version, merged cells, current values and attached context; superseded versions are labelled |
| `Sources` | File hash, page, PDF coordinates, character IDs and review state; cell links lead to this index |
| `Changes` | Revision history, including corrections and undo/redo operations |
| `Metadata` | Document identity, table context, extraction strategy and warnings |

Values are written as **literal strings**: `00007`, scientific symbols and text beginning with `=` are preserved. Convert numeric columns after review if you need calculations. Values exceeding Excel's cell limits or containing unsupported control characters produce an explicit export error.

The XLSX contains source references; it does **not embed the original PDF**. Keep or share the full project directory when someone needs to reopen the evidence in TableProof.

## Local data and privacy

Default project locations:

| Platform | Directory |
| --- | --- |
| Windows | `%LOCALAPPDATA%/TableProofResearch` |
| Linux/macOS | `~/.local/share/TableProofResearch` |

Each project keeps an unchanged `source.pdf` and a `project.json` containing the file hash, character geometry, tables, context and edit history. JSON saves use atomic replacement. A successful operation is acknowledged only after saving; failed saves leave the previous project file intact.

Override the location with `--data-dir PATH` or `TABLEPROOF_DATA_DIR`. Back up the **whole project directory**, preferably after stopping the service. Only one server should use a data directory, and project JSON should not be edited while the app runs. Browser tabs use version checks to prevent stale edits from overwriting newer changes.

## Current limitations

- Text-layer PDFs and **single-page tables** are supported. OCR, automatic cross-page joining, statistical conclusion checks, cloud services and collaboration are outside this preview.
- Automatic table geometry is a starting point for human review. All **12 automatic full-structure checks** in the current real-paper corpus fail: ten need grid correction, and two are blocked by unmapped glyphs. This is reported as 12 expected test failures, not an accuracy success.
- Manual column guides and two header merges recover the demonstrated Giofrè paper table: **80/80 cells** and merged headers match the independent publisher XML reference after whitespace normalization. This result applies to that example, not all research tables.
- Unreliable source mappings block extraction. A reviewed flag records the user's confirmation, not automatic correctness.
- Imports are limited to **100 MB**. Cancellation is checked between pages; a complex page can delay it. Upload-stage cancellation is not available.
- Windows portable startup and Microsoft Excel opening were checked. LibreOffice was unavailable; its interoperability remains unverified.

See the dated [verification record](docs/verification.md) for evidence and unresolved work. The [five-researcher trial](docs/research-trial.md) is prepared but has not been conducted. A 30% reduction in median task time is a validation target, not a measured benefit.

## Technology

| Layer | Stack |
| --- | --- |
| Frontend | React, TypeScript, Vite |
| PDF rendering | PDF.js with local worker, CMaps, standard fonts and WASM |
| Local API | Python 3.13, FastAPI, Uvicorn |
| PDF parsing | pdfplumber |
| XLSX export | openpyxl |
| Persistence | Local PDFs and atomically saved JSON |
| Packaging and checks | PyInstaller, pytest, Playwright; uv and npm lockfiles |

Source references use original, unrotated PDF coordinates; the viewer maps them through PDF.js. See [architecture and API contracts](docs/architecture.md) for details.

## Development and verification

After installing dependencies, run from the repository root in Windows PowerShell:

```powershell
uv run --frozen --cache-dir .tools/uv-cache pytest -q
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend exec -- playwright install chromium
npm.cmd --prefix frontend run test:e2e
```

In Bash, replace `npm.cmd` with `npm`. Browser tests use separate data directories. The recorded Windows run passed **80 Python tests and 9 browser tests**, with **12 visible expected failures** for automatic extraction limitations. The main browser workflow blocks external network requests.

Build a Windows portable package from the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/build-portable.ps1
```

The script builds the frontend and executable and includes the demo, documentation and dependency notices in `dist/TableProof-0.1.0-windows-x64.zip`.

## Contributing and samples

Bug reports and contributions are welcome. Include the page, selected region, expected result and observed result; use a synthetic or redistributable PDF rather than a confidential paper. See [CONTRIBUTING](CONTRIBUTING.md) for source-preservation and test requirements.

The source corpus contains eight generated geometry cases and twelve table regions from two CC BY 4.0 PLOS papers. Paper metadata, permissions, hashes and region changes are in [the corpus manifest](samples/papers/manifest.json). [Independent references](samples/papers/reference.json) come from publisher XML and remain separate from extractor observations.

## License

Project code and generated sample content use the [MIT License](LICENSE). Paper samples retain their CC BY attribution; embedded fonts and dependencies retain their own licenses. See [third-party notices](THIRD_PARTY_NOTICES.md).
