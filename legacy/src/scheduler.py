"""
scheduler.py
────────────
APScheduler wrapper that runs backup_device() for every device in the
inventory on a configurable cron or interval schedule.

Usage (from main.py)::

    from src.scheduler import start_scheduler
    start_scheduler()          # blocks until Ctrl-C
"""

import logging
import os

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.alerts import alert_backup_failure, alert_config_changed
from src.backup import backup_device
from src.utils import get_required_env, load_devices

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Job function (one execution = full inventory sweep)
# ──────────────────────────────────────────────

def run_backup_job() -> None:
    """
    Iterate over every device in devices.yaml, back it up,
    and fire alerts as needed.

    This function is registered as the APScheduler job.
    """
    logger.info("═" * 60)
    logger.info("Backup job started.")
    logger.info("═" * 60)

    username = get_required_env("DEVICE_USERNAME")
    password = get_required_env("DEVICE_PASSWORD")
    git_enabled = os.getenv("GIT_ENABLED", "true").lower() == "true"

    devices = load_devices()
    total  = len(devices)
    passed = 0
    failed = 0

    for device in devices:
        hostname = device.get("name", device["host"])
        result   = backup_device(device, username, password, git_enabled)

        if result["success"]:
            passed += 1
            # Fire change alert if config was modified
            if result["changed"] and result["diff"]:
                alert_config_changed(hostname, result["diff"])
        else:
            failed += 1
            alert_backup_failure(hostname, result["error"] or "Unknown error")

    logger.info(
        "Backup job finished. Total=%d  Passed=%d  Failed=%d",
        total, passed, failed,
    )
    logger.info("═" * 60)


# ──────────────────────────────────────────────
# Scheduler factory
# ──────────────────────────────────────────────

def _build_trigger():
    """
    Build an APScheduler trigger from environment variables.

    Supported modes (SCHEDULE_TYPE env var):
      • "interval"  – run every N minutes  (SCHEDULE_INTERVAL_MINUTES, default 60)
      • "cron"      – cron expression       (SCHEDULE_CRON, default "0 * * * *")

    Defaults to interval/60 min if SCHEDULE_TYPE is unset.
    """
    schedule_type = os.getenv("SCHEDULE_TYPE", "interval").lower()

    if schedule_type == "cron":
        cron_expr = os.getenv("SCHEDULE_CRON", "0 * * * *")
        # APScheduler CronTrigger accepts standard 5-field cron expressions
        parts = cron_expr.split()
        if len(parts) != 5:
            raise ValueError(
                f"SCHEDULE_CRON must be a 5-field cron expression, got: '{cron_expr}'"
            )
        minute, hour, day, month, day_of_week = parts
        trigger = CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
        )
        logger.info("Scheduler: cron trigger  → %s", cron_expr)

    else:  # default: interval
        minutes = int(os.getenv("SCHEDULE_INTERVAL_MINUTES", "60"))
        trigger = IntervalTrigger(minutes=minutes)
        logger.info("Scheduler: interval trigger → every %d minute(s).", minutes)

    return trigger


def start_scheduler(run_immediately: bool = True) -> None:
    """
    Create and start the BlockingScheduler.

    Args:
        run_immediately : If True, run one backup cycle before the first
                          scheduled tick so you don't wait a full interval
                          on startup.
    """
    if run_immediately:
        logger.info("Running immediate backup before scheduling …")
        run_backup_job()

    scheduler = BlockingScheduler(timezone=os.getenv("TIMEZONE", "UTC"))
    trigger   = _build_trigger()

    scheduler.add_job(
        run_backup_job,
        trigger=trigger,
        id="network_backup",
        name="Network Config Backup",
        max_instances=1,          # prevent overlapping runs
        coalesce=True,            # collapse missed runs into one
        misfire_grace_time=300,   # allow 5-minute grace for missed fires
    )

    logger.info("Scheduler started. Press Ctrl-C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped by user.")