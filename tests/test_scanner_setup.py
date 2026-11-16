"""Scanner detection, runtime data and status polling."""

import logging
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.helpers import entity_registry as er

from custom_components.home_print.client import CannotConnect
from custom_components.home_print.const import CONF_SCANNER_URL, DOMAIN
from custom_components.home_print.escl.errors import ScannerUnavailable
from custom_components.home_print.escl.models import ScannerStatus

from .common import CAPS, URL, UUID, make_entry, setup_entry

SCANNER_ENTITY = "sensor.generic_ippe_4000_series_scanner_status"


def _warnings(caplog):
    return [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING and r.name.startswith("custom_components")
    ]


async def test_setup_finds_scanner_on_printer_host(
    hass, mock_client, mock_escl, mock_find_scanner
):
    mock_find_scanner.return_value = URL
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    scanner = entry.runtime_data.scanner
    assert scanner is not None
    assert scanner.caps is CAPS
    assert scanner.status == ScannerStatus("idle", False)
    assert scanner.active is None
    assert entry.runtime_data.coordinator.scanner is scanner
    args = mock_find_scanner.call_args.args
    assert args[1:] == ("192.168.1.50", False, True)
    assert mock_escl.call_args.args[0] == URL
    assert hass.states.get(SCANNER_ENTITY).state == "idle"
    assert er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{UUID}_scanner_status"
    )


async def test_setup_without_scanner_has_none_and_no_sensor(hass, mock_client, caplog):
    with caplog.at_level(logging.WARNING):
        entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.scanner is None
    assert entry.runtime_data.coordinator.scanner is None
    assert hass.states.get(SCANNER_ENTITY) is None
    assert not _warnings(caplog)


async def test_manual_scanner_url_used(hass, mock_client, mock_escl, mock_find_scanner):
    entry = await setup_entry(
        hass, make_entry(**{CONF_SCANNER_URL: " https://scan.local/eSCL "})
    )
    assert entry.runtime_data.scanner is not None
    mock_find_scanner.assert_not_called()
    assert mock_escl.call_args.args[0] == "https://scan.local/eSCL"


async def test_manual_scanner_url_failure_warns_once(
    hass, mock_client, mock_escl, caplog
):
    mock_escl.client.capabilities.side_effect = ScannerUnavailable("down")
    with caplog.at_level(logging.WARNING):
        entry = await setup_entry(
            hass, make_entry(**{CONF_SCANNER_URL: "http://nope/eSCL"})
        )
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.scanner is None
    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert "http://nope/eSCL" in warnings[0].getMessage()


async def test_auto_detected_scanner_failing_caps_is_silent(
    hass, mock_client, mock_escl, mock_find_scanner, caplog
):
    mock_find_scanner.return_value = URL
    mock_escl.client.capabilities.side_effect = ScannerUnavailable("down")
    with caplog.at_level(logging.WARNING):
        entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.scanner is None
    assert not _warnings(caplog)


async def test_detection_crash_never_fails_setup(hass, mock_client, mock_find_scanner):
    mock_find_scanner.side_effect = RuntimeError("boom")
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.scanner is None


async def test_status_failure_keeps_printer_data(
    hass, mock_client, mock_escl, mock_find_scanner
):
    mock_find_scanner.return_value = URL
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data.coordinator
    printer = coordinator.data
    mock_escl.client.status.side_effect = ScannerUnavailable("gone")
    await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    assert coordinator.data == printer
    assert entry.runtime_data.scanner.status is None
    assert hass.states.get(SCANNER_ENTITY).state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.generic_ippe_4000_series_status").state == "idle"

    mock_escl.client.status.side_effect = None
    mock_escl.client.status.return_value = ScannerStatus("processing", False)
    await coordinator.async_refresh()
    assert hass.states.get(SCANNER_ENTITY).state == "scanning"


async def test_status_timeout_is_not_a_printer_failure(
    hass, mock_client, mock_escl, mock_find_scanner
):
    mock_find_scanner.return_value = URL
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data.coordinator
    mock_escl.client.status.side_effect = TimeoutError
    await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    assert entry.runtime_data.scanner.status is None


async def test_printer_failure_makes_scanner_sensor_unavailable(
    hass, mock_client, mock_escl, mock_find_scanner
):
    mock_find_scanner.return_value = URL
    entry = await setup_entry(hass)
    mock_client.get_printer.side_effect = CannotConnect("off")
    await entry.runtime_data.coordinator.async_refresh()
    assert hass.states.get(SCANNER_ENTITY).state == STATE_UNAVAILABLE


async def test_unload_flushes_and_remove_deletes_archive(
    hass, mock_client, mock_escl, mock_find_scanner
):
    mock_find_scanner.return_value = URL
    entry = await setup_entry(hass)
    archive = entry.runtime_data.scanner.archive
    with patch.object(archive, "async_flush", new=AsyncMock()) as flush:
        assert await hass.config_entries.async_unload(entry.entry_id)
    flush.assert_awaited_once()
    with patch(
        "custom_components.home_print.ScanArchive.async_remove", new=AsyncMock()
    ) as remove:
        await hass.config_entries.async_remove(entry.entry_id)
    remove.assert_awaited_once()


async def test_archive_load_failure_never_fails_setup(
    hass, mock_client, mock_escl, mock_find_scanner
):
    mock_find_scanner.return_value = URL
    with patch(
        "custom_components.home_print.scanner.ScanArchive.async_load",
        new=AsyncMock(side_effect=OSError("disk")),
    ):
        entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.scanner is None


async def test_unexpected_status_error_gives_none(
    hass, mock_client, mock_escl, mock_find_scanner
):
    mock_find_scanner.return_value = URL
    entry = await setup_entry(hass)
    mock_escl.client.status.side_effect = RuntimeError("boom")
    await entry.runtime_data.coordinator.async_refresh()
    assert entry.runtime_data.coordinator.last_update_success is True
    assert entry.runtime_data.scanner.status is None


async def test_printer_failure_drops_scanner_status(
    hass, mock_client, mock_escl, mock_find_scanner
):
    mock_find_scanner.return_value = URL
    entry = await setup_entry(hass)
    scanner = entry.runtime_data.scanner
    mock_escl.client.status.return_value = ScannerStatus("processing", False)
    mock_client.get_printer.side_effect = CannotConnect("off")
    await entry.runtime_data.coordinator.async_refresh()
    assert scanner.status == ScannerStatus("idle", False)  # unchanged
