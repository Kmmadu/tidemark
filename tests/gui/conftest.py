"""Force offscreen Qt for tests, and clean up top-level widgets between tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _offscreen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("QT_QPA_PLATFORMTHEME", "")


@pytest.fixture(autouse=True)
def _cleanup_widgets() -> Iterator[None]:
    yield
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    for w in app.topLevelWidgets():
        try:
            w.close()
            w.deleteLater()
        except Exception:
            pass
    app.processEvents()
