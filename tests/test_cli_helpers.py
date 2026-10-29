"""Formatting helpers used by the CLI."""

from __future__ import annotations

from tidemark.cli.main import _fmt_size, _fmt_utc


def test_fmt_size() -> None:
    assert _fmt_size(0) == "0 B"
    assert _fmt_size(1023) == "1023 B"
    assert _fmt_size(1024) == "1.0 KB"
    assert _fmt_size(1024 * 1024) == "1.0 MB"


def test_fmt_utc() -> None:
    assert _fmt_utc("2026-10-24T13:05:09.123456+00:00") == "2026-10-24 13:05:09"
