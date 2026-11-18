"""Tests for serving and auto-loading the dashboard card."""

from unittest.mock import patch

from homeassistant.setup import async_setup_component

from custom_components.home_print.const import DOMAIN
from custom_components.home_print.frontend import async_register_frontend


async def test_static_path_serves_card_js(hass, hass_client):
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_client()
    resp = await client.get("/home_print_static/home-print-card.js")
    assert resp.status == 200
    assert "javascript" in resp.headers["content-type"]
    assert "home-print-card" in await resp.text()


async def test_extra_js_url_registered_with_version(hass):
    with patch(
        "custom_components.home_print.frontend.ha_frontend.add_extra_js_url"
    ) as add:
        assert await async_setup_component(hass, DOMAIN, {})
    add.assert_called_once_with(hass, "/home_print_static/home-print-card.js?v=0.3.6")


async def test_register_frontend_idempotent(hass):
    with patch(
        "custom_components.home_print.frontend.ha_frontend.add_extra_js_url"
    ) as add:
        assert await async_setup_component(hass, DOMAIN, {})
        await async_register_frontend(hass)
    assert add.call_count == 1
