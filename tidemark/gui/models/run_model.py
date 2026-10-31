"""QAbstractTableModel over runs for the dashboard and history."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from tidemark.core.models import BackupRun


class RunTableModel(QAbstractTableModel):
    HEADERS = ["Device", "Started (UTC)", "Status", "Snapshot", "Error"]

    def __init__(self, runs: list[tuple[str, BackupRun]]) -> None:
        super().__init__()
        self._runs = runs

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._runs)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        name, run = self._runs[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return name
            if col == 1:
                return run.started_at_utc.isoformat().replace("T", " ")[:19]
            if col == 2:
                return run.status.value
            if col == 3:
                return run.snapshot_id
            if col == 4:
                return (run.error or "")[:80]
        return None
