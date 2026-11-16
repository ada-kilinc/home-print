"""Apple Raster (URF / UNIRAST) encoder, the fallback for AirPrint-only printers.

Sources (format as written by CUPS and read by cups-filters):
- OpenPrinting/cups ``cups/raster-stream.c``: the ``CUPS_RASTER_WRITE_APPLE``
  writer (file header ``UNIRAST\\0`` + uint32 BE page count; 32-byte page
  header; duplex byte 1 = none, 2 = short-edge (tumble), 3 = long-edge) and
  the Apple reader (code 128 clears the rest of the line to white, 0xFF).
- OpenPrinting/cups-filters ``filter/urftopdf.cpp``: ``urf_page_header``
  layout and decode loop.
- volkerschatz.com/hardware/t230-urf.html: independent write-up of the
  offsets (width at 12, height at 16, dpi at 20 of the page header).
- DM1..DM4 (``urf-supported``): cups-filters ``cfGetBackSideOrientation``
  maps DM1 -> normal, DM2 -> flipped, DM3 -> rotated, DM4 -> manual-tumble
  (as quoted in OpenPrinting/cups-filters issue 762; not confirmed by Apple's
  AirPrint spec, which is not public).

Page header (32 bytes): 0 bits per pixel (8/24), 1 colorspace (0 sGray,
1 sRGB), 2 duplex, 3 quality (0 = printer default), 4 media type, 5 media
position, 6-11 reserved, 12 width, 16 height, 20 dpi (uint32 BE), 24-31
reserved. URF has no copies, tumble or sheet-back field, so back sides are
always transformed in pixels, using the PWG Raster table (see ``pwg.py``).
"""

from __future__ import annotations

import struct
from collections.abc import Iterable, Iterator, Sized

import numpy as np
from PIL import Image

from .pwg import _BACK_TRANSFORMS, _PIXEL_TRANSFORMS, _check_page, encode_bitmap
from .render import ROTATED_INFO_KEY, PageSpec

MAGIC = b"UNIRAST\0"

_DUPLEX_NONE = 1
_DUPLEX_SHORT_EDGE = 2
_DUPLEX_LONG_EDGE = 3
_CS_SGRAY = 0
_CS_SRGB = 1

# urf-supported "DMn" -> pwg-raster-document-sheet-back equivalent.
DM_SHEET_BACK: dict[str, str] = {
    "DM1": "normal",
    "DM2": "flipped",
    "DM3": "rotated",
    "DM4": "manual-tumble",
}


def _page_header(spec: PageSpec, *, duplex: int) -> bytes:
    return struct.pack(
        ">BBBB8xIII8x",
        8 if spec.gray else 24,
        _CS_SGRAY if spec.gray else _CS_SRGB,
        duplex,
        0,  # quality: printer default
        spec.width_px,
        spec.height_px,
        spec.dpi,
    )


def encode_urf(
    pages: Iterable[Image.Image],
    spec: PageSpec,
    *,
    duplex: bool,
    tumble: bool,
    copies: int = 1,
    page_count: int | None = None,
    dm: str | None = None,
) -> Iterator[bytes]:
    """Encode full-sheet pages as an Apple Raster stream, one chunk per page.

    Yields the 12-byte file header first, then a 32-byte header plus bitmap
    per page; input pages are pulled one at a time. The file header carries
    the page count, so it must be known up front: it is ``len(pages)`` for a
    sized input, else ``page_count`` is required (``ValueError``). If both are
    given they must agree; an iterator that turns out to hold another number
    of pages raises ``ValueError`` while streaming (the count was already
    written, so the output must be discarded). With ``duplex`` and an odd
    page count a white back page is appended and counted.

    Duplex back sides (odd 0-based indexes) are transformed in pixels per the
    PWG Table 9 for the sheet-back mapped from ``dm`` (printer's ``urf-
    supported`` DM1..DM4; ``None`` = DM1/normal). A page turned 90° to fit
    (``home_print_rotated`` in ``info``) swaps the binding edge: effective
    tumble = tumble XOR rotated (Ruling O), which is also the header's duplex
    value (2 = short edge, 3 = long edge). URF has no copies field, so only
    ``copies=1`` is accepted; send more copies as the IPP ``copies`` attribute.
    """
    if copies != 1:
        raise ValueError("URF has no copies field: use the IPP copies attribute")
    sheet_back = "normal"
    if duplex and dm is not None:
        if dm not in DM_SHEET_BACK:
            raise ValueError(f"unknown urf-supported duplex mode: {dm!r}")
        sheet_back = DM_SHEET_BACK[dm]
    if isinstance(pages, Sized):
        if page_count is not None and page_count != len(pages):
            raise ValueError(f"page_count {page_count} != {len(pages)} pages")
        page_count = len(pages)
    if page_count is None:
        raise ValueError("page_count is required when pages has no length")
    if page_count < 1:
        raise ValueError("page_count must be at least 1")
    total = page_count + (1 if duplex and page_count % 2 else 0)
    return _encode_pages(
        pages,
        spec,
        duplex=duplex,
        tumble=tumble,
        sheet_back=sheet_back,
        page_count=page_count,
        total=total,
    )


def _encode_pages(
    pages: Iterable[Image.Image],
    spec: PageSpec,
    *,
    duplex: bool,
    tumble: bool,
    sheet_back: str,
    page_count: int,
    total: int,
) -> Iterator[bytes]:
    yield MAGIC + struct.pack(">I", total)
    bpp = 1 if spec.gray else 3
    index = 0
    for page in pages:
        if index >= page_count:
            raise ValueError(f"more pages than page_count ({page_count})")
        _check_page(page, spec)
        page_tumble = tumble != bool(page.info.get(ROTATED_INFO_KEY, False))
        value = _DUPLEX_NONE
        if duplex:
            value = _DUPLEX_SHORT_EDGE if page_tumble else _DUPLEX_LONG_EDGE
            if index % 2:
                transform = _BACK_TRANSFORMS[(sheet_back, page_tumble)]
                # FLIP_LEFT_RIGHT is 0: test for None, not truthiness.
                if (op := _PIXEL_TRANSFORMS[transform]) is not None:
                    page = page.transpose(op)
        yield _page_header(spec, duplex=value) + encode_bitmap(
            np.asarray(page), bpp, white_eol=True
        )
        del page
        index += 1
    if index != page_count:
        raise ValueError(f"page_count is {page_count} but {index} pages were given")
    if duplex and index % 2:
        value = _DUPLEX_SHORT_EDGE if tumble else _DUPLEX_LONG_EDGE
        white = np.full((spec.height_px, spec.width_px * bpp), 0xFF, dtype=np.uint8)
        yield _page_header(spec, duplex=value) + encode_bitmap(
            white, bpp, white_eol=True
        )
