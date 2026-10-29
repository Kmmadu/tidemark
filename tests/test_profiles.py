"""Bundled profiles load, user overrides win, invalid ones raise."""

from __future__ import annotations

from pathlib import Path

import pytest

from tidemark.core.profiles import ProfileError, ProfileRegistry


def test_bundled_profiles_load(tmp_xdg: Path) -> None:
    reg = ProfileRegistry()
    ids = reg.ids()
    assert "mikrotik_routeros" in ids
    assert "cisco_ios" in ids
    assert "custom" in ids
    assert reg.get("mikrotik_routeros").tested is True
    assert reg.get("cisco_ios").tested is True


def test_untested_profiles_load(tmp_xdg: Path) -> None:
    reg = ProfileRegistry()
    for pid in (
        "cisco_nxos", "cisco_asa", "juniper_junos", "arista_eos",
        "huawei", "fortinet", "ubiquiti_edgeswitch", "linux_generic",
    ):
        assert reg.get(pid).tested is False


def test_user_profile_overrides_bundled(tmp_xdg: Path) -> None:
    user_dir = tmp_xdg / "config" / "profiles"
    user_dir.mkdir(parents=True)
    (user_dir / "cisco_ios.yaml").write_text(
        "id: cisco_ios\n"
        "display_name: Cisco IOS (local override)\n"
        "netmiko_device_type: cisco_ios\n"
        "fetch_commands: ['show run']\n",
        encoding="utf-8",
    )
    reg = ProfileRegistry(user_profiles_dir=user_dir)
    p = reg.get("cisco_ios")
    assert p.display_name == "Cisco IOS (local override)"
    assert p.fetch_commands == ["show run"]


def test_missing_required_field_raises(tmp_xdg: Path) -> None:
    user_dir = tmp_xdg / "config" / "profiles"
    user_dir.mkdir(parents=True)
    (user_dir / "broken.yaml").write_text(
        "id: broken\ndisplay_name: Broken\n",  # missing netmiko_device_type/fetch_commands
        encoding="utf-8",
    )
    with pytest.raises(ProfileError):
        ProfileRegistry(user_profiles_dir=user_dir)


def test_invalid_restore_mode_raises(tmp_xdg: Path) -> None:
    user_dir = tmp_xdg / "config" / "profiles"
    user_dir.mkdir(parents=True)
    (user_dir / "bad_restore.yaml").write_text(
        "id: bad\n"
        "display_name: Bad\n"
        "netmiko_device_type: generic\n"
        "fetch_commands: ['x']\n"
        "restore: teleport\n",
        encoding="utf-8",
    )
    with pytest.raises(ProfileError):
        ProfileRegistry(user_profiles_dir=user_dir)
