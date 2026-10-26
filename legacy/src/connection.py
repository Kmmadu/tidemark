"""
connection.py
─────────────
Handles SSH connections to network devices via Netmiko.
Implements a retry mechanism so transient failures don't kill a full run.
"""
from typing import Optional

import time
import logging
from typing import Optional
from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoTimeoutException,
    NetmikoAuthenticationException,
    NetmikoBaseException,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def build_device_params(device: dict, username: str, password: str) -> dict:
    """Build connection parameters dictionary for Netmiko."""
    device_params = {
        'device_type': device['device_type'],
        'host': device['host'],
        'username': username,
        'password': password,
    }
    if device.get('secret'):
        device_params['secret'] = device['secret']
    if device.get('port'):
        device_params['port'] = device['port']
    return device_params


def connect_with_retry(
    device_params: dict,
    retries: int = 2,
    delay: int = 5,
) -> Optional[ConnectHandler]:
    """
    Attempt an SSH connection up to `retries + 1` times.

    Args:
        device_params : Netmiko connection dict (from build_device_params).
        retries       : Number of *extra* attempts after the first failure.
        delay         : Seconds to wait between attempts.

    Returns:
        An open ConnectHandler on success, or None on total failure.
    """
    host = device_params.get("host", "unknown")
    attempts = retries + 1  # total tries

    for attempt in range(1, attempts + 1):
        try:
            logger.info(
                "Connecting to %s (attempt %d/%d) …", host, attempt, attempts
            )
            connection = ConnectHandler(**device_params)
            logger.info("Connected to %s successfully.", host)
            return connection

        except NetmikoAuthenticationException:
            # Auth failure is not transient – no point retrying
            logger.error(
                "Authentication failed for %s. Check credentials.", host
            )
            return None

        except NetmikoTimeoutException as exc:
            logger.warning(
                "Timeout connecting to %s (attempt %d/%d): %s",
                host, attempt, attempts, exc,
            )

        except NetmikoBaseException as exc:
            logger.warning(
                "Connection error to %s (attempt %d/%d): %s",
                host, attempt, attempts, exc,
            )

        # Don't sleep after the last attempt
        if attempt < attempts:
            logger.info("Retrying %s in %d second(s) …", host, delay)
            time.sleep(delay)

    logger.error(
        "All %d connection attempt(s) failed for %s.", attempts, host
    )
    return None


def disconnect(connection: ConnectHandler, host: str = "device") -> None:
    """
    Safely close a Netmiko connection, swallowing any disconnect errors.

    Args:
        connection : An active ConnectHandler.
        host       : Device hostname / IP (used in log messages only).
    """
    try:
        connection.disconnect()
        logger.debug("Disconnected from %s.", host)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Error while disconnecting from %s: %s", host, exc)


# Legacy alias for backward compatibility
connect_device = connect_with_retry