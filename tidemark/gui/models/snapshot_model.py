"""QAbstractTableModel over snapshots for a device."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from tidemark.core.models import Snapshot


class SnapshotTableModel(QAbstractTableModel):
    HEADERS = ["ID", "Taken (UTC)", "Sha (short)", "Kind", "Size"]

    def __init__(self, snapshots: list[Snapshot]) -> None:
        super().__init__()
        self._snaps = snapshots

    def set_snapshots(self, snapshots: list[Snapshot]) -> None:
        self.beginResetModel()
        self._snaps = snapshots
        self.endResetModel()

    def snapshot_at(self, row: int) -> Snapshot:
        return self._snaps[row]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._snaps)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        s = self._snaps[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return [
                str(s.id), s.taken_at_utc.isoformat().replace("T", " ")[:19],
                s.sha256[:12], s.kind, str(s.size),
            ][col]
        return None
