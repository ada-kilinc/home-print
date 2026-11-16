"""Shared helpers for Home Print tests."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_print.const import (
    CONF_BASE_PATH,
    CONF_HOST,
    CONF_PORT,
    CONF_SSL,
    CONF_VERIFY_SSL,
    DOMAIN,
)
from custom_components.home_print.escl.models import ScannerCaps, SourceCaps

URL = "http://192.168.1.50/eSCL"
CAPS = ScannerCaps(
    version="2.63",
    make_model="Test Scanner",
    uuid=None,
    sources={
        "platen": SourceCaps(0, 2550, 0, 3507, ("color",), (300,), ("image/jpeg",))
    },
)

UUID = "0a1b2c3d-4e5f-6789-abcd-0123456789ef"

PDF = b"%PDF-1.7\n%test\n"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def make_entry(unique_id: str = UUID, **options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=unique_id,
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
