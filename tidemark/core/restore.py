"""
tidemark.core.restore
─────────────────────
Plan and apply a restore.

Flow:

1. ``plan_restore()`` reads the target snapshot from the git object at its
   ``commit_sha`` and verifies its sha256 against the ``snapshots`` row.
   Reads the current config from the running-config file in the git repo.
   Builds ``operations``, ``expected_post_text``, ``risk_flags`` and
   ``plan_hash``.

2. ``apply_restore()`` takes a plan and the token the user typed. It:
   - Refuses if the profile's ``restore`` is ``none`` or ``file_import``.
   - Refuses if the target snapshot is a pre-restore.
   - Refuses if the target snapshot is redacted (M3.1).
   - Refuses if ``plan_hash`` does not match the current state (recompute).
   - Refuses if the typed token does not equal ``plan.confirm_token``.
   - Refuses if the list of acknowledged high-risk flag codes does not
     equal ``plan.high_risk_codes``.
   - Writes a ``pending`` row to ``restore_attempts``.
   - Captures a pre-restore snapshot (via ``ConfigRepo.store_pre_restore``).
   - Sends the commands to the device (open SSH).
   - Re-fetches the config, normalises it, and compares against
     ``expected_post_text``. **Only then** saves (``write memory``).
   - Records the outcome: ``success``, ``failed`` or ``unverified``.
   - Never retries automatically after a partial restore.

The pre-restore snapshot is the safety net: because we do not save until
verification passes, a device that fails to verify can be reloaded into its
previous startup-config with no data loss.

M3.1 additions:
- ``plan_restore`` refuses three ways:
    (a) the target snapshot has ``is_redacted=True``;
    (b) the target content contains the redaction marker;
    (c) ``store_raw`` is currently false (pre-restore snapshot would be
        redacted and useless for recovery).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from netmiko import ConnectHandler

from tidemark.core.credentials import Credentials
from tidemark.core.models import Device, RestoreMode, Snapshot, VendorProfile
from tidemark.core.normalise import normalise
from tidemark.core.redact import REDACTED_MARKER, contains_redaction_marker
from tidemark.core.restore_blocks import (
    OperationKind,
    build_expected_post,
    plan_operations,
    render_commands,
)
from tidemark.core.restore_risk_ios import (
    Category,
    RiskFlag,
    Severity,
)
from tidemark.core.restore_risk_ios import (
    evaluate as evaluate_ios,
)
from tidemark.store.db import Database
from tidemark.store.git_repo import ConfigRepo
from tidemark.store.repositories import SettingsRepo, SnapshotRepo
from tidemark.store.restore_attempts import (
    AttemptOutcome,
    RestoreAttemptsRepo,
)

logger = logging.getLogger(__name__)


# ── Exceptions ──────────────────────────────────────────────────────────────

class RestoreError(RuntimeError):
    """Base class."""


class RestoreModeError(RestoreError):
    """Raised when the profile does not support restore."""


class RestoreConfirmationError(RestoreError):
    """Raised when the typed token or ack list does not match the plan."""


class RestorePlanStaleError(RestoreError):
    """Raised when the plan's hash no longer matches current state."""


class SnapshotIntegrityError(RestoreError):
    """Raised when the snapshot content does not hash to the stored sha256."""


class PreRestoreSnapshotError(RestoreError):
    """Raised when the pre-restore snapshot cannot be written."""


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class RestorePlan:
    device: Device
    profile: VendorProfile
    target_snapshot: Snapshot
    target_text: str
    current_text: str
    current_sha256: str
    target_sha256: str
    operations: list
    expected_post_text: str
    risk_flags: list[RiskFlag]
    lines_skipped: list[str]
    needs_manual_review: list[str]
    allow_removals: bool
    plan_hash: str
    status: str  # "ready" | "no_changes"
    confirm_token: str = field(default="")

    @property
    def high_risk_codes(self) -> list[str]:
        return sorted(f.code for f in self.risk_flags if f.severity is Severity.HIGH)


