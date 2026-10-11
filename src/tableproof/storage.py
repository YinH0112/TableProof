"""Atomic local projects. Original PDFs are written once and never edited."""

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def default_data_dir():
    override = os.environ.get("TABLEPROOF_DATA_DIR")
    if override:
        return Path(override)
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
    return base / "TableProofResearch"


class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root else default_data_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def directory(self, project_id):
        if not re.fullmatch(r"[a-f0-9]{32}", project_id):
            raise FileNotFoundError("PROJECT_NOT_FOUND")
        return self.root / project_id

    def load(self, project_id):
        with self.lock:
            return json.loads((self.directory(project_id) / "project.json").read_text(encoding="utf-8"))

    def save(self, project):
        directory = self.directory(project["id"])
        directory.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="project-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(project, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, directory / "project.json")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def list(self):
        result = []
        with self.lock:
            for path in self.root.glob("*/project.json"):
                try:
                    project = json.loads(path.read_text(encoding="utf-8"))
                    result.append({key: project[key] for key in ("id", "name", "version", "updatedAt")})
                except (OSError, ValueError, KeyError):
                    continue
        return sorted(result, key=lambda item: item["updatedAt"], reverse=True)
