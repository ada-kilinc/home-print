"""Tests for the Home Print problem binary sensor."""

import pytest

from .test_sensor import setup_entry

PROBLEM = "binary_sensor.generic_ippe_4000_series_problem"


async def _with_reasons(hass, mock_client, reasons):
    info = mock_client.get_printer.return_value
    mock_client.get_printer.return_value = type(info)(
        **{**info.__dict__, "state_reasons": reasons}
    )
    await setup_entry(hass)
    return hass.states.get(PROBLEM)


async def test_problem_binary_sensor_on_media_empty(hass, mock_client):
    state = await _with_reasons(hass, mock_client, ("media-empty-error",))
    assert state.state == "on"
    assert state.attributes["device_class"] == "problem"


async def test_problem_binary_sensor_off_when_none(hass, mock_client):
    state = await _with_reasons(hass, mock_client, ("none",))
    assert state.state == "off"


@pytest.mark.parametrize(
    ("reasons", "expected"),
    [
        (("media-jam-warning",), "on"),
        (("door-open",), "on"),
        (("cover-open-error",), "on"),
        (("marker-supply-empty-error",), "on"),
        (("media-needed-error",), "on"),
        (("media-needed",), "on"),
        (("marker-supply-missing-error",), "on"),
        (("toner-empty-report",), "off"),
        (("media-empty-report",), "off"),
        (("toner-low-warning",), "off"),
        (("toner-low-warning", "media-jam-error"), "on"),
        ((), "off"),
    ],
)
async def test_problem_reasons(hass, mock_client, reasons, expected):
    state = await _with_reasons(hass, mock_client, reasons)
    assert state.state == expected
