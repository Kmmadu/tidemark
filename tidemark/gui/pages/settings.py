"""Settings page."""

from __future__ import annotations

import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tidemark.gui.dialogs.credentials import CredentialsDialog
from tidemark.store.db import Database
from tidemark.store.paths import Paths
from tidemark.store.repositories import SettingsRepo

TIMEZONES = ["System", "UTC"]


class SettingsPage(QWidget):
    def __init__(self, db: Database, paths: Paths) -> None:
        super().__init__()
        self._db = db
        self._paths = paths
        self._settings = SettingsRepo(db)

        title = QLabel("Settings")
        title.setObjectName("title")

        # Credentials group
        creds_group = QGroupBox("Credentials")
        creds_form = QFormLayout(creds_group)
        self._backend_label = QLabel()
        self._manage_btn = QPushButton("Manage credentials…")
        self._manage_btn.clicked.connect(self._on_manage_credentials)
        row = QHBoxLayout()
        row.addWidget(self._backend_label, 1)
        row.addWidget(self._manage_btn)
        creds_form.addRow("Backend:", row)

        # Storage group
        storage_group = QGroupBox("Storage")
        storage_form = QFormLayout(storage_group)
        self._raw_check = QCheckBox(
            "store_raw — save normalised text with secrets intact "
            "(restore available; changes that only touch a secret are not detected)")
        self._store_raw_value = (
            (self._settings.get("store_raw") or "true").lower() == "true"
        )
        self._raw_check.setChecked(self._store_raw_value)
        self._raw_check.stateChanged.connect(self._on_raw_changed)
        storage_form.addRow(self._raw_check)

        data_label = QLabel(str(paths.data_dir))
        data_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        open_btn = QPushButton("Open in file manager")
        open_btn.clicked.connect(self._open_data_dir)
        data_row = QHBoxLayout()
        data_row.addWidget(data_label, 1)
        data_row.addWidget(open_btn)
        storage_form.addRow("Data directory:", data_row)

        # Display group
        display_group = QGroupBox("Display")
        display_form = QFormLayout(display_group)
        self._tz_combo = QComboBox()
        self._tz_combo.addItems(TIMEZONES)
        saved_tz = self._settings.get("display.timezone") or "System"
        if saved_tz in TIMEZONES:
            self._tz_combo.setCurrentText(saved_tz)
        self._tz_combo.currentTextChanged.connect(self._on_tz_changed)
        display_form.addRow("Timezone:", self._tz_combo)

        # About group
        about_group = QGroupBox("About")
        about_form = QFormLayout(about_group)
        from tidemark import __version__
        about_form.addRow("Version:", QLabel(__version__))
        about_form.addRow("Repository:", QLabel("github.com/Kmmadu/AutoConfigBackup"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addWidget(title)
        layout.addWidget(creds_group)
        layout.addWidget(storage_group)
        layout.addWidget(display_group)
        layout.addWidget(about_group)
        layout.addStretch(1)

        self.refresh()

    def refresh(self) -> None:
        from tidemark.store.credentials import CredentialStoreFactory
        factory = CredentialStoreFactory(self._paths.config_dir, self._db)
        self._backend_label.setText(factory.get_configured_backend())

    def _on_manage_credentials(self) -> None:
        dlg = CredentialsDialog(self._db, self._paths, self)
        dlg.exec()
        self.refresh()

    def _on_raw_changed(self, _state: int) -> None:
        new_value = self._raw_check.isChecked()
        if new_value is False and self._store_raw_value is True:
            # Turning redaction ON: confirm before applying.
            confirm = QMessageBox(self)
            confirm.setWindowTitle("Enable redaction?")
            confirm.setIcon(QMessageBox.Icon.Warning)
            confirm.setText(
                "Turning this off stores future snapshots with secrets "
                "replaced by <<TIDEMARK-REDACTED>>."
            )
            confirm.setInformativeText(
                "Those snapshots cannot be restored. Existing snapshots "
                "are not affected.\n\nEnable redaction?"
            )
            confirm.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            confirm.setDefaultButton(QMessageBox.StandardButton.No)
            if confirm.exec() != QMessageBox.StandardButton.Yes:
                # Decline: snap the checkbox back without re-firing.
                self._raw_check.blockSignals(True)
                self._raw_check.setChecked(self._store_raw_value)
                self._raw_check.blockSignals(False)
                return

        self._store_raw_value = new_value
        self._settings.set("store_raw", "true" if new_value else "false")

    def _on_tz_changed(self, text: str) -> None:
        self._settings.set("display.timezone", text)

    def _open_data_dir(self) -> None:
        try:
            subprocess.Popen(["xdg-open", str(self._paths.data_dir)])
        except FileNotFoundError:
            pass
