"""History page: snapshot list, config viewer, diff viewer, restore trigger."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from tidemark.core.engine import BackupRunner
from tidemark.core.redact import redact_lines
from tidemark.gui.models.snapshot_model import SnapshotTableModel
from tidemark.gui.widgets.config_viewer import ConfigViewer
from tidemark.gui.widgets.diff_viewer import DiffViewer
from tidemark.gui.wizard.restore_wizard import RestoreWizard
from tidemark.store.db import Database
from tidemark.store.git_repo import ConfigRepo
from tidemark.store.paths import Paths
from tidemark.store.repositories import DeviceRepo, SnapshotRepo


class HistoryPage(QWidget):
    def __init__(self, db: Database, paths: Paths, runner: BackupRunner) -> None:
        super().__init__()
        self._db = db
        self._paths = paths
        self._runner = runner
        self._config_repo = ConfigRepo(paths.configs_git_dir)

        title = QLabel("History")
        title.setObjectName("title")

        self._device_combo = QComboBox()
        self._device_combo.currentIndexChanged.connect(self._on_device_changed)

        self._snapshot_model = SnapshotTableModel([])
        self._snapshot_table = QTableView()
        self._snapshot_table.setModel(self._snapshot_model)
        self._snapshot_table.setSelectionBehavior(
            QTableView.SelectionBehavior.SelectRows)
        self._snapshot_table.horizontalHeader().setStretchLastSection(True)
        self._snapshot_table.selectionModel().selectionChanged.connect(
            lambda *_: self._on_snapshot_selected())

        self._config_viewer = ConfigViewer()
        self._diff_viewer = DiffViewer()
        self._diff_viewer.refresh_colours()

        self._tabs = QTabWidget()
        self._tabs.addTab(self._config_viewer, "Config")
        self._tabs.addTab(self._diff_viewer, "Diff")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Snapshots"))
        left_layout.addWidget(self._snapshot_table, 1)
        splitter.addWidget(left)
        splitter.addWidget(self._tabs)
        splitter.setSizes([360, 720])

        self._restore_btn = QPushButton("Restore this snapshot…")
        self._restore_btn.clicked.connect(self._on_restore)
        self._diff_prev_btn = QPushButton("Diff with previous")
        self._diff_prev_btn.clicked.connect(self._on_diff_prev)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Device:"))
        bar.addWidget(self._device_combo, 1)
        bar.addWidget(self._diff_prev_btn)
        bar.addWidget(self._restore_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addWidget(title)
        layout.addLayout(bar)
        layout.addWidget(splitter, 1)

        self.refresh()

    def refresh(self) -> None:
        current = self._device_combo.currentData()
        self._device_combo.blockSignals(True)
        self._device_combo.clear()
        for d in DeviceRepo(self._db).list():
            self._device_combo.addItem(f"{d.name} ({d.host})", d.id)
        self._device_combo.blockSignals(False)
        if current is not None:
            for i in range(self._device_combo.count()):
                if self._device_combo.itemData(i) == current:
                    self._device_combo.setCurrentIndex(i)
                    break
        self._on_device_changed()

    def _on_device_changed(self) -> None:
        device_id = self._device_combo.currentData()
        if device_id is None:
            self._snapshot_model.set_snapshots([])
            self._config_viewer.set_text("")
            self._diff_viewer.set_diff("", "")
            return
        snaps = SnapshotRepo(self._db).list_for_device(int(device_id), limit=200)
        self._snapshot_model.set_snapshots(snaps)
        if snaps:
            self._snapshot_table.selectRow(0)
        else:
            self._config_viewer.set_text("")
            self._diff_viewer.set_diff("", "")

    def _selected_snapshot(self):
        sel = self._snapshot_table.selectionModel().selectedRows() \
            if self._snapshot_table.selectionModel() else []
        if not sel:
            return None
        row = sel[0].row()
        try:
            return self._snapshot_model.snapshot_at(row)
        except IndexError:
            return None

    def _read_snapshot(self, snap) -> str:  # noqa: ANN001
        commit_sha = getattr(snap, "commit_sha", None)
        if commit_sha:
            device = DeviceRepo(self._db).get_by_id(snap.device_id)
            if device is None:
                return ""
            rel = f"{device.name}/running.cfg"
            if snap.kind == "pre_restore":
                try:
                    rel = str(
                        Path(snap.path).resolve().relative_to(self._config_repo.root)
                    )
                except ValueError:
                    return ""
            try:
                return self._config_repo.read_at(commit_sha, rel)
            except Exception:
                pass
        try:
            return Path(snap.path).read_text(encoding="utf-8")
        except OSError:
            return ""

    def _previous_snapshot_of(self, snap):  # noqa: ANN001, ANN201
        """Return the snapshot immediately older than ``snap`` for the same device."""
        snaps = SnapshotRepo(self._db).list_for_device(snap.device_id, limit=200)
        idx = next((i for i, s in enumerate(snaps) if s.id == snap.id), None)
        if idx is None or idx + 1 >= len(snaps):
            return None
        return snaps[idx + 1]

    def _on_snapshot_selected(self) -> None:
        snap = self._selected_snapshot()
        if snap is None:
            self._config_viewer.set_text("")
            self._diff_viewer.set_diff("", "")
            return

        current_text = self._read_snapshot(snap)
        self._config_viewer.set_text(
            "\n".join(redact_lines(current_text.splitlines()))
        )

        previous = self._previous_snapshot_of(snap)
        if previous is None:
            self._diff_viewer.set_diff("", "")
            return

        old_text = self._read_snapshot(previous)
        self._diff_viewer.set_diff(
            "\n".join(redact_lines(old_text.splitlines())),
            "\n".join(redact_lines(current_text.splitlines())),
        )

    def _on_diff_prev(self) -> None:
        # Keep the button as a shortcut; selecting a snapshot already
        # populates the diff tab. The button now switches to the Diff tab.
        self._on_snapshot_selected()
        self._tabs.setCurrentWidget(self._diff_viewer)

    def _on_restore(self) -> None:
        snap = self._selected_snapshot()
        if snap is None:
            return
        device = DeviceRepo(self._db).get_by_id(snap.device_id)
        if device is None:
            return
        wizard = RestoreWizard(self._db, self._paths, device, self)
        wizard.exec()
        self.refresh()
