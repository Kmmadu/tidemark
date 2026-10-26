"""
app.py
──────
Flask web dashboard for AutoConfigBackup.

Routes
──────
  GET  /                              Dashboard
  GET  /devices                       Device list
  GET  /history                       Backup history
  GET  /view/<filename>               View a config file

API
──────
  POST /api/backup/trigger            Backup all devices
  POST /api/backup/trigger/<name>     Backup one device
  GET  /api/backups/stats             Stats for dashboard cards
  GET  /api/backups                   List all backup files
  POST /api/restore/<filename>        Restore a config to its device
"""

import os
import sys
import logging
from datetime import datetime
from pathlib import Path

from flask import Flask, flash, jsonify, render_template, request

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.backup import restore_device_config
from src.main import run_single_backup
from src.utils import load_devices

logger = logging.getLogger(__name__)

# ── App init ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me-in-production")

BACKUP_DIR = Path("backups")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _all_backups() -> list[Path]:
    """Return all .cfg files under backups/, newest first."""
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.rglob("*.cfg"), key=lambda f: f.stat().st_mtime, reverse=True)


def _fmt_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 ** 2):.1f} MB"


# ── Page routes ───────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    devices = load_devices()
    backups = _all_backups()
    return render_template(
        "dashboard.html",
        devices=devices,
        total_backups=len(backups),
    )


@app.route("/devices")
def devices_page():
    devices = load_devices()
    return render_template("devices.html", devices=devices)


@app.route("/history")
def history():
    backups = []
    for f in _all_backups()[:100]:
        backups.append({
            "filename": f.name,
            "size":     _fmt_size(f.stat().st_size),
            "modified": datetime.fromtimestamp(
                f.stat().st_mtime
            ).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return render_template("history.html", backups=backups)


@app.route("/view/<filename>")
def view_config(filename):
    # Security: only allow plain filenames, no path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        return "Invalid filename", 400

    backup_path = BACKUP_DIR / filename
    if not backup_path.exists():
        return "File not found", 404

    content = backup_path.read_text()
    return render_template(
        "view_config.html",
        filename=filename,
        content=content,
        line_count=content.count("\n") + 1,
    )


# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/api/backup/trigger", methods=["POST"])
def trigger_backup():
    """Trigger a backup run for all devices."""
    try:
        exit_code = run_single_backup(device_filter=None, git_enabled=False)
        if exit_code == 0:
            return jsonify({"status": "success", "message": "Backup completed successfully"})
        return jsonify({"status": "partial", "message": "Backup completed with some failures"}), 207
    except Exception as exc:
        logger.error("trigger_backup error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route("/api/backup/trigger/<device_name>", methods=["POST"])
def trigger_device_backup(device_name):
    """Trigger a backup for one specific device."""
    try:
        exit_code = run_single_backup(device_filter=device_name, git_enabled=False)
        if exit_code == 0:
            return jsonify({"status": "success", "message": f"Backup completed for {device_name}"})
        return jsonify({"status": "error", "message": f"Backup failed for {device_name}"}), 500
    except Exception as exc:
        logger.error("trigger_device_backup error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route("/api/backups/stats")
def backup_stats():
    """Return stats for the dashboard stat cards."""
    backups = _all_backups()
    last_backup = (
        datetime.fromtimestamp(backups[0].stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        if backups else "Never"
    )
    return jsonify({
        "devices":     len(load_devices()),
        "backups":     len(backups),
        "last_backup": last_backup,
    })


@app.route("/api/backups")
def list_backups():
    """Return a JSON list of the 50 most recent backup files."""
    return jsonify([
        {
            "filename": f.name,
            "size":     f.stat().st_size,
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        }
        for f in _all_backups()[:50]
    ])


@app.route("/api/restore/<filename>", methods=["POST"])
def restore_config(filename):
    """Restore a saved config backup to its device."""
    # Security: block path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"status": "error", "message": "Invalid filename"}), 400

    # Derive device name from filename: DeviceName_YYYYMMDD_HHMMSS.cfg
    # Example: "Core-Switch-01_20260506_160540.cfg" -> "Core-Switch-01"
    device_name = filename.replace(".cfg", "").rsplit("_", 2)[0]

    devices = load_devices()
    target = next(
        (d for d in devices if d.get("name") == device_name or d.get("host") == device_name),
        None,
    )
    if not target:
        return jsonify({"status": "error", "message": f'Device "{device_name}" not found'}), 404

    username = os.getenv("DEVICE_USERNAME")
    password = os.getenv("DEVICE_PASSWORD")
    if not username or not password:
        return jsonify({"status": "error", "message": "DEVICE_USERNAME / DEVICE_PASSWORD not set"}), 500

    backup_path = BACKUP_DIR / filename
    result = restore_device_config(target, backup_path, username, password)

    if result["success"]:
        return jsonify({"status": "success", "message": result["message"]})
    return jsonify({"status": "error", "message": result["message"]}), 500


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
