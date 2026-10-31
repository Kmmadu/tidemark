"""QMainWindow with navigation and tray icon."""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QSystemTrayIcon,
    QWidget,
)

from tidemark.core.engine import BackupRunner
from tidemark.gui.pages.dashboard import DashboardPage
from tidemark.gui.pages.devices import DevicesPage
from tidemark.gui.pages.history import HistoryPage
from tidemark.gui.pages.settings import SettingsPage
from tidemark.store.db import Database
from tidemark.store.paths import Paths


class MainWindow(QMainWindow):
    def __init__(self, db: Database, paths: Paths, runner: BackupRunner,
                 demo: bool = False) -> None:
        super().__init__()
        title = "Tidemark"
        if demo:
            title += " [demo]"
        self.setWindowTitle(title)
        self.resize(1100, 700)

        self._db = db
        self._paths = paths
        self._runner = runner

        # Sidebar
        self._sidebar = QListWidget()
        self._sidebar.setObjectName("sidebar")
        self._sidebar.setFixedWidth(180)
        for label in ("Dashboard", "Devices", "History", "Settings"):
            QListWidgetItem(label, self._sidebar)
        self._sidebar.currentRowChanged.connect(self._on_navigate)

        # Pages
        self._stack = QStackedWidget()
        self._dashboard = DashboardPage(db, runner)
        self._devices = DevicesPage(db, runner)
        self._history = HistoryPage(db, paths, runner)
        self._settings = SettingsPage(db, paths)
        for page in (self._dashboard, self._devices, self._history, self._settings):
            self._stack.addWidget(page)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._sidebar)
        layout.addWidget(self._stack, 1)
        self.setCentralWidget(central)

        self._menu()

        # Tray
        self._tray = QSystemTrayIcon(self)
        self._tray.setToolTip(title)
        self._tray.setVisible(QSystemTrayIcon.isSystemTrayAvailable())

        self._sidebar.setCurrentRow(0)

    def _menu(self) -> None:
        mb = self.menuBar()
        file_menu = mb.addMenu("&File")
        backup_all = QAction("Backup all now", self)
        backup_all.triggered.connect(self._on_backup_all)
        file_menu.addAction(backup_all)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = mb.addMenu("&View")
        for i, label in enumerate(("Dashboard", "Devices", "History", "Settings")):
            act = QAction(label, self)
            act.triggered.connect(lambda _checked=False, idx=i: self._sidebar.setCurrentRow(idx))
            view_menu.addAction(act)

    def _on_navigate(self, row: int) -> None:
        if row < 0:
            return
        self._stack.setCurrentIndex(row)
        page = self._stack.currentWidget()
        if hasattr(page, "refresh"):
            page.refresh()

    def _on_backup_all(self) -> None:
        self._sidebar.setCurrentRow(0)
        self._dashboard._on_backup_all()
