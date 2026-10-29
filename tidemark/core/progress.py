"""
tidemark.core.progress
──────────────────────
Progress and cancellation primitives for ``BackupRunner``.

The GUI (M3) will connect these to Qt signals; the daemon (M4) will connect
them to log lines. The engine itself never imports PySide6.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ProgressPhase(StrEnum):
    """Phases a single backup can be in."""

    CONNECTING = "connecting"
    FETCHING = "fetching"
    NORMALISING = "normalising"
    STORING = "storing"
    COMMITTING = "committing"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class ProgressEvent:
    """One progress tick for one device."""

    device_name: str
    phase: ProgressPhase
    message: str = ""
