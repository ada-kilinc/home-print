"""Restart notice when a newer Home Print is installed on disk."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.helpers import issue_registry as ir

from custom_components.home_print.const import DOMAIN
from custom_components.home_print.update_check import (
    DATA_INSTALLED,
    ISSUE_ID,
    async_check_installed,
)

from .common import setup_entry

DISK = "custom_components.home_print.update_check._read_disk_version"


async def _running(hass) -> str:
    from homeassistant.loader import async_get_integration

    return str((await async_get_integration(hass, DOMAIN)).version)


async def test_no_notice_when_disk_matches(hass, mock_client):
    await setup_entry(hass)
    assert hass.data.get(DATA_INSTALLED) is None
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_ID) is None


async def test_notice_while_a_newer_version_waits_for_a_restart(
    hass, mock_client, hass_ws_client
):
    await setup_entry(hass)
    running = await _running(hass)
    with patch(DISK, return_value="9.9.9"):
        assert await async_check_installed(hass) == "9.9.9"

    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_ID)
    assert issue is not None
    assert issue.translation_placeholders == {"installed": "9.9.9", "running": running}
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "home_print/printers"})
    result = (await ws.receive_json())["result"]
    assert result["restart_required"] == "9.9.9"
    assert result["version"] == running

    # Back in step (e.g. the update was rolled back): the notice goes.
    with patch(DISK, return_value=running):
        assert await async_check_installed(hass) is None
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_ID) is None


async def test_unreadable_manifest_is_not_an_update(hass, mock_client):
    await setup_entry(hass)
    with patch(DISK, return_value=None):
        assert await async_check_installed(hass) is None
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_ID) is None
