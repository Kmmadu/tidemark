"""Read-only config viewer with search. Used on the History page."""

from __future__ import annotations

from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ConfigViewer(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.TypeWriter)
        self._text.setFont(mono)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search…")
        self._search.returnPressed.connect(self._on_find)
        self._next_btn = QPushButton("Find next")
        self._next_btn.clicked.connect(self._on_find)

        bar = QHBoxLayout()
        bar.addWidget(self._search, 1)
        bar.addWidget(self._next_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self._text, 1)

    def set_text(self, text: str) -> None:
        self._text.setPlainText(text)

    def text(self) -> str:
        return self._text.toPlainText()

    def _on_find(self) -> None:
        needle = self._search.text()
        if not needle:
            return
        if not self._text.find(needle):
            cursor = self._text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self._text.setTextCursor(cursor)
            self._text.find(needle)
