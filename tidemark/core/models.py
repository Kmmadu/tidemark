"""
tidemark.core.models
────────────────────
Data types shared by the CLI, engine, store and (later) GUI.

These are plain dataclasses. They carry no behaviour that requires a
connection, a database or a GUI, so they can be constructed and asserted
in tests without any I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class RestoreMode(StrEnum):
    """How a profile restores configuration.

    ``none`` disables restore for the profile entirely — calling
    ``apply_restore`` on a device with this mode raises NotSupported in M2.
    """

    NONE = "none"
    CLI_DELTA = "cli_delta"
    FILE_IMPORT = "file_import"


class RunStatus(StrEnum):
    """Terminal status of a backup run."""

    SUCCESS = "success"
    FAILED = "failed"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class VendorProfile:
    """A single vendor profile, loaded from a YAML file.

    All regex fields are compiled strings, not compiled patterns, so the
    dataclass stays cheap to compare and serialise. The engine compiles them
    once per run.
    """

    id: str
    display_name: str
    netmiko_device_type: str
    fetch_commands: list[str]
    pre_commands: list[str] = field(default_factory=list)
    volatile_patterns: list[str] = field(default_factory=list)
    invalid_patterns: list[str] = field(default_factory=list)
    min_length: int = 1
    requires_enable: bool = False
    restore: RestoreMode = RestoreMode.NONE
    description: str = ""
    tested: bool = False

    def __post_init__(self) -> None:
        if not self.id or not self.id.replace("_", "").isalnum():
            raise ValueError(f"invalid profile id: {self.id!r}")
        if not self.fetch_commands:
            raise ValueError(f"profile {self.id}: fetch_commands must be non-empty")
        if self.min_length < 0:
            raise ValueError(f"profile {self.id}: min_length must be >= 0")


@dataclass
class Device:
    """A managed network device."""

    name: str
    host: str
    port: int
    profile_id: str
    credential_ref: str
    group: str | None = None
    enabled: bool = True
    custom_command: str | None = None
    id: int | None = None

    def display_name(self) -> str:
        """Stable display name used in logs, CLI output and (later) the GUI."""
        return self.name or self.host


@dataclass
class Snapshot:
    """A single stored configuration snapshot."""

    device_id: int
    taken_at_utc: datetime
    sha256: str
    path: str
    size: int
    kind: str = "normal"  # "normal" | "pre_restore"
    is_redacted: bool = False
    id: int | None = None

@dataclass
class BackupRun:
    """One attempt at backing up one device."""

    device_id: int
    started_at_utc: datetime
    finished_at_utc: datetime
    status: RunStatus
    error: str | None = None
    snapshot_id: int | None = None
    id: int | None = None


@dataclass
class BackupResult:
    """The result of a single ``run_backup`` call, before it is persisted.

    ``diff`` is the full unified diff against the previous snapshot, or
    ``None`` if there was no previous snapshot or nothing changed.
    """

    device: Device
    status: RunStatus
    started_at_utc: datetime
    finished_at_utc: datetime
    normalised_text: str | None = None
    sha256: str | None = None
    diff: str | None = None
    error: str | None = None
    changed: bool = False
