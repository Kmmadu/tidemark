"""Devices page: table, add/edit dialog, per-row Backup now, Test connection."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from tidemark.core.engine import BackupRunner
from tidemark.core.models import Device
from tidemark.gui.dialogs.device_edit import DeviceEditDialog
from tidemark.gui.dialogs.import_yaml import ImportYamlDialog
from tidemark.gui.models.device_model import DeviceTableModel
from tidemark.gui.workers.backup_worker import BackupWorker
from tidemark.store.db import Database
from tidemark.store.repositories import DeviceRepo, RunRepo


class DevicesPage(QWidget):
    started_backup = Signal()

    def __init__(self, db: Database, runner: BackupRunner) -> None:
        super().__init__()
        self._db = db
        self._runner = runner

        title = QLabel("Devices")
        title.setObjectName("title")

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by name or host…")
        self._search.textChanged.connect(self._on_filter)

        self._add_btn = QPushButton("+ Add device")
        self._add_btn.setObjectName("primary")
        self._add_btn.clicked.connect(self._on_add)
        self._edit_btn = QPushButton("Edit")
        self._edit_btn.clicked.connect(self._on_edit)
        self._remove_btn = QPushButton("Remove")
        self._remove_btn.clicked.connect(self._on_remove)
        self._backup_btn = QPushButton("Backup now")
        self._backup_btn.clicked.connect(self._on_backup)
        self._test_btn = QPushButton("Test connection")
        self._test_btn.clicked.connect(self._on_test)
        self._import_btn = QPushButton("Import YAML…")
        self._import_btn.clicked.connect(self._on_import)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._add_btn)
        toolbar.addWidget(self._edit_btn)
        toolbar.addWidget(self._remove_btn)
        toolbar.addWidget(self._backup_btn)
        toolbar.addWidget(self._test_btn)
        toolbar.addWidget(self._import_btn)
        toolbar.addStretch(1)
        toolbar.addWidget(self._search, 2)

        self._table = QTableView()
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._table.doubleClicked.connect(lambda _i: self._on_edit())
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(True)

        self._last_runs: dict[int, str] = {}
        self._model = DeviceTableModel(DeviceRepo(self._db), self._last_runs)
        self._table.setModel(self._model)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addWidget(title)
        layout.addLayout(toolbar)
        layout.addWidget(self._table, 1)

        self.refresh()

    def refresh(self) -> None:
        run_repo = RunRepo(self._db)
        last: dict[int, str] = {}
        for d in DeviceRepo(self._db).list():
            r = run_repo.latest_for_device(d.id or 0)
            if r is not None:
                last[d.id or 0] = r.started_at_utc.isoformat().replace("T", " ")[:16]
        self._last_runs = last
        self._model = DeviceTableModel(DeviceRepo(self._db), last)
        self._table.setModel(self._model)
        self._on_filter(self._search.text())

    def _selected_device(self) -> Device | None:
        sel = self._table.selectionModel().selectedRows() if self._table.selectionModel() else []
        if not sel:
            return None
        row = sel[0].row()
        try:
            return self._model.device_at(row)
        except IndexError:
            return None

    def _on_filter(self, text: str) -> None:
        text = text.strip().lower()
        for row in range(self._model.rowCount()):
            d = self._model.device_at(row)
            hidden = text and (text not in d.name.lower() and text not in d.host.lower())
            self._table.setRowHidden(row, bool(hidden))

    def _on_add(self) -> None:
        dlg = DeviceEditDialog(self._db, None, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _on_edit(self) -> None:
        device = self._selected_device()
        if device is None:
            return
        dlg = DeviceEditDialog(self._db, device, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _on_remove(self) -> None:
        device = self._selected_device()
        if device is None:
            return
        if QMessageBox.question(
            self, "Remove device",
            f"Remove {device.name}? Snapshots on disk are kept.",
        ) != QMessageBox.StandardButton.Yes:
            return
        DeviceRepo(self._db).delete(device.id or 0)
        self.refresh()

    def _on_backup(self) -> None:
        device = self._selected_device()
        if device is None:
            return
        worker = BackupWorker(self._runner, device)
        worker.finished_one.connect(lambda _r: self.refresh())
        worker.failed.connect(lambda msg: QMessageBox.warning(self, "Backup failed", msg))
        worker.run_one()
        self.started_backup.emit()

    def _on_test(self) -> None:
        device = self._selected_device()
        if device is None:
            return
        worker = BackupWorker(self._runner, device)
        worker.finished_one.connect(
            lambda r: QMessageBox.information(
                self, "Test connection",
                f"Connected to {device.name}. "
                f"Config length: {len(r.normalised_text or '')} characters."))
        worker.failed.connect(lambda msg: QMessageBox.warning(self, "Test failed", msg))
        worker.run_one()

    def _on_import(self) -> None:
        dlg = ImportYamlDialog(self._db, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
