"""Strip device identifiers from printer and scanner answers.

Used by the diagnostics download and by ``scripts/redact_escl.py``. Only the
standard library, so the script can load this file without Home Assistant.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "**REDACTED**"
PLACEHOLDER_UUID = "00000000-0000-0000-0000-000000000000"

# eSCL elements whose whole text identifies the device.
_XML_ELEMENTS = {
    "SerialNumber": "XXXXXXXXXX",
    "UUID": PLACEHOLDER_UUID,
    "DeviceUuid": PLACEHOLDER_UUID,
    "AdminURI": "http://printer.local/",
    "IconURI": "http://printer.local/icon.png",
}

_PATTERNS = [
    # UUIDs anywhere, also inside URLs ("urn:uuid:...") and attributes.
    (
        re.compile(r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b"),
        PLACEHOLDER_UUID,
    ),
    # MAC addresses.
    (re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"), "00:00:00:00:00:00"),
    # IPv4 addresses.
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "192.0.2.1"),
    # HP-style host names (HP + 6 hex digits), with or without .local.
    (re.compile(r"\bHP[0-9A-Fa-f]{6}(?:\.local)?\b"), "printer.local"),
    # The serial number inside an IEEE 1284 device ID ("SN:CN12AB3CDE;").
    (re.compile(r"(?<=SN:)[^;]+"), "XXXXXXXXXX"),
]


def redact_text(text: str, extra: tuple[str, ...] = ()) -> str:
    """Replace identifiers in free text; ``extra`` are exact strings to hide."""
    for value in extra:
        if value:
            text = text.replace(value, REDACTED)
    for pattern, value in _PATTERNS:
        text = pattern.sub(value, text)
    return text


def redact_value(value: Any, keys: frozenset[str], extra: tuple[str, ...] = ()) -> Any:
    """Redact a JSON-like value: whole values under ``keys``, text everywhere."""
    if isinstance(value, dict):
        return {
            k: REDACTED if k in keys else redact_value(v, keys, extra)
            for k, v in value.items()
        }
    if isinstance(value, (set, frozenset)):
        return sorted(redact_value(v, keys, extra) for v in value)
    if isinstance(value, (list, tuple)):
        return [redact_value(v, keys, extra) for v in value]
    if isinstance(value, bytes):
        return redact_text(value.decode("utf-8", errors="replace"), extra)
    if isinstance(value, str):
        return redact_text(value, extra)
    return value


def redact_xml(
    xml: str, *, note: str | None = None, extra: tuple[str, ...] = ()
) -> str:
    """Redact an eSCL answer; with ``note``, replace its comments by that one."""
    for tag, value in _XML_ELEMENTS.items():
        xml = re.sub(
            rf"(<(?:[\w-]+:)?{tag}(?:\s[^>]*)?>)[^<]*(</(?:[\w-]+:)?{tag}>)",
            rf"\g<1>{value}\g<2>",
            xml,
        )
    xml = redact_text(xml, extra)
    if note is None:
        return xml
    xml = re.sub(r"<!--.*?-->\s*", "", xml, flags=re.S)
    if xml.startswith("<?xml"):
        head, _, rest = xml.partition("?>")
        return f"{head}?>\n<!-- {note} -->{rest}"
    return f"<!-- {note} -->\n{xml}"
