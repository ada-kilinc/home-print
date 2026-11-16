"""Serve the Home Print dashboard card and load it in the HA frontend."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend as ha_frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from ..const import DOMAIN

URL_BASE = "/home_print_static"
CARD_FILE = "home-print-card.js"
_REGISTERED = f"{DOMAIN}_frontend_registered"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Register the static path and auto-load the card (only once)."""
    if hass.data.get(_REGISTERED):
        return
    hass.data[_REGISTERED] = True
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(URL_BASE, str(Path(__file__).parent), cache_headers=False)]
    )
    ha_frontend.add_extra_js_url(
        hass, f"{URL_BASE}/{CARD_FILE}?v={integration.version}"
    )
