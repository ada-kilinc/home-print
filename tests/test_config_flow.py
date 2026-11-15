"""Config flow and options flow tests."""

from ipaddress import ip_address
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
    CONF_MAX_FILE_MB,
    CONF_SCAN_INTERVAL,
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
        create=True,
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
        CONF_VERIFY_SSL: False,
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
            CONF_MAX_FILE_MB: 50,
            CONF_SCAN_INTERVAL: 120,
            CONF_ADMIN_ONLY: True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_DEFAULT_SIDES: "two-sided-long-edge",
        CONF_DEFAULT_COLOR_MODE: "monochrome",
        CONF_MAX_FILE_MB: 50,
        CONF_SCAN_INTERVAL: 120,
        CONF_ADMIN_ONLY: True,
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
