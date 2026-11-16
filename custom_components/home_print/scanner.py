"""The eSCL scanner attached to a printer config entry."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import aiohttp

from .const import CONF_HOST, CONF_SCANNER_URL, CONF_SSL, CONF_VERIFY_SSL
from .escl.client import EsclClient, EsclError, find_scanner
from .escl.models import ScannerCaps, ScannerStatus
from .scans import ScanArchive

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# A slow scanner must not stall printer polling.
STATUS_TIMEOUT = 5  # seconds

_ERRORS = (EsclError, aiohttp.ClientError, TimeoutError, OSError)


@dataclass
class ScannerRuntime:
    """Everything the integration needs to talk to one entry's scanner."""

    client: EsclClient
    caps: ScannerCaps
    archive: ScanArchive
    status: ScannerStatus | None = None
    # ScanJobState of the running scan; owned by scanning.py (Task 5).
    active: Any = None
    # Keeps a background scan task referenced while it runs.
    task: asyncio.Task[Any] | None = None


async def async_setup_scanner(
    hass: HomeAssistant, entry: ConfigEntry, session: aiohttp.ClientSession
) -> ScannerRuntime | None:
    """Find the entry's scanner; None when there is none or it can't be read.

    A printer without a scanner is normal and silent. Only an address the
    user typed in is worth one warning when it doesn't answer.
    """
    verify_ssl = bool(entry.data[CONF_VERIFY_SSL])
    manual = str(entry.options.get(CONF_SCANNER_URL) or "").strip()
    try:
        url = manual or await find_scanner(
            session, entry.data[CONF_HOST], bool(entry.data[CONF_SSL]), verify_ssl
        )
        if not url:
            return None
        client = EsclClient(url, session, verify_ssl)
        caps = await client.capabilities()
    except _ERRORS as err:
        if manual:
            _LOGGER.warning("Scanner at %s could not be read: %s", manual, err)
        return None
    except Exception:  # noqa: BLE001 - a scanner must never fail the entry
        _LOGGER.debug("Unexpected error while setting up the scanner", exc_info=True)
        return None

    try:
        archive = ScanArchive(hass, entry)
        await archive.async_load()
        await archive.async_cleanup()
    except Exception as err:  # noqa: BLE001 - a scanner must never fail the entry
        _LOGGER.warning("Scan archive of the scanner could not be loaded: %s", err)
        return None
    return ScannerRuntime(client=client, caps=caps, archive=archive)


async def async_fetch_status(scanner: ScannerRuntime) -> ScannerStatus | None:
    """Read the scanner status; any failure gives None."""
    try:
        async with asyncio.timeout(STATUS_TIMEOUT):
            return await scanner.client.status()
    except _ERRORS:
        return None
    except Exception:  # noqa: BLE001 - scanner trouble must not reach the printer
        _LOGGER.debug("Unexpected error while reading scanner status", exc_info=True)
        return None


async def async_refresh_status(scanner: ScannerRuntime) -> None:
    """Update ``scanner.status``; any failure leaves it None."""
    scanner.status = await async_fetch_status(scanner)
