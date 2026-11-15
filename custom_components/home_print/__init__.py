"""Home Print: print to network IPP printers from Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import HomePrintClient
from .const import (
    CONF_BASE_PATH,
    CONF_HOST,
    CONF_PORT,
    CONF_SSL,
    CONF_VERIFY_SSL,
)
from .coordinator import HomePrintCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]


@dataclass
class HomePrintData:
    """Runtime data stored on the config entry."""

    client: HomePrintClient
    coordinator: HomePrintCoordinator


type HomePrintConfigEntry = ConfigEntry[HomePrintData]


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

    entry.runtime_data = HomePrintData(client=client, coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HomePrintConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(
    hass: HomeAssistant, entry: HomePrintConfigEntry
) -> None:
    """Reload so a changed scan interval takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)
