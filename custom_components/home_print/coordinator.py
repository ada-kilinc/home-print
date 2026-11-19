"""Data update coordinator for Home Print."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import CannotConnect, HomePrintClient, HomePrintError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .escl.models import ScannerStatus
from .models import LastJob, PrinterInfo
from .scanner import ScannerRuntime, async_fetch_status

if TYPE_CHECKING:
    from . import HomePrintConfigEntry

_LOGGER = logging.getLogger(__name__)


class HomePrintCoordinator(DataUpdateCoordinator[PrinterInfo]):
    """Poll the printer for state, reasons and marker levels."""

    config_entry: HomePrintConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HomePrintConfigEntry,
        client: HomePrintClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        self.last_job: LastJob | None = None
        # Set by async_setup_entry once a scanner was found.
        self.scanner: ScannerRuntime | None = None

    async def _async_update_data(self) -> PrinterInfo:
        scanner = self.scanner
        # Ask the scanner at the same time so it adds no latency; its answer
        # is dropped when the printer fails.
        status_task = (
            asyncio.ensure_future(async_fetch_status(scanner)) if scanner else None
        )
        try:
            info = await self.client.get_printer()
        except BaseException as err:
            if status_task is not None:
                status_task.cancel()
            if scanner is not None:
                # An unreachable printer's scanner is unreachable too.
                scanner.status = None
            if isinstance(err, CannotConnect):
                raise UpdateFailed(f"Printer unreachable: {err}") from err
            if isinstance(err, HomePrintError):
                raise UpdateFailed(f"Printer error: {err}") from err
            raise
        if scanner is not None and status_task is not None:
            scanner.status = await status_task
        return info

    def async_set_last_job(self, job: LastJob) -> None:
        """Record the latest submitted job and notify entities."""
        self.last_job = job
        self.async_update_listeners()


class ScannerCoordinator(DataUpdateCoordinator[ScannerStatus]):
    """Poll a scanner that has no printer (a scanner-only entry)."""

    config_entry: HomePrintConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HomePrintConfigEntry,
        scanner: ScannerRuntime,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.scanner: ScannerRuntime | None = scanner
        self.last_job: LastJob | None = None

    async def _async_update_data(self) -> ScannerStatus:
        assert self.scanner is not None
        status = await async_fetch_status(self.scanner)
        self.scanner.status = status
        if status is None:
            raise UpdateFailed("Scanner unreachable")
        return status
