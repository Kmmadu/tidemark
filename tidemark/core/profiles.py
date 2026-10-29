"""
tidemark.core.profiles
──────────────────────
Loads vendor profiles from bundled YAML and from user-supplied YAML.

User profiles live in ``<config_dir>/profiles/`` and override bundled
profiles by ``id``. Both are validated on load; a bad profile raises
``ProfileError`` rather than being silently skipped, so a typo cannot
turn into a silent fallback.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

import yaml

from tidemark.core.models import RestoreMode, VendorProfile

logger = logging.getLogger(__name__)


class ProfileError(ValueError):
    """Raised when a profile YAML is missing fields or malformed."""


_BUNDLED_DIR = Path(__file__).resolve().parent.parent / "profiles"


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ProfileError(f"{path}: expected a mapping, got {type(data).__name__}")
    return data


def _to_profile(data: dict, source: Path) -> VendorProfile:
    required = ("id", "display_name", "netmiko_device_type", "fetch_commands")
    for key in required:
        if key not in data:
            raise ProfileError(f"{source}: missing required field {key!r}")

    restore_raw = data.get("restore", "none")
    try:
        restore = RestoreMode(restore_raw)
    except ValueError as exc:
        raise ProfileError(
            f"{source}: restore must be one of "
            f"{[m.value for m in RestoreMode]}, got {restore_raw!r}"
        ) from exc

    fetch_commands = data["fetch_commands"]
    if not isinstance(fetch_commands, list) or not all(
        isinstance(x, str) and x for x in fetch_commands
    ):
        raise ProfileError(f"{source}: fetch_commands must be a non-empty list of strings")

    return VendorProfile(
        id=str(data["id"]),
        display_name=str(data["display_name"]),
        netmiko_device_type=str(data["netmiko_device_type"]),
        fetch_commands=[str(x) for x in fetch_commands],
        pre_commands=[str(x) for x in data.get("pre_commands", [])],
        volatile_patterns=[str(x) for x in data.get("volatile_patterns", [])],
        invalid_patterns=[str(x) for x in data.get("invalid_patterns", [])],
        min_length=int(data.get("min_length", 1)),
        requires_enable=bool(data.get("requires_enable", False)),
        restore=restore,
        description=str(data.get("description", "")),
        tested=bool(data.get("tested", False)),
    )


class ProfileRegistry:
    """A registry of vendor profiles.

    Loads bundled profiles from ``tidemark/profiles/*.yaml`` first, then any
    user profiles from ``<user_profiles_dir>/*.yaml``, which override bundled
    ones by ``id``.
    """

    def __init__(self, user_profiles_dir: Path | None = None) -> None:
        self._user_dir = user_profiles_dir
        self._by_id: dict[str, VendorProfile] = {}
        self._reload()

    def _reload(self) -> None:
        self._by_id.clear()
        if _BUNDLED_DIR.exists():
            for path in sorted(_BUNDLED_DIR.glob("*.yaml")):
                self._register(path)
        if self._user_dir and self._user_dir.exists():
            for path in sorted(self._user_dir.glob("*.yaml")):
                self._register(path, override=True)
        if not self._by_id:
            logger.warning("No vendor profiles loaded")

    def _register(self, path: Path, *, override: bool = False) -> None:
        try:
            data = _load_yaml(path)
            profile = _to_profile(data, path)
        except ProfileError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface a wrapped error
            raise ProfileError(f"{path}: {exc}") from exc

        if not override and profile.id in self._by_id:
            raise ProfileError(
                f"duplicate profile id {profile.id!r} in {path} "
                f"(already loaded from bundled profiles)"
            )
        self._by_id[profile.id] = profile

    def get(self, profile_id: str) -> VendorProfile:
        """Return the profile with ``profile_id`` or raise ``KeyError``."""
        try:
            return self._by_id[profile_id]
        except KeyError as exc:
            raise KeyError(
                f"unknown profile {profile_id!r}; "
                f"known: {sorted(self._by_id)}"
            ) from exc

    def ids(self) -> list[str]:
        """Return all loaded profile ids, sorted."""
        return sorted(self._by_id)

    def all(self) -> Iterable[VendorProfile]:
        """Iterate over all loaded profiles, sorted by id."""
        return (self._by_id[i] for i in self.ids())
