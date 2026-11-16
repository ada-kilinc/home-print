"""Parse eSCL capability/status XML and build scan settings XML."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from .errors import EsclError
from .models import ScannerCaps, ScannerStatus, ScanSettings, SourceCaps

PWG = "http://www.pwg.org/schemas/2010/12/sm"
SCAN = "http://schemas.hp.com/imaging/escl/2011/05/03"
ET.register_namespace("pwg", PWG)
ET.register_namespace("scan", SCAN)
_NS = {"pwg": PWG, "scan": SCAN}

_COLOR_IN = {"RGB24": "color", "Grayscale8": "gray", "BlackAndWhite1": "bw"}
_COLOR_OUT = {v: k for k, v in _COLOR_IN.items()}

_SOURCES = (
    ("platen", "scan:Platen/scan:PlatenInputCaps"),
    ("adf", "scan:Adf/scan:AdfSimplexInputCaps"),
    ("adf_duplex", "scan:Adf/scan:AdfDuplexInputCaps"),
)


def _root(xml: bytes, tag: str) -> ET.Element:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as err:
        raise EsclError("bad_response") from err
    if root.tag != f"{{{SCAN}}}{tag}":
        raise EsclError("bad_response")
    return root


def _text(el: ET.Element, path: str) -> str | None:
    found = el.find(path, _NS)
    if found is None or found.text is None:
        return None
    return found.text.strip() or None


def _int(el: ET.Element, path: str) -> int:
    value = _text(el, path)
    try:
        return int(value) if value is not None else 0
    except ValueError as err:
        raise EsclError("bad_response") from err


def _source(el: ET.Element) -> SourceCaps:
    colors: list[str] = []
    for node in el.findall(".//scan:ColorModes/scan:ColorMode", _NS):
        name = _COLOR_IN.get((node.text or "").strip())
        if name and name not in colors:
            colors.append(name)
    formats: list[str] = []
    for node in el.findall(".//scan:DocumentFormats/*", _NS):
        if node.tag in (f"{{{PWG}}}DocumentFormat", f"{{{SCAN}}}DocumentFormatExt"):
            mime = (node.text or "").strip()
            if mime and mime not in formats:
                formats.append(mime)
    resolutions: set[int] = set()
    for node in el.findall(
        ".//scan:SupportedResolutions/scan:DiscreteResolutions/scan:DiscreteResolution",
        _NS,
    ):
        x, y = _int(node, "scan:XResolution"), _int(node, "scan:YResolution")
        if x and x == y:
            resolutions.add(x)
    return SourceCaps(
        min_width=_int(el, "scan:MinWidth"),
        max_width=_int(el, "scan:MaxWidth"),
        min_height=_int(el, "scan:MinHeight"),
        max_height=_int(el, "scan:MaxHeight"),
        color_modes=tuple(colors),
        resolutions=tuple(sorted(resolutions)),
        formats=tuple(formats),
    )


def parse_capabilities(xml: bytes) -> ScannerCaps:
    """Parse a ScannerCapabilities document."""
    root = _root(xml, "ScannerCapabilities")
    sources: dict[str, SourceCaps] = {}
    for key, path in _SOURCES:
        el = root.find(path, _NS)
        if el is not None:
            sources[key] = _source(el)
    return ScannerCaps(
        version=_text(root, "pwg:Version") or "2.0",
        make_model=_text(root, "pwg:MakeAndModel"),
        uuid=_text(root, "scan:UUID"),
        sources=sources,
    )


def parse_status(xml: bytes) -> ScannerStatus:
    """Parse a ScannerStatus document."""
    root = _root(xml, "ScannerStatus")
    state = (_text(root, "pwg:State") or "").lower()
    if not state:
        raise EsclError("bad_response")
    adf = _text(root, "scan:AdfState")
    adf_loaded: bool | None = None
    if adf == "ScannerAdfLoaded":
        adf_loaded = True
    elif adf is not None:
        adf_loaded = False
    return ScannerStatus(state=state, adf_loaded=adf_loaded)


def build_settings(caps: ScannerCaps, settings: ScanSettings) -> bytes:
    """Build a ScanSettings body scanning the source's full maximum area."""
    src = caps.sources.get(settings.source)
    if src is None or settings.color_mode not in _COLOR_OUT:
        raise EsclError("invalid_option")
    root = ET.Element(f"{{{SCAN}}}ScanSettings")

    def add(parent: ET.Element, ns: str, tag: str, text: str) -> ET.Element:
        el = ET.SubElement(parent, f"{{{ns}}}{tag}")
        el.text = text
        return el

    add(root, PWG, "Version", caps.version)
    regions = ET.SubElement(root, f"{{{PWG}}}ScanRegions")
    region = ET.SubElement(regions, f"{{{PWG}}}ScanRegion")
    add(region, PWG, "Height", str(src.max_height))
    add(region, PWG, "ContentRegionUnits", "escl:ThreeHundredthsOfInches")
    add(region, PWG, "Width", str(src.max_width))
    add(region, PWG, "XOffset", "0")
    add(region, PWG, "YOffset", "0")
    add(root, PWG, "InputSource", "Platen" if settings.source == "platen" else "Feeder")
    add(root, SCAN, "ColorMode", _COLOR_OUT[settings.color_mode])
    add(root, SCAN, "XResolution", str(settings.resolution))
    add(root, SCAN, "YResolution", str(settings.resolution))
    add(root, PWG, "DocumentFormat", settings.mime)
    add(root, SCAN, "DocumentFormatExt", settings.mime)
    if settings.source == "adf_duplex":
        add(root, SCAN, "Duplex", "true")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
