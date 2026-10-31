"""Toggling store_raw to false prompts; decline reverts."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox

from tidemark.gui.pages.settings import SettingsPage
from tidemark.store.db import Database, migrate
from tidemark.store.paths import Paths
from tidemark.store.repositories import SettingsRepo


def _page(tmp_path: Path) -> tuple[SettingsPage, Database, SettingsRepo]:
    db = Database(tmp_path / "t.db")
    migrate(db)
    paths = Paths(config_dir=tmp_path, data_dir=tmp_path, state_dir=tmp_path)
    paths.ensure_dirs()
    page = SettingsPage(db, paths)
    return page, db, SettingsRepo(db)


def test_toggle_off_prompts_and_accepts(tmp_path: Path, qapp, monkeypatch) -> None:
    page, db, repo = _page(tmp_path)
    monkeypatch.setattr(
        QMessageBox, "exec",
        lambda self: QMessageBox.StandardButton.Yes,
    )
    page._raw_check.setChecked(False)
    assert repo.get("store_raw") == "false"


def test_toggle_off_prompts_and_declines(tmp_path: Path, qapp, monkeypatch) -> None:
    page, db, repo = _page(tmp_path)
    monkeypatch.setattr(
        QMessageBox, "exec",
        lambda self: QMessageBox.StandardButton.No,
    )
    page._raw_check.setChecked(False)
    assert page._raw_check.isChecked() is True
    # store_raw unchanged
    assert (repo.get("store_raw") or "true") == "true"
