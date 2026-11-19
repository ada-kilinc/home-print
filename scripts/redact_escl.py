"""Redact real eSCL answers so they can be committed as test fixtures.

`remote_check.py --scan-info` saves the scanner's raw answers as
`escl_capabilities.xml` and `escl_status.xml`. They carry the device's
serial number, UUID, addresses and host name. This removes those and
writes the result where the tests read fixtures:

    python scripts/redact_escl.py escl_capabilities.xml \
        tests/fixtures/escl/hp_capabilities_platen.xml

Check the output by eye before committing it.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

PLACEHOLDER_UUID = "00000000-0000-0000-0000-000000000000"

# Elements whose whole text identifies the device.
_ELEMENTS = {
    "SerialNumber": "XXXXXXXXXX",
    "UUID": PLACEHOLDER_UUID,
    "DeviceUuid": PLACEHOLDER_UUID,
    "AdminURI": "http://printer.local/",
    "IconURI": "http://printer.local/icon.png",
}

_PATTERNS = [
    # UUIDs anywhere (also inside URLs or attributes).
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
]


def redact(
    xml: str, *, note: str = "real dump, redacted by scripts/redact_escl.py"
) -> str:
    for tag, value in _ELEMENTS.items():
        xml = re.sub(
            rf"(<(?:[\w-]+:)?{tag}(?:\s[^>]*)?>)[^<]*(</(?:[\w-]+:)?{tag}>)",
            rf"\g<1>{value}\g<2>",
            xml,
        )
    for pattern, value in _PATTERNS:
        xml = pattern.sub(value, xml)
    # Drop an old "synthetic" note and say where the file came from.
    xml = re.sub(r"<!--.*?-->\s*", "", xml, flags=re.S)
    if xml.startswith("<?xml"):
        head, _, rest = xml.partition("?>")
        return f"{head}?>\n<!-- {note} -->{rest}"
    return f"<!-- {note} -->\n{xml}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="raw eSCL XML from remote_check.py")
    parser.add_argument("target", type=Path, help="where to write the redacted copy")
    args = parser.parse_args()
    args.target.write_text(
        redact(args.source.read_text(encoding="utf-8")), encoding="utf-8"
    )
    print(f"wrote {args.target}; check it before committing")


if __name__ == "__main__":
    main()
