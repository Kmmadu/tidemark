"""
Optional integration test against a real MikroTik CHR.

Skipped by default. To run:

    set -x TIDEMARK_CHR_HOST 192.0.2.10
    set -x TIDEMARK_CHR_USER admin
    set -x TIDEMARK_CHR_PASS secret
    pytest -q -m chr

Never commit these values.
"""

from __future__ import annotations

import os

import pytest

from tidemark.core.credentials import Credentials
from tidemark.core.engine import run_backup
from tidemark.core.models import Device, RunStatus
from tidemark.core.profiles import ProfileRegistry

pytestmark = pytest.mark.chr


def _env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} not set")
    return value


def test_backup_mikrotik_chr() -> None:
    host = _env("TIDEMARK_CHR_HOST")
    user = _env("TIDEMARK_CHR_USER")
    password = _env("TIDEMARK_CHR_PASS")

    device = Device(
        name="chr-lab", host=host, port=22,
        profile_id="mikrotik_routeros", credential_ref="env",
    )
    profile = ProfileRegistry().get("mikrotik_routeros")
    result = run_backup(device, profile, Credentials(user, password), retries=0)

    assert result.status in (RunStatus.SUCCESS, RunStatus.UNCHANGED), result.error
    assert result.normalised_text and len(result.normalised_text) > 20
    assert result.sha256 and len(result.sha256) == 64
