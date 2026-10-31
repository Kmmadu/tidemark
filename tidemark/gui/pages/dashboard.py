"""Dashboard page: stat cards, 'Backup all now', recent runs, daemon banner."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from tidemark.core.engine import BackupRunner
from tidemark.gui.models.run_model import RunTableModel
from tidemark.gui.widgets.stat_card import StatCard
from tidemark.gui.workers.backup_worker import BackupWorker
from tidemark.store.db import Database
from tidemark.store.repositories import DeviceRepo, RunRepo, SettingsRepo


class DashboardPage(QWidget):
    request_navigate = Signal(str)   # page name
    started_backup = Signal()

    def __init__(self, db: Database, runner: BackupRunner) -> None:
        super().__init__()
        self._db = db
        self._runner = runner
        self._worker: BackupWorker | None = None

        # daemon banner (placeholder until M4 writes the setting)
        self._banner = QLabel("")
        self._banner.setStyleSheet(
            "background-color: #f4d03f; color: black; padding: 6px; border-radius: 6px;")
        self._banner.setVisible(False)

        title = QLabel("Dashboard")
        title.setObjectName("title")
        subtitle = QLabel("Backup status and quick actions")
        subtitle.setObjectName("muted")

        header = QVBoxLayout()
        header.addWidget(self._banner)
        header.addWidget(title)
        header.addWidget(subtitle)

        # Stat cards
        self._devices_card = StatCard("Managed devices", "configured in inventory")
        self._backups_card = StatCard("Backup archives", "snapshots in git")
        self._last_card = StatCard("Last backup", "latest successful run")
        cards = QHBoxLayout()
        for c in (self._devices_card, self._backups_card, self._last_card):
            cards.addWidget(c)
        cards.addStretch(1)

        self._backup_all = QPushButton("Backup all now")
        self._backup_all.setObjectName("primary")
        self._backup_all.clicked.connect(self._on_backup_all)

        actions = QHBoxLayout()
        actions.addWidget(self._backup_all)
        actions.addStretch(1)

        # Recent runs
        recent_label = QLabel("Recent runs")
        recent_label.setObjectName("title")
        self._recent = QTableView()
        self._recent.horizontalHeader().setStretchLastSection(True)
        self._recent.setAlternatingRowColors(True)
        self._recent_model = RunTableModel([])
        self._recent.setModel(self._recent_model)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addLayout(header)
        layout.addSpacing(12)
        layout.addLayout(cards)
        layout.addLayout(actions)
        layout.addSpacing(20)
        layout.addWidget(recent_label)
        layout.addWidget(self._recent, 1)

        self.refresh()

    def refresh(self) -> None:
        device_repo = DeviceRepo(self._db)
        devices = device_repo.list()
        self._devices_card.set_value(str(len(devices)))

        self._backups_card.set_value(str(self._count_snapshots()))
        latest = self._latest_run_overall()
        if latest is None:
            self._last_card.set_value("Never")
        else:
            when, status = latest
            self._last_card.set_value(when.replace("T", " ")[:16])

        runs_with_names: list = []
        run_repo = RunRepo(self._db)
        for dev in devices:
            for r in run_repo.list_for_device(dev.id or 0, limit=5):
                runs_with_names.append((dev.name, r))
        runs_with_names.sort(key=lambda pair: pair[1].id or 0, reverse=True)
        self._recent_model = RunTableModel(runs_with_names[:20])
        self._recent.setModel(self._recent_model)

        daemon_status = SettingsRepo(self._db).get("daemon.status") or "not running"
        if daemon_status == "not running":
            self._banner.setText(
                "The scheduler daemon is not running. Run "
                "`tidemarkd` in a terminal, or start it via systemd (M4)."
            )
            self._banner.setVisible(True)
        else:
            self._banner.setVisible(False)

    def _count_snapshots(self) -> int:
        row = self._db.conn.execute(
            "SELECT COUNT(*) AS c FROM snapshots WHERE kind = 'normal'").fetchone()
        return int(row["c"])

    def _latest_run_overall(self) -> tuple[str, str] | None:
        row = self._db.conn.execute(
            "SELECT started_at_utc, status FROM runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return (row["started_at_utc"], row["status"])

    def _on_backup_all(self) -> None:
        self._backup_all.setEnabled(False)
        self._worker = BackupWorker(self._runner)
        self._worker.done.connect(self._on_worker_done)
        self._worker.finished_all.connect(lambda _r: self.refresh())
        self._worker.failed.connect(lambda msg: self._banner.setText(msg))
        self._worker.run_all()

    def _on_worker_done(self) -> None:
        self._backup_all.setEnabled(True)
        self.refresh()
