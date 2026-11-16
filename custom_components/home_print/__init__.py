"""Home Print: print to network IPP printers from Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .client import HomePrintClient
from .const import (
    CONF_BASE_PATH,
    CONF_HOST,
    CONF_PORT,
    CONF_SSL,
    CONF_VERIFY_SSL,
    DOMAIN,
)
from .coordinator import HomePrintCoordinator
from .frontend import async_register_frontend
from .history import PrintHistory
from .http import HomePrintUploadView
from .preview import HomePrintPreviewView
from .services import async_setup_services
from .websocket import async_setup_websocket

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Expired records and kept files are removed at least this often.
HISTORY_CLEANUP_INTERVAL = timedelta(hours=6)


@dataclass
class HomePrintData:
    """Runtime data stored on the config entry."""

    client: HomePrintClient
    coordinator: HomePrintCoordinator
    history: PrintHistory


type HomePrintConfigEntry = ConfigEntry[HomePrintData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the service and the upload view once for all entries."""
    async_setup_services(hass)
    async_setup_websocket(hass)
    hass.http.register_view(HomePrintUploadView())
    hass.http.register_view(HomePrintPreviewView())
    await async_register_frontend(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HomePrintConfigEntry) -> bool:
    """Set up Home Print from a config entry."""
    session = async_get_clientsession(hass, verify_ssl=entry.data[CONF_VERIFY_SSL])
    client = HomePrintClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_BASE_PATH],
        entry.data[CONF_SSL],
        entry.data[CONF_VERIFY_SSL],
        session,
    )
    coordinator = HomePrintCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    history = PrintHistory(hass, entry)
    await history.async_load()
    await history.async_cleanup()

    entry.runtime_data = HomePrintData(
        client=client, coordinator=coordinator, history=history
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    entry.async_on_unload(
        async_track_time_interval(hass, history.async_cleanup, HISTORY_CLEANUP_INTERVAL)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HomePrintConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        # A reload must not lose records still waiting for the delayed save.
        await entry.runtime_data.history.async_flush()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: HomePrintConfigEntry) -> None:
    """Delete the entry's history file and its kept files."""
    await PrintHistory(hass, entry).async_remove()


async def _async_options_updated(
    hass: HomeAssistant, entry: HomePrintConfigEntry
) -> None:
    """Reload so changed options (scan interval, kept days) take effect."""
    await hass.config_entries.async_reload(entry.entry_id)
