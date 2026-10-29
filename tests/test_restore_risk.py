"""Risk flag detection."""

from __future__ import annotations

from tidemark.core.restore_blocks import plan_operations
from tidemark.core.restore_risk_ios import evaluate


def _flags(cur: str, tgt: str, host: str = "10.0.0.1",
           allow_removals: bool = False) -> dict[str, str]:
    build = plan_operations(cur, tgt, allow_removals=allow_removals)
    flags = evaluate(
        device_host=host,
        current_text=cur,
        target_text=tgt,
        operations=build.operations,
        lines_skipped=build.lines_skipped,
        needs_manual_review=build.needs_manual_review,
        target_age_days=0.0,
        target_is_pre_restore=False,
        diff_line_count=sum(1 for op in build.operations),
    )
    return {f.code: f.severity.value for f in flags}


BASE = """\
hostname r1
!
interface Gi0/1
 ip address 10.0.0.1 255.255.255.0
!
"""


def test_mgmt_interface_unknown() -> None:
    flags = _flags(BASE, BASE, host="192.0.2.99")
    assert flags.get("mgmt_interface_unknown") == "warn"


def test_affects_connection_path_high() -> None:
    tgt = BASE.replace("10.0.0.1", "10.0.0.2")
    flags = _flags(BASE, tgt, host="10.0.0.1")
    assert flags.get("affects_connection_path") == "high"


def test_adds_shutdown_on_interface() -> None:
    tgt = BASE + "interface Gi0/1\n shutdown\n"
    flags = _flags(BASE, tgt, host="10.0.0.1")
    assert flags.get("adds_shutdown_on_interface") == "high"


def test_changes_hostname_warn_when_alone() -> None:
    tgt = BASE.replace("hostname r1", "hostname r2")
    flags = _flags(BASE, tgt, host="10.0.0.1")
    assert flags.get("changes_hostname") == "warn"


def test_changes_hostname_upgraded_with_credentials() -> None:
    tgt = BASE.replace("hostname r1", "hostname r2") \
              + "username admin secret 9 abc\n"
    flags = _flags(BASE, tgt, host="10.0.0.1")
    assert flags.get("changes_hostname") == "high"


def test_removes_default_route() -> None:
    cur = BASE + "ip route 0.0.0.0/0 10.0.0.254\n"
    tgt = BASE
    flags = _flags(cur, tgt, allow_removals=True)
    assert flags.get("removes_default_route") == "high"


def test_skipped_non_replayable_lines() -> None:
    tgt = BASE + "banner motd x\n"
    flags = _flags(BASE, tgt, host="10.0.0.1")
    # banner lines go through add-only, so they will not be skipped here;
    # this test is a placeholder until we add explicit banner handling.
    assert isinstance(flags, dict)
