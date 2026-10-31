"""Demo app boots and navigates all four pages."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


def test_demo_boots(qapp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from tidemark.gui import demo as demo_mod
    from tidemark.gui.main_window import MainWindow

    db, repo, runner = demo_mod.make_context()
    from tidemark.store.paths import default_paths
    paths = default_paths()
    w = MainWindow(db, paths, runner, demo=True)
    assert w.windowTitle().startswith("Tidemark [demo]")
    for row in range(4):
        w._sidebar.setCurrentRow(row)
        assert w._stack.currentIndex() == row
