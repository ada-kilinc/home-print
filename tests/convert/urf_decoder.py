"""A small, strict Apple Raster (URF / UNIRAST) decoder for tests.

Written from the format as implemented by CUPS (cups/raster-stream.c, the
``CUPS_RASTER_SYNCapple`` reader) and cups-filters ``urftopdf``, independently
of the encoder: it never imports it.

File: ``UNIRAST\\0`` + uint32 BE page count. Per page a 32-byte header
(bpp, colorspace, duplex, quality, media type, media position, 6 reserved,
uint32 BE width, height, dpi, 8 reserved) then the bitmap: per line a repeat
byte (count - 1), then pixel codes: 0-127 repeat the next pixel code+1 times,
129-255 are 257-code literal pixels, 128 fills the rest of the line white.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from PIL import Image

MAGIC = b"UNIRAST\0"
PAGE_HEADER_SIZE = 32

_COLORSPACES = {0: ("L", 1), 1: ("RGB", 3)}  # sGray/W (0), sRGB (1)


@dataclass
class Page:
    header: dict
    image: Image.Image


def parse_header(raw: bytes) -> dict:
    assert len(raw) == PAGE_HEADER_SIZE
    assert raw[6:12] == bytes(6), "reserved @6"
    assert raw[24:32] == bytes(8), "reserved @24"
    width, height, dpi = struct.unpack_from(">III", raw, 12)
    return {
        "BitsPerPixel": raw[0],
        "ColorSpace": raw[1],
        "Duplex": raw[2],
        "Quality": raw[3],
        "MediaType": raw[4],
        "MediaPosition": raw[5],
        "Width": width,
        "Height": height,
        "Resolution": dpi,
    }


def _decode_bitmap(data: bytes, pos: int, header: dict) -> tuple[bytes, int]:
    _, bpp = _COLORSPACES[header["ColorSpace"]]
    assert header["BitsPerPixel"] == 8 * bpp
    line_len = header["Width"] * bpp
    out = bytearray()
    y = 0
    while y < header["Height"]:
        repeat = data[pos] + 1
        pos += 1
        line = bytearray()
        while len(line) < line_len:
            code = data[pos]
            pos += 1
            if code == 128:
                line += b"\xff" * (line_len - len(line))
                break
            if code < 128:
                line += data[pos : pos + bpp] * (code + 1)
                pos += bpp
            else:
                count = 257 - code
                line += data[pos : pos + count * bpp]
                pos += count * bpp
            if len(line) > line_len:
                raise ValueError(f"run overruns line {y}")
        if y + repeat > header["Height"]:
            raise ValueError("line repeat overruns page")
        out += bytes(line) * repeat
        y += repeat
    return bytes(out), pos


def decode(data: bytes) -> list[Page]:
    """Decode a whole URF stream; the page count must match the pages."""
    if data[:8] != MAGIC:
        raise ValueError("bad file magic")
    (count,) = struct.unpack_from(">I", data, 8)
    pos = 12
    pages = []
    while pos < len(data):
        header = parse_header(data[pos : pos + PAGE_HEADER_SIZE])
        pos += PAGE_HEADER_SIZE
        pixels, pos = _decode_bitmap(data, pos, header)
        mode, _ = _COLORSPACES[header["ColorSpace"]]
        size = (header["Width"], header["Height"])
        pages.append(Page(header, Image.frombytes(mode, size, pixels)))
    if len(pages) != count:
        raise ValueError(f"header says {count} pages, found {len(pages)}")
    return pages
