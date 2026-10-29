"""Stable running.cfg, pre_restore content-addressed, name validator, read_at."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tidemark.store.git_repo import (
    ConfigRepo,
    InvalidDeviceNameError,
)


def _count_commits(repo_path: Path) -> int:
    return int(subprocess.run(
        ["git", "-C", str(repo_path), "rev-list", "--count", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip())


def test_second_identical_write_no_commit(tmp_path: Path) -> None:
    repo = ConfigRepo(tmp_path / "configs")
    now = datetime.now(UTC)
    repo.store_normal("core", "hostname r1\n", now)
    before = _count_commits(repo.root)
    repo.store_normal("core", "hostname r1\n", now)
    after = _count_commits(repo.root)
    assert after == before


def test_one_change_one_commit(tmp_path: Path) -> None:
    repo = ConfigRepo(tmp_path / "configs")
    now = datetime.now(UTC)
    repo.store_normal("core", "hostname r1\n", now)
    repo.store_normal("core", "hostname r2\n", now)
    assert _count_commits(repo.root) == 2


def test_read_at_commit(tmp_path: Path) -> None:
    repo = ConfigRepo(tmp_path / "configs")
    now = datetime.now(UTC)
    _, _, sha1 = repo.store_normal("core", "hostname r1\n", now)
    _, _, sha2 = repo.store_normal("core", "hostname r2\n", now)
    assert repo.read_at(sha1, "core/running.cfg").rstrip("\n") == "hostname r1"
    assert repo.read_at(sha2, "core/running.cfg").rstrip("\n") == "hostname r2"


def test_invalid_name_rejected(tmp_path: Path) -> None:
    repo = ConfigRepo(tmp_path / "configs")
    with pytest.raises(InvalidDeviceNameError):
        repo.store_normal("../etc", "x\n", datetime.now(UTC))


def test_pre_restore_content_addressed(tmp_path: Path) -> None:
    repo = ConfigRepo(tmp_path / "configs")
    now = datetime.now(UTC)
    sha_a = "a" * 64
    sha_b = "b" * 64
    p1, _ = repo.store_pre_restore("core", "x\n", sha_a, now)
    p2, _ = repo.store_pre_restore("core", "y\n", sha_b, now)
    assert p1 != p2
    assert "pre_restore" in str(p1)
