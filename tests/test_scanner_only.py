"""Scanners without a printer, and announced scanner addresses (issue #10)."""

from __future__ import annotations

import json
from http import HTTPStatus
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_print.const import (
    CONF_HOST,
    CONF_KIND,
    CONF_SCANNER_ANNOUNCED,
    CONF_SCANNER_TXT,
    CONF_SSL,
    CONF_VERIFY_SSL,
    DOMAIN,
    KIND_SCANNER,
)
from custom_components.home_print.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.home_print.escl.errors import ScannerUnavailable
from custom_components.home_print.escl.models import ScannerStatus

from .common import CAPS, URL, make_entry, setup_entry

SCANNER_UUID = "11111111-2222-3333-4444-555555555555"
ANNOUNCED = "http://192.168.1.60/eSCL"


def scanner_entry(**options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=SCANNER_UUID,
        title="Test Scanner",
        data={
            CONF_KIND: KIND_SCANNER,
            CONF_HOST: "192.168.1.60",
            CONF_SSL: False,
            CONF_VERIFY_SSL: False,
            CONF_SCANNER_ANNOUNCED: ANNOUNCED,
            CONF_SCANNER_TXT: {
                "ty": "Test Scanner",
                "rs": "eSCL",
                "UUID": SCANNER_UUID,
            },
        },
        options=options,
    )


@pytest.fixture
def mock_probe(mock_escl):
    mock_escl.client.base_url = ANNOUNCED
    with patch(
        "custom_components.home_print.scanner.probe_scanner",
        return_value=(ANNOUNCED, CAPS),
    ) as probe:
        yield probe


async def _setup_scanner(hass, tmp_path, entry=None):
    hass.config.media_dirs = {"local": str(tmp_path / "media")}
    entry = entry or scanner_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_scanner_only_entry_has_just_the_scanner_sensor(
    hass, tmp_path, mock_client, mock_escl, mock_probe, mock_find_scanner
):
    entry = await _setup_scanner(hass, tmp_path)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.client is None
    mock_client.get_printer.assert_not_called()
    mock_find_scanner.assert_not_called()
    assert mock_probe.call_args.args[1] == ANNOUNCED
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert [e.unique_id for e in entities] == [f"{SCANNER_UUID}_scanner_status"]
    state = hass.states.get(entities[0].entity_id)
    assert state.state == "idle"


async def test_scanner_only_entry_retries_while_the_scanner_is_off(
    hass, tmp_path, mock_client, mock_escl, mock_probe
):
    mock_probe.side_effect = ScannerUnavailable()
    entry = await _setup_scanner(hass, tmp_path)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_scanner_only_goes_unavailable_when_status_fails(
    hass, tmp_path, mock_client, mock_escl, mock_probe
):
    entry = await _setup_scanner(hass, tmp_path)
    [entity] = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    mock_escl.client.status.side_effect = ScannerUnavailable()
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity.entity_id).state == "unavailable"
    mock_escl.client.status.side_effect = None
    mock_escl.client.status.return_value = ScannerStatus("idle", True)
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity.entity_id).state == "adf_loaded"


async def test_card_lists_a_scanner_without_print_capabilities(
    hass, tmp_path, mock_client, mock_escl, mock_probe, hass_ws_client
):
    entry = await _setup_scanner(hass, tmp_path)
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "home_print/printers"})
    [printer] = (await ws.receive_json())["result"]["printers"]

    assert printer["kind"] == "scanner"
    assert printer["entry_id"] == entry.entry_id
    assert printer["available"] is True
    assert printer["capabilities"] is None
    assert printer["entities"]["status"] is None
    assert printer["entities"]["scanner_status"].startswith("sensor.")
    assert printer["entities"]["markers"] == []
    assert printer["scanner"]["sources"] == {
        "platen": {"color_modes": ["color"], "resolutions": [300]}
    }

    await ws.send_json(
        {"id": 2, "type": "home_print/job", "entry_id": entry.entry_id, "job_id": 1}
    )
    reply = await ws.receive_json()
    assert reply["success"] is False
    assert reply["error"]["code"] == "not_found"

    await ws.send_json(
        {"id": 3, "type": "home_print/history", "entry_id": entry.entry_id}
    )
    assert (await ws.receive_json())["result"] == {"entries": []}


async def test_print_file_on_a_scanner_is_refused(
    hass, tmp_path, mock_client, mock_escl, mock_probe
):
    entry = await _setup_scanner(hass, tmp_path)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "print_file",
            {"config_entry_id": entry.entry_id, "path": "/tmp/x.pdf"},
            blocking=True,
        )
    assert err.value.translation_key == "not_a_printer"


async def test_upload_to_a_scanner_is_refused(
    hass, tmp_path, mock_client, mock_escl, mock_probe, hass_client
):
    entry = await _setup_scanner(hass, tmp_path)
    client = await hass_client()
    resp = await client.post(
        f"/api/home_print/upload/{entry.entry_id}", data={"file": b"%PDF-1.7"}
    )
    assert resp.status == HTTPStatus.BAD_REQUEST
    assert (await resp.json())["error"] == "not_a_printer"


async def test_scanner_only_diagnostics(
    hass, tmp_path, mock_client, mock_escl, mock_probe
):
    entry = await _setup_scanner(hass, tmp_path)
    scanner = entry.runtime_data.scanner
    scanner.client.raw_xml.side_effect = ScannerUnavailable()

    result = await async_get_config_entry_diagnostics(hass, entry)

    text = json.dumps(result)
    assert "192.168.1.60" not in text
    assert SCANNER_UUID not in text
    assert result["kind"] == "scanner"
    assert result["printer"] is None
    assert result["ipp_attributes"] is None
    assert result["scanner_txt"]["ty"] == "Test Scanner"
    assert result["scanner_txt"]["rs"] == "eSCL"
    assert result["scanner"]["url"] == "http://**REDACTED**/eSCL"


async def test_printer_uses_the_announced_scanner_address(
    hass, tmp_path, mock_client, mock_escl, mock_probe, mock_find_scanner
):
    hass.config.media_dirs = {"local": str(tmp_path / "media")}
    base = make_entry()
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=base.unique_id,
        title=base.title,
        data={**base.data, CONF_SCANNER_ANNOUNCED: ANNOUNCED},
    )
    await setup_entry(hass, entry)

    assert entry.runtime_data.scanner is not None
    assert mock_probe.call_args.args[1] == ANNOUNCED
    mock_find_scanner.assert_not_called()


async def test_printer_falls_back_to_guessing_when_announced_fails(
    hass, tmp_path, mock_client, mock_escl, mock_probe, mock_find_scanner
):
    hass.config.media_dirs = {"local": str(tmp_path / "media")}
    mock_probe.side_effect = ScannerUnavailable()
    mock_find_scanner.return_value = (URL, CAPS)
    base = make_entry()
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=base.unique_id,
        title=base.title,
        data={**base.data, CONF_SCANNER_ANNOUNCED: ANNOUNCED},
    )
    await setup_entry(hass, entry)

    assert entry.runtime_data.scanner is not None
    mock_find_scanner.assert_called_once()
