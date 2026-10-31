"""A small card: big value, label below, muted sub-label."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class StatCard(QFrame):
    def __init__(self, label: str, sub: str = "") -> None:
        super().__init__()
        self.setObjectName("card")
        self.setMinimumWidth(200)
        self.setMaximumHeight(110)

        self._value = QLabel("—")
        self._value.setObjectName("title")
        self._value.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self._label = QLabel(label)
        self._label.setObjectName("muted")

        self._sub = QLabel(sub)
        self._sub.setObjectName("muted")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addWidget(self._value)
        layout.addWidget(self._label)
        layout.addWidget(self._sub)

    def set_value(self, value: str) -> None:
        self._value.setText(value)

    def set_sub(self, sub: str) -> None:
        self._sub.setText(sub)
