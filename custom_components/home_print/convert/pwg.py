"""PWG Raster (PWG 5102.4) encoder, plus the run-length core shared with URF.

Sources for the back-side handling:
- PWG 5102.4-2012 section 5.1.1 (pwg-raster-document-sheet-back keywords) and
  Table 9 (CrossFeedTransform / FeedTransform for backside images).
- CUPS ``cupsRasterInitHeader`` (cups/raster-stream.c) and the CUPS PPD spec
  ``cupsBackSide`` table, which agree with Table 9 except CUPS documents
  Rotated + Tumble as mirrored; PWG 5102.4 (no transform) is followed here.

Back pages are transformed in pixels (what every printer understands) and
the header transform fields are set to match, as PWG 5102.4 requires.
"""

from __future__ import annotations

import logging
import struct
from collections.abc import Iterable, Iterator, Sized

import numpy as np
from PIL import Image

from .render import ROTATED_INFO_KEY, PageSpec

_LOGGER = logging.getLogger(__name__)

SYNC = b"RaS2"
HEADER_SIZE = 1796

_SGRAY = 18
_SRGB = 19
_ALTERNATE_PRIMARY = 0xFFFFFF  # what CUPS writes; only used by Black/1-bit

_MAX_RUN = 128  # pixels per run code (PWG 5102.4 section 4.4)
_MAX_LINE_REPEAT = 256
_WHITE_EOL = 128  # URF only: "rest of the line is white"; not in PWG 5102.4

# PWG 5102.4 Table 9: (sheet_back, tumble) -> (CrossFeedTransform,
# FeedTransform) for back sides. tumble False = two-sided-long-edge.
# -1 cross-feed = right-to-left (mirror X), -1 feed = bottom-to-top (mirror Y);
# both = rotated 180°.
_BACK_TRANSFORMS: dict[tuple[str, bool], tuple[int, int]] = {
    ("normal", False): (1, 1),
    ("normal", True): (1, 1),
    ("manual-tumble", False): (1, 1),
    ("manual-tumble", True): (-1, -1),
    ("rotated", False): (-1, -1),
    ("rotated", True): (1, 1),
    ("flipped", False): (1, -1),
    ("flipped", True): (-1, 1),
}
_PIXEL_TRANSFORMS = {
    (1, 1): None,
    (-1, -1): Image.Transpose.ROTATE_180,
    (1, -1): Image.Transpose.FLIP_TOP_BOTTOM,
    (-1, 1): Image.Transpose.FLIP_LEFT_RIGHT,
}


# --- compression (shared with URF) -----------------------------------------


def _encode_line(line: np.ndarray, bytes_per_pixel: int, white_eol: bool) -> bytes:
    """Run-length encode one line of ``(width, bytes_per_pixel)`` pixels.

    Codes 0-127: the next pixel repeated code+1 times. 129-255: 257-code
    literal pixels follow. With ``white_eol``, 128 ends the line with white
    (0xFF) pixels; only formats that define it (URF) may ask for it.
    """
    raw = line.tobytes()
    width = line.shape[0]
    bpp = bytes_per_pixel
    # Run boundaries: where a pixel differs from the one before it.
    change = np.flatnonzero(np.any(line[1:] != line[:-1], axis=1)) + 1
    starts = np.concatenate(([0], change))
    lengths = np.diff(np.append(starts, width))
    # Merge neighbouring single pixels into literal segments.
    single = lengths == 1
    new_segment = np.ones(len(starts), dtype=bool)
    new_segment[1:] = ~(single[1:] & single[:-1])
    seg_index = np.flatnonzero(new_segment)
    seg_starts = starts[seg_index].tolist()
    seg_ends = seg_starts[1:] + [width]
    seg_literal = single[seg_index].tolist()

    tail = len(seg_starts)
    if white_eol and not seg_literal[-1] and raw[-bpp:] == b"\xff" * bpp:
        tail -= 1  # the last run is white: replaced by the 0x80 code

    out = bytearray()
    for start, end, literal in zip(
        seg_starts[:tail], seg_ends[:tail], seg_literal[:tail], strict=True
    ):
        if literal:
            pos = start
            while pos < end:
                count = min(end - pos, _MAX_RUN)
                # One pixel cannot be a literal (2-128); send a repeat of 1.
                out.append(0 if count == 1 else 257 - count)
                out += raw[pos * bpp : (pos + count) * bpp]
                pos += count
        else:
            pixel = raw[start * bpp : (start + 1) * bpp]
            remaining = end - start
            while remaining:
                count = min(remaining, _MAX_RUN)
                out.append(count - 1)
                out += pixel
                remaining -= count
    if tail < len(seg_starts):
        out.append(_WHITE_EOL)
    return bytes(out)


