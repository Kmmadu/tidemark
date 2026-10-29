"""Volatile lines are dropped, hashes are stable, CRLF is normalised."""

from __future__ import annotations

from tidemark.core.normalise import normalise

SAMPLE = """\
! Last configuration change at 12:00:00 UTC
hostname core
!
interface Gi0/1
 ip address 10.0.0.1 255.255.255.0
"""


def test_strips_volatile_and_trailing_ws() -> None:
    n = normalise(SAMPLE, [r"^! Last configuration change at .*"])
    assert "Last configuration change" not in n.text
    assert n.text.startswith("hostname core")
    assert n.size == len(n.text)


def test_crlf_becomes_lf() -> None:
    n = normalise("a\r\nb\r\n", [])
    assert n.text == "a\nb"


def test_same_input_same_hash() -> None:
    a = normalise(SAMPLE, [r"^! Last configuration change at .*"])
    b = normalise(SAMPLE, [r"^! Last configuration change at .*"])
    assert a.sha256 == b.sha256


def test_only_volatile_change_same_hash() -> None:
    other = SAMPLE.replace("12:00:00", "13:00:00")
    a = normalise(SAMPLE, [r"^! Last configuration change at .*"])
    b = normalise(other, [r"^! Last configuration change at .*"])
    assert a.sha256 == b.sha256


def test_real_change_changes_hash() -> None:
    other = SAMPLE.replace("10.0.0.1", "10.0.0.2")
    a = normalise(SAMPLE, [r"^! Last configuration change at .*"])
    b = normalise(other, [r"^! Last configuration change at .*"])
    assert a.sha256 != b.sha256
