"""Tests for the dashboard card's WebSocket commands."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.home_print.client import (
    CannotConnect,
    PrinterRejected,
    parse_printer,
)
from custom_components.home_print.const import CONF_ADMIN_ONLY, CONF_MAX_FILE_MB
from custom_components.home_print.models import JobStatus

from .common import make_entry, setup_entry
from .convert.samples import blank_pdf

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


async def test_printers_lists_setup_retry_entry(hass, mock_client, hass_ws_client):
    """A printer that is off while HA starts is listed as unreachable."""
    _setup_deskjet(mock_client)
    entry = await setup_entry(hass, make_entry(**{CONF_MAX_FILE_MB: 10}))
    reg = er.async_get(hass)
    by_uid = {
        e.unique_id: e.entity_id
        for e in er.async_entries_for_config_entry(reg, entry.entry_id)
    }
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    mock_client.get_printer.side_effect = CannotConnect("down")
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY

    [printer] = await _printers(hass, hass_ws_client)
    ident = entry.unique_id
    assert printer == {
        "entry_id": entry.entry_id,
        "kind": "printer",
        "title": "Printer",
        "available": False,
        "can_print": True,
        "state": None,
        "entities": {
            "status": by_uid[f"{ident}_status"],
            "scanner_status": None,
            "problem": by_uid[f"{ident}_problem"],
            "last_job": by_uid[f"{ident}_last_job"],
            "markers": [
                by_uid[f"{ident}_marker_{i}"] for i in range(len(DESKJET.markers))
            ],
        },
        "capabilities": None,
        "defaults": {"sides": "one-sided", "color_mode": None},
        "max_file_mb": 10,
        "scanner": None,
    }

    ws = await hass_ws_client(hass)
    await ws.send_json(
        {"id": 2, "type": "home_print/job", "entry_id": entry.entry_id, "job_id": 1}
    )
    msg = await ws.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"


async def test_printers_never_loaded_retry_entry(hass, mock_client, hass_ws_client):
    mock_client.get_printer.side_effect = CannotConnect("down")
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    [printer] = await _printers(hass, hass_ws_client)
    assert printer["available"] is False
    assert printer["capabilities"] is None
    assert printer["entities"] == {
        "status": None,
        "scanner_status": None,
        "problem": None,
        "last_job": None,
        "markers": [],
    }


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


async def _job_error(hass, hass_ws_client, entry_id, job_id=1):
    ws = await hass_ws_client(hass)
    await ws.send_json(
        {"id": 1, "type": "home_print/job", "entry_id": entry_id, "job_id": job_id}
    )
    msg = await ws.receive_json()
    assert not msg["success"]
    return msg["error"]["code"]


async def test_job_purged_by_printer_is_gone(hass, mock_client, hass_ws_client):
    """A finished job the printer already forgot is reported as job_gone."""
    entry = await setup_entry(hass)
    mock_client.get_job = AsyncMock(
        side_effect=PrinterRejected("client-error-not-found")
    )
    assert await _job_error(hass, hass_ws_client, entry.entry_id) == "job_gone"


async def test_job_other_rejection_is_printer_error(hass, mock_client, hass_ws_client):
    entry = await setup_entry(hass)
    mock_client.get_job = AsyncMock(
        side_effect=PrinterRejected("client-error-bad-request")
    )
    assert await _job_error(hass, hass_ws_client, entry.entry_id) == "printer_error"


async def test_job_negative_id_invalid_format(hass, mock_client, hass_ws_client):
    entry = await setup_entry(hass)
    mock_client.get_job = AsyncMock()
    code = await _job_error(hass, hass_ws_client, entry.entry_id, job_id=-1)
    assert code == "invalid_format"
    mock_client.get_job.assert_not_awaited()


async def _history_call(hass, hass_ws_client, msg_type, token=None, **fields):
    ws = await hass_ws_client(hass, token) if token else await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": f"home_print/{msg_type}", **fields})
    return await ws.receive_json()


def _add_history(entry, name, job_id=None, data=None):
    return entry.runtime_data.history.add(
        file_name=name,
        user="Ada",
        job_id=job_id,
        state="sent",
        pages=None,
        converted_to=None,
        error=None,
        data=data,
        mime="application/pdf" if data else None,
    )


async def test_history_counts_pages_from_kept_file(hass, mock_client, hass_ws_client):
    entry = await setup_entry(hass)
    _add_history(entry, "two.pdf", data=blank_pdf(2))
    _add_history(entry, "none.pdf")
    await hass.async_block_till_done()
    msg = await _history_call(hass, hass_ws_client, "history", entry_id=entry.entry_id)
    assert msg["success"], msg
    first, second = msg["result"]["entries"]
    assert first["file_name"] == "none.pdf"
    assert (first["pages"], first["file"]) == (None, False)
    assert (second["pages"], second["file"]) == (2, True)
    assert second["size"] > 0
    assert second["mime"] == "application/pdf"


async def test_history_delete_removes_file(hass, mock_client, hass_ws_client):
    entry = await setup_entry(hass)
    record = _add_history(entry, "one.pdf", data=blank_pdf(1))
    await hass.async_block_till_done()
    path = entry.runtime_data.history.file_path(record["id"])
    assert path.exists()
    msg = await _history_call(
        hass,
        hass_ws_client,
        "history/delete",
        entry_id=entry.entry_id,
        history_id=record["id"],
    )
    assert msg["result"] == {"deleted": True}
    assert not path.exists()


async def test_history_lists_newest_first(hass, mock_client, hass_ws_client):
    entry = await setup_entry(hass)
    _add_history(entry, "one.pdf")
    _add_history(entry, "two.pdf")
    msg = await _history_call(hass, hass_ws_client, "history", entry_id=entry.entry_id)
    assert msg["success"], msg
    assert [e["file_name"] for e in msg["result"]["entries"]] == [
        "two.pdf",
        "one.pdf",
    ]


async def test_history_unknown_entry_not_found(hass, mock_client, hass_ws_client):
    await setup_entry(hass)
    msg = await _history_call(hass, hass_ws_client, "history", entry_id="nope")
    assert msg["error"]["code"] == "not_found"
    msg = await _history_call(
        hass, hass_ws_client, "history/delete", entry_id="nope", history_id="x"
    )
    assert msg["error"]["code"] == "not_found"


async def test_history_delete(hass, mock_client, hass_ws_client):
    entry = await setup_entry(hass)
    record = _add_history(entry, "one.pdf")
    msg = await _history_call(
        hass,
        hass_ws_client,
        "history/delete",
        entry_id=entry.entry_id,
        history_id=record["id"],
    )
    assert msg["success"], msg
    assert msg["result"] == {"deleted": True}
    assert entry.runtime_data.history.entries() == []
    msg = await _history_call(
        hass,
        hass_ws_client,
        "history/delete",
        entry_id=entry.entry_id,
        history_id=record["id"],
    )
    assert msg["result"] == {"deleted": False}


async def test_history_admin_only_read_ok_delete_unauthorized(
    hass, mock_client, hass_ws_client, hass_read_only_access_token
):
    entry = await setup_entry(hass, make_entry(**{CONF_ADMIN_ONLY: True}))
    record = _add_history(entry, "one.pdf")
    msg = await _history_call(
        hass,
        hass_ws_client,
        "history",
        hass_read_only_access_token,
        entry_id=entry.entry_id,
    )
    assert msg["success"], msg
    assert len(msg["result"]["entries"]) == 1
    msg = await _history_call(
        hass,
        hass_ws_client,
        "history/delete",
        hass_read_only_access_token,
        entry_id=entry.entry_id,
        history_id=record["id"],
    )
    assert not msg["success"]
    assert msg["error"]["code"] == "unauthorized"
    assert len(entry.runtime_data.history.entries()) == 1


async def test_job_finished_updates_history(hass, mock_client, hass_ws_client):
    entry = await setup_entry(hass)
    record = _add_history(entry, "one.pdf", job_id=42)
    mock_client.get_job = AsyncMock(
        return_value=JobStatus(
            job_id=42, state="completed", reasons=(), impressions=1, sheets=None
        )
    )
    ws = await hass_ws_client(hass)
    await ws.send_json(
        {"id": 1, "type": "home_print/job", "entry_id": entry.entry_id, "job_id": 42}
    )
    assert (await ws.receive_json())["success"]
    [stored] = entry.runtime_data.history.entries()
    assert stored["id"] == record["id"]
    assert stored["state"] == "completed"


async def test_job_processing_keeps_history_state(hass, mock_client, hass_ws_client):
    entry = await setup_entry(hass)
    _add_history(entry, "one.pdf", job_id=42)
    mock_client.get_job = AsyncMock(
        return_value=JobStatus(
            job_id=42, state="processing", reasons=(), impressions=None, sheets=None
        )
    )
    ws = await hass_ws_client(hass)
    await ws.send_json(
        {"id": 1, "type": "home_print/job", "entry_id": entry.entry_id, "job_id": 42}
    )
    assert (await ws.receive_json())["success"]
    assert entry.runtime_data.history.entries()[0]["state"] == "sent"


async def test_job_gone_keeps_history_state(hass, mock_client, hass_ws_client):
    entry = await setup_entry(hass)
    _add_history(entry, "one.pdf", job_id=42)
    mock_client.get_job = AsyncMock(
        side_effect=PrinterRejected("client-error-not-found")
    )
    await _job_error(hass, hass_ws_client, entry.entry_id, job_id=42)
    assert entry.runtime_data.history.entries()[0]["state"] == "sent"


async def test_printers_reports_the_integration_version(
    hass, mock_client, hass_ws_client
):
    """The card compares it with its own and reloads after an update."""
    manifest = json.loads(
        (
            Path(__file__).parent.parent / "custom_components/home_print/manifest.json"
        ).read_text()
    )
    _setup_deskjet(mock_client)
    await setup_entry(hass)
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "home_print/printers"})
    msg = await ws.receive_json()
    assert msg["result"]["version"] == manifest["version"]
