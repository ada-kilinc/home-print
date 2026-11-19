"""Config flow for scanners: _uscan discovery and scanners without a printer."""

from __future__ import annotations

from ipaddress import ip_address
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_print.client import CannotConnect
from custom_components.home_print.const import (
    CONF_ADMIN_ONLY,
    CONF_KIND,
    CONF_MAX_FILE_MB,
    CONF_SCAN_DAYS,
    CONF_SCAN_INTERVAL,
    CONF_SCAN_MAX_MB,
    CONF_SCANNER_ANNOUNCED,
    CONF_SCANNER_TXT,
    CONF_SCANNER_URL,
    DOMAIN,
    KIND_SCANNER,
)
from custom_components.home_print.escl.errors import ScannerUnavailable

from .common import CAPS, make_entry

SCANNER_UUID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(autouse=True)
def no_setup():
    with patch("custom_components.home_print.async_setup_entry", return_value=True):
        yield


@pytest.fixture
def flow_probe():
    with patch(
        "custom_components.home_print.config_flow.probe_scanner",
        return_value=("http://192.168.1.60/eSCL", CAPS),
    ) as probe:
        yield probe


@pytest.fixture
def flow_find():
    with patch(
        "custom_components.home_print.config_flow.find_scanner", return_value=None
    ) as find:
        yield find


def _uscan(host="192.168.1.60", secure=False, port=None, **props):
    type_ = "_uscans._tcp.local." if secure else "_uscan._tcp.local."
    props = {
        "ty": "Test Scanner",
        "rs": "eSCL",
        "UUID": SCANNER_UUID.upper(),
        "note": "Kitchen",
        **props,
    }
    return ZeroconfServiceInfo(
        ip_address=ip_address(host),
        ip_addresses=[ip_address(host)],
        port=port or (443 if secure else 80),
        hostname="scanner.local.",
        type=type_,
        name=f"Scanner.{type_}",
        properties={k: v for k, v in props.items() if v is not None},
    )


async def _discover(hass, info):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=info
    )


async def test_uscan_of_a_known_printer_stores_the_announced_address(hass, mock_client):
    entry = make_entry()
    entry.add_to_hass(hass)
    result = await _discover(hass, _uscan(host="192.168.1.50", rs="eSCL"))

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_SCANNER_ANNOUNCED] == "http://192.168.1.50/eSCL"
    assert entry.data[CONF_SCANNER_TXT]["ty"] == "Test Scanner"
    assert "note" not in entry.data[CONF_SCANNER_TXT]
    mock_client.get_printer.assert_not_called()


async def test_uscan_keeps_a_typed_scanner_address(hass, mock_client):
    entry = make_entry(**{CONF_SCANNER_URL: "http://192.168.1.50:8080/eSCL"})
    entry.add_to_hass(hass)
    result = await _discover(hass, _uscan(host="192.168.1.50"))

    assert result["reason"] == "already_configured"
    assert CONF_SCANNER_ANNOUNCED not in entry.data


async def test_uscans_builds_an_https_address_with_port(hass, mock_client):
    entry = make_entry()
    entry.add_to_hass(hass)
    await _discover(hass, _uscan(host="192.168.1.50", secure=True, port=8443, rs="/x/"))
    assert entry.data[CONF_SCANNER_ANNOUNCED] == "https://192.168.1.50:8443/x"


async def test_uscan_with_a_printer_at_the_host_offers_the_printer(
    hass, mock_client, flow_probe
):
    result = await _discover(hass, _uscan(host="192.168.1.50"))

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"
    flow_probe.assert_not_called()
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert CONF_KIND not in data
    assert data[CONF_HOST] == "192.168.1.50"
    assert data[CONF_SCANNER_ANNOUNCED] == "http://192.168.1.50/eSCL"


