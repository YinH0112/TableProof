# Third-party notices

Project code and generated sample content: MIT. Embedded Bitstream Vera font subsets retain their upstream font license; standard CJK font references use the viewer's fonts. Lockfiles identify exact dependency versions. Generated PDF layouts/data are invented, not copied from the paper samples.

Primary dependencies: pdfplumber, pdfminer.six, openpyxl, FastAPI, React and Vite (MIT); Uvicorn (BSD-3-Clause); PDF.js (Apache-2.0); pypdfium2 (Apache-2.0/BSD-3-Clause wrapper, plus PDFium upstream licenses). Preserve bundled upstream notices. PyInstaller's bootloader exception allows application distribution under its own license.

## Paper samples

PDFs are unchanged. Region and extracted-text annotations are generated separately; hashes are in samples/papers/manifest.json.

- Ryan P. Womack (2015), *Research Data in Core Journals in Biology, Chemistry, Mathematics, and Physics*. PLOS ONE 10(12): e0143460. [Source](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0143460), [DOI](https://doi.org/10.1371/journal.pone.0143460).
- David Giofrè, Geoff Cumming, Luca Fresc, Ingrid Boedker and Patrizio Tressoldi (2017), *The influence of journal submission guidelines on authors' reporting of statistics and use of open research practices*. PLOS ONE 12(4): e0175583. [Source](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0175583), [DOI](https://doi.org/10.1371/journal.pone.0175583).

Both specify [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). No endorsement is implied. Seeded extractor observations are separate from the independent publisher XML reference in `samples/papers/reference.json`; see `docs/verification.md` for the checks and known limitations.
