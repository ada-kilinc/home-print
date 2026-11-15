"""Data update coordinator for Home Print."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import CannotConnect, HomePrintClient, HomePrintError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .models import LastJob, PrinterInfo

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

    async def _async_update_data(self) -> PrinterInfo:
        try:
            return await self.client.get_printer()
        except CannotConnect as err:
            raise UpdateFailed(f"Printer unreachable: {err}") from err
        except HomePrintError as err:
            raise UpdateFailed(f"Printer error: {err}") from err

    def async_set_last_job(self, job: LastJob) -> None:
        """Record the latest submitted job and notify entities."""
        self.last_job = job
        self.async_update_listeners()
