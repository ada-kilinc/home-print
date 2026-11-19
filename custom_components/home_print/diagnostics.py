"""Diagnostics download: what the printer and its scanner report.

Settings → Devices & services → Home Print → ⋮ → Download diagnostics.
Serial numbers, UUIDs, addresses, host names and locations are removed, so
the file can be attached to a GitHub issue. File names of prints and scans
are left out; only counts are included.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from . import HomePrintConfigEntry
from .const import CONF_HOST, CONF_SCANNER_URL, DOMAIN
from .redact import redact_value, redact_xml
from .scanning import active_state, allowed_resolutions, scan_defaults, usable_sources

# IPP attributes that identify the device or where it stands.
IPP_KEYS = frozenset(
    {
        "printer-uuid",
        "device-uuid",
        "printer-uri-supported",
        "printer-more-info",
        "printer-supply-info-uri",
        "printer-icons",
        "printer-dns-sd-name",
        "printer-name",
        "printer-location",
        "printer-geo-location",
        "printer-organization",
        "printer-organizational-unit",
        "printer-contact-col",
    }
)
ENTRY_KEYS = frozenset({CONF_HOST, CONF_SCANNER_URL})
INFO_KEYS = frozenset({"uuid", "serial"})
CAPS_KEYS = frozenset({"uuid"})

SCANNER_XML = ("ScannerCapabilities", "ScannerStatus")


def _error(err: Exception) -> dict[str, str]:
    return {"error": type(err).__name__, "message": str(err)}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HomePrintConfigEntry
) -> dict[str, Any]:
    """Return the entry's diagnostics."""
    integration = await async_get_integration(hass, DOMAIN)
    host = str(entry.data.get(CONF_HOST, ""))
    data = entry.runtime_data
    info = data.coordinator.data
    serial = info.serial if info is not None else None
    extra = tuple(v for v in (host, serial) if v)

    try:
        ipp: Any = await data.client.get_printer_attributes()
    except Exception as err:  # noqa: BLE001 - reported, never raised
        ipp = _error(err)

    result: dict[str, Any] = {
        "version": str(integration.version),
        "entry": {
            "title": redact_value(entry.title, frozenset(), extra),
            "data": redact_value(dict(entry.data), ENTRY_KEYS, extra),
            "options": redact_value(dict(entry.options), ENTRY_KEYS, extra),
        },
        "printer": redact_value(
            dataclasses.asdict(info) if info is not None else None, INFO_KEYS, extra
        ),
        "ipp_attributes": redact_value(ipp, IPP_KEYS, extra),
        "history_entries": len(data.history.entries()),
        "scanner": await _scanner(data.scanner, extra),
    }
    return result


async def _scanner(scanner: Any, extra: tuple[str, ...]) -> dict[str, Any] | None:
    if scanner is None:
        return None
    caps = scanner.caps
    active = active_state(scanner)
    raw: dict[str, Any] = {}
    for name in SCANNER_XML:
        try:
            body = await scanner.client.raw_xml(name)
        except Exception as err:  # noqa: BLE001 - reported, never raised
            raw[name] = _error(err)
            continue
        raw[name] = redact_xml(body.decode("utf-8", errors="replace"), extra=extra)
    return {
        "url": redact_value(scanner.client.base_url, frozenset(), extra),
        "capabilities": redact_value(dataclasses.asdict(caps), CAPS_KEYS, extra),
        "status": dataclasses.asdict(scanner.status) if scanner.status else None,
        # What the card is offered, after the save-size limit.
        "card": {
            "sources": {
                name: {
                    "color_modes": list(src.color_modes),
                    "resolutions": list(allowed_resolutions(src)),
                }
                for name, src in caps.sources.items()
                if name in usable_sources(caps)
            },
            "defaults": scan_defaults(caps),
        },
        "active_scan": active.state if active is not None else None,
        "scans": len(scanner.archive.entries()),
        "raw_xml": raw,
    }
