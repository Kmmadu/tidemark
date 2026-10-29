"""Shared fixtures for M1 tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def tmp_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point XDG dirs at a temp tree so tests never touch the real one."""
    config = tmp_path / "config"
    data = tmp_path / "data"
    state = tmp_path / "state"
    for d in (config, data, state):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    yield tmp_path


@pytest.fixture
def clear_credential_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("TIDEMARK_USER", "TIDEMARK_PASS"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def fake_connect_handler() -> Iterator[type]:
    """A fake ``ConnectHandler`` class. Set instance return values via ``.outputs``."""
    MagicMock(name="ConnectHandler")  # kept as a marker for future use

    class Fake:
        outputs: dict[str, str] = {}

        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def send_command(self, command: str, **_: object) -> str:
            return self.outputs.get(command, "")

        def enable(self) -> None:
            return None

        def disconnect(self) -> None:
            return None

    yield Fake