# ── Plan ───────────────────────────────────────────────────────────────────

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _compute_plan_hash(
    device_id: int,
    target_snapshot_id: int,
    current_sha256: str,
    target_sha256: str,
    flag_codes: list[str],
) -> str:
    payload = (
        f"{device_id}|{target_snapshot_id}|{current_sha256}|"
        f"{target_sha256}|{','.join(sorted(flag_codes))}"
    )
    return _sha256(payload)


def _read_target_text(
    config_repo: ConfigRepo, snapshot: Snapshot
) -> str:
    """Read target text from the git object at ``snapshot.commit_sha``."""
    commit_sha = getattr(snapshot, "commit_sha", None)
    if not commit_sha:
        from pathlib import Path
        return Path(snapshot.path).read_text(encoding="utf-8")
    rel = f"pre_restore/{_relative_from_path(snapshot.path, config_repo.root)}" \
        if "/pre_restore/" in snapshot.path.replace("\\", "/") else None
    if rel is None:
        rel = f"{_device_dir_of(snapshot)}/running.cfg"
    text = config_repo.read_at(commit_sha, rel)
    actual = _sha256(text.rstrip("\n"))
    if actual != snapshot.sha256:
        raise SnapshotIntegrityError(
            f"snapshot {snapshot.id} content hashes to {actual[:12]}…, "
            f"expected {snapshot.sha256[:12]}…"
        )
    return text


def _device_dir_of(snapshot: Snapshot) -> str:
    from pathlib import Path
    p = Path(snapshot.path)
    parts = p.parts
    for i, part in enumerate(parts):
        if part == "configs" and i + 1 < len(parts):
            return parts[i + 1]
    return p.parent.name


def _relative_from_path(path: str, root) -> str:  # noqa: ANN001
    from pathlib import Path
    p = Path(path).resolve()
    try:
        return str(p.relative_to(Path(root).resolve()))
    except ValueError:
        return Path(path).name


