"""
main.py
───────
CLI entry point for AutoConfigBackup.

Modes
─────
  python main.py              # single run – back up all devices once
  python main.py --schedule   # run once then start the APScheduler loop
  python main.py --device core-sw-01   # back up one specific device

Usage examples::

    # One-shot backup of all devices
    python main.py

    # Start the scheduler (runs immediately, then on interval/cron)
    python main.py --schedule

    # Back up a single device by hostname
    python main.py --device edge-rtr-01

    # Override log level
    python main.py --log-level DEBUG
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# ── Make sure the project root is on sys.path when run directly ──────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.alerts import alert_backup_failure, alert_config_changed
from src.backup import backup_device
from src.scheduler import start_scheduler
from src.utils import get_required_env, load_devices, load_env, setup_logging

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# CLI argument parser
# ──────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="AutoConfigBackup – Network Configuration Backup Tool",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Start APScheduler loop after an initial backup run.",
    )
    parser.add_argument(
        "--device",
        metavar="HOSTNAME",
        help="Back up a single device by hostname (skips the rest).",
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="Disable git commit/push for this run.",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )
    return parser


# ──────────────────────────────────────────────
# Single-run logic
# ──────────────────────────────────────────────

def run_single_backup(device_filter: str | None, git_enabled: bool) -> int:
    """
    Back up all devices (or one if device_filter is set).

    Returns:
        Exit code – 0 if all backups succeeded, 1 if any failed.
    """
    username = get_required_env("DEVICE_USERNAME")
    password = get_required_env("DEVICE_PASSWORD")

    devices = load_devices()

    # Optionally filter to a single device
    if device_filter:
        devices = [
            d for d in devices
            if d.get("hostname", d["host"]) == device_filter
        ]
        if not devices:
            logger.error(
                "Device '%s' not found in devices.yaml.", device_filter
            )
            return 1
        logger.info("Targeting single device: %s", device_filter)

    total  = len(devices)
    passed = 0
    failed = 0

    logger.info("Starting backup run – %d device(s).", total)
    logger.info("─" * 50)

    for device in devices:
        hostname = device.get("hostname", device["host"])
        result   = backup_device(device, username, password, git_enabled)

        if result["success"]:
            passed += 1
            status = "✓ OK"
            if result["changed"] and result["diff"]:
                status = "✓ CHANGED"
                alert_config_changed(hostname, result["diff"])
        else:
            failed += 1
            status = "✗ FAILED"
            alert_backup_failure(hostname, result["error"] or "Unknown error")

        logger.info("  [%s] %s", status, hostname)

    logger.info("─" * 50)
    logger.info(
        "Done. Total=%d  Passed=%d  Failed=%d", total, passed, failed
    )

    return 0 if failed == 0 else 1


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

def main() -> None:
    parser  = _build_parser()
    args    = parser.parse_args()

    # 1. Bootstrap environment and logging
    load_env()
    setup_logging(level=args.log_level)

    logger.info("AutoConfigBackup starting …")

    git_enabled = not args.no_git and os.getenv("GIT_ENABLED", "true").lower() == "true"

    # 2. Dispatch
    if args.schedule:
        # Scheduler does its own full run on startup
        start_scheduler(run_immediately=True)
    else:
        exit_code = run_single_backup(
            device_filter=args.device,
            git_enabled=git_enabled,
        )
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