def encode_bitmap(
    rows: np.ndarray, bytes_per_pixel: int, *, white_eol: bool = False
) -> bytes:
    """Compress a bitmap: per line a repeat count, then pixel runs.

    ``rows`` is ``(height, width)`` for 1-byte pixels or ``(height, width,
    bytes_per_pixel)``. Identical consecutive lines share one encoded line
    (repeat count 0-255 = 1-256 lines). ``white_eol`` enables the 0x80
    "white to end of line" code, which URF has and PWG Raster does not.
    """
    height = rows.shape[0]
    pixels = np.ascontiguousarray(rows, dtype=np.uint8).reshape(
        height, -1, bytes_per_pixel
    )
    flat = pixels.reshape(height, -1)
    # Lines that differ from the line before them start a new group.
    change = np.flatnonzero(np.any(flat[1:] != flat[:-1], axis=1)) + 1
    starts = np.concatenate(([0], change)).tolist()
    ends = starts[1:] + [height]

    out = bytearray()
    for start, end in zip(starts, ends, strict=True):
        encoded = _encode_line(pixels[start], bytes_per_pixel, white_eol)
        remaining = end - start
        while remaining:
            count = min(remaining, _MAX_LINE_REPEAT)
            out.append(count - 1)
            out += encoded
            remaining -= count
    return bytes(out)


# --- PWG Raster ------------------------------------------------------------


def _cstr(value: str) -> bytes:
    """A 64-byte NUL-padded header string.

    The printer's own value goes here, so a bad one must not fail the job:
    non-ASCII is left blank (a mangled name is worse than none) and anything
    over 63 bytes is cut.
    """
    try:
        data = value.encode("ascii")
    except UnicodeEncodeError:
        data = b""
    return data[:63].ljust(64, b"\0")


def _header(
    spec: PageSpec,
    *,
    duplex: bool,
    tumble: bool,
    copies: int,
    total_pages: int,
    transform: tuple[int, int],
    page_size_name: str,
) -> bytes:
    """A 1796-byte page header; offsets from PWG 5102.4 Table 2."""
    header = bytearray(HEADER_SIZE)  # reserved and unused fields stay 0
    bpp = 1 if spec.gray else 3

    def put(offset: int, fmt: str, *values: int) -> None:
        struct.pack_into(">" + fmt, header, offset, *values)

    header[0:64] = _cstr("PwgRaster")
    # 64 MediaColor, 128 MediaType, 192 PrintContentOptimize: empty.
    put(272, "I", int(duplex))  # Duplex
    put(276, "II", spec.dpi, spec.dpi)  # HWResolution
    put(340, "I", copies)  # NumCopies
    put(
        352,
        "II",
        round(spec.width_px * 72 / spec.dpi),
        round(spec.height_px * 72 / spec.dpi),
    )  # PageSize, points
    put(368, "I", int(duplex and tumble))  # Tumble
    put(372, "II", spec.width_px, spec.height_px)  # Width, Height
    put(384, "III", 8, 8 * bpp, spec.width_px * bpp)  # Bits/Color, /Pixel, Bytes
    put(396, "II", 0, _SGRAY if spec.gray else _SRGB)  # ColorOrder chunky, space
    put(420, "I", bpp)  # NumColors
    put(452, "I", total_pages)  # TotalPageCount, 0 = unknown
    put(456, "ii", *transform)  # CrossFeedTransform, FeedTransform
    put(464, "IIII", *_image_box(spec, transform))
    put(480, "I", _ALTERNATE_PRIMARY)
    # 484 PrintQuality 0 (default); 508.. Vendor*: 0; 1668 RenderingIntent "".
    header[1732:1796] = _cstr(page_size_name)  # PageSizeName
    return bytes(header)


