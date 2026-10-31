"""
Side-by-side and unified diff.

Rendered as a QPlainTextEdit with formatted lines. Add/remove colours come
from ``theme.diff_colors`` so both light and dark palettes work. Unchanged
runs can be collapsed to show only add/remove context.
"""

from __future__ import annotations

from difflib import unified_diff

from PySide6.QtGui import QColor, QFont, QTextCharFormat
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tidemark.gui.theme import diff_colors


class DiffViewer(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._add_colour = QColor("#d7f5d7")
        self._remove_colour = QColor("#f7d7d7")
        self._old = ""
        self._new = ""
        self._collapse = False

        self._mode = QComboBox()
        self._mode.addItems(["Unified", "Side-by-side"])
        self._mode.currentTextChanged.connect(lambda _t: self._render())

        self._collapse_btn = QPushButton("Collapse unchanged")
        self._collapse_btn.setCheckable(True)
        self._collapse_btn.toggled.connect(self._on_collapse)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("View:"))
        bar.addWidget(self._mode)
        bar.addWidget(self._collapse_btn)
        bar.addStretch(1)

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.TypeWriter)
        self._text.setFont(mono)

        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self._text, 1)

    def refresh_colours(self) -> None:
        from PySide6.QtWidgets import QApplication
        self._add_colour, self._remove_colour = diff_colors(QApplication.instance())
        self._render()

    def set_diff(self, old: str, new: str) -> None:
        self._old = old
        self._new = new
        self._render()

    def _on_collapse(self, checked: bool) -> None:
        self._collapse = checked
        self._render()

    def _render(self) -> None:
        self._text.clear()
        if self._mode.currentText() == "Unified":
            self._render_unified()
        else:
            self._render_side_by_side()

    def _render_unified(self) -> None:
        cursor = self._text.textCursor()
        lines = list(unified_diff(
            self._old.splitlines(), self._new.splitlines(),
            fromfile="old", tofile="new", lineterm="",
        ))
        prev_was_change = True
        for line in lines:
            is_change = line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
            if self._collapse and not is_change and not prev_was_change:
                prev_was_change = False
                continue
            fmt = QTextCharFormat()
            if line.startswith("+") and not line.startswith("+++"):
                fmt.setBackground(self._add_colour)
            elif line.startswith("-") and not line.startswith("---"):
                fmt.setBackground(self._remove_colour)
            cursor.insertText(line + "\n", fmt)
            prev_was_change = is_change

    def _render_side_by_side(self) -> None:
        old_lines = self._old.splitlines()
        new_lines = self._new.splitlines()
        n = max(len(old_lines), len(new_lines))
        cursor = self._text.textCursor()
        header = QTextCharFormat()
        header.setFontWeight(QFont.Weight.Bold)
        cursor.insertText(f"{'OLD':<40}    NEW\n", header)
        cursor.insertText(f"{'-' * 40}    {'-' * 40}\n", header)
        for i in range(n):
            o = old_lines[i] if i < len(old_lines) else ""
            t = new_lines[i] if i < len(new_lines) else ""
            if o == t:
                if self._collapse:
                    continue
                cursor.insertText(f"{o:<40}    {t}\n")
            else:
                fmt = QTextCharFormat()
                fmt.setBackground(self._remove_colour if o else self._add_colour)
                cursor.insertText(f"{o:<40}    ", fmt)
                fmt2 = QTextCharFormat()
                fmt2.setBackground(self._add_colour if t else self._remove_colour)
                cursor.insertText(f"{t}\n", fmt2)
