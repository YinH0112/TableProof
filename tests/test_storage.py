import json
from pathlib import Path

import pytest

from tableproof.storage import Store


def test_atomic_save_failure_keeps_prior_project(tmp_path, monkeypatch):
    store = Store(tmp_path)
    project = {"id": "a" * 32, "version": 1, "name": "原文", "updatedAt": "2026-10-11"}
    store.save(project)

    def fail(*_):
        raise OSError("disk full")

    monkeypatch.setattr("tableproof.storage.os.replace", fail)
    with pytest.raises(OSError):
        store.save({**project, "version": 2})
    assert store.load(project["id"])["version"] == 1
    assert not list(store.directory(project["id"]).glob("*.tmp"))


def test_ids_cannot_escape_store(tmp_path):
    with pytest.raises(FileNotFoundError):
        Store(tmp_path).directory("../../other")
