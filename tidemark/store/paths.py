"""
tidemark.store.paths
────────────────────
All XDG-derived paths in one place. Nothing else in the codebase should
build paths from ``~/.config`` or ``~/.local/share`` by hand.

Layout::

    <config_dir>/config.toml              (reserved, unused in M1)
    <config_dir>/profiles/*.yaml          (user profile overrides)
    <data_dir>/tidemark.db                (SQLite)
    <data_dir>/configs/                   (git repo of normalised configs)
    <state_dir>/logs/                     (rotating logs)
    <state_dir>/daemon/                   (reserved, M4)

``platformdirs`` handles the OS defaults:
  - Linux:   ~/.config/tidemark, ~/.local/share/tidemark, ~/.local/state/tidemark
  - macOS:   ~/Library/Application Support/tidemark, ~/Library/Logs/tidemark
  - Windows: %APPDATA%\\tidemark, %LOCALAPPDATA%\\tidemark
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import PlatformDirs

_APP_NAME = "tidemark"
_APP_AUTHOR = "tidemark"


@dataclass(frozen=True)
class Paths:
    """Resolved paths for a Tidemark installation."""

    config_dir: Path
    data_dir: Path
    state_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "tidemark.db"

    @property
    def configs_git_dir(self) -> Path:
        return self.data_dir / "configs"

    @property
    def user_profiles_dir(self) -> Path:
        return self.config_dir / "profiles"

    @property
    def log_dir(self) -> Path:
        return self.state_dir / "logs"

    @property
    def daemon_dir(self) -> Path:
        return self.state_dir / "daemon"

    def ensure_dirs(self) -> None:
        """Create all directories Tidemark needs. Idempotent."""
        for d in (
            self.config_dir,
            self.data_dir,
            self.state_dir,
            self.user_profiles_dir,
            self.log_dir,
            self.daemon_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)
        self.configs_git_dir.mkdir(parents=True, exist_ok=True)


def default_paths() -> Paths:
    """Resolve the default paths for this OS.

    ``platformdirs`` honours ``XDG_*`` environment variables on Linux, which
    is what the test suite relies on.
    """
    dirs = PlatformDirs(appname=_APP_NAME, appauthor=_APP_AUTHOR)
    return Paths(
        config_dir=Path(dirs.user_config_dir),
        data_dir=Path(dirs.user_data_dir),
        state_dir=Path(dirs.user_state_dir),
    )
