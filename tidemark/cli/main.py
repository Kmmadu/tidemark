"""
tidemark.cli.main
─────────────────
Command line interface for Tidemark (M1).

Commands
────────
  tidemark init                          Create XDG dirs and the SQLite DB.
  tidemark device add NAME                Add a device (prompts for missing fields).
  tidemark device list                    List devices.
  tidemark backup --all                   Back up every enabled device.
  tidemark backup --device NAME           Back up one device.
  tidemark history --device NAME          Show the last 20 runs for a device.
  tidemark diff DEVICE [--from ID --to ID]  Show a unified diff between two snapshots.
  tidemark import-yaml PATH               Import a legacy devices.yaml.
  tidemark --version                      Print the version.

Exit codes
──────────
  0  success
  1  runtime error (device not found, unreachable, diff error, ...)
  2  usage error (argparse default)

Credentials (temporary until M2)
────────────────────────────────
  Read from TIDEMARK_USER / TIDEMARK_PASS in the environment, or prompted
  via getpass. Never printed, never persisted. M2 replaces this with a
  keyring-backed CredentialStore.

This file contains no SQL, no Netmiko calls, and no git operations. It
calls tidemark.store and tidemark.core and formats output for the terminal.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from tidemark import __version__
from tidemark.core.credentials import read_credentials
from tidemark.core.models import Device, RunStatus
from tidemark.core.profiles import ProfileRegistry
from tidemark.store.db import Database, migrate
from tidemark.store.git_repo import ConfigRepo
from tidemark.store.importer import ImportError_, import_legacy_yaml
from tidemark.store.paths import Paths, default_paths
from tidemark.store.repositories import (
    DeviceRepo,
    RunRepo,
    SettingsRepo,
    SnapshotRepo,
)
from tidemark.store.service import backup_and_persist

logger = logging.getLogger(__name__)


# ── Shared state ─────────────────────────────────────────────────────────────

class _Context:
    """Opened once per invocation, closed on exit."""

    def __init__(self, paths: Paths) -> None:
        self.paths = paths
        self.db = Database(paths.db_path)
        migrate(self.db)

    def close(self) -> None:
        self.db.close()


# ── Formatting helpers ───────────────────────────────────────────────────────

def _fmt_utc(iso: str) -> str:
    """Render an ISO 8601 UTC timestamp as ``YYYY-MM-DD HH:MM:SS``."""
    return iso.replace("T", " ")[:19]


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _warn(msg: str) -> None:
    print(f"[tidemark] {msg}", file=sys.stderr)


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> int:  # noqa: ARG001
    paths = default_paths()
    paths.ensure_dirs()
    ctx = _Context(paths)
    try:
        SettingsRepo(ctx.db).set("created_at", "m1c")
        ConfigRepo(paths.configs_git_dir)
    finally:
        ctx.close()
    print(f"initialised: {paths.data_dir}")
    print(f"config dir : {paths.config_dir}")
    print(f"state dir  : {paths.state_dir}")
    return 0


def cmd_device_add(args: argparse.Namespace) -> int:
    paths = default_paths()
    paths.ensure_dirs()
    ctx = _Context(paths)
    try:
        repo = DeviceRepo(ctx.db)
        if repo.get_by_name(args.name) is not None:
            _warn(f"device {args.name!r} already exists; use a different name")
            return 1

        host = args.host or input("host: ").strip()
        profile_id = args.profile or input("profile id: ").strip()
        if not host or not profile_id:
            _warn("host and profile are required")
            return 1

        profiles = ProfileRegistry(user_profiles_dir=paths.user_profiles_dir)
        try:
            profiles.get(profile_id)
        except KeyError:
            _warn(f"unknown profile {profile_id!r}; known: {profiles.ids()}")
            return 1

        device = Device(
            name=args.name,
            host=host,
            port=int(args.port),
            profile_id=profile_id,
            credential_ref=args.credential_ref,
            group=args.group,
            enabled=not args.disabled,
            custom_command=args.custom_command,
        )
        repo.add(device)
        print(f"added device {device.name} ({device.host}:{device.port}, profile={device.profile_id})")
        return 0
    finally:
        ctx.close()


def cmd_device_list(args: argparse.Namespace) -> int:  # noqa: ARG001
    paths = default_paths()
    paths.ensure_dirs()
    ctx = _Context(paths)
    try:
        devices = DeviceRepo(ctx.db).list()
        if not devices:
            print("(no devices)")
            return 0
        print(f"{'NAME':<24}{'HOST':<20}{'PORT':<6}{'PROFILE':<24}ENABLED")
        for d in devices:
            print(
                f"{d.name:<24}{d.host:<20}{d.port:<6}{d.profile_id:<24}"
                f"{'yes' if d.enabled else 'no'}"
            )
        return 0
    finally:
        ctx.close()


def cmd_backup(args: argparse.Namespace) -> int:
    if not args.all and not args.device:
        _warn("specify --all or --device NAME")
        return 2
    if args.all and args.device:
        _warn("--all and --device are mutually exclusive")
        return 2

    paths = default_paths()
    paths.ensure_dirs()
    ctx = _Context(paths)
    try:
        device_repo = DeviceRepo(ctx.db)
        if args.all:
            devices = device_repo.list(enabled_only=True)
            if not devices:
                _warn("no enabled devices to back up")
                return 1
        else:
            device = device_repo.get_by_name(args.device)
            if device is None:
                _warn(f"device {args.device!r} not found")
                return 1
            devices = [device]

        profiles = ProfileRegistry(user_profiles_dir=paths.user_profiles_dir)
        config_repo = ConfigRepo(paths.configs_git_dir)

        _warn("using temporary M1 credentials (env or prompt); replaced by CredentialStore in M2")
        credentials = read_credentials(prompt_device=", ".join(d.name for d in devices))

        counts = {"OK": 0, "UNCHANGED": 0, "FAILED": 0}
        for device in devices:
            try:
                result = backup_and_persist(
                    device, profiles.get(device.profile_id),
                    credentials, ctx.db, config_repo, retries=1,
                )
            except Exception as exc:  # noqa: BLE001 - one device must not stop the run
                counts["FAILED"] += 1
                print(f"[FAILED]     {device.name:<24}unexpected error: {exc}")
                continue

            if result.status is RunStatus.SUCCESS:
                counts["OK"] += 1
                detail = "new snapshot committed" if result.changed else "first snapshot"
                print(f"[OK]         {device.name:<24}{detail}")
            elif result.status is RunStatus.UNCHANGED:
                counts["UNCHANGED"] += 1
                print(f"[UNCHANGED]  {device.name:<24}no config change")
            else:
                counts["FAILED"] += 1
                print(f"[FAILED]     {device.name:<24}{result.error or 'unknown error'}")

        print(f"done: {counts['OK']} OK, {counts['UNCHANGED']} UNCHANGED, {counts['FAILED']} FAILED")
        return 0 if counts["FAILED"] == 0 else 1
    finally:
        ctx.close()


def cmd_history(args: argparse.Namespace) -> int:
    if not args.device:
        _warn("history requires --device NAME")
        return 2

    paths = default_paths()
    paths.ensure_dirs()
    ctx = _Context(paths)
    try:
        device = DeviceRepo(ctx.db).get_by_name(args.device)
        if device is None:
            _warn(f"device {args.device!r} not found")
            return 1
        runs = RunRepo(ctx.db).list_for_device(device.id or 0, limit=20)
        if not runs:
            print(f"(no runs for {device.name})")
            return 0
        print(f"{'ID':<6}{'STARTED (UTC)':<22}{'STATUS':<12}{'SNAPSHOT':<10}ERROR")
        for run in runs:
            snap = str(run.snapshot_id) if run.snapshot_id is not None else "-"
            err = (run.error or "").replace("\n", " ")
            if len(err) > 80:
                err = err[:80] + "…"
            print(
                f"{run.id:<6}{_fmt_utc(run.started_at_utc.isoformat()):<22}"
                f"{run.status.value:<12}{snap:<10}{err}"
            )
        return 0
    finally:
        ctx.close()


def cmd_diff(args: argparse.Namespace) -> int:
    paths = default_paths()
    paths.ensure_dirs()
    ctx = _Context(paths)
    try:
        device = DeviceRepo(ctx.db).get_by_name(args.device)
        if device is None:
            _warn(f"device {args.device!r} not found")
            return 1

        snap_repo = SnapshotRepo(ctx.db)
        if args.from_id is None and args.to_id is None:
            snaps = snap_repo.list_for_device(device.id or 0, limit=2)
            if len(snaps) < 2:
                _warn(f"need at least two snapshots for {device.name}")
                return 1
            to_snap, from_snap = snaps[0], snaps[1]
        else:
            if args.from_id is None or args.to_id is None:
                _warn("--from and --to must be provided together")
                return 2
            from_snap = snap_repo.get_by_id(args.from_id)
            to_snap = snap_repo.get_by_id(args.to_id)
            if from_snap is None or to_snap is None:
                _warn("--from/--to id not found")
                return 1
            if from_snap.device_id != device.id or to_snap.device_id != device.id:
                _warn("snapshot does not belong to that device")
                return 1

        try:
            from tidemark.core.diffing import unified_diff
            old = Path(from_snap.path).read_text(encoding="utf-8")
            new = Path(to_snap.path).read_text(encoding="utf-8")
        except OSError as exc:
            _warn(f"cannot read snapshot file: {exc}")
            return 1

        if old == new:
            print(f"no differences between snapshot {from_snap.id} and {to_snap.id}")
            return 0
        print(unified_diff(
            old, new,
            from_label=f"{device.name}#{from_snap.id}",
            to_label=f"{device.name}#{to_snap.id}",
        ))
        return 0
    finally:
        ctx.close()


def cmd_import_yaml(args: argparse.Namespace) -> int:
    paths = default_paths()
    paths.ensure_dirs()
    ctx = _Context(paths)
    try:
        try:
            imported = import_legacy_yaml(Path(args.path), DeviceRepo(ctx.db))
        except ImportError_ as exc:
            _warn(str(exc))
            return 1
        if not imported:
            print("no new devices imported")
        else:
            print(f"imported {len(imported)} device(s):")
            for d in imported:
                print(f"  - {d.name} ({d.host}:{d.port}, profile={d.profile_id})")
        return 0
    finally:
        ctx.close()


# ── Argparse wiring ─────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tidemark",
        description="Tidemark — back up, compare and safely restore network device configs over SSH.",
    )
    parser.add_argument("--version", action="version", version=f"tidemark {__version__}")

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p_init = sub.add_parser("init", help="Create XDG dirs, SQLite DB and configs git repo.")
    p_init.set_defaults(func=cmd_init)

    p_device = sub.add_parser("device", help="Manage the device inventory.")
    device_sub = p_device.add_subparsers(dest="device_command", required=True, metavar="SUBCOMMAND")

    p_add = device_sub.add_parser("add", help="Add a device.")
    p_add.add_argument("name", help="Unique device name (letters, digits, . - _ only).")
    p_add.add_argument("--host", help="Hostname or IP.")
    p_add.add_argument("--port", type=int, default=22, help="SSH port (default 22).")
    p_add.add_argument("--profile", help="Vendor profile id (e.g. cisco_ios, mikrotik_routeros).")
    p_add.add_argument("--group", help="Optional group name.")
    p_add.add_argument("--credential-ref", default="default",
                       help="Reference to credentials (M1 stores only the reference).")
    p_add.add_argument("--custom-command", help="Fetch command override (profile 'custom').")
    p_add.add_argument("--disabled", action="store_true", help="Add the device but do not back it up.")
    p_add.set_defaults(func=cmd_device_add)

    p_list = device_sub.add_parser("list", help="List devices.")
    p_list.set_defaults(func=cmd_device_list)

    p_backup = sub.add_parser("backup", help="Back up one or all devices.")
    p_backup.add_argument("--all", action="store_true", help="Back up all enabled devices.")
    p_backup.add_argument("--device", help="Back up a single device by name.")
    p_backup.set_defaults(func=cmd_backup)

    p_hist = sub.add_parser("history", help="Show recent runs for a device.")
    p_hist.add_argument("--device", required=True, help="Device name.")
    p_hist.set_defaults(func=cmd_history)

    p_diff = sub.add_parser("diff", help="Show a unified diff between two snapshots.")
    p_diff.add_argument("device", help="Device name.")
    p_diff.add_argument("--from", dest="from_id", type=int, help="Snapshot id to diff from.")
    p_diff.add_argument("--to", dest="to_id", type=int, help="Snapshot id to diff to.")
    p_diff.set_defaults(func=cmd_diff)

    p_import = sub.add_parser("import-yaml", help="Import a legacy devices.yaml.")
    p_import.add_argument("path", help="Path to the legacy devices.yaml.")
    p_import.set_defaults(func=cmd_import_yaml)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``tidemark`` console script."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