def plan_restore(
    device: Device,
    profile: VendorProfile,
    target_snapshot_id: int,
    db: Database,
    config_repo: ConfigRepo,
    *,
    allow_removals: bool = False,
    now: datetime | None = None,
) -> RestorePlan:
    """Compute a restore plan for ``device`` targeting ``target_snapshot_id``."""
    if profile.restore is RestoreMode.NONE:
        raise RestoreModeError(
            f"profile {profile.id!r} has restore=none; restore is not supported"
        )
    if profile.restore is RestoreMode.FILE_IMPORT:
        raise RestoreModeError(
            f"profile {profile.id!r} has restore=file_import; "
            f"file-import restore is not implemented in M2"
        )

    snap_repo = SnapshotRepo(db)
    target = snap_repo.get_by_id(target_snapshot_id)
    if target is None:
        raise RestoreError(f"snapshot {target_snapshot_id} not found")
    if target.device_id != device.id:
        raise RestoreError(
            f"snapshot {target_snapshot_id} belongs to a different device"
        )
    if target.kind == "pre_restore":
        raise RestoreConfirmationError(
            "pre-restore snapshots cannot be used as restore targets"
        )

    # M3.1 refusal (a): snapshot was stored with redaction enabled.
    if getattr(target, "is_redacted", False):
        raise RestoreModeError(
            f"snapshot {target.id} was stored with redaction "
            f"(store_raw=false); it contains placeholders and cannot be "
            f"restored. Restores are only available from snapshots stored "
            f"with store_raw=true."
        )

    target_text = _read_target_text(config_repo, target)

    # M3.1 refusal (b): defence in depth, catch pre-v3 rows whose
    # is_redacted column defaults to 0 but whose content is redacted.
    if contains_redaction_marker(target_text):
        raise RestoreModeError(
            f"snapshot {target.id} content contains {REDACTED_MARKER!r}; "
            f"restoring it would set real secrets to the placeholder text."
        )

    # M3.1 refusal (c): store_raw is off, so the pre-restore snapshot
    # we would capture would be redacted and useless for recovery.
    store_raw_now = (
        SettingsRepo(db).get("store_raw") or "true"
    ).lower() == "true"
    if not store_raw_now:
        raise RestoreModeError(
            "restore is disabled while store_raw=false: the pre-restore "
            "snapshot would be redacted and useless for recovery."
        )

    target_norm = normalise(target_text, profile.volatile_patterns)

    current_raw = config_repo.current_content(device.name) or ""
    current_norm = normalise(current_raw, profile.volatile_patterns)

    build = plan_operations(
        current_norm.text, target_norm.text, allow_removals=allow_removals,
    )
    expected_post = build_expected_post(current_norm.text, build.operations)

    diff_count = sum(
        1 for op in build.operations if op.kind is not OperationKind.NOOP
    )

    now_utc = now or datetime.now(UTC)
    target_age = (now_utc - target.taken_at_utc).total_seconds() / 86400.0

    flags = evaluate_ios(
        device_host=device.host,
        current_text=current_norm.text,
        target_text=target_norm.text,
        operations=build.operations,
        lines_skipped=build.lines_skipped,
        needs_manual_review=build.needs_manual_review,
        target_age_days=target_age,
        target_is_pre_restore=False,
        diff_line_count=diff_count,
    )

    status = "no_changes" if not build.operations else "ready"
    if status == "no_changes":
        flags.append(RiskFlag(
            "diff_empty", Severity.WARN, Category.OTHER,
            "no changes needed; restore is a no-op",
        ))

    plan_hash = _compute_plan_hash(
        device.id or 0,
        target.id or 0,
        current_norm.sha256,
        target_norm.sha256,
        [f.code for f in flags],
    )

    token = f"{device.name}@{target.id}"
    if allow_removals:
        token += "+rm"

    return RestorePlan(
        device=device,
        profile=profile,
        target_snapshot=target,
        target_text=target_norm.text,
        current_text=current_norm.text,
        current_sha256=current_norm.sha256,
        target_sha256=target_norm.sha256,
        operations=build.operations,
        expected_post_text=expected_post,
        risk_flags=flags,
        lines_skipped=build.lines_skipped,
        needs_manual_review=build.needs_manual_review,
        allow_removals=allow_removals,
        plan_hash=plan_hash,
        status=status,
        confirm_token=token,
    )


# ── Apply ──────────────────────────────────────────────────────────────────

