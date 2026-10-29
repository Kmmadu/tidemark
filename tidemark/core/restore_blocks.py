"""
tidemark.core.restore_blocks
────────────────────────────
IOS-only block-aware restore planner.

Takes the *current* normalised config and the *target* normalised config,
and produces a list of ``RestoreOperation`` objects. Also renders those
operations into device commands and builds the expected post-restore config
in memory, so verification compares against a reconstruction of the same
plan that was sent.

The planner is deliberately conservative:

- A line that appears identically in both: sends nothing.
- A line whose command is *single-valued* (curated list) and appears in both
  with a different value: sends the new line only (never ``no <old>`` then
  ``<new>``; the second command would drop the SSH session on the management
  interface).
- A line only in target: sends the line (``AddLine``).
- A line only in current: sends ``no <line>`` ONLY if ``allow_removals=True``
  (``RemoveLine``).
- Any other line that differs: sends the target line and adds a
  ``needs_manual_review`` note. Never removes anything for these lines even
  when ``allow_removals=True``.
- An ordered block (named ACL, route-map, prefix-list) is never deleted and
  recreated in place unless ``allow_removals=True``, and then it raises
  ``ReplaceOrderedBlock`` which the risk layer flags as ``replaces_ordered_block``.
- Removing an entire interface block uses ``default interface X`` for
  physical interfaces and ``no interface X`` for logical interfaces
  (Loopback*, Vlan*, Port-channel*, Tunnel*). ``default interface`` on the
  interface holding the SSH address raises ``affects_connection_path`` at the
  risk layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

# Commands where a change should be expressed as overwrite-in-place, not
# "remove old, add new". Curated; anything not on this list falls into
# AddOnlyReview, never OverwriteLine.
SINGLE_VALUED_PREFIXES: tuple[str, ...] = (
    "ip address ",
    "ipv6 address ",
    "description ",
    "speed ",
    "duplex ",
    "mtu ",
    "switchport mode ",
    "switchport access vlan ",
    "switchport native vlan ",
    "switchport trunk allowed vlan ",
    "ip access-group ",
    "transport input ",
    "access-class ",
)

# Ordered blocks: never delete/recreate in place unless allow_removals.
_ORDERED_OPENERS = (
    re.compile(r"^ip access-list (standard|extended) \S+$"),
    re.compile(r"^route-map \S+( (permit|deny) \d+)?$"),
    re.compile(r"^ip prefix-list \S+ "),
    re.compile(r"^ipv6 access-list \S+$"),
)

_LOGICAL_IFACE_PREFIXES = ("Loopback", "Vlan", "Port-channel", "Tunnel", "Dialer")

# Lines we cannot meaningfully replay line-by-line. Surfaced as
# ``lines_skipped`` in the plan.
_SKIP_LINE_PREFIXES = ("!", "end", "Building configuration", "Current configuration")


class OperationKind(StrEnum):
    NOOP = "noop"
    ADD_LINE = "add_line"
    OVERWRITE_LINE = "overwrite_line"
    REMOVE_LINE = "remove_line"
    ADD_ONLY_REVIEW = "add_only_review"
    DEFAULT_INTERFACE = "default_interface"
    NO_INTERFACE = "no_interface"
    REPLACE_ORDERED_BLOCK = "replace_ordered_block"


@dataclass(frozen=True)
class RestoreOperation:
    kind: OperationKind
    interface: str | None
    line: str | None            # for Add/Overwrite/RemoveLine
    current_line: str | None    # for OverwriteLine (informational)
    reason: str = ""


@dataclass
class Block:
    opener: str | None
    lines: list[str] = field(default_factory=list)


@dataclass
class PlanBuild:
    operations: list[RestoreOperation]
    lines_skipped: list[str]
    needs_manual_review: list[str]


# ── Parsing ─────────────────────────────────────────────────────────────────

def _parse_blocks(text: str) -> list[Block]:
    """Split a normalised IOS config into top-level blocks.

    An interface block is an ``interface <name>`` line plus every indented
    line until the next unindented line. Everything else is a sequence of
    one-line blocks.
    """
    blocks: list[Block] = []
    current_iface: Block | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith(" "):
            if current_iface is not None:
                current_iface.lines.append(line.strip())
            else:
                blocks.append(Block(opener=None, lines=[line.strip()]))
            continue
        # Unindented: start a new block.
        if line.startswith("interface "):
            current_iface = Block(opener=line, lines=[])
            blocks.append(current_iface)
        else:
            current_iface = None
            blocks.append(Block(opener=None, lines=[line]))
    return blocks


def _is_ordered(opener: str | None) -> bool:
    if opener is None:
        return False
    return any(rx.match(opener) for rx in _ORDERED_OPENERS)


def _is_single_valued(line: str) -> bool:
    stripped = line.strip()
    return any(stripped.startswith(p) for p in SINGLE_VALUED_PREFIXES)


def _command_key(line: str) -> str:
    """Return the leading token(s) that identify a single-valued command."""
    stripped = line.strip()
    for p in SINGLE_VALUED_PREFIXES:
        if stripped.startswith(p):
            return p
    return stripped


def _is_logical_iface(name: str) -> bool:
    return name.startswith(_LOGICAL_IFACE_PREFIXES)


# ── Planner ─────────────────────────────────────────────────────────────────

def plan_operations(
    current_text: str,
    target_text: str,
    *,
    allow_removals: bool = False,
) -> PlanBuild:
    """Return the operations that would transform ``current_text`` into
    (a superset of) ``target_text``."""
    current = _parse_blocks(current_text)
    target = _parse_blocks(target_text)

    cur_by_key: dict[str, Block] = {}
    for b in current:
        key = b.opener or (b.lines[0] if b.lines else "")
        cur_by_key[key] = b
    tgt_by_key: dict[str, Block] = {}
    for b in target:
        key = b.opener or (b.lines[0] if b.lines else "")
        tgt_by_key[key] = b

    ops: list[RestoreOperation] = []
    skipped: list[str] = []
    review: list[str] = []

    # Top-level add-only lines: iterate target blocks in order.
    for tgt_key, tgt in tgt_by_key.items():
        cur = cur_by_key.get(tgt_key)
        if cur is None:
            if tgt.opener is not None:
                # New interface block: add opener and its children in order.
                ops.append(RestoreOperation(OperationKind.ADD_LINE, tgt.opener, tgt.opener, None))
                for line in tgt.lines:
                    ops.append(RestoreOperation(OperationKind.ADD_LINE, tgt.opener, line, None))
            else:
                for line in tgt.lines:
                    if _should_skip_line(line):
                        skipped.append(line)
                        continue
                    ops.append(RestoreOperation(OperationKind.ADD_LINE, None, line, None))
            continue

        if _is_ordered(tgt.opener):
            # Ordered block: only touch it if there is a real difference.
            if tgt.lines != cur.lines:
                if allow_removals:
                    ops.append(RestoreOperation(
                        OperationKind.REPLACE_ORDERED_BLOCK, tgt.opener, None, None,
                        reason="ordered block fully replaced",
                    ))
                    for line in tgt.lines:
                        ops.append(RestoreOperation(
                            OperationKind.ADD_LINE, tgt.opener, line, None))
                else:
                    for line in tgt.lines:
                        if line not in cur.lines:
                            ops.append(RestoreOperation(
                                OperationKind.ADD_LINE, tgt.opener, line, None))
                    review.append(f"ordered block '{tgt.opener}' has changes; "
                                  f"re-run with --allow-removals to fully replace")
            continue

        if tgt.opener is None:
            # Single-line top-level block.
            cur_line = cur.lines[0] if cur.lines else ""
            tgt_line = tgt.lines[0] if tgt.lines else ""
            if cur_line == tgt_line:
                continue
            if _is_single_valued(tgt_line) and _is_single_valued(cur_line) \
                    and _command_key(cur_line) == _command_key(tgt_line):
                ops.append(RestoreOperation(
                    OperationKind.OVERWRITE_LINE, None, tgt_line, cur_line))
            elif _is_single_valued(tgt_line) and not _is_single_valued(cur_line):
                ops.append(RestoreOperation(
                    OperationKind.ADD_LINE, None, tgt_line, None))
            else:
                ops.append(RestoreOperation(
                    OperationKind.ADD_ONLY_REVIEW, None, tgt_line, cur_line,
                    reason="non-single-valued line differs; add-only"))
                review.append(f"top-level line '{tgt_line}' differs; add-only")
            continue

        # Interface block, both sides exist.
        for tgt_line in tgt.lines:
            if _should_skip_line(tgt_line):
                skipped.append(tgt_line)
                continue
            if tgt_line in cur.lines:
                continue
            if _is_single_valued(tgt_line):
                matches = [c for c in cur.lines
                           if _is_single_valued(c)
                           and _command_key(c) == _command_key(tgt_line)]
                if matches:
                    ops.append(RestoreOperation(
                        OperationKind.OVERWRITE_LINE, tgt.opener, tgt_line,
                        matches[0]))
                else:
                    ops.append(RestoreOperation(
                        OperationKind.ADD_LINE, tgt.opener, tgt_line, None))
            else:
                ops.append(RestoreOperation(
                    OperationKind.ADD_ONLY_REVIEW, tgt.opener, tgt_line, None,
                    reason="non-single-valued interface line differs; add-only"))
                review.append(f"interface '{tgt.opener}' line '{tgt_line}' "
                              f"differs; add-only")

    # Removals: only if allow_removals.
    if allow_removals:
        for cur_key, cur in cur_by_key.items():
            tgt = tgt_by_key.get(cur_key)
            if tgt is None:
                # Whole block was removed.
                if cur.opener is not None and cur.opener.startswith("interface "):
                    name = cur.opener[len("interface "):].strip()
                    kind = (OperationKind.NO_INTERFACE if _is_logical_iface(name)
                            else OperationKind.DEFAULT_INTERFACE)
                    ops.append(RestoreOperation(kind, cur.opener, cur.opener, None))
                else:
                    for line in cur.lines:
                        if _should_skip_line(line):
                            continue
                        ops.append(RestoreOperation(
                            OperationKind.REMOVE_LINE, None, line, line))
                continue
            # Both exist: lines only in current.
            for cur_line in cur.lines:
                if _should_skip_line(cur_line):
                    continue
                if cur_line in tgt.lines:
                    continue
                if _is_single_valued(cur_line):
                    # The matched target line was already overwritten; no `no`.
                    continue
                ops.append(RestoreOperation(
                    OperationKind.REMOVE_LINE, cur.opener, cur_line, cur_line))

    return PlanBuild(operations=ops, lines_skipped=skipped, needs_manual_review=review)


def _should_skip_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    for p in _SKIP_LINE_PREFIXES:
        if stripped.startswith(p):
            return True
    if stripped.startswith("certificate ") or stripped == "quit":
        return True
    return False


# ── Rendering and expected post ─────────────────────────────────────────────

def render_commands(
    operations: list[RestoreOperation],
    *,
    plan_interface_for: dict[str, str] | None = None,
) -> list[str]:
    """Return the ordered list of commands to send.

    The caller is responsible for entering config mode and saving. This
    function emits exactly the operations, in order.
    """
    commands: list[str] = []
    current_iface: str | None = None
    for op in operations:
        if op.kind is OperationKind.NOOP:
            continue
        if op.kind in (OperationKind.DEFAULT_INTERFACE, OperationKind.NO_INTERFACE):
            commands.append(op.line or "")
            current_iface = None
            continue
        if op.kind is OperationKind.REPLACE_ORDERED_BLOCK:
            commands.append(f"no {op.interface}")  # type: ignore[arg-type]
            commands.append(op.interface or "")    # type: ignore[arg-type]
            current_iface = None
            continue
        if op.interface is not None and current_iface != op.interface:
            commands.append(op.interface)
            current_iface = op.interface
        if op.interface is None and current_iface is not None:
            commands.append("exit")
            current_iface = None
        if op.kind is OperationKind.REMOVE_LINE:
            commands.append(f"no {op.line}")
        elif op.kind in (OperationKind.ADD_LINE, OperationKind.OVERWRITE_LINE,
                         OperationKind.ADD_ONLY_REVIEW):
            commands.append(op.line or "")
    if current_iface is not None:
        commands.append("exit")
    return commands


def build_expected_post(
    current_text: str,
    operations: list[RestoreOperation],
) -> str:
    """Return the expected post-restore normalised text.

    Only the operations that would actually be sent are applied.
    ``AddOnlyReview`` is included because its line *will* be sent.
    ``REMOVE_LINE`` is included only if present in ``operations`` (i.e. the
    caller passed ``allow_removals=True`` and the planner emitted them).

    The result is not re-sorted; it preserves the order of the current
    config with added/overwritten lines appended to their block.
    """
    blocks = _parse_blocks(current_text)
    by_key = {b.opener or (b.lines[0] if b.lines else ""): b for b in blocks}

    for op in operations:
        if op.kind in (OperationKind.ADD_LINE, OperationKind.ADD_ONLY_REVIEW):
            if op.interface is not None and op.interface in by_key:
                by_key[op.interface].lines.append(op.line or "")
            elif op.interface is not None:
                by_key[op.interface] = Block(opener=op.interface, lines=[op.line or ""])
            else:
                by_key[op.line or ""] = Block(opener=None, lines=[op.line or ""])
        elif op.kind is OperationKind.OVERWRITE_LINE:
            target = by_key.get(op.interface) if op.interface else None
            if target is None:
                if op.interface is not None:
                    by_key[op.interface] = Block(opener=op.interface, lines=[op.line or ""])
                else:
                    by_key[op.line or ""] = Block(opener=None, lines=[op.line or ""])
                continue
            new_lines = []
            for line in target.lines:
                if _is_single_valued(line) and _command_key(line) == _command_key(op.line or ""):
                    new_lines.append(op.line or "")
                else:
                    new_lines.append(line)
            target.lines = new_lines
        elif op.kind is OperationKind.REMOVE_LINE:
            target = by_key.get(op.interface) if op.interface else None
            if target is not None and op.line in target.lines:
                target.lines.remove(op.line)
            elif op.interface is None:
                by_key.pop(op.line or "", None)
        elif op.kind in (OperationKind.DEFAULT_INTERFACE, OperationKind.NO_INTERFACE):
            if op.interface is not None:
                by_key.pop(op.interface, None)

    out_lines: list[str] = []
    seen: set[str] = set()
    for b in blocks:
        key = b.opener or (b.lines[0] if b.lines else "")
        if key in seen:
            continue
        seen.add(key)
        block = by_key.get(key)
        if block is None:
            continue
        if block.opener is not None:
            out_lines.append(block.opener)
            for line in block.lines:
                out_lines.append(" " + line)
        else:
            out_lines.extend(block.lines)
    # Append new blocks that were created after the initial parse.
    for key, block in by_key.items():
        if key in seen:
            continue
        if block.opener is not None:
            out_lines.append(block.opener)
            for line in block.lines:
                out_lines.append(" " + line)
        else:
            out_lines.extend(block.lines)

    return "\n".join(line.rstrip() for line in out_lines if line.strip())
