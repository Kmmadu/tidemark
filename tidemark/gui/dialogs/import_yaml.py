"""Import legacy devices.yaml."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from tidemark.store.db import Database
from tidemark.store.importer import ImportError_, import_legacy_yaml
from tidemark.store.repositories import DeviceRepo


class ImportYamlDialog(QDialog):
    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self.setWindowTitle("Import legacy devices.yaml")
        self.resize(560, 180)

        self._path = QLineEdit()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._on_browse)

        path_row = QVBoxLayout()
        path_row.addWidget(QLabel("Path to devices.yaml"))
        row = QHBoxLayout()
        row.addWidget(self._path, 1)
        row.addWidget(browse)
        path_row.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(path_row)
        layout.addWidget(buttons)

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "devices.yaml", "", "YAML (*.yaml *.yml)")
        if path:
            self._path.setText(path)

    def _on_ok(self) -> None:
        path = Path(self._path.text().strip())
        if not path.exists():
            QMessageBox.warning(self, "Not found", f"{path} does not exist")
            return
        try:
            imported = import_legacy_yaml(path, DeviceRepo(self._db))
        except ImportError_ as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        QMessageBox.information(
            self, "Import",
            f"Imported {len(imported)} device(s).")
        self.accept()
