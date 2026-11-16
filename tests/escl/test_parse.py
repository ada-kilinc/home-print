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


def test_parse_platen_caps():
    caps = parse_capabilities(_read("hp_capabilities_platen.xml"))
    assert caps.sources.keys() == {"platen"}
    src = caps.sources["platen"]
    assert src.resolutions == (75, 100, 200, 300, 600)
    assert src.color_modes == ("color", "gray", "bw")
    assert src.max_width == 2550
    assert src.max_height == 3508
    assert src.formats == ("image/jpeg", "application/pdf")
    assert caps.version == "2.63"
    assert caps.make_model == "HP DeskJet 4670 series"
    assert caps.uuid == "11111111-2222-3333-4444-555555555555"


def test_parse_adf_caps():
    caps = parse_capabilities(_read("hp_capabilities_adf.xml"))
    assert caps.sources.keys() == {"platen", "adf", "adf_duplex"}


def test_parse_status_variants():
    idle = parse_status(_read("status_idle.xml"))
    assert (idle.state, idle.adf_loaded) == ("idle", False)
    busy = parse_status(_read("status_processing.xml"))
    assert (busy.state, busy.adf_loaded) == ("processing", None)
    loaded = parse_status(_read("status_adf_loaded.xml"))
    assert (loaded.state, loaded.adf_loaded) == ("idle", True)


def test_build_settings_platen():
    caps = parse_capabilities(_read("hp_capabilities_platen.xml"))
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
    caps = parse_capabilities(_read("hp_capabilities_adf.xml"))
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
