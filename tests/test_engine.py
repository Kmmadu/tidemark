"""run_backup / run_many behaviour with a fake driver."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from tidemark.core import engine as engine_mod
from tidemark.core.credentials import Credentials
from tidemark.core.driver import DriverError, FetchResult
from tidemark.core.models import Device, RunStatus, VendorProfile
from tidemark.core.profiles import ProfileRegistry


def _device(name: str = "core", profile: str = "cisco_ios") -> Device:
    return Device(
        name=name, host="10.0.0.1", port=22,
        profile_id=profile, credential_ref="default",
    )


def _profile() -> VendorProfile:
    return VendorProfile(
        id="cisco_ios", display_name="Cisco IOS",
        netmiko_device_type="cisco_ios",
        fetch_commands=["show running-config"],
        invalid_patterns=["% Invalid"],
        min_length=5,
    )


def test_run_backup_success_first_time() -> None:
    with patch.object(engine_mod.Driver, "fetch",
                      return_value=FetchResult(text="hostname r1\n")):
        res = engine_mod.run_backup(_device(), _profile(), Credentials("u", "p"))
    assert res.status is RunStatus.SUCCESS
    assert res.normalised_text == "hostname r1"
    assert res.diff is None
    assert res.changed is False


def test_run_backup_change_detected() -> None:
    with patch.object(engine_mod.Driver, "fetch",
                      return_value=FetchResult(text="hostname r2\n")):
        res = engine_mod.run_backup(
            _device(), _profile(), Credentials("u", "p"),
            previous_text="hostname r1",
        )
    assert res.changed is True
    assert res.status is RunStatus.SUCCESS
    assert res.diff and "+hostname r2" in res.diff


def test_run_backup_unchanged() -> None:
    with patch.object(engine_mod.Driver, "fetch",
                      return_value=FetchResult(text="hostname r1\n")):
        res = engine_mod.run_backup(
            _device(), _profile(), Credentials("u", "p"),
            previous_text="hostname r1",
        )
    assert res.status is RunStatus.UNCHANGED
    assert res.changed is False


def test_run_backup_failure_after_retries() -> None:
    with patch.object(engine_mod.Driver, "fetch",
                      side_effect=DriverError("boom")):
        res = engine_mod.run_backup(
            _device(), _profile(), Credentials("u", "p"),
            retries=1, backoff_seconds=0,
        )
    assert res.status is RunStatus.FAILED
    assert "boom" in (res.error or "")


def test_run_many_isolates_failures() -> None:
    good = _device(name="good")
    bad = _device(name="bad")

    def _fake_run(device, profile, creds, **kwargs):
        if device.name == "bad":
            return engine_mod.BackupResult(
                device=device, status=RunStatus.FAILED,
                started_at_utc=datetime.now(UTC),
                finished_at_utc=datetime.now(UTC),
                error="nope",
            )
        return engine_mod.BackupResult(
            device=device, status=RunStatus.SUCCESS,
            started_at_utc=datetime.now(UTC),
            finished_at_utc=datetime.now(UTC),
            normalised_text="x", sha256="h", changed=False,
        )

    reg = ProfileRegistry()
    with patch.object(engine_mod, "run_backup", side_effect=_fake_run):
        results = engine_mod.run_many(
            [good, bad], reg, Credentials("u", "p"), max_workers=2,
        )
    assert len(results) == 2
    statuses = {r.device.name: r.status for r in results}
    assert statuses["good"] is RunStatus.SUCCESS
    assert statuses["bad"] is RunStatus.FAILED
