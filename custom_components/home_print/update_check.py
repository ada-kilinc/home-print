"""Notice when Home Print was updated on disk but Home Assistant still runs the old one.

HACS (the Marketplace) writes the new files at once, but Home Assistant keeps
running the version it loaded at start-up until it restarts. Until then the
card is served for the old version too, so nothing seems to change. This
compares manifest.json on disk with the loaded version every few minutes
and, while they differ, raises a repair ("restart to finish the update")
and tells the card (home_print/printers ``restart_required``).
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.loader import async_get_integration

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CHECK_INTERVAL = timedelta(minutes=5)
ISSUE_ID = "restart_required"
# The version found on disk while it differs from the running one, else None.
DATA_INSTALLED = f"{DOMAIN}_installed_version"
_STARTED = f"{DOMAIN}_update_check"
_MANIFEST = Path(__file__).parent / "manifest.json"


def _read_disk_version() -> str | None:
    try:
        return str(json.loads(_MANIFEST.read_text(encoding="utf-8"))["version"])
    except (OSError, ValueError, KeyError, TypeError):
        # Mid-update the file may be missing or half written: try again later.
        return None


async def async_check_installed(hass: HomeAssistant) -> str | None:
    """Compare disk and running versions; returns the pending one, if any."""
    running = str((await async_get_integration(hass, DOMAIN)).version)
    disk = await hass.async_add_executor_job(_read_disk_version)
    pending = disk if disk and disk != running else None
    if pending == hass.data.get(DATA_INSTALLED):
        return pending
    hass.data[DATA_INSTALLED] = pending
    if pending:
        _LOGGER.info(
            "Home Print %s is installed but %s is running; restart Home Assistant",
            pending,
            running,
        )
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_ID,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_ID,
            translation_placeholders={"installed": pending, "running": running},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_ID)
    return pending


async def async_setup_update_check(hass: HomeAssistant) -> None:
    """Check now and every CHECK_INTERVAL (once per Home Assistant run)."""
    if hass.data.get(_STARTED):
        return
    hass.data[_STARTED] = True
    await async_check_installed(hass)

    @callback
    def _tick(_now: Any) -> None:
        hass.async_create_background_task(
            async_check_installed(hass), f"{DOMAIN} update check"
        )

    async_track_time_interval(hass, _tick, CHECK_INTERVAL)
