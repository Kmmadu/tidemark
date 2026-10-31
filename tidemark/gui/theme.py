"""
tidemark.gui.theme
──────────────────
Loads the base QSS and hands out the two colours used only for diff add/remove
lines. Everything else follows the system Qt palette, so the app respects the
user's light/dark preference without a second QSS.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

_RESOURCES = Path(__file__).resolve().parent / "resources"


def _is_dark(app: QApplication) -> bool:
    palette = app.palette()
    window = palette.color(QPalette.ColorRole.Window)
    return window.lightness() < 128


def diff_colors(app: QApplication) -> tuple[QColor, QColor]:
    """Return ``(add_colour, remove_colour)`` tuned for the current theme."""
    if _is_dark(app):
        return QColor("#2e5d34"), QColor("#6b2f2f")
    return QColor("#d7f5d7"), QColor("#f7d7d7")


def apply_theme(app: QApplication) -> None:
    """Apply the base QSS. Called once in ``app.main``."""
    qss_path = _RESOURCES / "style.qss"
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))
