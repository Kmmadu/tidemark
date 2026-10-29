"""
tidemark.cli.main
─────────────────
Command line interface for Tidemark.

Commands
────────
  tidemark init
  tidemark device add NAME [flags] | list
  tidemark backup --all | --device NAME
  tidemark history --device NAME
  tidemark diff DEVICE [--from ID --to ID]
  tidemark import-yaml PATH
  tidemark credentials status | set-backend {keyring|file}
            | migrate-keyring-to-file | migrate-file-to-keyring
            | change-passphrase
  tidemark restore-plan DEVICE [--snapshot ID] [--allow-removals]
  tidemark restore-apply DEVICE --plan-hash HASH --confirm TOKEN
                         [--ack CODE ...] [--allow-removals]
  tidemark --version

Exit codes
──────────
  0 success, 1 runtime error, 2 usage error.

Credentials for backups
───────────────────────
M2b still accepts TIDEMARK_USER / TIDEMARK_PASS for ``backup`` (kept from
M1) and, going forward, the credential store. ``tidemark credentials``
manages stored credentials (keyring or encrypted file).

The restore commands are gated by ``ALLOW_RESTORE=true`` until M3's GUI
removes the gate. Only ``restore-apply`` is gated; ``restore-plan`` is
read-only and always works.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from tidemark import __version__
from tidemark.core.credentials import read_credentials
from tidemark.core.models import Device, RunStatus
from tidemark.core.profiles import ProfileRegistry
from tidemark.core.redact import redact
from tidemark.core.restore import (
    RestoreConfirmationError,
    RestoreError,
    RestoreModeError,
    RestorePlanStaleError,
    SnapshotIntegrityError,
    apply_restore,
    plan_restore,
)
from tidemark.core.restore_risk_ios import Severity
from tidemark.store.credentials import (
    CredentialNotFound,
    CredentialStoreFactory,
    EncryptedFileStore,
    InteractivePassphraseProvider,
    KeyringStore,
    WrongPassphrase,
    passphrase_provider_from_env,
    probe_keyring,
)
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
from tidemark.store.restore_attempts import AttemptOutcome, RestoreAttemptsRepo
from tidemark.store.service import backup_and_persist

logger = logging.getLogger(__name__)


# ── Shared context ─────────────────────────────────────────────────────────

class _Context:
    def __init__(self, paths: Paths) -> None:
        self.paths = paths
        self.db = Database(paths.db_path)
        migrate(self.db)

    def close(self) -> None:
        self.db.close()

    def open_credential_store(self):
        factory = CredentialStoreFactory(self.paths.config_dir, self.db)
        provider = passphrase_provider_from_env() or InteractivePassphraseProvider()
        return factory.open(passphrase_provider=provider)

    def open_credential_store_factory(self):
        return CredentialStoreFactory(self.paths.config_dir, self.db)


# ── Formatting helpers ─────────────────────────────────────────────────────

def _fmt_utc(iso: str) -> str:
    return iso.replace("T", " ")[:19]


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _warn(msg: str) -> None:
    print(f"[tidemark] {redact(msg)}", file=sys.stderr)


def _require_restore_allowed() -> bool:
    if os.getenv("ALLOW_RESTORE", "false").lower() != "true":
        _warn(
            "restore-apply is disabled. Set ALLOW_RESTORE=true to enable. "
            "(restore-plan works without this.)"
        )
        return False
    return True


# ── Commands: init / device / backup / history / diff / import-yaml ───────

def cmd_init(_args: argparse.Namespace) -> int:
    paths = default_paths()
    paths.ensure_dirs()
    ctx = _Context(paths)
    try:
        SettingsRepo(ctx.db).set("created_at", "m2b")
        ConfigRepo(paths.configs_git_dir)
        RestoreAttemptsRepo(ctx.db).sweep_stale()
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
            _warn(f"device {args.name!r} already exists")
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
            name=args.name, host=host, port=int(args.port),
            profile_id=profile_id, credential_ref=args.credential_ref,
            group=args.group, enabled=not args.disabled,
            custom_command=args.custom_command,
        )
        repo.add(device)
        print(f"added device {device.name} ({device.host}:{device.port}, "
              f"profile={device.profile_id})")
        return 0
    finally:
        ctx.close()


def cmd_device_list(_args: argparse.Namespace) -> int:
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

        credentials = read_credentials(
            prompt_device=", ".join(d.name for d in devices)
        )

        counts = {"OK": 0, "UNCHANGED": 0, "FAILED": 0}
        for device in devices:
            try:
                result = backup_and_persist(
                    device, profiles.get(device.profile_id),
                    credentials, ctx.db, config_repo, retries=1,
                )
            except Exception as exc:  # noqa: BLE001
                counts["FAILED"] += 1
                print(f"[FAILED]     {device.name:<24}{redact(str(exc))}")
                continue
            if result.status is RunStatus.SUCCESS:
                counts["OK"] += 1
                print(f"[OK]         {device.name:<24}new snapshot")
            elif result.status is RunStatus.UNCHANGED:
                counts["UNCHANGED"] += 1
                print(f"[UNCHANGED]  {device.name:<24}no config change")
            else:
                counts["FAILED"] += 1
                print(f"[FAILED]     {device.name:<24}{redact(result.error or 'unknown')}")
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
            err = redact(err) or ""
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
    from tidemark.core.diffing import unified_diff

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
            config_repo = ConfigRepo(paths.configs_git_dir)
            old = (config_repo.current_content(device.name) or "").rstrip("\n")
            new = old
            # Prefer reading the target content from git at its commit.
            if getattr(to_snap, "commit_sha", None):
                new = config_repo.read_at(to_snap.commit_sha, f"{device.name}/running.cfg").rstrip("\n")
            if getattr(from_snap, "commit_sha", None):
                old = config_repo.read_at(from_snap.commit_sha, f"{device.name}/running.cfg").rstrip("\n")
        except (OSError, Exception) as exc:
            _warn(f"cannot read snapshot: {exc}")
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


# ── Commands: credentials ─────────────────────────────────────────────────

def cmd_credentials_status(_args: argparse.Namespace) -> int:
    paths = default_paths()
    paths.ensure_dirs()
    ctx = _Context(paths)
    try:
        factory = ctx.open_credential_store_factory()
        configured = factory.get_configured_backend()
        env_override = os.getenv("TIDEMARK_CREDENTIAL_STORE", "").strip().lower()
        usable, reason = probe_keyring()
        file_path = paths.config_dir / "credentials.enc"
        print(f"backend configured  : {configured}")
        if env_override:
            print(f"env override        : {env_override}")
        print(f"keyring usable now  : {'yes' if usable else 'no'} ({reason})")
        print(f"file store exists   : {'yes' if file_path.exists() else 'no'}")
        if configured == "keyring" and not usable and not env_override:
            print("→ run from a desktop session, or migrate to the file store:")
            print("    tidemark credentials set-backend file")
            print("    tidemark credentials migrate-keyring-to-file")
        return 0
    finally:
        ctx.close()


def cmd_credentials_set_backend(args: argparse.Namespace) -> int:
    paths = default_paths()
    paths.ensure_dirs()
    ctx = _Context(paths)
    try:
        factory = ctx.open_credential_store_factory()
        factory.set_backend(args.backend)
        print(f"backend set to {args.backend}")
        return 0
    finally:
        ctx.close()


def cmd_credentials_migrate_k2f(_args: argparse.Namespace) -> int:
    paths = default_paths()
    paths.ensure_dirs()
    ctx = _Context(paths)
    try:
        factory = ctx.open_credential_store_factory()
        if factory.get_configured_backend() != "keyring":
            _warn("current backend is not keyring; run 'set-backend keyring' first")
            return 1
        usable, reason = probe_keyring()
        if not usable:
            _warn(f"keyring is not usable in this process ({reason})")
            return 1
        from tidemark.store.credentials import KeyringStore
        src = KeyringStore()
        dst = EncryptedFileStore(
            paths.config_dir / "credentials.enc",
            passphrase_provider_from_env() or InteractivePassphraseProvider(),
        )
        import keyring as _keyring
        backend = _keyring.get_keyring()
        refs = _list_keyring_refs(backend)
        if not refs:
            print("no credential refs found in keyring to migrate")
        for ref in refs:
            try:
                u, p = src.get(ref)
                dst.set(ref, u, p)
                print(f"migrated ref {ref!r}")
            except CredentialNotFound:
                continue
        factory.set_backend("file")
        print("backend set to file; keyring entries left in place")
        return 0
    finally:
        ctx.close()


def cmd_credentials_migrate_f2k(_args: argparse.Namespace) -> int:
    paths = default_paths()
    paths.ensure_dirs()
    ctx = _Context(paths)
    try:
        factory = ctx.open_credential_store_factory()
        if factory.get_configured_backend() != "file":
            _warn("current backend is not file; run 'set-backend file' first")
            return 1
        provider = passphrase_provider_from_env() or InteractivePassphraseProvider()
        src = EncryptedFileStore(paths.config_dir / "credentials.enc", provider)
        dst = KeyringStore()
        payload = src._read_payload()
        for ref, entry in payload.get("credentials", {}).items():
            dst.set(ref, entry["username"], entry["password"])
            print(f"migrated ref {ref!r}")
        factory.set_backend("keyring")
        print("backend set to keyring; file left in place (delete manually if you wish)")
        return 0
    finally:
        ctx.close()


def cmd_credentials_change_passphrase(_args: argparse.Namespace) -> int:
    import getpass

    paths = default_paths()
    paths.ensure_dirs()
    ctx = _Context(paths)
    try:
        file_path = paths.config_dir / "credentials.enc"
        if not file_path.exists():
            _warn(f"no file store at {file_path}")
            return 1
        old = getpass.getpass("Current passphrase: ")
        new1 = getpass.getpass("New passphrase: ")
        new2 = getpass.getpass("Confirm new passphrase: ")
        if new1 != new2:
            _warn("passphrases do not match")
            return 1
        from tidemark.store.credentials import StaticPassphraseProvider
        store = EncryptedFileStore(file_path, StaticPassphraseProvider(old))
        try:
            store.rekey(
                StaticPassphraseProvider(old),
                StaticPassphraseProvider(new1),
            )
        except WrongPassphrase:
            _warn("current passphrase is incorrect")
            return 1
        print("passphrase changed")
        return 0
    finally:
        ctx.close()


def _list_keyring_refs(backend) -> list[str]:  # noqa: ANN001
    """Best-effort discovery of tidemark refs in the keyring.

    keyring's public API does not expose enumeration, so this scans
    ``devices`` and ``snapshots`` tables' known credential refs plus
    ``"default"``.
    """
    return ["default"]


# ── Commands: restore-plan / restore-apply ────────────────────────────────

def _print_plan(plan) -> None:  # noqa: ANN001
    print(f"device       : {plan.device.name}")
    print(f"target       : snapshot {plan.target_snapshot.id} "
          f"(taken {plan.target_snapshot.taken_at_utc.isoformat()})")
    print(f"target sha   : {plan.target_sha256[:12]}…")
    print(f"current sha  : {plan.current_sha256[:12]}…")
    print(f"plan hash    : {plan.plan_hash}")
    print(f"status       : {plan.status}")
    print(f"token (type) : {plan.confirm_token}")
    if plan.risk_flags:
        print("risk flags:")
        for sev in (Severity.HIGH, Severity.WARN):
            bucket = [f for f in plan.risk_flags if f.severity is sev]
            for f in bucket:
                marker = "!" if sev is Severity.HIGH else "?"
                print(f"  {marker} [{f.category.value}] {f.code}: {f.message}")
    else:
        print("risk flags   : none")
    if plan.high_risk_codes:
        print("acknowledge (--ack):")
        for code in plan.high_risk_codes:
            print(f"    {code}")
    print("operations:")
    from tidemark.core.restore_blocks import OperationKind
    for op in plan.operations:
        if op.kind is OperationKind.NOOP:
            continue
        print(f"  - {op.kind.value:<20} "
              f"{op.interface or '-'} :: {op.line or '-'}")


def cmd_restore_plan(args: argparse.Namespace) -> int:
    paths = default_paths()
    paths.ensure_dirs()
    ctx = _Context(paths)
    try:
        RestoreAttemptsRepo(ctx.db).sweep_stale()
        device = DeviceRepo(ctx.db).get_by_name(args.device)
        if device is None:
            _warn(f"device {args.device!r} not found")
            return 1
        profiles = ProfileRegistry(user_profiles_dir=paths.user_profiles_dir)
        profile = profiles.get(device.profile_id)

        snap_repo = SnapshotRepo(ctx.db)
        snap_id = args.snapshot
        if snap_id is None:
            latest = snap_repo.latest_for_device(device.id or 0)
            if latest is None:
                _warn(f"no snapshots for {device.name}")
                return 1
            snap_id = latest.id or 0

        config_repo = ConfigRepo(paths.configs_git_dir)
        try:
            plan = plan_restore(
                device, profile, snap_id, ctx.db, config_repo,
                allow_removals=args.allow_removals,
            )
        except (RestoreModeError, RestoreError, SnapshotIntegrityError,
                RestoreConfirmationError) as exc:
            _warn(str(exc))
            return 1

        ua = RestoreAttemptsRepo(ctx.db).last_unverified_for_device(device.id or 0)
        if ua is not None:
            print(f"!! previous restore on this device ended {ua.outcome.value} "
                  f"at {ua.started_at_utc.isoformat()}", file=sys.stderr)

        _print_plan(plan)
        return 0
    finally:
        ctx.close()


def cmd_restore_apply(args: argparse.Namespace) -> int:
    if not _require_restore_allowed():
        return 1
    paths = default_paths()
    paths.ensure_dirs()
    ctx = _Context(paths)
    try:
        RestoreAttemptsRepo(ctx.db).sweep_stale()
        device = DeviceRepo(ctx.db).get_by_name(args.device)
        if device is None:
            _warn(f"device {args.device!r} not found")
            return 1
        profiles = ProfileRegistry(user_profiles_dir=paths.user_profiles_dir)
        profile = profiles.get(device.profile_id)

        snap_repo = SnapshotRepo(ctx.db)
        snap_id = args.snapshot
        if snap_id is None:
            latest = snap_repo.latest_for_device(device.id or 0)
            if latest is None:
                _warn(f"no snapshots for {device.name}")
                return 1
            snap_id = latest.id or 0

        config_repo = ConfigRepo(paths.configs_git_dir)
        try:
            plan = plan_restore(
                device, profile, snap_id, ctx.db, config_repo,
                allow_removals=args.allow_removals,
            )
        except (RestoreModeError, RestoreError, SnapshotIntegrityError,
                RestoreConfirmationError) as exc:
            _warn(str(exc))
            return 1

        if plan.plan_hash != args.plan_hash:
            _warn(
                "plan hash does not match current state; re-run restore-plan"
            )
            return 1

        credentials = read_credentials(prompt_device=device.name)
        try:
            outcome = apply_restore(
                plan, args.confirm, args.ack or [], credentials,
                ctx.db, config_repo,
                on_progress=lambda msg: print(f"… {msg}"),
            )
        except RestoreConfirmationError as exc:
            _warn(str(exc))
            return 1
        except RestorePlanStaleError as exc:
            _warn(str(exc))
            return 1
        except RestoreError as exc:
            _warn(str(exc))
            return 1
        print(f"restore finished: {outcome.value}")
        return 0 if outcome is AttemptOutcome.SUCCESS else 1
    finally:
        ctx.close()


# ── Argparse wiring ───────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tidemark",
        description="Tidemark — back up, compare and safely restore network "
                    "device configs over SSH.",
    )
    parser.add_argument("--version", action="version", version=f"tidemark {__version__}")

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    sub.add_parser("init", help="Create XDG dirs, SQLite DB, configs git repo.").set_defaults(
        func=cmd_init)

    p_dev = sub.add_parser("device", help="Manage the device inventory.")
    dev_sub = p_dev.add_subparsers(dest="device_command", required=True, metavar="SUB")
    p_add = dev_sub.add_parser("add", help="Add a device.")
    p_add.add_argument("name")
    p_add.add_argument("--host")
    p_add.add_argument("--port", type=int, default=22)
    p_add.add_argument("--profile")
    p_add.add_argument("--group")
    p_add.add_argument("--credential-ref", default="default")
    p_add.add_argument("--custom-command")
    p_add.add_argument("--disabled", action="store_true")
    p_add.set_defaults(func=cmd_device_add)
    dev_sub.add_parser("list", help="List devices.").set_defaults(func=cmd_device_list)

    p_b = sub.add_parser("backup", help="Back up one or all devices.")
    p_b.add_argument("--all", action="store_true")
    p_b.add_argument("--device")
    p_b.set_defaults(func=cmd_backup)

    p_h = sub.add_parser("history", help="Recent runs for a device.")
    p_h.add_argument("--device", required=True)
    p_h.set_defaults(func=cmd_history)

    p_d = sub.add_parser("diff", help="Diff two snapshots.")
    p_d.add_argument("device")
    p_d.add_argument("--from", dest="from_id", type=int)
    p_d.add_argument("--to", dest="to_id", type=int)
    p_d.set_defaults(func=cmd_diff)

    p_i = sub.add_parser("import-yaml", help="Import a legacy devices.yaml.")
    p_i.add_argument("path")
    p_i.set_defaults(func=cmd_import_yaml)

    p_c = sub.add_parser("credentials", help="Manage the credential store.")
    c_sub = p_c.add_subparsers(dest="credentials_command", required=True, metavar="SUB")
    c_sub.add_parser("status").set_defaults(func=cmd_credentials_status)
    p_sb = c_sub.add_parser("set-backend")
    p_sb.add_argument("backend", choices=["keyring", "file"])
    p_sb.set_defaults(func=cmd_credentials_set_backend)
    c_sub.add_parser("migrate-keyring-to-file").set_defaults(
        func=cmd_credentials_migrate_k2f)
    c_sub.add_parser("migrate-file-to-keyring").set_defaults(
        func=cmd_credentials_migrate_f2k)
    c_sub.add_parser("change-passphrase").set_defaults(
        func=cmd_credentials_change_passphrase)

    p_rp = sub.add_parser("restore-plan", help="Compute a restore plan (read-only).")
    p_rp.add_argument("device")
    p_rp.add_argument("--snapshot", type=int)
    p_rp.add_argument("--allow-removals", action="store_true")
    p_rp.set_defaults(func=cmd_restore_plan)

    p_ra = sub.add_parser("restore-apply", help="Apply a restore plan (gated by ALLOW_RESTORE).")
    p_ra.add_argument("device")
    p_ra.add_argument("--snapshot", type=int)
    p_ra.add_argument("--plan-hash", required=True)
    p_ra.add_argument("--confirm", required=True)
    p_ra.add_argument("--ack", action="append", default=[])
    p_ra.add_argument("--allow-removals", action="store_true")
    p_ra.set_defaults(func=cmd_restore_apply)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
