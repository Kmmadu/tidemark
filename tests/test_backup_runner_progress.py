"""DirectBackupRunner emits ProgressEvents and honours cancel_event."""

from __future__ import annotations

import threading
from unittest.mock import patch

from tidemark.core import engine as engine_mod
from tidemark.core.credentials import Credentials
from tidemark.core.driver import FetchResult
from tidemark.core.models import Device
from tidemark.core.profiles import ProfileRegistry
from tidemark.core.progress import ProgressEvent, ProgressPhase


def test_progress_events_emitted() -> None:
    device = Device(name="core", host="10.0.0.1", port=22,
                    profile_id="cisco_ios", credential_ref="default")
    profile = ProfileRegistry().get("cisco_ios")
    events: list[ProgressEvent] = []

    with patch.object(engine_mod.Driver, "fetch",
                      return_value=FetchResult(text="hostname r1\n")):
        engine_mod.run_backup(
            device, profile, Credentials("u", "p"),
            retries=0, on_progress=events.append,
        )

    phases = [e.phase for e in events]
    assert ProgressPhase.NORMALISING in phases
    assert ProgressPhase.DONE in phases


def test_cancel_event_short_circuits() -> None:
    device = Device(name="core", host="10.0.0.1", port=22,
                    profile_id="cisco_ios", credential_ref="default")
    profile = ProfileRegistry().get("cisco_ios")
    cancel = threading.Event()
    cancel.set()

    with patch.object(engine_mod.Driver, "fetch") as fetch:
        result = engine_mod.run_backup(
            device, profile, Credentials("u", "p"),
            retries=0, cancel_event=cancel,
        )
    fetch.assert_not_called()
    assert "cancelled" in (result.error or "")
