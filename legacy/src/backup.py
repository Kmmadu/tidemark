"""
backup.py
─────────
Handles backing up and restoring Cisco IOS device configurations.

Functions
─────────
  backup_device()         - SSH in, pull running-config, save, diff, git
  find_previous_backup()  - Locate the last .cfg file for a device
  restore_device_config() - Push a saved config back to a device
"""

import logging
from datetime import datetime
from difflib import unified_diff
from pathlib import Path
from typing import TypedDict, Optional

from src.connection import build_device_params, connect_with_retry
from src.utils import git_commit_and_push

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Type definitions
# ──────────────────────────────────────────────

class BackupResult(TypedDict):
    """Return type for backup_device function."""
    success: bool
    changed: bool
    diff: Optional[str]
    error: Optional[str]
    backup_file: Optional[str]


class RestoreResult(TypedDict):
    """Return type for restore_device_config function."""
    success: bool
    message: str
    restored_config: Optional[str]
    pre_restore_backup: Optional[str]


# ──────────────────────────────────────────────
# Backup
# ──────────────────────────────────────────────

def backup_device(
    device: dict,
    username: str,
    password: str,
    git_enabled: bool = True
) -> BackupResult:
    """
    Back up a single device's running configuration.

    Args:
        device:      Device dict with host, device_type, optional name/secret.
        username:    SSH username.
        password:    SSH password.
        git_enabled: Whether to commit the new backup to Git.

    Returns:
        BackupResult with success status, change detection, diff, and file path.
    """
    hostname = device.get("name", device["host"])
    result: BackupResult = {
        "success":     False,
        "changed":     False,
        "diff":        None,
        "error":       None,
        "backup_file": None,
    }

    # ── Build connection params ───────────────
    device_params = build_device_params(device, username, password)

    # ── Connect ───────────────────────────────
    conn = connect_with_retry(device_params, retries=2)
    if not conn:
        result["error"] = "Failed to connect after retries"
        return result

    try:
        # ── Pull config ───────────────────────
        logger.info("Retrieving running-config from %s", hostname)
        running_config = conn.send_command("show running-config")

        # ── Save to disk ──────────────────────
        backup_dir = Path("backups")
        backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename  = f"{hostname}_{timestamp}.cfg"
        filepath  = backup_dir / filename

        filepath.write_text(running_config)
        result["backup_file"] = str(filepath)
        result["success"]     = True
        logger.info("Backup saved: %s", filepath)

        # ── Diff against previous backup ──────
        previous = find_previous_backup(hostname)
        if previous:
            previous_config = previous.read_text()
            if running_config.strip() != previous_config.strip():
                result["changed"] = True
                diff_lines = list(unified_diff(
                    previous_config.splitlines(),
                    running_config.splitlines(),
                    fromfile=f"{hostname}_previous",
                    tofile=f"{hostname}_current",
                    lineterm="",
                ))
                result["diff"] = "\n".join(diff_lines[:50])
                logger.warning("Configuration CHANGE detected for %s", hostname)
            else:
                logger.info("No configuration change for %s", hostname)
        else:
            logger.info("First backup for %s (no baseline to diff)", hostname)

        # ── Git commit ────────────────────────
        if git_enabled:
            git_commit_and_push(
                commit_message=f"Backup {hostname} - {timestamp}"
            )

    except Exception as exc:
        logger.error("Backup failed for %s: %s", hostname, exc)
        result["error"] = str(exc)

    finally:
        conn.disconnect()

    return result


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def find_previous_backup(device_name: str) -> Path | None:
    """
    Return the most recent existing .cfg file for a device.

    When called right after saving a new backup there will be at least
    two files, so we return the second-most-recent (index 1).
    If only one file exists we return that one so the first backup ever
    still gets a diff baseline.
    """
    backup_dir = Path("backups")
    backups    = sorted(backup_dir.glob(f"{device_name}_*.cfg"), reverse=True)

    if len(backups) >= 2:
        return backups[1]   # skip the file we just wrote
    if len(backups) == 1:
        return backups[0]
    return None


# ──────────────────────────────────────────────
# Restore
# ──────────────────────────────────────────────

def restore_device_config(
    device: dict,
    backup_file: Path,
    username: str,
    password: str,
) -> RestoreResult:
    """
    Push a saved configuration back to a Cisco IOS device.

    SAFETY: Automatically creates a backup of the current config BEFORE
    restoring, so you can always roll back.

    Sends each non-comment config line individually via
    `configure terminal`, then saves with `write memory`.

    Args:
        device:      Device dict with host, device_type, optional name/secret.
        backup_file: Path to the .cfg file to restore.
        username:    SSH username.
        password:    SSH password.

    Returns:
        RestoreResult with success status, message, and config preview.
    """
    hostname = device.get("name", device["host"])
    result: RestoreResult = {
        "success":           False,
        "message":           "",
        "restored_config":   None,
        "pre_restore_backup": None,
    }

    # ── Read backup file ──────────────────────
    try:
        config_to_restore      = Path(backup_file).read_text()
        result["restored_config"] = config_to_restore[:200] + "…"
    except Exception as exc:
        result["message"] = f"Failed to read backup file: {exc}"
        return result

    # ── Connect ───────────────────────────────
    device_params = build_device_params(device, username, password)
    conn = connect_with_retry(device_params, retries=2)
    if not conn:
        result["message"] = f"Failed to connect to {hostname}"
        return result

    try:
        # ── SAFETY: Backup current config first ──
        logger.info("Creating pre-restore backup of current config...")
        current_config = conn.send_command("show running-config")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pre_restore_file = Path("backups") / f"{hostname}_PRE_RESTORE_{timestamp}.cfg"
        pre_restore_file.write_text(current_config)
        result["pre_restore_backup"] = str(pre_restore_file)
        logger.info("Pre-restore backup saved: %s", pre_restore_file)

        # ── Confirm before proceeding ───────────
        logger.warning("RESTORING CONFIG to %s from %s", hostname, backup_file)

        conn.send_command("configure terminal", expect_string=r"#")

        # Send each non-blank, non-comment line
        lines_applied = 0
        for line in config_to_restore.splitlines():
            if line.strip() and not line.startswith("!"):
                conn.send_command(line, expect_string=r"#")
                lines_applied += 1

        conn.send_command("end")
        conn.send_command("write memory", expect_string=r"#")

        result["success"] = True
        result["message"] = f"Successfully restored config to {hostname} ({lines_applied} lines applied)"
        logger.info("Restore complete: %s (%d lines)", hostname, lines_applied)

    except Exception as exc:
        result["message"] = f"Restore failed: {exc}"
        logger.error("Restore failed for %s: %s", hostname, exc)

    finally:
        conn.disconnect()

    return result