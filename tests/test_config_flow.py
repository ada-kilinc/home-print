"""Config flow and options flow tests."""

import json
from ipaddress import ip_address
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SSL, CONF_VERIFY_SSL
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_print.client import CannotConnect
from custom_components.home_print.const import (
    CONF_ADMIN_ONLY,
    CONF_BASE_PATH,
    CONF_DEFAULT_COLOR_MODE,
    CONF_DEFAULT_SIDES,
    CONF_HISTORY_DAYS,
    CONF_MAX_FILE_MB,
    CONF_SCAN_DAYS,
    CONF_SCAN_INTERVAL,
    CONF_SCAN_MAX_MB,
    CONF_SCANNER_URL,
    DEFAULT_PATH,
    DEFAULT_PORT,
    DOMAIN,
)

UUID = "0a1b2c3d-4e5f-6789-abcd-0123456789ef"


@pytest.fixture(autouse=True)
def no_setup():
    with patch(
        "custom_components.home_print.async_setup_entry",
        return_value=True,
    ) as m:
        yield m


def _zc(type_: str = "_ipp._tcp.local.", host="192.168.1.50", port=631, **props):
    props = {"rp": "ipp/print", "UUID": UUID.upper(), **props}
    props = {k: v for k, v in props.items() if v is not None}
    return ZeroconfServiceInfo(
        ip_address=ip_address(host),
        ip_addresses=[ip_address(host)],
        port=port,
        hostname="printer.local.",
        type=type_,
        name=f"Printer.{type_}",
        properties=props,
    )


async def _start_zc(hass, info):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=info
    )


async def test_user_flow_creates_entry(hass, mock_client):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.50"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Generic IPPE-4000 series"
    assert result["data"] == {
        CONF_HOST: "192.168.1.50",
        CONF_PORT: DEFAULT_PORT,
        CONF_BASE_PATH: DEFAULT_PATH,
        CONF_SSL: False,
        CONF_VERIFY_SSL: True,
    }
    assert result["result"].unique_id == UUID


async def test_user_flow_cannot_connect(hass, mock_client):
    mock_client.get_printer.side_effect = CannotConnect
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.50"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_unknown_error(hass, mock_client):
    mock_client.get_printer.side_effect = RuntimeError
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.50"}
    )
    assert result["errors"] == {"base": "unknown"}


async def test_user_flow_empty_uuid_falls_back_to_serial(hass, mock_client):
    mock_client.get_printer.return_value = type(mock_client.get_printer.return_value)(
        **{**mock_client.get_printer.return_value.__dict__, "uuid": ""}
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.50"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == mock_client.get_printer.return_value.serial


async def test_user_flow_empty_uuid_and_serial_falls_back_to_address(hass, mock_client):
    base = mock_client.get_printer.return_value
    mock_client.get_printer.return_value = type(base)(
        **{**base.__dict__, "uuid": "", "serial": None}
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.50"}
    )
    assert result["result"].unique_id == "192.168.1.50:631/ipp/print"


async def test_user_flow_duplicate_aborts(hass, mock_client):
    MockConfigEntry(domain=DOMAIN, unique_id=UUID, data={CONF_HOST: "x"}).add_to_hass(
        hass
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.50"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_zeroconf_discovery_confirm(hass, mock_client):
    result = await _start_zc(hass, _zc())
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_HOST: "192.168.1.50",
        CONF_PORT: 631,
        CONF_BASE_PATH: "/ipp/print",
        CONF_SSL: False,
        CONF_VERIFY_SSL: False,
    }
    assert result["result"].unique_id == UUID


async def test_zeroconf_ipps_sets_tls(hass, mock_client):
    result = await _start_zc(hass, _zc("_ipps._tcp.local.", port=443))
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["data"][CONF_SSL] is True
    assert result["data"][CONF_PORT] == 443
    assert result["data"][CONF_VERIFY_SSL] is False


async def test_zeroconf_without_txt_uuid_uses_printer_uuid(hass, mock_client):
    result = await _start_zc(hass, _zc(UUID=None, rp=None))
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["result"].unique_id == UUID
    assert result["data"][CONF_BASE_PATH] == DEFAULT_PATH


async def test_zeroconf_cannot_connect_aborts(hass, mock_client):
    mock_client.get_printer.side_effect = CannotConnect
    result = await _start_zc(hass, _zc())
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_zeroconf_same_uuid_both_types_single_entry(hass, mock_client):
    result = await _start_zc(hass, _zc())
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    result = await _start_zc(hass, _zc("_ipps._tcp.local.", port=443))
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_zeroconf_updates_host_on_ip_change(hass, mock_client):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=UUID,
        data={
            CONF_HOST: "192.168.1.50",
            CONF_PORT: 631,
            CONF_BASE_PATH: "/ipp/print",
            CONF_SSL: False,
            CONF_VERIFY_SSL: False,
        },
    )
    entry.add_to_hass(hass)
    result = await _start_zc(hass, _zc(host="192.168.1.77"))
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "192.168.1.77"


