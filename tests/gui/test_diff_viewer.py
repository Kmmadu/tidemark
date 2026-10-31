"""DiffViewer renders add/remove lines and can collapse."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from tidemark.gui.widgets.diff_viewer import DiffViewer

OLD = "hostname r1\ninterface Gi0/1\n ip address 10.0.0.1 255.255.255.0\n"
NEW = "hostname r1\ninterface Gi0/1\n ip address 10.0.0.2 255.255.255.0\n"


def test_unified_shows_added_line(qapp) -> None:
    v = DiffViewer()
    v.set_diff(OLD, NEW)
    text = v._text.toPlainText()  # noqa: SLF001 - test introspection
    assert "+" in text
    assert "10.0.0.2" in text


def test_side_by_side_contains_both(qapp) -> None:
    v = DiffViewer()
    v._mode.setCurrentText("Side-by-side")
    v.set_diff(OLD, NEW)
    text = v._text.toPlainText()  # noqa: SLF001
    assert "10.0.0.1" in text
    assert "10.0.0.2" in text


def test_collapse_hides_unchanged(qapp) -> None:
    v = DiffViewer()
    v._mode.setCurrentText("Side-by-side")
    v.set_diff(OLD, NEW)
    v._collapse_btn.setChecked(True)
    text = v._text.toPlainText()  # noqa: SLF001
    # 'hostname r1' is unchanged and should not appear when collapsed
    assert "hostname r1" not in text
