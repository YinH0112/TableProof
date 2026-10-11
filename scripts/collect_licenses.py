"""Copy bundled dependency license files into a portable release."""
import json
import shutil
import sys
from pathlib import Path
from importlib.metadata import distributions

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "dist" / "TableProof" / "licenses"


def collect():
    TARGET.mkdir(parents=True, exist_ok=True)
    records = []
    for dist in distributions():
        name = dist.metadata.get("Name", "unknown")
        # The build/test tools are not runtime dependencies.
        if name.lower() in {"pytest", "reportlab", "httpx", "pypdf", "pyinstaller", "hatchling"}:
            continue
        paths = []
        for entry in dist.files or []:
            if entry.name.lower().startswith(("license", "licence", "copying", "notice")):
                path = Path(dist.locate_file(entry))
                if path.is_file():
                    destination = TARGET / "python" / name / str(entry).replace("../", "_")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, destination)
                    paths.append(str(destination.relative_to(TARGET)))
        records.append({"name": name, "version": dist.version, "licenseFiles": paths})
    node_modules = ROOT / "frontend" / "node_modules"
    for path in node_modules.rglob("*"):
        if path.is_file() and path.name.lower().startswith(("license", "licence", "copying", "notice")):
            destination = TARGET / "javascript" / path.relative_to(node_modules)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
    for filename in ("LICENSE.txt", "LICENSE_PYTHON.txt", "LICENSE_PYTHON"):
        path = Path(sys.base_prefix) / filename
        if path.exists():
            shutil.copyfile(path, TARGET / f"Python-{filename}")
    sample_font_license = ROOT / "samples" / "Bitstream-Vera-LICENSE.txt"
    if sample_font_license.exists():
        shutil.copyfile(sample_font_license, TARGET / sample_font_license.name)
    (TARGET / "python-packages.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print("Dependency licenses collected.")


if __name__ == "__main__":
    collect()
