"""Diagnostics: what the printer and scanner report, without identifiers."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.home_print.client import CannotConnect
from custom_components.home_print.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.home_print.escl.errors import ScannerUnavailable
from custom_components.home_print.escl.parse import parse_capabilities

from .common import setup_entry, setup_scanner_entry

FIXTURES = Path(__file__).parent / "fixtures"
CAPS_XML = (FIXTURES / "escl" / "deskjet4670_capabilities.xml").read_bytes()
STATUS_XML = (FIXTURES / "escl" / "deskjet4670_status_idle.xml").read_bytes()
RAW_CAPS = CAPS_XML.replace(b"XXXXXXXXXX", b"CN12AB3CDE").replace(
    b"<pwg:SerialNumber>",
    b"<scan:UUID>1c852a4d-b800-1f08-abcd-a0d3c1234567</scan:UUID>"
    b"<scan:AdminURI>http://192.168.1.50/</scan:AdminURI><pwg:SerialNumber>",
)
IPP = json.loads((FIXTURES / "printer_generic.json").read_text())

SECRETS = (
    "192.168.1.50",
    "ABC123456789",
    "0A1B2C3D-4E5F-6789-ABCD-0123456789EF",
    "0a1b2c3d-4e5f-6789-abcd-0123456789ef",
    "CN12AB3CDE",
    "1c852a4d",
    "printer.local:631",
)


def _assert_clean(result: dict) -> str:
    text = json.dumps(result)
    for secret in SECRETS:
        assert secret not in text, secret
    return text


async def test_printer_without_scanner(hass, mock_client):
    mock_client.get_printer_attributes.return_value = IPP
    entry = await setup_entry(hass)

    result = await async_get_config_entry_diagnostics(hass, entry)

    _assert_clean(result)
    assert result["version"]
    assert result["entry"]["data"]["host"] == "**REDACTED**"
    assert result["entry"]["data"]["port"] == 631
    assert result["printer"]["make_model"]
    assert result["printer"]["uuid"] == "**REDACTED**"
    attrs = result["ipp_attributes"]
    assert attrs["printer-uuid"] == "**REDACTED**"
    assert attrs["printer-uri-supported"] == "**REDACTED**"
    assert "SN:XXXXXXXXXX;" in attrs["printer-device-id"]
    assert attrs["marker-names"] == IPP["marker-names"]
    assert result["history_entries"] == 0
    assert result["scanner"] is None


async def test_printer_offline_is_reported(hass, mock_client):
    entry = await setup_entry(hass)
    mock_client.get_printer_attributes.side_effect = CannotConnect("timed out")

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["ipp_attributes"] == {
        "error": "CannotConnect",
        "message": "timed out",
    }


async def test_scanner_raw_answers_are_redacted(
    hass, tmp_path, mock_client, mock_escl, mock_find_scanner
):
    mock_client.get_printer_attributes.return_value = IPP
    caps = parse_capabilities(CAPS_XML)
    mock_escl.client.capabilities.return_value = caps
    entry = await setup_scanner_entry(hass, tmp_path, mock_find_scanner, caps=caps)
    scanner = entry.runtime_data.scanner
    scanner.client.base_url = "http://192.168.1.50/eSCL"
    answers = {"ScannerCapabilities": RAW_CAPS, "ScannerStatus": STATUS_XML}
    scanner.client.raw_xml.side_effect = lambda name: answers[name]

    result = await async_get_config_entry_diagnostics(hass, entry)

    text = _assert_clean(result)
    assert "DeskJet Ink Advantage 4670" in text
    block = result["scanner"]
    assert block["url"] == "http://**REDACTED**/eSCL"
    assert block["capabilities"]["make_model"].startswith("DeskJet")
    assert set(block["card"]["sources"]) == {"platen", "adf"}
    assert block["card"]["sources"]["platen"]["resolutions"] == [75, 100, 200, 300, 600]
    assert block["status"] == {"state": "idle", "adf_loaded": False}
    assert block["scans"] == 0
    caps_xml = block["raw_xml"]["ScannerCapabilities"]
    assert "<pwg:SerialNumber>XXXXXXXXXX</pwg:SerialNumber>" in caps_xml
    assert "<scan:MaxWidth>2550</scan:MaxWidth>" in caps_xml
    assert "<pwg:State>Idle</pwg:State>" in block["raw_xml"]["ScannerStatus"]


async def test_scanner_offline_is_reported(
    hass, tmp_path, mock_client, mock_escl, mock_find_scanner
):
    mock_client.get_printer_attributes.return_value = IPP
    entry = await setup_scanner_entry(hass, tmp_path, mock_find_scanner)
    entry.runtime_data.scanner.client.raw_xml.side_effect = ScannerUnavailable()

    result = await async_get_config_entry_diagnostics(hass, entry)

    raw = result["scanner"]["raw_xml"]
    assert raw["ScannerCapabilities"]["error"] == "ScannerUnavailable"
    assert raw["ScannerStatus"]["error"] == "ScannerUnavailable"
