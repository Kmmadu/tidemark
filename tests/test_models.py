"""Smoke tests for the model dataclasses."""

from __future__ import annotations

import pytest

from tidemark.core.models import (
    Device,
    RestoreMode,
    RunStatus,
    VendorProfile,
)


def test_vendor_profile_rejects_empty_fetch_commands() -> None:
    with pytest.raises(ValueError):
        VendorProfile(
            id="x", display_name="X", netmiko_device_type="generic",
            fetch_commands=[],
        )


def test_vendor_profile_rejects_bad_id() -> None:
    with pytest.raises(ValueError):
        VendorProfile(
            id="not valid!", display_name="X",
            netmiko_device_type="generic", fetch_commands=["a"],
        )


def test_restore_mode_values() -> None:
    assert RestoreMode("none") is RestoreMode.NONE
    assert RestoreMode("cli_delta") is RestoreMode.CLI_DELTA
    assert RestoreMode("file_import") is RestoreMode.FILE_IMPORT


def test_run_status_values() -> None:
    assert RunStatus("success") is RunStatus.SUCCESS
    assert RunStatus("failed") is RunStatus.FAILED
    assert RunStatus("unchanged") is RunStatus.UNCHANGED


def test_device_display_name_prefers_name() -> None:
    d = Device(name="core", host="10.0.0.1", port=22,
               profile_id="cisco_ios", credential_ref="x")
    assert d.display_name() == "core"


def test_device_display_name_falls_back_to_host() -> None:
    d = Device(name="", host="10.0.0.1", port=22,
               profile_id="cisco_ios", credential_ref="x")
    assert d.display_name() == "10.0.0.1"
