"""
tidemark.store.importer
───────────────────────
Import the legacy ``devices.yaml`` inventory into the SQLite ``devices``
table. Names are validated by ``DeviceRepo`` and additionally here so the
error message points at the YAML file, not the DB layer.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from tidemark.core.models import Device
from tidemark.store.repositories import DeviceRepo

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

_DEVICE_TYPE_TO_PROFILE: dict[str, str] = {
    "cisco_ios": "cisco_ios",
    "cisco_nxos": "cisco_nxos",
    "cisco_asa": "cisco_asa",
    "juniper_junos": "juniper_junos",
    "arista_eos": "arista_eos",
    "huawei": "huawei",
    "fortinet": "fortinet",
    "mikrotik_routeros": "mikrotik_routeros",
    "ubiquiti_edgeswitch": "ubiquiti_edgeswitch",
    "linux": "linux_generic",
}


class ImportError_(RuntimeError):
    """Raised when the legacy file cannot be interpreted."""


def import_legacy_yaml(path: Path, device_repo: DeviceRepo) -> list[Device]:
    """Import ``path`` into ``device_repo``. Returns the imported devices."""
    path = Path(path)
    if not path.exists():
        raise ImportError_(f"{path} does not exist")

    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    raw_devices = data.get("devices") or []
    if not isinstance(raw_devices, list):
        raise ImportError_(f"{path}: 'devices' must be a list")

    imported: list[Device] = []
    for entry in raw_devices:
        if not isinstance(entry, dict):
            raise ImportError_(f"{path}: each device must be a mapping")
        host = entry.get("host")
        device_type = entry.get("device_type")
        if not host or not device_type:
            raise ImportError_(f"{path}: device missing host or device_type: {entry!r}")
        profile_id = _DEVICE_TYPE_TO_PROFILE.get(str(device_type))
        if profile_id is None:
            raise ImportError_(
                f"{path}: unsupported device_type {device_type!r} "
                f"(known: {sorted(_DEVICE_TYPE_TO_PROFILE)})"
            )

        name = str(entry.get("name") or host)
        if not _NAME_RE.match(name):
            raise ImportError_(
                f"{path}: invalid device name {name!r}; "
                f"must match ^[A-Za-z0-9._-]+$"
            )
        if device_repo.get_by_name(name) is not None:
            continue

        device = Device(
            name=name,
            host=str(host),
            port=int(entry.get("port", 22)),
            profile_id=profile_id,
            credential_ref="default",
            group=None,
            enabled=True,
            custom_command=None,
        )
        imported.append(device_repo.add(device))

    return imported
