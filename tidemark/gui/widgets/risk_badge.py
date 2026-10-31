"""Colour-coded badge for a RiskFlag."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel

from tidemark.core.restore_risk_ios import RiskFlag, Severity


class RiskBadge(QLabel):
    def __init__(self, flag: RiskFlag) -> None:
        super().__init__(flag.code)
        self.setToolTip(flag.message)
        colour = "#c0392b" if flag.severity is Severity.HIGH else "#d68910"
        self.setStyleSheet(
            f"padding: 2px 6px; border-radius: 4px; color: white; "
            f"background-color: {QColor(colour).name()}; font-size: 11px;"
        )
