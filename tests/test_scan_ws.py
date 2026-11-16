"""WebSocket commands for scanning."""

import asyncio

import pytest

from custom_components.home_print.const import CONF_ADMIN_ONLY
from custom_components.home_print.escl.errors import ScannerUnavailable
from custom_components.home_print.escl.models import ScannerStatus

from .common import scan_jpeg, setup_entry, setup_scanner_entry

BODY = {
    "source": "platen",
    "color_mode": "color",
    "resolution": 300,
    "format": "pdf",
}


@pytest.fixture
async def entry(hass, tmp_path, mock_client, mock_escl, mock_find_scanner):
    mock_escl.client.scan.return_value = [scan_jpeg()]
    return await setup_scanner_entry(hass, tmp_path, mock_find_scanner)


async def send(hass, hass_ws_client, type_, token=None, **data):
    ws = await hass_ws_client(hass, token) if token else await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": f"home_print/{type_}", **data})
    return await ws.receive_json()


async def test_printers_includes_scanner_block(hass, entry, hass_ws_client):
    entry.runtime_data.scanner.status = ScannerStatus("idle", True)
    msg = await send(hass, hass_ws_client, "printers")
    [printer] = msg["result"]["printers"]
    assert printer["scanner"] == {
        "available": True,
        "state": "idle",
        "adf_loaded": True,
        "sources": {"platen": {"color_modes": ["color"], "resolutions": [300]}},
        "formats": ["pdf", "jpeg"],
        "defaults": {
            "source": "platen",
            "color_mode": "color",
            "resolution": 300,
            "format": "pdf",
        },
        "active_scan_id": None,
    }


async def test_printers_scanner_unavailable_when_status_missing(
    hass, entry, hass_ws_client
):
    entry.runtime_data.scanner.status = None
    msg = await send(hass, hass_ws_client, "printers")
    scanner = msg["result"]["printers"][0]["scanner"]
    assert scanner["available"] is False
    assert scanner["state"] is None


async def test_printers_scanner_null_without_scanner(hass, mock_client, hass_ws_client):
    await setup_entry(hass)
    msg = await send(hass, hass_ws_client, "printers")
    assert msg["result"]["printers"][0]["scanner"] is None


async def test_start_and_poll_until_done(hass, entry, hass_ws_client):
    gate = asyncio.Event()

    async def scan(caps, settings, on_page=None):
        await gate.wait()
        on_page(1)
        return [scan_jpeg()]

    entry.runtime_data.scanner.client.scan = scan
    msg = await send(
        hass, hass_ws_client, "scan/start", entry_id=entry.entry_id, **BODY, name="x"
    )
    assert msg["success"], msg
    scan = msg["result"]["scan"]
    assert scan["state"] == "scanning"
    assert scan["pages"] == 0
    assert len(scan["scan_id"]) == 32

    printers = await send(hass, hass_ws_client, "printers")
    assert (
        printers["result"]["printers"][0]["scanner"]["active_scan_id"]
        == scan["scan_id"]
    )

    busy = await send(
        hass, hass_ws_client, "scan/start", entry_id=entry.entry_id, **BODY
    )
    assert busy["error"]["code"] == "scanner_busy"

    gate.set()
    await entry.runtime_data.scanner.task
    msg = await send(
        hass,
        hass_ws_client,
        "scan/state",
        entry_id=entry.entry_id,
        scan_id=scan["scan_id"],
    )
    done = msg["result"]["scan"]
    assert done["state"] == "done"
    assert done["record"]["name"] == "x"
    assert done["user"] == "Mock User"

    printers = await send(hass, hass_ws_client, "printers")
    assert printers["result"]["printers"][0]["scanner"]["active_scan_id"] is None

    msg = await send(hass, hass_ws_client, "scans", entry_id=entry.entry_id)
    assert [e["id"] for e in msg["result"]["entries"]] == [done["record"]["id"]]


async def test_start_error_codes(hass, entry, hass_ws_client):
    msg = await send(
        hass,
        hass_ws_client,
        "scan/start",
        entry_id=entry.entry_id,
        **{**BODY, "resolution": 600},
    )
    assert msg["error"]["code"] == "invalid_option"
    msg = await send(
        hass,
        hass_ws_client,
        "scan/start",
        entry_id=entry.entry_id,
        **BODY,
        append_to="f" * 32,
    )
    assert msg["error"]["code"] == "not_found"
    msg = await send(hass, hass_ws_client, "scan/start", entry_id="nope", **BODY)
    assert msg["error"]["code"] == "not_found"


