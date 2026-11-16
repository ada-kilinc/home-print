"""WebSocket commands used by the Home Print dashboard card."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .client import CannotConnect, HomePrintError
from .const import CONF_ADMIN_ONLY, CONF_DEFAULT_COLOR_MODE, CONF_DEFAULT_SIDES, DOMAIN
from .convert.pipeline import accepted_formats
from .printing import COLOR_AUTO, max_file_mb

if TYPE_CHECKING:
    from . import HomePrintConfigEntry


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register the card's WebSocket commands."""
    websocket_api.async_register_command(hass, ws_printers)
    websocket_api.async_register_command(hass, ws_job)


def _loaded_entries(hass: HomeAssistant) -> list[HomePrintConfigEntry]:
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]


def _can_print(entry: HomePrintConfigEntry, connection: Any) -> bool:
    user = connection.user
    return not entry.options.get(CONF_ADMIN_ONLY) or bool(user and user.is_admin)


def _entities(hass: HomeAssistant, entry: HomePrintConfigEntry) -> dict[str, Any]:
    ident = entry.unique_id or entry.entry_id
    by_uid = {
        e.unique_id: e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    prefix = f"{ident}_marker_"
    markers = sorted(
        (int(uid[len(prefix) :]), entity_id)
        for uid, entity_id in by_uid.items()
        if uid.startswith(prefix) and uid[len(prefix) :].isdigit()
    )
    return {
        "status": by_uid.get(f"{ident}_status"),
        "problem": by_uid.get(f"{ident}_problem"),
        "last_job": by_uid.get(f"{ident}_last_job"),
        "markers": [entity_id for _, entity_id in markers],
    }


def _printer(
    hass: HomeAssistant, entry: HomePrintConfigEntry, connection: Any
) -> dict[str, Any]:
    coordinator = entry.runtime_data.coordinator
    info = coordinator.data
    capabilities = None
    if info is not None:
        caps = info.capabilities
        capabilities = {
            "formats": sorted(accepted_formats(caps)),
            "sides": sorted(caps.sides),
            "color_modes": sorted(caps.color_modes),
            "copies_max": caps.copies_max,
            "page_ranges_passthrough": caps.page_ranges,
        }
    color_mode = entry.options.get(CONF_DEFAULT_COLOR_MODE)
    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "available": coordinator.last_update_success,
        "can_print": _can_print(entry, connection),
        "state": info.state if info is not None else None,
        "entities": _entities(hass, entry),
        "capabilities": capabilities,
        "defaults": {
            "sides": entry.options.get(CONF_DEFAULT_SIDES) or "one-sided",
            "color_mode": None if color_mode in (None, COLOR_AUTO) else color_mode,
        },
        "max_file_mb": max_file_mb(entry),
    }


@websocket_api.websocket_command({vol.Required("type"): "home_print/printers"})
@callback
def ws_printers(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """List the loaded printers with what the card needs to render."""
    connection.send_result(
        msg["id"],
        {
            "printers": [
                _printer(hass, entry, connection) for entry in _loaded_entries(hass)
            ]
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_print/job",
        vol.Required("entry_id"): str,
        vol.Required("job_id"): vol.All(int, vol.Range(min=0)),
    }
)
@websocket_api.async_response
async def ws_job(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the live state of one job."""
    entry = next(
        (e for e in _loaded_entries(hass) if e.entry_id == msg["entry_id"]), None
    )
    if entry is None:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Printer not found"
        )
        return
    if not _can_print(entry, connection):
        connection.send_error(
            msg["id"], websocket_api.ERR_UNAUTHORIZED, "Administrator required"
        )
        return
    try:
        job = await entry.runtime_data.client.get_job(msg["job_id"])
    except CannotConnect:
        connection.send_error(
            msg["id"], "printer_unavailable", "The printer could not be reached"
        )
        return
    except HomePrintError as err:
        connection.send_error(msg["id"], "printer_error", str(err))
        return
    connection.send_result(
        msg["id"],
        {
            "job": {
                "job_id": job.job_id,
                "state": job.state,
                "reasons": list(job.reasons),
                "impressions": job.impressions,
                "sheets": job.sheets,
            }
        },
    )