async def test_options_flow_saves_values(hass, mock_client):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=UUID, data={CONF_HOST: "x"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_DEFAULT_SIDES: "two-sided-long-edge",
            CONF_DEFAULT_COLOR_MODE: "monochrome",
            CONF_MAX_FILE_MB: 50.0,
            CONF_SCAN_INTERVAL: 120.0,
            CONF_ADMIN_ONLY: True,
            CONF_HISTORY_DAYS: 30.0,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_DEFAULT_SIDES: "two-sided-long-edge",
        CONF_DEFAULT_COLOR_MODE: "monochrome",
        CONF_MAX_FILE_MB: 50,
        CONF_SCAN_INTERVAL: 120,
        CONF_ADMIN_ONLY: True,
        CONF_HISTORY_DAYS: 30,
        CONF_SCANNER_URL: "",
        CONF_SCAN_DAYS: 30,
        CONF_SCAN_MAX_MB: 2000,
    }
    assert isinstance(entry.options[CONF_MAX_FILE_MB], int)
    assert isinstance(entry.options[CONF_SCAN_INTERVAL], int)
    assert isinstance(entry.options[CONF_HISTORY_DAYS], int)


async def test_options_flow_history_days_default_and_range(hass, mock_client):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=UUID, data={CONF_HOST: "x"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    [key] = [k for k in schema if k == CONF_HISTORY_DAYS]
    assert key.default() == 7
    config = schema[key].config
    assert (config["min"], config["max"]) == (0, 90)


async def test_options_flow_scan_fields(hass, mock_client):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=UUID, data={CONF_HOST: "x"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    keys = {str(k): k for k in schema}
    assert keys[CONF_SCAN_DAYS].default() == 30
    assert keys[CONF_SCAN_MAX_MB].default() == 2000
    assert keys[CONF_SCANNER_URL].default() == ""
    assert (
        schema[keys[CONF_SCAN_DAYS]].config["min"],
        schema[keys[CONF_SCAN_DAYS]].config["max"],
    ) == (0, 3650)
    assert (
        schema[keys[CONF_SCAN_MAX_MB]].config["min"],
        schema[keys[CONF_SCAN_MAX_MB]].config["max"],
    ) == (0, 100000)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_DEFAULT_SIDES: "one-sided",
            CONF_DEFAULT_COLOR_MODE: "auto",
            CONF_MAX_FILE_MB: 25,
            CONF_SCAN_INTERVAL: 60,
            CONF_ADMIN_ONLY: False,
            CONF_SCANNER_URL: "  http://192.168.1.9/eSCL ",
            CONF_SCAN_DAYS: 0.0,
            CONF_SCAN_MAX_MB: 500.0,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SCANNER_URL] == "http://192.168.1.9/eSCL"
    assert entry.options[CONF_SCAN_DAYS] == 0
    assert entry.options[CONF_SCAN_MAX_MB] == 500
    assert isinstance(entry.options[CONF_SCAN_DAYS], int)
    assert isinstance(entry.options[CONF_SCAN_MAX_MB], int)


def test_history_days_labels():
    root = Path(__file__).parent.parent / "custom_components/home_print"
    labels = {
        name: json.loads((root / name).read_text())["options"]["step"]["init"]["data"][
            CONF_HISTORY_DAYS
        ]
        for name in ("strings.json", "translations/en.json", "translations/tr.json")
    }
    assert labels == {
        "strings.json": "Keep files (days)",
        "translations/en.json": "Keep files (days)",
        "translations/tr.json": "Dosyaları sakla (gün)",
    }


async def test_options_flow_auto_color_stores_none(hass, mock_client):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=UUID, data={CONF_HOST: "x"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_DEFAULT_SIDES: "one-sided",
            CONF_DEFAULT_COLOR_MODE: "auto",
            CONF_MAX_FILE_MB: 25,
            CONF_SCAN_INTERVAL: 60,
            CONF_ADMIN_ONLY: False,
        },
    )
    assert entry.options[CONF_DEFAULT_COLOR_MODE] is None


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (("_ipp._tcp.local.", 631), ("_ipps._tcp.local.", 443)),
        (("_ipps._tcp.local.", 443), ("_ipp._tcp.local.", 631)),
    ],
)
async def test_zeroconf_other_type_only_updates_host(hass, mock_client, first, second):
    result = await _start_zc(hass, _zc(first[0], port=first[1]))
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    entry = result["result"]
    before = dict(entry.data)
    result = await _start_zc(
        hass, _zc(second[0], host="192.168.1.77", port=second[1], rp="ipp/other")
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data == {**before, CONF_HOST: "192.168.1.77"}


async def test_zeroconf_same_type_updates_port_and_path(hass, mock_client):
    result = await _start_zc(hass, _zc())
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    entry = result["result"]
    result = await _start_zc(hass, _zc(host="192.168.1.77", port=8631, rp="ipp/other"))
    assert result["type"] is FlowResultType.ABORT
    assert entry.data[CONF_HOST] == "192.168.1.77"
    assert entry.data[CONF_PORT] == 8631
    assert entry.data[CONF_BASE_PATH] == "/ipp/other"
    assert entry.data[CONF_SSL] is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", ""),
        ("   ", ""),
        ("192.168.1.20", "http://192.168.1.20/eSCL"),
        (" 192.168.1.20:8080/eSCL ", "http://192.168.1.20:8080/eSCL"),
        ("https://printer.local", "https://printer.local/eSCL"),
        ("HTTP://printer.local/", "http://printer.local/eSCL"),
        ("http://10.0.0.2/eSCL/", "http://10.0.0.2/eSCL"),
        ("http://10.0.0.2/scan", "http://10.0.0.2/scan"),
    ],
)
def test_normalize_scanner_url(value, expected):
    from custom_components.home_print.config_flow import normalize_scanner_url

    assert normalize_scanner_url(value) == expected


