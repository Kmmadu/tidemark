"""
tidemark.core.diffing
─────────────────────
Unified diff between two normalised configs.
"""

from __future__ import annotations


def unified_diff(
    old: str,
    new: str,
    from_label: str = "previous",
    to_label: str = "current",
    n: int = 3,
) -> str:
    """Return a unified diff between ``old`` and ``new`` as a single string."""
    import difflib

    diff_lines = list(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=from_label,
            tofile=to_label,
            lineterm="",
            n=n,
        )
    )
    return "\n".join(diff_lines)
