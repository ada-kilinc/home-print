"""Turn an uploaded document into bytes the printer accepts.

Synchronous and CPU-heavy: callers run ``prepare`` in an executor.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from ..models import Capabilities, PrintOptions
from .errors import InvalidDocument, NoConversionRoute, TooManyPages
from .pwg import encode_pwg
from .render import (
    DEFAULT_DPI,
    DEFAULT_MAX_PAGES,
    JPEG,
    PDF,
    PNG,
    count_pages,
    fit_jpeg,
    iter_pages,
    page_spec_for,
    parse_page_ranges,
    png_to_jpeg,
)
from .urf import encode_urf

__all__ = [
    "NoConversionRoute",
    "PreparedJob",
    "choose_target",
    "is_gray",
    "prepare",
]

PWG = "image/pwg-raster"
URF = "image/urf"

GRAY_MODES = frozenset({"monochrome", "process-monochrome", "auto-monochrome"})

# Target formats per source format, best first (Global Constraints).
_TARGETS: dict[str, tuple[str, ...]] = {
    PDF: (PDF, PWG, URF),
    PNG: (PNG, JPEG, PWG, URF),
    JPEG: (JPEG, PWG, URF),
}

_URF_KEY = re.compile(r"^([A-Z]+)(\d+(?:-\d+)*)$")
_URF_DM = re.compile(r"^DM\d$", re.IGNORECASE)


@dataclass(frozen=True)
class PreparedJob:
    """What to send: the bytes, their format and how to treat page-ranges.

    ``page_count`` is the number of pages converted (before any blank duplex
    back page); ``None`` when the file is sent as it came.
    """

    data: bytes
    document_format: str
    send_page_ranges: bool
    page_count: int | None


def is_gray(options: PrintOptions) -> bool:
    """True when the job asks for a monochrome print."""
    return options.color_mode in GRAY_MODES


def _urf_values(caps: Capabilities, prefix: str) -> set[int]:
    """Numbers listed for ``prefix`` in urf-supported: ``W8-16`` -> {8, 16}."""
    values: set[int] = set()
    if caps.raster is None:
        return values
    for key in caps.raster.urf:
        match = _URF_KEY.match(key.upper())
        if match and match.group(1) == prefix:
            values.update(int(v) for v in match.group(2).split("-"))
    return values


def _pwg_ok(caps: Capabilities, gray: bool) -> bool:
    types = caps.raster.pwg_types if caps.raster else frozenset()
    # Not reported: IPP Everywhere makes sgray_8 and srgb_8 mandatory.
    return not types or ("sgray_8" if gray else "srgb_8") in types


def _urf_ok(caps: Capabilities, gray: bool) -> bool:
    if caps.raster is None or not caps.raster.urf:
        return True  # not reported: W8 and SRGB24 are AirPrint's baseline
    if gray:
        return 8 in _urf_values(caps, "W")
    return 24 in _urf_values(caps, "SRGB")


def choose_target(
    src_fmt: str, caps: Capabilities, *, gray: bool = False
) -> str | None:
    """The format to send ``src_fmt`` as, or ``None`` if there is no route.

    A printer that lists no formats at all gets the file as it is. Raster
    targets need the matching 8-bit type (``sgray_8``/``srgb_8``, URF
    ``W8``/``SRGB24``) when the printer reports its raster types.
    """
    formats = caps.document_formats
    if not formats:
        return src_fmt
    for target in _TARGETS.get(src_fmt, (src_fmt,)):
        if target not in formats:
            continue
        if target == PWG and not _pwg_ok(caps, gray):
            continue
        if target == URF and not _urf_ok(caps, gray):
            continue
        return target
    return None


def _closest_to_default(values: set[int] | tuple[int, ...]) -> int:
    if not values:
        return DEFAULT_DPI
    return min(values, key=lambda dpi: (abs(dpi - DEFAULT_DPI), dpi))


def _urf_resolution(caps: Capabilities) -> int:
    return _closest_to_default(_urf_values(caps, "RS"))


def _urf_dm(caps: Capabilities) -> str | None:
    if caps.raster is None:
        return None
    modes = sorted(k.upper() for k in caps.raster.urf if _URF_DM.match(k))
    return modes[0] if modes else None


def _selected_pages(
    data: bytes, options: PrintOptions, max_pages: int
) -> tuple[list[int] | None, int]:
    """Pages to print (``None`` = all) and how many that is."""
    count = count_pages(data)
    pages = parse_page_ranges(options.page_ranges, count)
    selected = len(pages) if pages is not None else count
    if selected > max_pages:
        raise TooManyPages(selected, max_pages)
    return pages, selected


def prepare(
    data: bytes,
    src_fmt: str,
    caps: Capabilities,
    options: PrintOptions,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> PreparedJob:
    """Pick the target format and produce the bytes to send.

    Passthrough (target == ``src_fmt``) keeps the file, only shrinking a JPEG
    over the printer's limits, and leaves page-ranges to the printer.
    Otherwise the selected pages are rendered and encoded one at a time and
    page-ranges must not be sent. Raises ``NoConversionRoute``,
    ``InvalidDocument`` or ``TooManyPages``.
    """
    gray = is_gray(options)
    target = choose_target(src_fmt, caps, gray=gray)
    if target is None:
        raise NoConversionRoute(src_fmt)
    if target == src_fmt:
        if src_fmt == JPEG:
            data = fit_jpeg(data, caps.jpeg)
        return PreparedJob(data, src_fmt, send_page_ranges=True, page_count=None)

    pages, selected = _selected_pages(data, options, max_pages)
    if target == JPEG:  # PNG -> JPEG; an image is a single page
        return PreparedJob(
            fit_jpeg(png_to_jpeg(data), caps.jpeg),
            JPEG,
            send_page_ranges=False,
            page_count=selected,
        )

    duplex = options.sides != "one-sided"
    tumble = options.sides == "two-sided-short-edge"
    media = caps.media
    chunks: Iterator[bytes]
    if target == PWG:
        resolutions = caps.raster.pwg_resolutions if caps.raster else ()
        spec = page_spec_for(media, _closest_to_default(resolutions), gray)
        chunks = encode_pwg(
            iter_pages(data, src_fmt, spec, pages, max_pages),
            spec,
            duplex=duplex,
            tumble=tumble,
            sheet_back=caps.raster.pwg_sheet_back if caps.raster else None,
            copies=1,
            page_count=selected,
            page_size_name=media.default_name if media else "",
        )
    elif target == URF:
        spec = page_spec_for(media, _urf_resolution(caps), gray)
        chunks = encode_urf(
            iter_pages(data, src_fmt, spec, pages, max_pages),
            spec,
            duplex=duplex,
            tumble=tumble,
            copies=1,
            page_count=selected,
            dm=_urf_dm(caps),
        )
    else:  # pragma: no cover - _TARGETS only lists the formats handled above
        raise InvalidDocument("unsupported_format")
    return PreparedJob(
        b"".join(chunks), target, send_page_ranges=False, page_count=selected
    )