@pytest.mark.parametrize("value", ["ftp://h/eSCL", "http://", "file:///etc", "h:x:y"])
def test_normalize_scanner_url_rejects(value):
    from custom_components.home_print.config_flow import normalize_scanner_url

    with pytest.raises(ValueError):
        normalize_scanner_url(value)


async def _options_input(**over):
    data = {
        CONF_DEFAULT_SIDES: "one-sided",
        CONF_DEFAULT_COLOR_MODE: "auto",
        CONF_MAX_FILE_MB: 25,
        CONF_SCAN_INTERVAL: 60,
        CONF_ADMIN_ONLY: False,
        CONF_SCAN_DAYS: 30,
        CONF_SCAN_MAX_MB: 2000,
    }
    data.update(over)
    return data


async def test_options_scanner_url_normalized_or_rejected(hass, mock_client):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=UUID, data={CONF_HOST: "x"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], await _options_input(**{CONF_SCANNER_URL: "ftp://x/eSCL"})
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SCANNER_URL: "invalid_scanner_url"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], await _options_input(**{CONF_SCANNER_URL: "192.168.1.20"})
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SCANNER_URL] == "http://192.168.1.20/eSCL"


def test_scanner_url_translations():
    root = Path(__file__).parent.parent / "custom_components/home_print"
    for name in ("strings.json", "translations/en.json", "translations/tr.json"):
        data = json.loads((root / name).read_text())
        init = data["options"]["step"]["init"]
        assert "http://192.168.1.20/eSCL" in init["data_description"]["scanner_url"]
        assert data["options"]["error"]["invalid_scanner_url"]
