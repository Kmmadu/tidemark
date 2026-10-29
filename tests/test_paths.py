"""XDG paths resolve under the temp XDG tree and ensure_dirs creates them."""

from __future__ import annotations

from pathlib import Path

from tidemark.store.paths import default_paths


def test_defaults_under_tmp_xdg(tmp_xdg: Path) -> None:
    p = default_paths()
    assert str(p.config_dir).startswith(str(tmp_xdg))
    assert str(p.data_dir).startswith(str(tmp_xdg))
    assert str(p.state_dir).startswith(str(tmp_xdg))


def test_ensure_dirs_creates_everything(tmp_xdg: Path) -> None:
    p = default_paths()
    p.ensure_dirs()
    for d in (p.config_dir, p.data_dir, p.state_dir,
              p.user_profiles_dir, p.log_dir, p.daemon_dir, p.configs_git_dir):
        assert d.is_dir()
    assert p.db_path.name == "tidemark.db"
