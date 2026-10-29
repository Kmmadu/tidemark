"""
tidemark.core.credentials
─────────────────────────
TEMPORARY credential source for M1 only.

Until M2's CredentialStore lands, this module reads credentials from the
environment (``TIDEMARK_USER`` / ``TIDEMARK_PASS``) or, if those are unset,
prompts on the terminal with ``getpass``.

Nothing here writes credentials anywhere. Nothing here logs them.
Every caller in M1 must treat what this module returns as opaque and never
persist it.
"""

from __future__ import annotations

import getpass
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Credentials:
    """A username/password pair. Never log or serialise this."""

    username: str
    password: str

    def __repr__(self) -> str:  # pragma: no cover - defensive
        return "Credentials(username=<redacted>, password=<redacted>)"


def read_credentials(prompt_device: str | None = None) -> Credentials:
    """Return credentials from the environment, or prompt if absent.

    Args:
        prompt_device: if provided, used in the interactive prompt.
    """
    username = os.getenv("TIDEMARK_USER")
    password = os.getenv("TIDEMARK_PASS")
    if username and password:
        return Credentials(username=username, password=password)

    label = prompt_device or "device"
    if not username:
        username = input(f"Username for {label}: ")
    if not password:
        password = getpass.getpass(f"Password for {label}: ")
    if not username or not password:
        raise RuntimeError(
            "Credentials are required: set TIDEMARK_USER and TIDEMARK_PASS, "
            "or answer the prompts."
        )
    return Credentials(username=username, password=password)
