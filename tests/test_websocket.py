"""Tests for the dashboard card's WebSocket commands."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.home_print.client import CannotConnect, parse_printer
from custom_components.home_print.const import CONF_ADMIN_ONLY, CONF_MAX_FILE_MB
from custom_components.home_print.models import JobStatus

from .common import make_entry, setup_entry

DESKJET = parse_printer(
    json.loads(
        (Path(__file__).parent / "fixtures/printer_hp_deskjet_4670.json").read_text()
    )
)


def _setup_deskjet(mock_client):
    mock_client.get_printer.return_value = DESKJET


async def _printers(hass, hass_ws_client, user=None):
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "home_print/printers"})
    msg = await ws.receive_json()
    assert msg["success"], msg
    return msg["result"]["printers"]


async def test_printers_lists_loaded_entry(hass, mock_client, hass_ws_client):
    _setup_deskjet(mock_client)
    entry = await setup_entry(hass)
    reg = er.async_get(hass)
    by_uid = {
        e.unique_id: e.entity_id
        for e in er.async_entries_for_config_entry(reg, entry.entry_id)
    }
    ident = entry.unique_id
    [printer] = await _printers(hass, hass_ws_client)
    assert printer["entry_id"] == entry.entry_id
    assert printer["title"] == "Printer"
    assert printer["available"] is True
    assert printer["can_print"] is True
    assert printer["state"] == "idle"
    assert printer["max_file_mb"] == 25
    ents = printer["entities"]
    assert ents["status"] == by_uid[f"{ident}_status"]
    assert ents["problem"] == by_uid[f"{ident}_problem"]
    assert ents["last_job"] == by_uid[f"{ident}_last_job"]
    assert ents["markers"] == [
        by_uid[f"{ident}_marker_{i}"] for i in range(len(DESKJET.markers))
    ]
    assert ents["markers"]
    caps = printer["capabilities"]
    assert caps["formats"] == ["application/pdf", "image/jpeg", "image/png"]
    assert caps["sides"] == sorted(DESKJET.capabilities.sides)
    assert caps["color_modes"] == sorted(DESKJET.capabilities.color_modes)
    assert caps["copies_max"] == 99
    assert caps["page_ranges_passthrough"] is DESKJET.capabilities.page_ranges
    assert printer["defaults"] == {
        "sides": "one-sided",
        "color_mode": None,
    }


async def test_printers_uses_entry_options(hass, mock_client, hass_ws_client):
    _setup_deskjet(mock_client)
    entry = make_entry(**{CONF_MAX_FILE_MB: 10})
    await setup_entry(hass, entry)
    [printer] = await _printers(hass, hass_ws_client)
    assert printer["max_file_mb"] == 10


async def test_printers_offline_entry(hass, mock_client, hass_ws_client):
    _setup_deskjet(mock_client)
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data.coordinator
    mock_client.get_printer.side_effect = CannotConnect("down")
    await coordinator.async_refresh()
    assert isinstance(coordinator.last_exception, UpdateFailed)
    [printer] = await _printers(hass, hass_ws_client)
    assert printer["available"] is False
    assert printer["capabilities"]["formats"] == [
        "application/pdf",
        "image/jpeg",
        "image/png",
    ]
    assert printer["capabilities"]["copies_max"] == 99


async def test_printers_skips_unloaded_entries(hass, mock_client, hass_ws_client):
    _setup_deskjet(mock_client)
    entry = await setup_entry(hass)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await _printers(hass, hass_ws_client) == []


async def test_printers_admin_only_non_admin_can_print_false(
    hass, mock_client, hass_ws_client, hass_read_only_access_token
):
    _setup_deskjet(mock_client)
    await setup_entry(hass, make_entry(**{CONF_ADMIN_ONLY: True}))
    ws = await hass_ws_client(hass, hass_read_only_access_token)
    await ws.send_json({"id": 1, "type": "home_print/printers"})
    msg = await ws.receive_json()
    assert msg["success"]
    [printer] = msg["result"]["printers"]
    assert printer["can_print"] is False


async def test_printers_admin_only_admin_can_print(hass, mock_client, hass_ws_client):
    _setup_deskjet(mock_client)
    await setup_entry(hass, make_entry(**{CONF_ADMIN_ONLY: True}))
    [printer] = await _printers(hass, hass_ws_client)
    assert printer["can_print"] is True


async def test_job_returns_status(hass, mock_client, hass_ws_client):
    entry = await setup_entry(hass)
    mock_client.get_job = AsyncMock(
        return_value=JobStatus(
            job_id=42,
            state="processing",
            reasons=("job-printing",),
            impressions=1,
            sheets=None,
        )
    )
    ws = await hass_ws_client(hass)
    await ws.send_json(
        {"id": 1, "type": "home_print/job", "entry_id": entry.entry_id, "job_id": 42}
    )
    msg = await ws.receive_json()
    assert msg["success"], msg
    assert msg["result"] == {
        "job": {
            "job_id": 42,
            "state": "processing",
            "reasons": ["job-printing"],
            "impressions": 1,
            "sheets": None,
        }
    }
    mock_client.get_job.assert_awaited_once_with(42)


async def test_job_unknown_entry_not_found(hass, mock_client, hass_ws_client):
    await setup_entry(hass)
    ws = await hass_ws_client(hass)
    await ws.send_json(
        {"id": 1, "type": "home_print/job", "entry_id": "nope", "job_id": 1}
    )
    msg = await ws.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"


async def test_job_unloaded_entry_not_found(hass, mock_client, hass_ws_client):
    entry = await setup_entry(hass)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    ws = await hass_ws_client(hass)
    await ws.send_json(
        {"id": 1, "type": "home_print/job", "entry_id": entry.entry_id, "job_id": 1}
    )
    msg = await ws.receive_json()
    assert msg["error"]["code"] == "not_found"


async def test_job_printer_offline(hass, mock_client, hass_ws_client):
    entry = await setup_entry(hass)
    mock_client.get_job = AsyncMock(side_effect=CannotConnect("down"))
    ws = await hass_ws_client(hass)
    await ws.send_json(
        {"id": 1, "type": "home_print/job", "entry_id": entry.entry_id, "job_id": 1}
    )
    msg = await ws.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "printer_unavailable"


async def test_job_admin_only_non_admin_unauthorized(
    hass, mock_client, hass_ws_client, hass_read_only_access_token
):
    entry = await setup_entry(hass, make_entry(**{CONF_ADMIN_ONLY: True}))
    mock_client.get_job = AsyncMock()
    ws = await hass_ws_client(hass, hass_read_only_access_token)
    await ws.send_json(
        {"id": 1, "type": "home_print/job", "entry_id": entry.entry_id, "job_id": 1}
    )
    msg = await ws.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "unauthorized"
    mock_client.get_job.assert_not_awaited()
