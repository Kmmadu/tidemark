"""
Every CLI command, run via subprocess against a temp XDG tree.

We do not use Click/CliRunner — the CLI is argparse-based and its
observable contract is stdout/stderr/exit code, so subprocess is the
most honest test.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run(
    args: list[str],
    xdg_home: Path,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(xdg_home / "config")
    env["XDG_DATA_HOME"] = str(xdg_home / "data")
    env["XDG_STATE_HOME"] = str(xdg_home / "state")
    for k in ("TIDEMARK_USER", "TIDEMARK_PASS"):
        env.pop(k, None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "tidemark.cli.main", *args],
        capture_output=True, text=True, env=env,
    )


@pytest.fixture
def xdg(tmp_path: Path) -> Path:
    return tmp_path


def test_version(xdg: Path) -> None:
    r = _run(["--version"], xdg)
    assert r.returncode == 0
    assert r.stdout.strip() == "tidemark 0.1.0"


def test_init(xdg: Path) -> None:
    r = _run(["init"], xdg)
    assert r.returncode == 0
    assert (xdg / "data" / "tidemark" / "tidemark.db").exists()
    assert (xdg / "data" / "tidemark" / "configs" / ".git").exists()


def test_device_add_and_list(xdg: Path) -> None:
    _run(["init"], xdg)
    r = _run(
        ["device", "add", "core", "--host", "10.0.0.1",
         "--profile", "cisco_ios"],
        xdg,
    )
    assert r.returncode == 0, r.stderr
    r = _run(["device", "list"], xdg)
    assert r.returncode == 0
    assert "core" in r.stdout
    assert "cisco_ios" in r.stdout


def test_device_add_unknown_profile(xdg: Path) -> None:
    _run(["init"], xdg)
    r = _run(
        ["device", "add", "x", "--host", "1.2.3.4", "--profile", "nonexistent"],
        xdg,
    )
    assert r.returncode == 1
    assert "unknown profile" in r.stderr


def test_device_add_duplicate(xdg: Path) -> None:
    _run(["init"], xdg)
    args = ["device", "add", "core", "--host", "10.0.0.1",
            "--profile", "cisco_ios"]
    _run(args, xdg)
    r = _run(args, xdg)
    assert r.returncode == 1
    assert "already exists" in r.stderr


def test_backup_requires_target(xdg: Path) -> None:
    _run(["init"], xdg)
    r = _run(["backup"], xdg)
    assert r.returncode == 2
    assert "--all or --device" in r.stderr


def test_backup_device_not_found(xdg: Path) -> None:
    _run(["init"], xdg)
    r = _run(["backup", "--device", "missing"], xdg)
    assert r.returncode == 1
    assert "not found" in r.stderr


def test_history_requires_device(xdg: Path) -> None:
    _run(["init"], xdg)
    r = _run(["history"], xdg)
    assert r.returncode == 2


def test_history_no_runs(xdg: Path) -> None:
    _run(["init"], xdg)
    _run(["device", "add", "core", "--host", "10.0.0.1",
          "--profile", "cisco_ios"], xdg)
    r = _run(["history", "--device", "core"], xdg)
    assert r.returncode == 0
    assert "no runs" in r.stdout


def test_diff_needs_two_snapshots(xdg: Path) -> None:
    _run(["init"], xdg)
    _run(["device", "add", "core", "--host", "10.0.0.1",
          "--profile", "cisco_ios"], xdg)
    r = _run(["diff", "core"], xdg)
    assert r.returncode == 1
    assert "at least two snapshots" in r.stderr


def test_import_yaml_roundtrip(xdg: Path) -> None:
    _run(["init"], xdg)
    legacy = xdg / "devices.yaml"
    legacy.write_text(
        "devices:\n"
        "  - name: core\n"
        "    host: 10.0.0.1\n"
        "    device_type: cisco_ios\n"
        "  - host: 10.0.0.2\n"
        "    device_type: mikrotik_routeros\n",
        encoding="utf-8",
    )
    r = _run(["import-yaml", str(legacy)], xdg)
    assert r.returncode == 0, r.stderr
    assert "imported 2 device(s)" in r.stdout

    r = _run(["device", "list"], xdg)
    assert "core" in r.stdout
    assert "mikrotik_routeros" in r.stdout


def test_cli_never_prints_credentials(xdg: Path) -> None:
    _run(["init"], xdg)
    r = _run(
        ["device", "add", "core", "--host", "10.0.0.1",
         "--profile", "cisco_ios"],
        xdg,
        env_extra={
            "TIDEMARK_USER": "user-do-not-print",
            "TIDEMARK_PASS": "pass-do-not-print",
        },
    )
    assert "pass-do-not-print" not in r.stdout
    assert "pass-do-not-print" not in r.stderr
    assert "user-do-not-print" not in r.stdout
    assert "user-do-not-print" not in r.stderr
