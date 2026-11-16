"""WebSocket commands used by the Home Print dashboard card."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .client import CannotConnect, HomePrintError, PrinterRejected
from .const import CONF_ADMIN_ONLY, CONF_DEFAULT_COLOR_MODE, CONF_DEFAULT_SIDES, DOMAIN
from .convert.pipeline import accepted_formats
from .printing import COLOR_AUTO, max_file_mb

if TYPE_CHECKING:
    from . import HomePrintConfigEntry


_FINAL_JOB_STATES = ("completed", "aborted", "canceled")


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register the card's WebSocket commands."""
    websocket_api.async_register_command(hass, ws_printers)
    websocket_api.async_register_command(hass, ws_job)
    websocket_api.async_register_command(hass, ws_history)
    websocket_api.async_register_command(hass, ws_history_delete)


def _loaded_entries(hass: HomeAssistant) -> list[HomePrintConfigEntry]:
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]


# Entries the card lists. A printer that was off while Home Assistant started
# sits in SETUP_RETRY; the card shows it as unreachable instead of missing.
_LISTED_STATES = (
    ConfigEntryState.LOADED,
    ConfigEntryState.SETUP_RETRY,
    ConfigEntryState.SETUP_IN_PROGRESS,
)


def _listed_entries(hass: HomeAssistant) -> list[HomePrintConfigEntry]:
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state in _LISTED_STATES
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


def _defaults(entry: HomePrintConfigEntry) -> dict[str, Any]:
    color_mode = entry.options.get(CONF_DEFAULT_COLOR_MODE)
    return {
        "sides": entry.options.get(CONF_DEFAULT_SIDES) or "one-sided",
        "color_mode": None if color_mode in (None, COLOR_AUTO) else color_mode,
    }


def _printer(
    hass: HomeAssistant, entry: HomePrintConfigEntry, connection: Any
) -> dict[str, Any]:
    if entry.state is not ConfigEntryState.LOADED:
        # Not set up yet (printer off at start-up): no client, no data.
        return {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "available": False,
            "can_print": _can_print(entry, connection),
            "state": None,
            "entities": _entities(hass, entry),
            "capabilities": None,
            "defaults": _defaults(entry),
            "max_file_mb": max_file_mb(entry),
        }
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
    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "available": coordinator.last_update_success,
        "can_print": _can_print(entry, connection),
        "state": info.state if info is not None else None,
        "entities": _entities(hass, entry),
        "capabilities": capabilities,
        "defaults": _defaults(entry),
        "max_file_mb": max_file_mb(entry),
    }


@websocket_api.websocket_command({vol.Required("type"): "home_print/printers"})
@callback
def ws_printers(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """List the printers with what the card needs to render."""
    connection.send_result(
        msg["id"],
        {
            "printers": [
                _printer(hass, entry, connection) for entry in _listed_entries(hass)
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
    except PrinterRejected as err:
        if "not-found" in err.status:
            # Finished jobs drop off the printer's list after a while.
            connection.send_error(
                msg["id"], "job_gone", "The printer no longer lists the job"
            )
        else:
            connection.send_error(msg["id"], "printer_error", str(err))
        return
    except HomePrintError as err:
        connection.send_error(msg["id"], "printer_error", str(err))
        return
    if job.state in _FINAL_JOB_STATES:
        entry.runtime_data.history.update_state(job.job_id, job.state)
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


def _history_entry(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> HomePrintConfigEntry | None:
    entry = next(
        (e for e in _loaded_entries(hass) if e.entry_id == msg["entry_id"]), None
    )
    if entry is None:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Printer not found"
        )
    return entry


@websocket_api.websocket_command(
    {vol.Required("type"): "home_print/history", vol.Required("entry_id"): str}
)
@websocket_api.async_response
async def ws_history(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the printer's print history, newest first.

    Unknown page counts are read from kept files (in the executor) and cached.
    """
    if (entry := _history_entry(hass, connection, msg)) is None:
        return
    entries = await entry.runtime_data.history.async_entries()
    connection.send_result(msg["id"], {"entries": entries})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_print/history/delete",
        vol.Required("entry_id"): str,
        vol.Required("history_id"): str,
    }
)
@websocket_api.async_response
async def ws_history_delete(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete one history record and its kept file."""
    if (entry := _history_entry(hass, connection, msg)) is None:
        return
    if not _can_print(entry, connection):
        connection.send_error(
            msg["id"], websocket_api.ERR_UNAUTHORIZED, "Administrator required"
        )
        return
    deleted = await entry.runtime_data.history.async_delete(msg["history_id"])
    connection.send_result(msg["id"], {"deleted": deleted})
