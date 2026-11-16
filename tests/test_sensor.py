"""Tests for Home Print sensors and entry setup."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.home_print.client import CannotConnect
from custom_components.home_print.const import (
    CONF_BASE_PATH,
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SSL,
    CONF_VERIFY_SSL,
    DOMAIN,
)
from custom_components.home_print.escl.models import ScannerStatus
from custom_components.home_print.models import LastJob

from .common import URL

UUID = "0a1b2c3d-4e5f-6789-abcd-0123456789ef"


def make_entry(**options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=UUID,
        title="Printer",
        data={
            CONF_HOST: "192.168.1.50",
            CONF_PORT: 631,
            CONF_BASE_PATH: "/ipp/print",
            CONF_SSL: False,
            CONF_VERIFY_SSL: True,
        },
        options=options,
    )


async def setup_entry(hass, entry=None):
    entry = entry or make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_status_and_marker_sensors_created(hass, mock_client):
    await setup_entry(hass)
    status = hass.states.get("sensor.generic_ippe_4000_series_status")
    assert status is not None
    assert status.state == "idle"
    assert status.attributes["reasons"] == []

    expected = {
        "black_ink": ("80", "#000000", "ink-cartridge"),
        "cyan_ink": ("55", "#00FFFF", "ink-cartridge"),
        "magenta_ink": ("30", "#FF00FF", "ink-cartridge"),
        "yellow_ink": (STATE_UNKNOWN, "#FFFF00", "ink-cartridge"),
        "maintenance_box": ("90", None, "waste-ink"),
    }
    for slug, (level, color, kind) in expected.items():
        state = hass.states.get(f"sensor.generic_ippe_4000_series_{slug}")
        assert state is not None, slug
        assert state.state == level
        assert state.attributes["unit_of_measurement"] == "%"
        assert state.attributes["color"] == color
        assert state.attributes["kind"] == kind


async def test_entity_unique_ids_and_device(hass, mock_client):
    await setup_entry(hass)
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{UUID}_status")
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{UUID}_marker_0")
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{UUID}_marker_4")
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{UUID}_last_job")
    assert registry.async_get_entity_id("binary_sensor", DOMAIN, f"{UUID}_problem")


async def test_status_reasons_attribute(hass, mock_client):
    info = mock_client.get_printer.return_value
    mock_client.get_printer.return_value = type(info)(
        **{**info.__dict__, "state": "stopped", "state_reasons": ("media-empty-error",)}
    )
    await setup_entry(hass)
    status = hass.states.get("sensor.generic_ippe_4000_series_status")
    assert status.state == "stopped"
    assert status.attributes["reasons"] == ["media-empty-error"]


async def test_last_job_sensor(hass, mock_client):
    entry = await setup_entry(hass)
    state = hass.states.get("sensor.generic_ippe_4000_series_last_job")
    assert state.state == STATE_UNKNOWN

    when = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
    entry.runtime_data.coordinator.async_set_last_job(
        LastJob(
            file_name="report.pdf",
            job_id=42,
            state="pending",
            user="ada",
            time=when,
        )
    )
    await hass.async_block_till_done()
    state = hass.states.get("sensor.generic_ippe_4000_series_last_job")
    assert state.state == "report.pdf"
    assert state.attributes["job_id"] == 42
    assert state.attributes["state"] == "pending"
    assert state.attributes["user"] == "ada"
    assert state.attributes["time"] == when.isoformat()


async def test_entities_unavailable_when_printer_offline(hass, mock_client):
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data.coordinator
    mock_client.get_printer.side_effect = CannotConnect
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    states = [
        s
        for s in hass.states.async_all()
        if s.entity_id.startswith(("sensor.generic", "binary_sensor.generic"))
    ]
    assert len(states) == 8
    assert all(s.state == STATE_UNAVAILABLE for s in states)


async def test_setup_fails_retry_when_offline_at_start(hass, mock_client):
    mock_client.get_printer.side_effect = CannotConnect
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_entry(hass, mock_client):
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    state = hass.states.get("sensor.generic_ippe_4000_series_status")
    assert state.state == STATE_UNAVAILABLE


async def test_options_change_reloads_entry(hass, mock_client):
    entry = await setup_entry(hass)
    with patch.object(
        hass.config_entries, "async_reload", wraps=hass.config_entries.async_reload
    ) as reload:
        hass.config_entries.async_update_entry(entry, options={CONF_SCAN_INTERVAL: 30})
        await hass.async_block_till_done()
    reload.assert_called_once_with(entry.entry_id)
    assert entry.runtime_data.coordinator.update_interval.total_seconds() == 30


@pytest.mark.parametrize("interval", [None, 15])
async def test_scan_interval(hass, mock_client, interval):
    options = {} if interval is None else {CONF_SCAN_INTERVAL: interval}
    entry = await setup_entry(hass, make_entry(**options))
    expected = 60 if interval is None else interval
    assert entry.runtime_data.coordinator.update_interval.total_seconds() == expected


async def test_polling_updates_state(hass, mock_client, freezer):
    from datetime import timedelta

    await setup_entry(hass)
    info = mock_client.get_printer.return_value
    mock_client.get_printer.return_value = type(info)(
        **{**info.__dict__, "state": "processing"}
    )
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert (
        hass.states.get("sensor.generic_ippe_4000_series_status").state == "processing"
    )


async def test_marker_sensor_category_and_state_class(hass, mock_client):
    await setup_entry(hass)
    registry = er.async_get(hass)
    for slug, diagnostic in (
        ("black_ink", False),
        ("yellow_ink", False),
        ("maintenance_box", True),
    ):
        entity_id = f"sensor.generic_ippe_4000_series_{slug}"
        reg = registry.async_get(entity_id)
        assert (reg.entity_category == "diagnostic") is diagnostic, slug
        assert hass.states.get(entity_id).attributes["state_class"] == "measurement"


@pytest.mark.parametrize(
    ("state", "adf", "expected"),
    [
        ("idle", False, "idle"),
        ("idle", None, "idle"),
        ("idle", True, "adf_loaded"),
        ("processing", False, "scanning"),
        ("testing", False, "scanning"),
        ("stopped", False, "stopped"),
        ("down", None, "stopped"),
    ],
)
async def test_status_sensor_states(
    hass, mock_client, mock_escl, mock_find_scanner, state, adf, expected
):
    mock_find_scanner.return_value = URL
    mock_escl.client.status.return_value = ScannerStatus(state, adf)
    await setup_entry(hass)
    sensor = hass.states.get("sensor.generic_ippe_4000_series_scanner_status")
    assert sensor.state == expected
    assert sensor.attributes["options"] == ["idle", "scanning", "adf_loaded", "stopped"]


async def test_status_sensor_unavailable_without_status(
    hass, mock_client, mock_escl, mock_find_scanner
):
    mock_find_scanner.return_value = URL
    mock_escl.client.status.side_effect = TimeoutError
    await setup_entry(hass)
    sensor = hass.states.get("sensor.generic_ippe_4000_series_scanner_status")
    assert sensor.state == STATE_UNAVAILABLE
