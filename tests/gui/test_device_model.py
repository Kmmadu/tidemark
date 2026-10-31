"""DeviceTableModel reads from DeviceRepo and edits the Enabled column."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

from tidemark.core.models import Device
from tidemark.gui.models.device_model import DeviceTableModel
from tidemark.store.db import Database, migrate
from tidemark.store.repositories import DeviceRepo


@pytest.fixture
def seeded(tmp_path: Path) -> tuple[Database, DeviceRepo]:
    db = Database(tmp_path / "t.db")
    migrate(db)
    repo = DeviceRepo(db)
    repo.add(Device(name="core", host="10.0.0.1", port=22,
                    profile_id="cisco_ios", credential_ref="default"))
    repo.add(Device(name="edge", host="10.0.0.2", port=22,
                    profile_id="cisco_ios", credential_ref="default",
                    enabled=False))
    return db, repo


def test_row_and_column_counts(seeded, qapp) -> None:
    db, repo = seeded
    model = DeviceTableModel(repo, {})
    assert model.rowCount() == 2
    assert model.columnCount() == 6


def test_display_name(seeded, qapp) -> None:
    db, repo = seeded
    model = DeviceTableModel(repo, {})
    idx = model.index(0, 0)
    assert model.data(idx, Qt.ItemDataRole.DisplayRole) == "core"


def test_enabled_checkbox_reflects_state(seeded, qapp) -> None:
    db, repo = seeded
    model = DeviceTableModel(repo, {})
    assert model.data(model.index(0, 4), Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    assert model.data(model.index(1, 4), Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked


def test_editing_checkbox_updates_db(seeded, qapp) -> None:
    db, repo = seeded
    model = DeviceTableModel(repo, {})
    model.setData(model.index(0, 4), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert repo.get_by_name("core").enabled is False
