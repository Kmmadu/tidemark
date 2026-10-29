"""
tidemark.core.engine
────────────────────
High-level operations: ``run_backup`` for one device, ``run_many`` for many.

``BackupRunner`` is the interface the GUI (M3) will call. ``DirectBackupRunner``
runs backups in worker threads and emits ``ProgressEvent``s. M4 will add a
``DaemonBackupRunner`` that enqueues commands for ``tidemarkd`` without
changing the GUI.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Protocol

from tidemark.core.credentials import Credentials
from tidemark.core.diffing import unified_diff
from tidemark.core.driver import Driver, DriverError
from tidemark.core.models import (
    BackupResult,
    Device,
    RunStatus,
    VendorProfile,
)
from tidemark.core.normalise import normalise
from tidemark.core.profiles import ProfileRegistry
from tidemark.core.progress import ProgressEvent, ProgressPhase

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _emit(
    cb: Callable[[ProgressEvent], None] | None,
    device: Device,
    phase: ProgressPhase,
    message: str = "",
) -> None:
    if cb is None:
        return
    try:
        cb(ProgressEvent(device_name=device.display_name(), phase=phase, message=message))
    except Exception:  # noqa: BLE001 - never let progress break the backup
        logger.exception("progress callback raised")


def run_backup(
    device: Device,
    profile: VendorProfile,
    credentials: Credentials,
    *,
    previous_text: str | None = None,
    retries: int = 2,
    backoff_seconds: float = 1.0,
    on_progress: Callable[[ProgressEvent], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> BackupResult:
    """Back up one device."""
    started = _now_utc()
    driver = Driver(device, profile, credentials)

    last_error: str | None = None
    raw: str | None = None
    for attempt in range(1, retries + 2):
        if cancel_event is not None and cancel_event.is_set():
            return BackupResult(
                device=device, status=RunStatus.FAILED,
                started_at_utc=started, finished_at_utc=_now_utc(),
                error="cancelled before fetch",
            )
        _emit(on_progress, device, ProgressPhase.CONNECTING if attempt == 1 else ProgressPhase.FETCHING)
        try:
            raw = driver.fetch().text
            break
        except DriverError as exc:
            last_error = str(exc)
            logger.warning(
                "backup attempt %d/%d failed for %s: %s",
                attempt, retries + 1, device.display_name(), exc,
            )
            if attempt < retries + 1:
                time.sleep(backoff_seconds * attempt)

    if raw is None:
        _emit(on_progress, device, ProgressPhase.FAILED, last_error or "unknown error")
        return BackupResult(
            device=device,
            status=RunStatus.FAILED,
            started_at_utc=started,
            finished_at_utc=_now_utc(),
            error=last_error or "unknown error",
        )

    _emit(on_progress, device, ProgressPhase.NORMALISING)
    norm = normalise(raw, profile.volatile_patterns)

    diff_text: str | None = None
    changed = False
    if previous_text is not None and previous_text != norm.text:
        diff_text = unified_diff(
            previous_text,
            norm.text,
            from_label=f"{device.display_name()}_previous",
            to_label=f"{device.display_name()}_current",
        )
        changed = True

    status = RunStatus.SUCCESS if changed or previous_text is None else RunStatus.UNCHANGED
    _emit(on_progress, device, ProgressPhase.DONE)
    return BackupResult(
        device=device,
        status=status,
        started_at_utc=started,
        finished_at_utc=_now_utc(),
        normalised_text=norm.text,
        sha256=norm.sha256,
        diff=diff_text,
        changed=changed,
    )


def run_many(
    devices: Iterable[Device],
    profiles: ProfileRegistry,
    credentials: Credentials,
    *,
    max_workers: int = 5,
    on_progress: Callable[[ProgressEvent], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> list[BackupResult]:
    """Run ``run_backup`` for many devices in parallel."""
    device_list = list(devices)
    results: list[BackupResult] = []

    def _one(device: Device) -> BackupResult:
        profile = profiles.get(device.profile_id)
        return run_backup(
            device, profile, credentials,
            on_progress=on_progress, cancel_event=cancel_event,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_one, d): d for d in device_list}
        for fut in as_completed(futures):
            device = futures[fut]
            try:
                results.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                logger.exception("unexpected error backing up %s", device.display_name())
                results.append(
                    BackupResult(
                        device=device,
                        status=RunStatus.FAILED,
                        started_at_utc=_now_utc(),
                        finished_at_utc=_now_utc(),
                        error=f"unexpected error: {exc}",
                    )
                )
    return results


class BackupRunner(Protocol):
    """Interface used by the GUI (M3) and CLI (M1c) to run backups."""

    def run_one(
        self,
        device: Device,
        on_progress: Callable[[ProgressEvent], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> BackupResult: ...

    def run_all(
        self,
        on_progress: Callable[[ProgressEvent], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> list[BackupResult]: ...


class DirectBackupRunner:
    """A ``BackupRunner`` that runs backups in worker threads."""

    def __init__(
        self,
        devices: list[Device],
        profiles: ProfileRegistry,
        credentials: Credentials,
        *,
        max_workers: int = 5,
    ) -> None:
        self._devices = devices
        self._profiles = profiles
        self._credentials = credentials
        self._max_workers = max_workers

    def run_one(
        self,
        device: Device,
        on_progress: Callable[[ProgressEvent], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> BackupResult:
        return run_backup(
            device, self._profiles.get(device.profile_id), self._credentials,
            on_progress=on_progress, cancel_event=cancel_event,
        )

    def run_all(
        self,
        on_progress: Callable[[ProgressEvent], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> list[BackupResult]:
        return run_many(
            self._devices,
            self._profiles,
            self._credentials,
            max_workers=self._max_workers,
            on_progress=on_progress,
            cancel_event=cancel_event,
        )
