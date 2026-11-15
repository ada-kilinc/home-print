"""Basic repository sanity tests."""

import json
from pathlib import Path

MANIFEST = (
    Path(__file__).parent.parent / "custom_components" / "home_print" / "manifest.json"
)


def test_manifest_valid():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest["domain"] == "home_print"
    assert "_ipp._tcp.local." in manifest["zeroconf"]
    assert "_ipps._tcp.local." in manifest["zeroconf"]