def apply_restore(
    plan: RestorePlan,
    typed_token: str,
    acknowledged_high_risks: list[str],
    credentials: Credentials,
    db: Database,
    config_repo: ConfigRepo,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> AttemptOutcome:
    """Apply the plan. See module docstring for the full flow."""

    def _notify(msg: str) -> None:
        if on_progress is not None:
            on_progress(msg)

    # 1. Confirmation checks.
    if plan.confirm_token != typed_token:
        raise RestoreConfirmationError(
            f"confirmation did not match; expected format "
            f"{plan.device.name}@{plan.target_snapshot.id}"
            + ("+rm" if plan.allow_removals else "")
        )
    if sorted(acknowledged_high_risks) != plan.high_risk_codes:
        raise RestoreConfirmationError(
            f"acknowledged high-risk codes {sorted(acknowledged_high_risks)!r} "
            f"do not equal plan's high-risk codes {plan.high_risk_codes!r}"
        )

    if plan.status == "no_changes":
        _notify("no changes to apply")
        return AttemptOutcome.SUCCESS

    # 2. Staleness check — recompute plan_hash from current state.
    current_now = normalise(
        config_repo.current_content(plan.device.name) or "",
        plan.profile.volatile_patterns,
    )
    recomputed = _compute_plan_hash(
        plan.device.id or 0,
        plan.target_snapshot.id or 0,
        current_now.sha256,
        plan.target_sha256,
        [f.code for f in plan.risk_flags],
    )
    if recomputed != plan.plan_hash:
        raise RestorePlanStaleError(
            "device configuration changed since the plan was made; "
            "re-run restore-plan"
        )

    # 3. Pre-restore snapshot FIRST. Refuse to touch the device if it fails.
    attempt_repo = RestoreAttemptsRepo(db)
    import getpass
    attempt = attempt_repo.begin(
        plan.device.id or 0,
        plan.target_snapshot.id,
        getpass.getuser(),
        plan.plan_hash,
    )

    try:
        _notify("writing pre-restore snapshot")
        pre_sha = current_now.sha256
        config_repo.store_pre_restore(
            plan.device.name, current_now.text, pre_sha, datetime.now(UTC),
        )
    except Exception as exc:  # noqa: BLE001
        attempt_repo.finish(attempt.id or 0, AttemptOutcome.FAILED,
                            notes=f"pre-restore snapshot failed: {exc}")
        raise PreRestoreSnapshotError(
            f"could not write pre-restore snapshot: {exc}"
        ) from exc

    # 4. Build commands from the plan's operations (single source of truth).
    commands = render_commands(plan.operations)

    # 5. Connect and send.
    kwargs = {
        "device_type": plan.profile.netmiko_device_type,
        "host": plan.device.host,
        "port": plan.device.port,
        "username": credentials.username,
        "password": credentials.password,
        "conn_timeout": 20,
    }
    if plan.profile.requires_enable:
        kwargs["secret"] = credentials.password

    conn = None
    try:
        _notify("connecting to device")
        conn = ConnectHandler(**kwargs)
        if plan.profile.requires_enable:
            conn.enable()

        _notify("sending commands")
        conn.send_command("configure terminal", expect_string=r"#")
        for cmd in commands:
            conn.send_command(cmd, expect_string=r"[#>]", read_timeout=30)
        conn.send_command("end", expect_string=r"#")
    except Exception as exc:  # noqa: BLE001
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:
                pass
        attempt_repo.finish(attempt.id or 0, AttemptOutcome.UNVERIFIED,
                            notes=f"command send failed: {exc}")
        raise RestoreError(f"failed to send commands: {exc}") from exc

    # 6. Re-fetch and verify BEFORE saving.
    try:
        _notify("verifying")
        refetched = conn.send_command("show running-config", read_timeout=60)
    except Exception as exc:  # noqa: BLE001
        try:
            conn.disconnect()
        except Exception:
            pass
        attempt_repo.finish(attempt.id or 0, AttemptOutcome.UNVERIFIED,
                            notes=f"re-fetch failed: {exc}")
        raise RestoreError(
            "device is unreachable after applying commands. "
            "Reload the device to roll back to the pre-restore "
            "startup-config. Attempt recorded as unverified."
        ) from exc

    refetch_norm = normalise(refetched, plan.profile.volatile_patterns)
    expected_norm = normalise(plan.expected_post_text, plan.profile.volatile_patterns)

    if refetch_norm.text != expected_norm.text:
        try:
            conn.disconnect()
        except Exception:
            pass
        attempt_repo.finish(attempt.id or 0, AttemptOutcome.UNVERIFIED,
                            notes="post-restore config does not match expectation")
        raise RestoreError(
            "post-restore configuration does not match the plan's expected "
            "state. The running-config has NOT been saved. Reload the "
            "device to roll back, or inspect the diff manually."
        )

    # 7. Save.
    try:
        _notify("saving startup-config")
        conn.send_command("write memory", expect_string=r"[#>]", read_timeout=60)
    except Exception as exc:  # noqa: BLE001
        try:
            conn.disconnect()
        except Exception:
            pass
        attempt_repo.finish(attempt.id or 0, AttemptOutcome.UNVERIFIED,
                            notes=f"write memory failed: {exc}")
        raise RestoreError(f"verification passed but save failed: {exc}") from exc

    try:
        conn.disconnect()
    except Exception:
        pass

    attempt_repo.finish(attempt.id or 0, AttemptOutcome.SUCCESS)
    _notify("restore verified and saved")
    return AttemptOutcome.SUCCESS
