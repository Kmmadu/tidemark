"""
Runs backups off the GUI thread via ``QThreadPool``.

Uses the ``BackupRunner`` protocol exactly as M2a shipped it. ``DirectBackupRunner``
is passed by default; M4's ``DaemonBackupRunner`` will be a drop-in.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from tidemark.core.engine import BackupRunner
from tidemark.core.models import BackupResult, Device
from tidemark.core.progress import ProgressEvent


class _Signals(QObject):
    progress = Signal(ProgressEvent)
    finished_one = Signal(object)   # BackupResult
    finished_all = Signal(list)     # list[BackupResult]
    failed = Signal(str)
    done = Signal()


class _Runnable(QRunnable):
    def __init__(self, fn: Callable[[], None]) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:  # noqa: D401 - QRunnable
        self._fn()


class BackupWorker(QObject):
    """Public façade: create, connect to signals, call ``run_one`` / ``run_all``."""

    def __init__(self, runner: BackupRunner, device: Device | None = None) -> None:
        super().__init__()
        self._runner = runner
        self._device = device
        self._cancel = threading.Event()
        self._signals = _Signals()

    # signals exposed for convenience
    @property
    def progress(self):  # noqa: ANN201
        return self._signals.progress

    @property
    def finished_one(self):  # noqa: ANN201
        return self._signals.finished_one

    @property
    def finished_all(self):  # noqa: ANN201
        return self._signals.finished_all

    @property
    def failed(self):  # noqa: ANN201
        return self._signals.failed

    @property
    def done(self):  # noqa: ANN201
        return self._signals.done

    def cancel(self) -> None:
        self._cancel.set()

    def run_one(self) -> None:
        device = self._device
        if device is None:
            self._signals.failed.emit("no device")
            return

        def _go() -> None:
            try:
                result = self._runner.run_one(
                    device,
                    on_progress=self._signals.progress.emit,
                    cancel_event=self._cancel,
                )
                self._signals.finished_one.emit(result)
            except Exception as exc:  # noqa: BLE001
                self._signals.failed.emit(str(exc))
            finally:
                self._signals.done.emit()

        QThreadPool.globalInstance().start(_Runnable(_go))

    def run_all(self) -> None:
        def _go() -> None:
            try:
                results: list[BackupResult] = self._runner.run_all(
                    on_progress=self._signals.progress.emit,
                    cancel_event=self._cancel,
                )
                self._signals.finished_all.emit(results)
            except Exception as exc:  # noqa: BLE001
                self._signals.failed.emit(str(exc))
            finally:
                self._signals.done.emit()

        QThreadPool.globalInstance().start(_Runnable(_go))
