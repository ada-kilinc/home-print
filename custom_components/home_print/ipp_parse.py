"""Turn a Get-Printer-Attributes answer into PrinterInfo.

Pure: no Home Assistant imports, so ``scripts/remote_check.py`` can load it
next to ``models.py`` without running the integration's ``__init__``.
"""

from __future__ import annotations

from typing import Any

from pyipp.parser import parse_ieee1284_device_id

from .models import (
    Capabilities,
    JpegLimits,
    Marker,
    MediaCaps,
    PrinterInfo,
    RasterCaps,
    normalize_uuid,
)

PRINTER_STATES = {3: "idle", 4: "processing", 5: "stopped"}


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _marker_level(value: Any) -> int | None:
    if isinstance(value, int) and 0 <= value <= 100:
        return value
    return None


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _resolutions(value: Any) -> tuple[int, ...]:
    """Square dpi values from a flat ``[x, y, units]`` or a list of those."""
    items = as_list(value)
    if items and all(isinstance(i, int) for i in items):
        items = [items]
    result: list[int] = []
    for item in items:
        if (
            isinstance(item, (list, tuple))
            and len(item) >= 2
            and isinstance(item[0], int)
            and item[0] == item[1]
            and item[0] not in result
        ):
            result.append(item[0])
    return tuple(result)


def _raster_caps(data: dict[str, Any]) -> RasterCaps | None:
    keys = (
        "pwg-raster-document-type-supported",
        "pwg-raster-document-resolution-supported",
        "urf-supported",
    )
    if not any(k in data for k in keys):
        return None
    sheet_back = data.get("pwg-raster-document-sheet-back")
    return RasterCaps(
        pwg_types=frozenset(as_list(data.get(keys[0]))),
        pwg_resolutions=_resolutions(data.get(keys[1])),
        pwg_sheet_back=sheet_back if isinstance(sheet_back, str) else None,
        urf=frozenset(as_list(data.get(keys[2]))),
    )


def _media_caps(data: dict[str, Any]) -> MediaCaps | None:
    col = data.get("media-col-default")
    if not isinstance(col, dict) or not isinstance(col.get("media-size"), dict):
        return None
    size = col["media-size"]
    width, height = (
        _int_or_none(size.get("x-dimension")),
        _int_or_none(size.get("y-dimension")),
    )
    if width is None or height is None:
        return None
    margins = tuple(
        _int_or_none(col.get(f"media-{side}-margin")) or 0
        for side in ("top", "right", "bottom", "left")
    )
    return MediaCaps(
        default_name=str(data.get("media-default") or col.get("media-size-name") or ""),
        width_hmm=width,
        height_hmm=height,
        margins_hmm=margins,  # type: ignore[arg-type]
    )


def _jpeg_limits(data: dict[str, Any]) -> JpegLimits | None:
    keys = (
        "jpeg-x-dimension-supported",
        "jpeg-y-dimension-supported",
        "jpeg-k-octets-supported",
    )
    if not any(k in data for k in keys):
        return None
    maxima = []
    for key in keys:
        values = [v for v in as_list(data.get(key)) if _int_or_none(v) is not None]
        maxima.append(max(values) if values else None)
    return JpegLimits(*maxima)


def parse_printer(data: dict[str, Any]) -> PrinterInfo:
    """Build PrinterInfo from one pyipp-parsed ``printers`` entry."""
    names = as_list(data.get("marker-names"))
    colors = as_list(data.get("marker-colors"))
    levels = as_list(data.get("marker-levels"))
    kinds = as_list(data.get("marker-types"))
    markers = tuple(
        Marker(
            name=name,
            color=(colors[i] if i < len(colors) and colors[i] != "none" else None),
            level=_marker_level(levels[i]) if i < len(levels) else None,
            kind=kinds[i] if i < len(kinds) else "unknown",
        )
        for i, name in enumerate(names)
    )

    try:
        serial = parse_ieee1284_device_id(data.get("printer-device-id", "")).get("SN")
    except ValueError:
        serial = None

    copies = as_list(data.get("copies-supported"))
    capabilities = Capabilities(
        document_formats=frozenset(as_list(data.get("document-format-supported"))),
        sides=frozenset(as_list(data.get("sides-supported"))),
        color_modes=frozenset(as_list(data.get("print-color-mode-supported"))),
        copies_max=int(copies[-1]) if copies else 1,
        page_ranges=bool(data.get("page-ranges-supported", False)),
        raster=_raster_caps(data),
        media=_media_caps(data),
        jpeg=_jpeg_limits(data),
    )
    return PrinterInfo(
        uuid=normalize_uuid(str(data.get("printer-uuid", ""))),
        make_model=data.get("printer-make-and-model", ""),
        serial=serial or None,
        state=PRINTER_STATES.get(int(data.get("printer-state", 3)), "idle"),
        state_reasons=tuple(as_list(data.get("printer-state-reasons"))),
        markers=markers,
        capabilities=capabilities,
    )
