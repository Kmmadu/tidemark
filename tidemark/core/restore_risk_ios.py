"""
tidemark.core.restore_risk_ios
──────────────────────────────
IOS-specific risk flags for a restore plan.

Each flag has a stable ``code`` and a ``category`` that the CLI and (M3)
GUI use for grouping:

    connection  — changes that can break your ability to reach the device
    identity    — hostname, enable secret, AAA, local users
    routing     — routing processes, management VLANs
    security    — ACLs, crypto/PKI
    other       — NTP, logging, SNMP, size, age

Severity is ``warn`` or ``high``. ``apply_restore`` refuses when the user
has not acknowledged every ``high`` flag by name.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from enum import StrEnum


class Category(StrEnum):
    CONNECTION = "connection"
    IDENTITY = "identity"
    ROUTING = "routing"
    SECURITY = "security"
    OTHER = "other"


class Severity(StrEnum):
    WARN = "warn"
    HIGH = "high"


@dataclass(frozen=True)
class RiskFlag:
    code: str
    severity: Severity
    category: Category
    message: str


# ── Matchers ────────────────────────────────────────────────────────────────

_RE_IFACE = re.compile(r"^interface (\S+)")
_RE_IP = re.compile(r"^\s*ip address (\d+\.\d+\.\d+\.\d+) (\d+\.\d+\.\d+\.\d+)")
_RE_SHUT = re.compile(r"^\s*shutdown\s*$")
_RE_VTY = re.compile(r"^line vty\b")
_RE_TRANSPORT = re.compile(r"^\s*transport input (\S+)")
_RE_AAA = re.compile(r"^(aaa |login authentication )")
_RE_ROUTE_DEFAULT = re.compile(r"^(ip route 0\.0\.0\.0/0 |ip default-gateway )")
_RE_ROUTE_ANY = re.compile(r"^ip route ")
_RE_ROUTING_PROC = re.compile(r"^router (ospf|bgp|eigrp|rip|isis)\b")
_RE_LOCAL_USER = re.compile(r"^username \S+ (secret|password) ")
_RE_ENABLE = re.compile(r"^enable (secret|password) ")
_RE_SNMP = re.compile(r"^snmp-server (community|host) ")
_RE_NTP = re.compile(r"^ntp server ")
_RE_LOG = re.compile(r"^logging (host |trap |\d)")
_RE_PKI = re.compile(r"^crypto pki ")
_RE_HOSTNAME = re.compile(r"^hostname (\S+)$")


# ── Public entry point ─────────────────────────────────────────────────────

def evaluate(
    *,
    device_host: str,
    current_text: str,
    target_text: str,
    operations,  # list[RestoreOperation] — avoid import cycle
    lines_skipped: list[str],
    needs_manual_review: list[str],
    target_age_days: float | None,
    target_is_pre_restore: bool,
    diff_line_count: int,
) -> list[RiskFlag]:
    flags: list[RiskFlag] = []
    current_ifaces = _iface_map(current_text)
    target_ifaces = _iface_map(target_text)

    # affects_connection_path: any change to the interface holding device_host.
    mgmt_iface = _find_mgmt_iface(current_text, device_host)
    if mgmt_iface is None:
        flags.append(RiskFlag(
            "mgmt_interface_unknown", Severity.WARN, Category.CONNECTION,
            f"no interface in current config holds the address {device_host!r}",
        ))
    else:
        cur = current_ifaces.get(mgmt_iface, [])
        tgt = target_ifaces.get(mgmt_iface, [])
        if cur != tgt:
            flags.append(RiskFlag(
                "affects_connection_path", Severity.HIGH, Category.CONNECTION,
                f"plan modifies interface {mgmt_iface!r} which holds {device_host!r}",
            ))

    # adds_shutdown_on_interface
    for name, lines in target_ifaces.items():
        if any(_RE_SHUT.match(line) for line in lines):
            if name not in current_ifaces or not any(
                _RE_SHUT.match(line) for line in current_ifaces.get(name, [])
            ):
                flags.append(RiskFlag(
                    "adds_shutdown_on_interface", Severity.HIGH, Category.CONNECTION,
                    f"interface {name!r} is shut down in target",
                ))

    # changes_hostname -> warn; upgrade to high if identity also changes.
    cur_host = _hostname(current_text)
    tgt_host = _hostname(target_text)
    hostname_changed = cur_host and tgt_host and cur_host != tgt_host
    aaa_changed = _any_line_change(operations, _RE_AAA)
    localuser_changed = _any_line_change(operations, _RE_LOCAL_USER)
    enable_changed = _any_line_change(operations, _RE_ENABLE)
    if hostname_changed:
        coupled = aaa_changed or localuser_changed or enable_changed
        flags.append(RiskFlag(
            "changes_hostname",
            Severity.HIGH if coupled else Severity.WARN,
            Category.IDENTITY,
            f"hostname {cur_host!r} -> {tgt_host!r}"
            + (" (also changes credentials/AAA)" if coupled else ""),
        ))

    if aaa_changed:
        flags.append(RiskFlag(
            "changes_aaa", Severity.HIGH, Category.IDENTITY,
            "plan changes AAA or login authentication",
        ))
    if localuser_changed:
        flags.append(RiskFlag(
            "removes_local_user", Severity.HIGH, Category.IDENTITY,
            "plan changes a local username password/secret",
        ))
    if enable_changed:
        flags.append(RiskFlag(
            "changes_enable_secret", Severity.HIGH, Category.IDENTITY,
            "plan changes the enable secret",
        ))

    # removes_default_route (includes ip default-gateway)
    if _any_line_removed(operations, _RE_ROUTE_DEFAULT) or _line_differs(
        current_text, target_text, _RE_ROUTE_DEFAULT
    ):
        flags.append(RiskFlag(
            "removes_default_route", Severity.HIGH, Category.ROUTING,
            "plan removes or changes the default route / default gateway",
        ))

    if _any_line_removed(operations, _RE_ROUTING_PROC):
        flags.append(RiskFlag(
            "removes_routing_process", Severity.HIGH, Category.ROUTING,
            "plan removes a routing process",
        ))

    if _any_line_removed(operations, re.compile(r"^(no )?vlan \d+$")) or _vlan_mgmt_removed(
        current_text, target_text
    ):
        flags.append(RiskFlag(
            "removes_mgmt_vlan", Severity.HIGH, Category.ROUTING,
            "plan removes the management VLAN or its SVI",
        ))

    if _any_line_removed(operations, re.compile(r"^access-class \d+ in")):
        flags.append(RiskFlag(
            "changes_vty_acl", Severity.HIGH, Category.SECURITY,
            "plan changes the VTY access-class",
        ))
    if _any_line_change(operations, _RE_TRANSPORT):
        flags.append(RiskFlag(
            "changes_vty_transport", Severity.HIGH, Category.SECURITY,
            "plan changes VTY transport input",
        ))

    if _any_line_removed(operations, _RE_PKI):
        flags.append(RiskFlag(
            "removes_pki_trustpoint", Severity.HIGH, Category.SECURITY,
            "plan removes a PKI trustpoint",
        ))

    if _any_line_removed(operations, _RE_SNMP):
        flags.append(RiskFlag(
            "removes_snmp_community", Severity.WARN, Category.OTHER,
            "plan removes SNMP community or host configuration",
        ))
    if _any_line_removed(operations, _RE_NTP):
        flags.append(RiskFlag(
            "removes_ntp_servers", Severity.WARN, Category.OTHER,
            "plan removes one or more NTP servers",
        ))
    if _any_line_removed(operations, _RE_LOG):
        flags.append(RiskFlag(
            "removes_logging_targets", Severity.WARN, Category.OTHER,
            "plan removes logging destinations",
        ))

    if lines_skipped:
        flags.append(RiskFlag(
            "skipped_non_replayable_lines", Severity.WARN, Category.OTHER,
            f"{len(lines_skipped)} line(s) cannot be replayed line-by-line "
            f"(banners, certificates, !-markers)",
        ))

    if needs_manual_review:
        flags.append(RiskFlag(
            "needs_manual_review", Severity.WARN, Category.OTHER,
            f"{len(needs_manual_review)} line(s) will be added without "
            f"removing the previous form; review the diff",
        ))

    if diff_line_count > 200:
        flags.append(RiskFlag(
            "large_diff", Severity.WARN, Category.OTHER,
            f"{diff_line_count} changed lines",
        ))

    if target_is_pre_restore:
        flags.append(RiskFlag(
            "target_snapshot_is_pre_restore", Severity.HIGH, Category.OTHER,
            "target snapshot is a pre-restore snapshot; not a valid restore source",
        ))
    if target_age_days is not None and target_age_days > 7:
        flags.append(RiskFlag(
            "target_snapshot_older_than_7_days", Severity.WARN, Category.OTHER,
            f"target snapshot is {target_age_days:.1f} days old",
        ))

    return _sort(flags)


# ── Helpers ────────────────────────────────────────────────────────────────

def _iface_map(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("interface "):
            current = line[len("interface "):].strip()
            out.setdefault(current, [])
        elif line.startswith(" "):
            if current is not None:
                out[current].append(line.strip())
        else:
            current = None
    return out


def _find_mgmt_iface(text: str, host: str) -> str | None:
    try:
        target = ipaddress.ip_address(host)
    except ValueError:
        return None
    for name, lines in _iface_map(text).items():
        for line in lines:
            m = _RE_IP.match(line)
            if m and m.group(1) == str(target):
                return name
    return None


def _hostname(text: str) -> str | None:
    for line in text.splitlines():
        m = _RE_HOSTNAME.match(line)
        if m:
            return m.group(1)
    return None


def _any_line_change(operations, pattern: re.Pattern[str]) -> bool:  # noqa: ANN001
    from tidemark.core.restore_blocks import OperationKind
    for op in operations:
        if op.kind in (OperationKind.ADD_LINE, OperationKind.OVERWRITE_LINE,
                       OperationKind.REMOVE_LINE, OperationKind.ADD_ONLY_REVIEW):
            if op.line and pattern.match(op.line):
                return True
    return False


def _any_line_removed(operations, pattern: re.Pattern[str]) -> bool:  # noqa: ANN001
    from tidemark.core.restore_blocks import OperationKind
    for op in operations:
        if op.kind is OperationKind.REMOVE_LINE and op.line and pattern.match(op.line):
            return True
    return False


def _line_differs(current: str, target: str, pattern: re.Pattern[str]) -> bool:
    cur = {line for line in current.splitlines() if pattern.match(line)}
    tgt = {line for line in target.splitlines() if pattern.match(line)}
    return cur != tgt


def _vlan_mgmt_removed(current: str, target: str) -> bool:
    cur = {line for line in current.splitlines() if line.startswith("interface Vlan")}
    tgt = {line for line in target.splitlines() if line.startswith("interface Vlan")}
    return bool(cur - tgt)


def _sort(flags: list[RiskFlag]) -> list[RiskFlag]:
    order = {Severity.HIGH: 0, Severity.WARN: 1}
    return sorted(flags, key=lambda f: (order[f.severity], f.code))
