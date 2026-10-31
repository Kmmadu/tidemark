"""
Demo mode context.

Boots the GUI against a temporary XDG tree, seeded devices, and a fake
backup runner that pretends every backup succeeds. Nothing under ``--demo``
writes to real XDG dirs, touches the real credential store, or opens an
SSH connection.
"""

from __future__ import annotations

import tempfile
from datetime import UTC
from pathlib import Path

from tidemark.core.credentials import Credentials
from tidemark.core.driver import FetchResult
from tidemark.core.models import Device, RunStatus
from tidemark.core.profiles import ProfileRegistry
from tidemark.core.progress import ProgressEvent
from tidemark.store.db import Database, migrate
from tidemark.store.git_repo import ConfigRepo
from tidemark.store.repositories import DeviceRepo
from tidemark.store.service import backup_and_persist

DEMO_DEVICES = [
    {"name": "demo-core",  "host": "10.0.0.10", "profile": "cisco_ios",
     "config": "hostname demo-core\n!\ninterface Gi0/1\n ip address 10.0.0.10 255.255.255.0\n!\n"},
    {"name": "demo-edge",  "host": "10.0.0.11", "profile": "cisco_ios",
     "config": "hostname demo-edge\n!\ninterface Gi0/1\n ip address 10.0.0.11 255.255.255.0\n!\n"},
    {"name": "demo-mik",   "host": "10.0.0.12", "profile": "mikrotik_routeros",
     "config": "/interface ethernet\nadd name=ether1\n/ip address\nadd address=10.0.0.12/24 interface=ether1\n"},
]


class DemoBackupRunner:
    """In-memory runner: pretends to back up, returns SUCCESS."""

    def __init__(self) -> None:
        pass

    def run_one(self, device, on_progress=None, cancel_event=None):  # noqa: ANN001
        if on_progress is not None:
            on_progress(ProgressEvent(device_name=device.name, phase="connecting"))
        import time
        time.sleep(0.2)
        if on_progress is not None:
            on_progress(ProgressEvent(device_name=device.name, phase="done"))
        from datetime import datetime

        from tidemark.core.models import BackupResult
        now = datetime.now(UTC)
        return BackupResult(
            device=device, status=RunStatus.SUCCESS,
            started_at_utc=now, finished_at_utc=now,
            normalised_text=f"# demo backup of {device.name}\n",
            sha256="0" * 64, changed=False,
        )

    def run_all(self, on_progress=None, cancel_event=None):  # noqa: ANN001
        results = []
        for name in ["demo-core", "demo-edge", "demo-mik"]:
            from tidemark.core.models import Device
            d = Device(name=name, host="10.0.0.x", port=22,
                       profile_id="cisco_ios", credential_ref="demo")
            results.append(self.run_one(d, on_progress, cancel_event))
        return results


def seed(db: Database, config_repo: ConfigRepo) -> None:
    profiles = ProfileRegistry()
    repo = DeviceRepo(db)
    for spec in DEMO_DEVICES:
        d = repo.add(Device(
            name=spec["name"], host=spec["host"], port=22,
            profile_id=spec["profile"], credential_ref="demo",
            enabled=True, custom_command="DEMO",
        ))
        profile = profiles.get(spec["profile"])
        from unittest.mock import patch

        from tidemark.core import engine as engine_mod
        with patch.object(engine_mod.Driver, "fetch",
                          return_value=FetchResult(text=spec["config"])):
            backup_and_persist(d, profile, Credentials("demo", "demo"),
                               db, config_repo, retries=0)


def make_context() -> tuple[Database, ConfigRepo, DemoBackupRunner]:
    tmp = tempfile.TemporaryDirectory(prefix="tidemark-demo-")
    root = Path(tmp.name)
    db = Database(root / "demo.db")
    migrate(db)
    repo = ConfigRepo(root / "configs")
    seed(db, repo)
    return db, repo, DemoBackupRunner()
