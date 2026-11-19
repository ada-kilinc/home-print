"""Redact real eSCL answers so they can be committed as test fixtures.

`remote_check.py --scan-info` saves the scanner's raw answers as
`escl_capabilities.xml` and `escl_status.xml`. They carry the device's
serial number, UUID, addresses and host name. This removes those and
writes the result where the tests read fixtures:

    python scripts/redact_escl.py escl_capabilities.xml \
        tests/fixtures/escl/deskjet4670_capabilities.xml

Check the output by eye before committing it. The diagnostics download
in Home Assistant uses the same rules.
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

NOTE = "real dump, redacted by scripts/redact_escl.py"

# Loaded by path: importing the package would need Home Assistant.
_PATH = (
    Path(__file__).resolve().parent.parent / "custom_components/home_print/redact.py"
)
_SPEC = importlib.util.spec_from_file_location("home_print_redact", _PATH)
_redact = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_redact)


def redact(xml: str, *, note: str = NOTE) -> str:
    return _redact.redact_xml(xml, note=note)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="raw eSCL XML from remote_check.py")
    parser.add_argument("target", type=Path, help="where to write the redacted copy")
    args = parser.parse_args()
    text = args.source.read_text(encoding="utf-8")
    args.target.write_text(redact(text), encoding="utf-8")
    print(f"wrote {args.target}; check it before committing")


if __name__ == "__main__":
    main()
