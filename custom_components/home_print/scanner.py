"""The eSCL scanner attached to a printer config entry."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.helpers.event import async_call_later

from .const import CONF_HOST, CONF_SCANNER_URL, CONF_SSL, CONF_VERIFY_SSL
from .escl.client import EsclClient, EsclError, find_scanner
from .escl.models import ScannerCaps, ScannerStatus
from .scans import ScanArchive

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .scanning import ScanJobState

_LOGGER = logging.getLogger(__name__)

# A slow scanner must not stall printer polling.
STATUS_TIMEOUT = 5  # seconds
# Per candidate URL while setting up; a missing scanner must not slow setup.
DETECT_TIMEOUT = 5  # seconds
# When no scanner answered at setup (asleep, or no scanner at all).
RETRY_DELAYS = (60, 300, 1800)  # seconds
RETRY_INTERVAL = 3600  # seconds, after RETRY_DELAYS

_ERRORS = (EsclError, aiohttp.ClientError, TimeoutError, OSError)


@dataclass
class ScannerRuntime:
    """Everything the integration needs to talk to one entry's scanner."""

    client: EsclClient
    caps: ScannerCaps
    archive: ScanArchive
    status: ScannerStatus | None = None
    # The running (or recently finished) scan; owned by scanning.py.
    active: ScanJobState | None = None
    # Keeps a background scan task referenced while it runs.
    task: asyncio.Task[Any] | None = None


def scanner_verify_ssl(entry: ConfigEntry) -> bool:
    """Whether to verify the scanner's https certificate.

    HP printers answer eSCL over https (or redirect there) with a self-signed
    certificate. An entry that prints over plain IPP never chose https, so its
    scanner's certificate is not verified; an IPPS entry keeps its setting.
    """
    return bool(entry.data[CONF_SSL]) and bool(entry.data[CONF_VERIFY_SSL])


async def _async_detect(
    entry: ConfigEntry, session: aiohttp.ClientSession, warn: bool
) -> tuple[EsclClient, ScannerCaps] | None:
    """Find the entry's scanner and read its capabilities; None if there is none.

    A printer without a scanner is normal and silent. Only an address the
    user typed in is worth a warning (``warn``) when it doesn't answer.
    """
    verify_ssl = scanner_verify_ssl(entry)
    manual = str(entry.options.get(CONF_SCANNER_URL) or "").strip()
    try:
        if manual:
            client = EsclClient(manual, session, verify_ssl)
            async with asyncio.timeout(DETECT_TIMEOUT):
                caps = await client.capabilities()
            return client, caps
        found = await find_scanner(
            session,
            entry.data[CONF_HOST],
            bool(entry.data[CONF_SSL]),
            verify_ssl,
            timeout=DETECT_TIMEOUT,
        )
        if found is None:
            return None
        url, caps = found
        return EsclClient(url, session, verify_ssl), caps
    except _ERRORS as err:
        if manual:
            log = _LOGGER.warning if warn else _LOGGER.debug
            log("Scanner at %s could not be read: %s", manual, err)
        return None
    except Exception:  # noqa: BLE001 - a scanner must never fail the entry
        _LOGGER.debug("Unexpected error while setting up the scanner", exc_info=True)
        return None


def _retry_delays() -> Iterator[int]:
    yield from RETRY_DELAYS
    while True:
        yield RETRY_INTERVAL


@callback
def _async_schedule_retry(
    hass: HomeAssistant, entry: ConfigEntry, session: aiohttp.ClientSession
) -> None:
    """Look for the scanner again later (it may have been asleep).

    Each attempt waits on a timer and runs as an entry background task, so
    nothing lingers between attempts; unloading cancels both. Once a scanner
    answers the entry is reloaded.
    """
    delays = _retry_delays()
    cancel_timer: CALLBACK_TYPE | None = None

    async def attempt() -> None:
        if await _async_detect(entry, session, warn=False) is not None:
            _LOGGER.info("Scanner found for %s; reloading", entry.title)
            hass.config_entries.async_schedule_reload(entry.entry_id)
            return
        schedule()

    @callback
    def fire(_now: Any) -> None:
        nonlocal cancel_timer
        cancel_timer = None
        entry.async_create_background_task(
            hass, attempt(), f"home_print scanner detection {entry.entry_id}"
        )

    def schedule() -> None:
        nonlocal cancel_timer
        cancel_timer = async_call_later(hass, next(delays), fire)

    @callback
    def stop() -> None:
        if cancel_timer is not None:
            cancel_timer()

    entry.async_on_unload(stop)
    schedule()


async def async_setup_scanner(
    hass: HomeAssistant, entry: ConfigEntry, session: aiohttp.ClientSession
) -> ScannerRuntime | None:
    """Find the entry's scanner; None when there is none or it can't be read.

    When no scanner answers, detection is retried in the background
    (``RETRY_DELAYS``, then hourly) and the entry reloads once one does.
    """
    detected = await _async_detect(entry, session, warn=True)
    if detected is None:
        _async_schedule_retry(hass, entry, session)
        return None
    client, caps = detected

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
