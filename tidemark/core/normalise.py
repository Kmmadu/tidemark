"""
tidemark.core.normalise
───────────────────────
Turn a raw device config into the canonical text we hash and store.

Rules:
  - CRLF → LF, no trailing whitespace on any line, no trailing blank lines.
  - Lines matching any ``volatile_patterns`` regex are dropped.
  - Text is stripped of leading and trailing blank lines.

The returned sha256 is over the normalised text, so a device whose only
change is a volatile line produces the same hash and no new git commit.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalisedConfig:
    """A normalised config and its sha256."""

    text: str
    sha256: str
    size: int  # length of ``text`` in characters


def normalise(raw: str, volatile_patterns: list[str]) -> NormalisedConfig:
    """Normalise ``raw`` and compute its sha256.

    Args:
        raw: the raw device output.
        volatile_patterns: regex strings; any line matching any of them is
            dropped before hashing.
    """
    patterns = [re.compile(p) for p in volatile_patterns]

    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in raw.split("\n")]
    kept = [line for line in lines if not any(p.search(line) for p in patterns)]

    while kept and not kept[0]:
        kept.pop(0)
    while kept and not kept[-1]:
        kept.pop()

    text = "\n".join(kept)
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return NormalisedConfig(text=text, sha256=sha, size=len(text))
