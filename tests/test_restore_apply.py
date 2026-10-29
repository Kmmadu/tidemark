"""apply_restore: verify-before-save, ack list, no auto-retry."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tidemark.core import engine as engine_mod
from tidemark.core.credentials import Credentials
from tidemark.core.driver import FetchResult
from tidemark.core.models import Device
from tidemark.core.profiles import ProfileRegistry
from tidemark.core.restore import (
    RestoreConfirmationError,
    RestorePlanStaleError,
    apply_restore,
    plan_restore,
)
from tidemark.store.db import Database, migrate
from tidemark.store.git_repo import ConfigRepo
from tidemark.store.repositories import DeviceRepo, SnapshotRepo
from tidemark.store.restore_attempts import AttemptOutcome
from tidemark.store.service import backup_and_persist

CONFIG1 = "hostname r1\n"
CONFIG2 = "hostname r1\ninterface Gi0/1\n ip address 10.0.0.1 255.255.255.0\n"
CONFIG3 = "hostname r3\n"  # differs in hostname value, not just a subset


def _setup(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    migrate(db)
    repo = ConfigRepo(tmp_path / "configs")
    device = DeviceRepo(db).add(Device(
        name="core", host="10.0.0.1", port=22,
        profile_id="cisco_ios", credential_ref="default",
    ))
    profile = ProfileRegistry().get("cisco_ios")

    def run(text: str) -> None:
        with patch.object(engine_mod.Driver, "fetch",
                          return_value=FetchResult(text=text)):
            backup_and_persist(device, profile, Credentials("u", "p"),
                               db, repo, retries=0)

    for text in (CONFIG1, CONFIG2, CONFIG3):
        run(text)
    return db, repo, device, profile


def _plan_with_operations(db, repo, device, profile):
    """Return a plan whose current != target by content (not just subset)."""
    snaps = SnapshotRepo(db).list_for_device(device.id)
    # newest = CONFIG3 (id DESC order), oldest = CONFIG1
    target = snaps[-1]  # CONFIG1 ("hostname r1\n")
    plan = plan_restore(device, profile, target.id or 0, db, repo)
    assert plan.status == "ready", "test setup must produce a non-empty plan"
    return plan


def test_apply_refuses_wrong_token(tmp_path: Path) -> None:
    db, repo, device, profile = _setup(tmp_path)
    plan = _plan_with_operations(db, repo, device, profile)
    with pytest.raises(RestoreConfirmationError):
        apply_restore(
            plan, "wrong-token", plan.high_risk_codes, Credentials("u", "p"),
            db, repo,
        )


def test_apply_refuses_incomplete_ack(tmp_path: Path) -> None:
    db, repo, device, profile = _setup(tmp_path)
    plan = _plan_with_operations(db, repo, device, profile)
    with pytest.raises(RestoreConfirmationError):
        apply_restore(
            plan, plan.confirm_token, ["wrong"], Credentials("u", "p"),
            db, repo,
        )


def test_apply_refuses_on_stale(tmp_path: Path) -> None:
    db, repo, device, profile = _setup(tmp_path)
    plan = _plan_with_operations(db, repo, device, profile)

    # Mutate current config on disk so plan_hash no longer matches.
    repo.store_normal("core", "hostname totally-different\n", datetime.now(UTC))

    with pytest.raises(RestorePlanStaleError):
        apply_restore(
            plan, plan.confirm_token, plan.high_risk_codes,
            Credentials("u", "p"), db, repo,
        )


def test_apply_verify_before_save(tmp_path: Path) -> None:
    db, repo, device, profile = _setup(tmp_path)
    plan = _plan_with_operations(db, repo, device, profile)

    fake = MagicMock()

    def _send(cmd: str, **kwargs) -> str:
        if cmd == "show running-config":
            return plan.expected_post_text
        return ""

    fake.send_command.side_effect = _send

    with patch("tidemark.core.restore.ConnectHandler", return_value=fake):
        outcome = apply_restore(
            plan, plan.confirm_token, plan.high_risk_codes,
            Credentials("u", "p"), db, repo,
        )

    assert outcome is AttemptOutcome.SUCCESS
    commands = [call.args[0] for call in fake.send_command.call_args_list
                if call.args]
    assert "write memory" in commands, f"commands sent: {commands}"
