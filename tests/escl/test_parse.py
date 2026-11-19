"""Tests for eSCL XML parsing and settings building."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from custom_components.home_print.escl.errors import EsclError
from custom_components.home_print.escl.models import ScanSettings
from custom_components.home_print.escl.parse import (
    PWG,
    SCAN,
    build_settings,
    parse_capabilities,
    parse_status,
)

FIX = Path(__file__).parent.parent / "fixtures" / "escl"


def _read(name: str) -> bytes:
    return (FIX / name).read_bytes()


def _find(xml: bytes, ns: str, tag: str) -> str | None:
    el = ET.fromstring(xml).find(f".//{{{ns}}}{tag}")
    return None if el is None else el.text


def test_parse_real_deskjet_caps():
    """A redacted dump from a real HP DeskJet 4670: glass and a simplex feeder."""
    caps = parse_capabilities(_read("deskjet4670_capabilities.xml"))
    assert caps.sources.keys() == {"platen", "adf"}
    platen = caps.sources["platen"]
    assert platen.resolutions == (75, 100, 200, 300, 600, 1200)
    assert platen.color_modes == ("gray", "color")
    assert (platen.max_width, platen.max_height) == (2550, 3508)
    assert platen.formats == (
        "application/octet-stream",
        "image/jpeg",
        "application/pdf",
    )
    adf = caps.sources["adf"]
    assert adf.resolutions == (75, 100, 200, 300, 600)
    assert (adf.max_width, adf.max_height) == (2550, 4200)
    assert caps.version == "2.5"
    assert caps.make_model == "DeskJet Ink Advantage 4670 All-in-One Printer series"
    assert caps.uuid is None


def test_parse_adf_caps():
    caps = parse_capabilities(_read("synthetic_capabilities_duplex.xml"))
    assert caps.sources.keys() == {"platen", "adf", "adf_duplex"}


def test_parse_status_variants():
    idle = parse_status(_read("deskjet4670_status_idle.xml"))
    assert (idle.state, idle.adf_loaded) == ("idle", False)
    busy = parse_status(_read("status_processing.xml"))
    assert (busy.state, busy.adf_loaded) == ("processing", None)
    loaded = parse_status(_read("status_adf_loaded.xml"))
    assert (loaded.state, loaded.adf_loaded) == ("idle", True)


def test_build_settings_platen():
    caps = parse_capabilities(_read("deskjet4670_capabilities.xml"))
    xml = build_settings(caps, ScanSettings("platen", "color", 300, "image/jpeg"))
    assert _find(xml, PWG, "InputSource") == "Platen"
    assert _find(xml, SCAN, "ColorMode") == "RGB24"
    assert _find(xml, SCAN, "XResolution") == "300"
    assert _find(xml, SCAN, "YResolution") == "300"
    assert _find(xml, PWG, "Width") == "2550"
    assert _find(xml, PWG, "Height") == "3508"
    assert _find(xml, PWG, "ContentRegionUnits") == "escl:ThreeHundredthsOfInches"
    assert _find(xml, PWG, "DocumentFormat") == "image/jpeg"
    assert _find(xml, SCAN, "DocumentFormatExt") == "image/jpeg"
    assert _find(xml, SCAN, "Duplex") is None


def test_build_settings_duplex():
    caps = parse_capabilities(_read("synthetic_capabilities_duplex.xml"))
    xml = build_settings(caps, ScanSettings("adf_duplex", "gray", 200, "image/jpeg"))
    assert _find(xml, PWG, "InputSource") == "Feeder"
    assert _find(xml, SCAN, "Duplex") == "true"
    assert _find(xml, SCAN, "ColorMode") == "Grayscale8"


def test_bad_xml_raises():
    for func in (parse_capabilities, parse_status):
        with pytest.raises(EsclError) as err:
            func(b"<not xml")
        assert err.value.code == "bad_response"
    with pytest.raises(EsclError):
        parse_status(b"<a/>")
