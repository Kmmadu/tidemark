"""
tidemark.core.redact
────────────────────
The single redaction function used by the CLI, alerts (M5), the GUI (M3)
and the SQLite ``runs.error`` column.

Applied to everything that leaves the process in a human-readable form.
Never applied to the config snapshot itself when ``store_raw=true``.
"""

from __future__ import annotations

import re

# Ordered most-specific-first. Each rule is (compiled_regex, replacement).
# The regexes use a group so the value is preserved as ``<redacted>``.
_RULES: list[tuple[re.Pattern[str], str]] = [
    # Cisco IOS
    (re.compile(r"(?im)^(\s*(?:enable\s+(?:secret|password)\s+)(?:\d+\s+)?)(\S+)\s*$"),
     r"\1<redacted>"),
    (re.compile(r"(?im)^(\s*(?:username\s+\S+\s+(?:secret|password)\s+)(?:\d+\s+)?)(\S+)\s*$"),
     r"\1<redacted>"),
    (re.compile(r"(?im)^(\s*snmp-server\s+community\s+)(\S+)"),
     r"\1<redacted>"),
    (re.compile(r"(?im)^(\s*snmp-server\s+host\s+\S+\s+\S+\s+)(\S+)"),
     r"\1<redacted>"),
    (re.compile(r"(?im)^(\s*key-string\s+(?:\d+\s+)?)(\S+)"),
     r"\1<redacted>"),
    (re.compile(r"(?im)^(\s*pre-shared-key\s+(?:address\s+\S+\s+key\s+(?:\d+\s+)?)?)(\S+)"),
     r"\1<redacted>"),
    (re.compile(r"(?im)^(\s*password\s+(?:\d+\s+)?)(\S+)"),
     r"\1<redacted>"),
    (re.compile(r"(?im)^(\s*ppp\s+chap\s+password\s+(?:\d+\s+)?)(\S+)"),
     r"\1<redacted>"),
    (re.compile(r"(?im)^(\s*neighbor\s+\S+\s+password\s+(?:\d+\s+)?)(\S+)"),
     r"\1<redacted>"),

    # MikroTik RouterOS
    (re.compile(r"(?i)(\bpassword=)(\S+)"), r"\1<redacted>"),
    (re.compile(r"(?i)(\bsecret=)(\S+)"), r"\1<redacted>"),
    (re.compile(r"(?i)(\bkey=)(\S+)"), r"\1<redacted>"),

    # Generic key=value in the same line
    (re.compile(r"(?i)\b(pass(?:word|wd|phrase)\s*=\s*)([^\s,;]+)"), r"\1<redacted>"),
    (re.compile(r"(?i)\b(token\s*=\s*)([^\s,;]+)"), r"\1<redacted>"),
    (re.compile(r"(?i)\b(psk\s*=\s*)([^\s,;]+)"), r"\1<redacted>"),
    (re.compile(r"(?i)\b(api[-_]?key\s*=\s*)([^\s,;]+)"), r"\1<redacted>"),
]


def redact(text: str | None) -> str | None:
    """Return ``text`` with any obvious secrets replaced by ``<redacted>``.

    Returns ``None`` unchanged so callers can pass through ``None``.
    """
    if text is None:
        return None
    out = text
    for pattern, replacement in _RULES:
        out = pattern.sub(replacement, out)
    return out


def redact_lines(lines: list[str]) -> list[str]:
    """Apply :func:`redact` line by line, preserving line count."""
    return [redact(line) or "" for line in lines]