async def test_uscan_without_a_printer_offers_a_scanner(hass, mock_client, flow_probe):
    mock_client.get_printer.side_effect = CannotConnect("no ipp")
    result = await _discover(hass, _uscan())

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm_scanner"
    assert result["description_placeholders"] == {
        "name": "Test Scanner",
        "host": "192.168.1.60",
    }
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test Scanner"
    assert result["result"].unique_id == SCANNER_UUID
    data = result["data"]
    assert data[CONF_KIND] == KIND_SCANNER
    assert data[CONF_SCANNER_ANNOUNCED] == "http://192.168.1.60/eSCL"
    assert data[CONF_SCANNER_TXT]["UUID"] == SCANNER_UUID.upper()


async def test_uscan_of_an_unreadable_scanner_is_dropped(hass, mock_client, flow_probe):
    mock_client.get_printer.side_effect = CannotConnect("no ipp")
    flow_probe.side_effect = ScannerUnavailable()
    result = await _discover(hass, _uscan())
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_uscan_follows_a_scanner_only_entry_to_a_new_address(hass, mock_client):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SCANNER_UUID,
        data={
            CONF_KIND: KIND_SCANNER,
            CONF_HOST: "192.168.1.60",
            CONF_SCANNER_ANNOUNCED: "http://192.168.1.60/eSCL",
        },
    )
    entry.add_to_hass(hass)
    result = await _discover(hass, _uscan(host="192.168.1.61"))
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "192.168.1.61"
    assert entry.data[CONF_SCANNER_ANNOUNCED] == "http://192.168.1.61/eSCL"


async def test_user_step_adds_a_scanner_when_no_printer_answers(
    hass, mock_client, flow_find
):
    mock_client.get_printer.side_effect = CannotConnect("no ipp")
    flow_find.return_value = ("https://192.168.1.60/eSCL", CAPS)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.60"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test Scanner"
    assert result["result"].unique_id == "scanner:192.168.1.60"
    data = result["data"]
    assert data[CONF_KIND] == KIND_SCANNER
    assert data[CONF_SCANNER_ANNOUNCED] == "https://192.168.1.60/eSCL"


async def test_user_step_takes_an_escl_address(hass, mock_client, flow_probe):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "http://192.168.1.60/eSCL"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_KIND] == KIND_SCANNER
    assert flow_probe.call_args.args[1] == "http://192.168.1.60/eSCL"
    mock_client.get_printer.assert_not_called()


async def test_user_step_without_printer_or_scanner_shows_an_error(
    hass, mock_client, flow_find
):
    mock_client.get_printer.side_effect = CannotConnect("nothing")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.70"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_scanner_options_show_only_scanning_settings(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SCANNER_UUID,
        data={CONF_KIND: KIND_SCANNER, CONF_HOST: "192.168.1.60"},
        options={CONF_MAX_FILE_MB: 9},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    fields = {str(key) for key in result["data_schema"].schema}
    assert fields == {
        CONF_SCAN_INTERVAL,
        CONF_ADMIN_ONLY,
        CONF_SCANNER_URL,
        CONF_SCAN_DAYS,
        CONF_SCAN_MAX_MB,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SCAN_INTERVAL: 120,
            CONF_ADMIN_ONLY: True,
            CONF_SCANNER_URL: "",
            CONF_SCAN_DAYS: 10,
            CONF_SCAN_MAX_MB: 500,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SCAN_INTERVAL] == 120
    assert entry.options[CONF_ADMIN_ONLY] is True
    # Settings the form didn't show are kept.
    assert entry.options[CONF_MAX_FILE_MB] == 9


async def test_uscan_and_uscans_dont_take_turns(hass, mock_client):
    entry = make_entry()
    entry.add_to_hass(hass)
    await _discover(hass, _uscan(host="192.168.1.50"))
    assert entry.data[CONF_SCANNER_ANNOUNCED] == "http://192.168.1.50/eSCL"
    await _discover(hass, _uscan(host="192.168.1.50", secure=True))
    assert entry.data[CONF_SCANNER_ANNOUNCED] == "http://192.168.1.50/eSCL"
    await _discover(hass, _uscan(host="192.168.1.50", rs="eSCL2"))
    assert entry.data[CONF_SCANNER_ANNOUNCED] == "http://192.168.1.50/eSCL2"
