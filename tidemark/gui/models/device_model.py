"""
QAbstractTableModel over ``DeviceRepo``. Editing the Enabled checkbox updates
the DB. Adding/removing goes through the page (not the model), so the model
is a read/edit view only.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from tidemark.core.models import Device
from tidemark.store.repositories import DeviceRepo


class DeviceTableModel(QAbstractTableModel):
    HEADERS = ["Name", "Host", "Port", "Profile", "Enabled", "Last backup"]

    def __init__(self, repo: DeviceRepo, last_backup: dict[int, str]) -> None:
        super().__init__()
        self._repo = repo
        self._last = last_backup
        self._devices: list[Device] = repo.list()

    def refresh(self) -> None:
        self.beginResetModel()
        self._devices = self._repo.list()
        self.endResetModel()

    def device_at(self, row: int) -> Device:
        return self._devices[row]

    # Qt overrides ────────────────────────────────────────────────────────

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._devices)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def flags(self, index: QModelIndex):  # noqa: N802
        base = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        if index.column() == 4:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        device = self._devices[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return [
                device.name, device.host, str(device.port), device.profile_id,
                "", self._last.get(device.id or 0, "Never"),
            ][col]
        if role == Qt.ItemDataRole.CheckStateRole and col == 4:
            return Qt.CheckState.Checked if device.enabled else Qt.CheckState.Unchecked
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if role != Qt.ItemDataRole.CheckStateRole or index.column() != 4:
            return False
        device = self._devices[index.row()]
        device.enabled = (value == Qt.CheckState.Checked.value
                          or value == Qt.CheckState.Checked)
        self._repo.update(device)
        self.dataChanged.emit(index, index, [role])
        return True
