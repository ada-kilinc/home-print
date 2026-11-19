"""scripts/redact_escl.py strips device identifiers from eSCL dumps."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PATH = Path(__file__).parent.parent / "scripts" / "redact_escl.py"
_SPEC = importlib.util.spec_from_file_location("redact_escl", _PATH)
redact_escl = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(redact_escl)

RAW = """<?xml version="1.0" encoding="UTF-8"?>
<!-- old note -->
<scan:ScannerCapabilities xmlns:pwg="p" xmlns:scan="s">
  <pwg:MakeAndModel>HP DeskJet 4670 series</pwg:MakeAndModel>
  <pwg:SerialNumber>CN12AB3CDE</pwg:SerialNumber>
  <scan:UUID>1c852a4d-b800-1f08-abcd-a0d3c1234567</scan:UUID>
  <scan:AdminURI>http://HP1A2B3C.local./#hId-pgDevInfo</scan:AdminURI>
  <scan:IconURI>http://192.168.1.37/ipp/images/printer.png</scan:IconURI>
  <scan:Note>mac a0:d3:c1:12:34:56 at 192.168.1.37 HP1A2B3C</scan:Note>
  <scan:MaxWidth>2550</scan:MaxWidth>
</scan:ScannerCapabilities>
"""


def test_redacts_identifiers_and_keeps_capabilities() -> None:
    out = redact_escl.redact(RAW)
    for secret in (
        "CN12AB3CDE",
        "1c852a4d",
        "HP1A2B3C",
        "192.168.1.37",
        "a0:d3:c1",
        "old note",
    ):
        assert secret not in out
    assert "<pwg:MakeAndModel>HP DeskJet 4670 series</pwg:MakeAndModel>" in out
    assert "<scan:MaxWidth>2550</scan:MaxWidth>" in out
    assert out.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<!-- real dump')


def test_command_line(tmp_path: Path) -> None:
    source = tmp_path / "escl_capabilities.xml"
    source.write_text(RAW, encoding="utf-8")
    target = tmp_path / "out.xml"
    argv = sys.argv
    sys.argv = ["redact_escl.py", str(source), str(target)]
    try:
        redact_escl.main()
    finally:
        sys.argv = argv
    assert "CN12AB3CDE" not in target.read_text(encoding="utf-8")
