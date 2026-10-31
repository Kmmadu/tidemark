"""
tidemark.core.redact
────────────────────
The single redaction function used by the CLI, alerts (M5), the GUI and the
SQLite ``runs.error`` column.

Applied to everything that leaves the process in a human-readable form.
Never applied to the config snapshot itself when ``store_raw=true``.

Redaction replaces every secret value with ``REDACTED_MARKER``. The marker is
a single fixed string so downstream code can detect when a snapshot contains
redacted placeholders — restoring such a snapshot would set real secrets to
the placeholder text.
"""

from __future__ import annotations

import re

# The one string every redacted value is replaced with. Do not change without
# a migration — the marker is written to disk in snapshots and audit rows.
REDACTED_MARKER = "<<TIDEMARK-REDACTED>>"

# Ordered most-specific-first. Each rule is (compiled_regex, replacement).
# The regexes use a group so the value is preserved as ``<redacted>``.
_RULES: list[tuple[re.Pattern[str], str]] = [
    # Cisco IOS
    (re.compile(r"(?im)^(\s*(?:enable\s+(?:secret|password)\s+)(?:\d+\s+)?)(\S+)\s*$"),
     rf"\1{REDACTED_MARKER}"),
    (re.compile(r"(?im)^(\s*(?:username\s+\S+\s+(?:secret|password)\s+)(?:\d+\s+)?)(\S+)\s*$"),
     rf"\1{REDACTED_MARKER}"),
    (re.compile(r"(?im)^(\s*snmp-server\s+community\s+)(\S+)"),
     rf"\1{REDACTED_MARKER}"),
    (re.compile(r"(?im)^(\s*snmp-server\s+host\s+\S+\s+\S+\s+)(\S+)"),
     rf"\1{REDACTED_MARKER}"),
    (re.compile(r"(?im)^(\s*key-string\s+(?:\d+\s+)?)(\S+)"),
     rf"\1{REDACTED_MARKER}"),
    (re.compile(r"(?im)^(\s*pre-shared-key\s+(?:address\s+\S+\s+key\s+(?:\d+\s+)?)?)(\S+)"),
     rf"\1{REDACTED_MARKER}"),
    (re.compile(r"(?im)^(\s*password\s+(?:\d+\s+)?)(\S+)"),
     rf"\1{REDACTED_MARKER}"),
    (re.compile(r"(?im)^(\s*ppp\s+chap\s+password\s+(?:\d+\s+)?)(\S+)"),
     rf"\1{REDACTED_MARKER}"),
    (re.compile(r"(?im)^(\s*neighbor\s+\S+\s+password\s+(?:\d+\s+)?)(\S+)"),
     rf"\1{REDACTED_MARKER}"),

    # MikroTik RouterOS
    (re.compile(r"(?i)(\bpassword=)(\S+)"), rf"\1{REDACTED_MARKER}"),
    (re.compile(r"(?i)(\bsecret=)(\S+)"), rf"\1{REDACTED_MARKER}"),
    (re.compile(r"(?i)(\bkey=)(\S+)"), rf"\1{REDACTED_MARKER}"),

    # Generic key=value in the same line
    (re.compile(r"(?i)\b(pass(?:word|wd|phrase)\s*=\s*)([^\s,;]+)"), rf"\1{REDACTED_MARKER}"),
    (re.compile(r"(?i)\b(token\s*=\s*)([^\s,;]+)"), rf"\1{REDACTED_MARKER}"),
    (re.compile(r"(?i)\b(psk\s*=\s*)([^\s,;]+)"), rf"\1{REDACTED_MARKER}"),
    (re.compile(r"(?i)\b(api[-_]?key\s*=\s*)([^\s,;]+)"), rf"\1{REDACTED_MARKER}"),
]


def redact(text: str | None) -> str | None:
    """Return ``text`` with any obvious secrets replaced by ``REDACTED_MARKER``.

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


def contains_redaction_marker(text: str | None) -> bool:
    """Return True if ``text`` contains the redaction marker."""
    return text is not None and REDACTED_MARKER in text
