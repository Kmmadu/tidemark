"""Block-aware planner: line-level overwrites, ordered blocks, interface types."""

from __future__ import annotations

from tidemark.core.restore_blocks import (
    OperationKind,
    build_expected_post,
    plan_operations,
    render_commands,
)

CUR = """\
hostname r1
!
interface Gi0/1
 ip address 10.0.0.1 255.255.255.0
!
interface Gi0/2
 ip address 10.0.1.1 255.255.255.0
!
"""

TGT = """\
hostname r1
!
interface Gi0/1
 ip address 10.0.0.2 255.255.255.0
!
interface Gi0/2
 ip address 10.0.1.1 255.255.255.0
!
"""


def test_unchanged_line_is_noop() -> None:
    build = plan_operations(CUR, CUR)
    assert [op for op in build.operations if op.kind is not OperationKind.NOOP] == []


def test_single_valued_change_is_overwrite() -> None:
    build = plan_operations(CUR, TGT)
    assert any(op.kind is OperationKind.OVERWRITE_LINE and "10.0.0.2" in (op.line or "")
               for op in build.operations)
    assert not any(op.kind is OperationKind.REMOVE_LINE for op in build.operations)


def test_render_never_sends_no_ip_address() -> None:
    build = plan_operations(CUR, TGT)
    commands = render_commands(build.operations)
    assert not any("no ip address" in c for c in commands)
    assert " ip address 10.0.0.2 255.255.255.0" in commands or \
           "ip address 10.0.0.2 255.255.255.0" in commands


def test_expected_post_reflects_overwrite() -> None:
    build = plan_operations(CUR, TGT)
    post = build_expected_post(CUR, build.operations)
    assert "ip address 10.0.0.2 255.255.255.0" in post
    assert "ip address 10.0.0.1 255.255.255.0" not in post


def test_add_only_when_removals_off() -> None:
    tgt = CUR + "interface Gi0/3\n"
    build = plan_operations(CUR, tgt, allow_removals=False)
    assert any(op.kind is OperationKind.ADD_LINE and op.interface == "interface Gi0/3"
               for op in build.operations)


def test_remove_line_only_with_allow_removals() -> None:
    cur = CUR
    tgt = """\
hostname r1
!
interface Gi0/1
 ip address 10.0.0.1 255.255.255.0
 description new
!
interface Gi0/2
 ip address 10.0.1.1 255.255.255.0
!
"""
    build_no = plan_operations(cur, tgt, allow_removals=False)
    assert any(op.kind is OperationKind.ADD_LINE and op.line == "description new"
               for op in build_no.operations)
    assert not any(op.kind is OperationKind.REMOVE_LINE for op in build_no.operations)


def test_default_interface_vs_no_interface() -> None:
    cur = CUR
    tgt = "hostname r1\n"
    build = plan_operations(cur, tgt, allow_removals=True)
    # Physical Gi -> DEFAULT_INTERFACE
    assert any(op.kind is OperationKind.DEFAULT_INTERFACE for op in build.operations)


def test_no_interface_for_logical() -> None:
    cur = "hostname r1\ninterface Loopback0\n ip address 1.1.1.1 255.255.255.255\n"
    tgt = "hostname r1\n"
    build = plan_operations(cur, tgt, allow_removals=True)
    assert any(op.kind is OperationKind.NO_INTERFACE and "Loopback0" in (op.interface or "")
               for op in build.operations)