def _image_box(spec: PageSpec, transform: tuple[int, int]) -> tuple[int, ...]:
    """Printable area in bitmap pixels, after the back-side transform.

    Right/bottom are inclusive, as CUPS writes them.
    """
    top, right, bottom, left = spec.margins_px
    if transform[0] < 0:
        left, right = right, left
    if transform[1] < 0:
        top, bottom = bottom, top
    return (left, top, spec.width_px - right - 1, spec.height_px - bottom - 1)


def _check_page(page: Image.Image, spec: PageSpec) -> None:
    if page.size != (spec.width_px, spec.height_px) or page.mode != spec.mode:
        raise ValueError(
            f"page is {page.mode} {page.size}, expected "
            f"{spec.mode} {(spec.width_px, spec.height_px)}"
        )


def encode_pwg(
    pages: Iterable[Image.Image],
    spec: PageSpec,
    *,
    duplex: bool,
    tumble: bool,
    sheet_back: str | None,
    copies: int = 1,
    page_count: int | None = None,
    page_size_name: str = "",
) -> Iterator[bytes]:
    """Encode full-sheet pages as a PWG Raster stream, one chunk per page.

    Yields the ``RaS2`` sync word first, then a header plus bitmap per page;
    input pages are pulled one at a time. With ``duplex`` and an odd page
    count a white back page is added. ``TotalPageCount`` comes from
    ``page_count`` or ``len(pages)``; when neither is known it is 0.

    Duplex back sides (odd 0-based indexes) follow ``sheet_back`` per PWG
    5102.4 Table 9 (``None`` or an unknown keyword = ``normal``, logged). A
    page whose content was turned 90° to fit (``home_print_rotated`` in its
    ``info``) swaps the binding edge, so it uses tumble XOR rotated (Ruling
    O). That is the page's header Tumble too, so printers that transform back
    sides themselves agree.
    """
    sheet_back = sheet_back or "normal"
    if (sheet_back, False) not in _BACK_TRANSFORMS:
        if duplex:
            _LOGGER.warning(
                "Unknown pwg-raster-document-sheet-back %r; using 'normal'",
                sheet_back,
            )
        sheet_back = "normal"
    if page_count is None and isinstance(pages, Sized):
        page_count = len(pages)
    total = page_count or 0
    if duplex and total % 2:
        total += 1  # the blank back page
    return _encode_pages(
        pages,
        spec,
        duplex=duplex,
        tumble=tumble,
        sheet_back=sheet_back,
        copies=copies,
        total=total,
        page_size_name=page_size_name,
    )


def _encode_pages(
    pages: Iterable[Image.Image],
    spec: PageSpec,
    *,
    duplex: bool,
    tumble: bool,
    sheet_back: str,
    copies: int,
    total: int,
    page_size_name: str,
) -> Iterator[bytes]:
    yield SYNC
    bpp = 1 if spec.gray else 3
    index = 0
    for page in pages:
        _check_page(page, spec)
        page_tumble = tumble != bool(page.info.get(ROTATED_INFO_KEY, False))
        transform = (1, 1)
        if duplex and index % 2:
            transform = _BACK_TRANSFORMS[(sheet_back, page_tumble)]
            if (op := _PIXEL_TRANSFORMS[transform]) is not None:
                page = page.transpose(op)
        header = _header(
            spec,
            duplex=duplex,
            tumble=page_tumble,
            copies=copies,
            total_pages=total,
            transform=transform,
            page_size_name=page_size_name,
        )
        yield header + encode_bitmap(np.asarray(page), bpp)
        del page
        index += 1
    if duplex and index % 2:
        # White back side for the last sheet; white needs no transform, but
        # the header still states the sheet's transform.
        transform = _BACK_TRANSFORMS[(sheet_back, tumble)]
        header = _header(
            spec,
            duplex=True,
            tumble=tumble,
            copies=copies,
            total_pages=total,
            transform=transform,
            page_size_name=page_size_name,
        )
        white = np.full((spec.height_px, spec.width_px * bpp), 0xFF, dtype=np.uint8)
        yield header + encode_bitmap(white, bpp)
