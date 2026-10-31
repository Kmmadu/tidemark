"""Add or edit a device."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from tidemark.core.models import Device
from tidemark.core.profiles import ProfileRegistry
from tidemark.store.db import Database
from tidemark.store.paths import default_paths
from tidemark.store.repositories import DeviceRepo


class DeviceEditDialog(QDialog):
    def __init__(self, db: Database, device: Device | None, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._device = device

        self.setWindowTitle("Edit device" if device else "Add device")
        self.resize(500, 320)

        self._name = QLineEdit(device.name if device else "")
        self._host = QLineEdit(device.host if device else "")
        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(device.port if device else 22)
        self._profile = QComboBox()
        profiles = ProfileRegistry(user_profiles_dir=default_paths().user_profiles_dir)
        for pid in profiles.ids():
            self._profile.addItem(pid)
        if device:
            idx = self._profile.findText(device.profile_id)
            if idx >= 0:
                self._profile.setCurrentIndex(idx)
        self._group = QLineEdit(device.group if device and device.group else "")
        self._custom = QLineEdit(
            device.custom_command if device and device.custom_command else "")
        self._enabled = QCheckBox("Enabled")
        self._enabled.setChecked(device.enabled if device else True)

        form = QFormLayout()
        form.addRow("Name:", self._name)
        form.addRow("Host:", self._host)
        form.addRow("Port:", self._port)
        form.addRow("Profile:", self._profile)
        form.addRow("Group:", self._group)
        form.addRow("Custom command (profile 'custom'):", self._custom)
        form.addRow(self._enabled)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _on_ok(self) -> None:
        name = self._name.text().strip()
        host = self._host.text().strip()
        if not name or not host:
            QMessageBox.warning(self, "Invalid", "Name and host are required.")
            return
        repo = DeviceRepo(self._db)
        try:
            if self._device is None:
                repo.add(Device(
                    name=name, host=host, port=self._port.value(),
                    profile_id=self._profile.currentText(),
                    credential_ref="default",
                    group=self._group.text().strip() or None,
                    enabled=self._enabled.isChecked(),
                    custom_command=self._custom.text().strip() or None,
                ))
            else:
                self._device.name = name
                self._device.host = host
                self._device.port = self._port.value()
                self._device.profile_id = self._profile.currentText()
                self._device.group = self._group.text().strip() or None
                self._device.enabled = self._enabled.isChecked()
                self._device.custom_command = self._custom.text().strip() or None
                repo.update(self._device)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", str(exc))
            return
        self.accept()
