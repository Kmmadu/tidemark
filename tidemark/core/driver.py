"""
tidemark.core.driver
────────────────────
The one generic driver used for every vendor.

The driver reads ``netmiko_device_type``, ``pre_commands`` and
``fetch_commands`` from a ``VendorProfile`` and does not contain any
vendor-specific logic. Adding a vendor is a YAML file, not a Python class.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoBaseException,
    NetmikoTimeoutException,
)

from tidemark.core.credentials import Credentials
from tidemark.core.models import Device, VendorProfile

logger = logging.getLogger(__name__)


class DriverError(RuntimeError):
    """Raised for connection and fetch errors that callers should catch."""


@dataclass
class FetchResult:
    """The raw text produced by ``Driver.fetch``."""

    text: str


class Driver:
    """Generic SSH driver. One class, many profiles."""

    def __init__(
        self,
        device: Device,
        profile: VendorProfile,
        credentials: Credentials,
        *,
        connect_timeout: int = 20,
    ) -> None:
        self._device = device
        self._profile = profile
        self._credentials = credentials
        self._connect_timeout = connect_timeout

    def _connect(self) -> ConnectHandler:
        kwargs: dict = {
            "device_type": self._profile.netmiko_device_type,
            "host": self._device.host,
            "port": self._device.port,
            "username": self._credentials.username,
            "password": self._credentials.password,
            "conn_timeout": self._connect_timeout,
        }
        if self._profile.requires_enable:
            kwargs["secret"] = self._credentials.password
        try:
            return ConnectHandler(**kwargs)
        except NetmikoAuthenticationException as exc:
            raise DriverError(f"authentication failed for {self._device.host}") from exc
        except NetmikoTimeoutException as exc:
            raise DriverError(f"timeout connecting to {self._device.host}") from exc
        except NetmikoBaseException as exc:
            raise DriverError(f"connection error: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - netmiko can raise a variety
            raise DriverError(f"unexpected connection error: {exc}") from exc

    def fetch(self) -> FetchResult:
        """Open a connection, run pre_commands, run fetch_commands, concatenate."""
        conn = self._connect()
        try:
            if self._profile.requires_enable:
                try:
                    conn.enable()
                except Exception as exc:  # noqa: BLE001
                    raise DriverError(f"enable failed: {exc}") from exc

            for cmd in self._profile.pre_commands:
                conn.send_command(cmd, read_timeout=30)

            chunks: list[str] = []
            for cmd in self._profile.fetch_commands:
                chunks.append(conn.send_command(cmd, read_timeout=60))

            text = "\n".join(chunks)

            for pattern in self._profile.invalid_patterns:
                if re.search(pattern, text):
                    raise DriverError(
                        f"output matched invalid pattern {pattern!r}"
                    )

            if len(text) < self._profile.min_length:
                raise DriverError(
                    f"output shorter than min_length "
                    f"({len(text)} < {self._profile.min_length})"
                )

            return FetchResult(text=text)
        finally:
            try:
                conn.disconnect()
            except Exception:  # noqa: BLE001
                pass