async def test_failed_scan_reports_error_state(hass, entry, hass_ws_client):
    entry.runtime_data.scanner.client.scan.side_effect = ScannerUnavailable()
    msg = await send(
        hass, hass_ws_client, "scan/start", entry_id=entry.entry_id, **BODY
    )
    scan_id = msg["result"]["scan"]["scan_id"]
    await entry.runtime_data.scanner.task
    msg = await send(
        hass, hass_ws_client, "scan/state", entry_id=entry.entry_id, scan_id=scan_id
    )
    assert msg["result"]["scan"]["state"] == "error"
    assert msg["result"]["scan"]["error"] == "scanner_unavailable"


async def test_no_scanner_error(hass, mock_client, hass_ws_client):
    entry = await setup_entry(hass)
    for type_, extra in (
        ("scan/start", BODY),
        ("scan/state", {"scan_id": "a"}),
        ("scans", {}),
        ("scans/delete", {"scan_record_id": "a"}),
        ("scans/rename", {"scan_record_id": "a", "name": "b"}),
    ):
        msg = await send(hass, hass_ws_client, type_, entry_id=entry.entry_id, **extra)
        assert msg["error"]["code"] == "no_scanner", type_


async def test_admin_only_blocks_start_delete_rename(
    hass, tmp_path, mock_client, mock_escl, mock_find_scanner, hass_ws_client,
    hass_read_only_access_token,
):  # fmt: skip
    mock_escl.client.scan.return_value = [scan_jpeg()]
    entry = await setup_scanner_entry(
        hass, tmp_path, mock_find_scanner, **{CONF_ADMIN_ONLY: True}
    )
    record = await entry.runtime_data.scanner.archive.async_add(
        name="a", data=b"%PDF-1", mime="application/pdf", pages=1, user=None,
        source="platen", color_mode="color", resolution=300,
    )  # fmt: skip
    token = hass_read_only_access_token
    for type_, extra in (
        ("scan/start", BODY),
        ("scans/delete", {"scan_record_id": record["id"]}),
        ("scans/rename", {"scan_record_id": record["id"], "name": "b"}),
    ):
        msg = await send(
            hass, hass_ws_client, type_, token, entry_id=entry.entry_id, **extra
        )
        assert msg["error"]["code"] == "unauthorized", type_
    entry.runtime_data.scanner.client.scan.assert_not_called()
    assert len(entry.runtime_data.scanner.archive.entries()) == 1
    # Looking is allowed for everyone.
    msg = await send(hass, hass_ws_client, "scans", token, entry_id=entry.entry_id)
    assert msg["success"]
    assert len(msg["result"]["entries"]) == 1


async def test_rename_and_delete(hass, entry, hass_ws_client, tmp_path):
    archive = entry.runtime_data.scanner.archive
    record = await archive.async_add(
        name="a", data=b"%PDF-1", mime="application/pdf", pages=1, user=None,
        source="platen", color_mode="color", resolution=300,
    )  # fmt: skip
    msg = await send(
        hass,
        hass_ws_client,
        "scans/rename",
        entry_id=entry.entry_id,
        scan_record_id=record["id"],
        name="Fatura ğ",
    )
    assert msg["result"]["entry"]["name"] == "Fatura ğ"
    assert (tmp_path / "media" / msg["result"]["entry"]["path"]).is_file()
    msg = await send(
        hass,
        hass_ws_client,
        "scans/rename",
        entry_id=entry.entry_id,
        scan_record_id="0" * 32,
        name="b",
    )
    assert msg["result"] == {"entry": None}
    msg = await send(
        hass,
        hass_ws_client,
        "scans/delete",
        entry_id=entry.entry_id,
        scan_record_id=record["id"],
    )
    assert msg["result"] == {"deleted": True}
    msg = await send(
        hass,
        hass_ws_client,
        "scans/delete",
        entry_id=entry.entry_id,
        scan_record_id=record["id"],
    )
    assert msg["result"] == {"deleted": False}
    assert archive.entries() == []


async def test_unknown_scan_not_found(hass, entry, hass_ws_client):
    msg = await send(
        hass, hass_ws_client, "scan/state", entry_id=entry.entry_id, scan_id="0" * 32
    )
    assert msg["error"]["code"] == "not_found"
