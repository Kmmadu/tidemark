"""unified_diff produces the expected shape."""

from __future__ import annotations

from tidemark.core.diffing import unified_diff


def test_diff_basic() -> None:
    d = unified_diff("a\nb\n", "a\nc\n", from_label="old", to_label="new")
    assert "--- old" in d
    assert "+++ new" in d
    assert "-b" in d
    assert "+c" in d


def test_diff_empty_when_identical() -> None:
    assert unified_diff("same\n", "same\n") == ""
