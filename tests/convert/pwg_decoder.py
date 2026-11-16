"""A small, strict PWG Raster (PWG 5102.4) decoder for tests.

Written from the spec, independently of the encoder: it never imports it.
Strict on purpose: octet 128 (not defined by PWG 5102.4 section 4.4) and
runs that overrun a line are errors.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from PIL import Image

SYNC = b"RaS2"
HEADER_SIZE = 1796


def _u32(header: bytes, offset: int) -> int:
    return struct.unpack_from(">I", header, offset)[0]


def _i32(header: bytes, offset: int) -> int:
    return struct.unpack_from(">i", header, offset)[0]


def _cstr(header: bytes, offset: int, size: int = 64) -> str:
    return header[offset : offset + size].split(b"\0", 1)[0].decode("ascii")


# Offsets from PWG 5102.4 Table 2 (page header).
_RESERVED = (
    (256, 12),
    (284, 16),
    (312, 12),
    (332, 8),
    (348, 4),
    (360, 8),
    (380, 4),
    (404, 16),
    (424, 28),
    (488, 20),
    (1604, 64),
)


def parse_header(header: bytes) -> dict:
    assert len(header) == HEADER_SIZE
    for offset, size in _RESERVED:
        assert header[offset : offset + size] == bytes(size), f"reserved @{offset}"
    return {
        "PwgRaster": _cstr(header, 0),
        "MediaColor": _cstr(header, 64),
        "MediaType": _cstr(header, 128),
        "PrintContentOptimize": _cstr(header, 192),
        "CutMedia": _u32(header, 268),
        "Duplex": _u32(header, 272),
        "HWResolution": (_u32(header, 276), _u32(header, 280)),
        "InsertSheet": _u32(header, 300),
        "Jog": _u32(header, 304),
        "LeadingEdge": _u32(header, 308),
        "MediaPosition": _u32(header, 324),
        "MediaWeightMetric": _u32(header, 328),
        "NumCopies": _u32(header, 340),
        "Orientation": _u32(header, 344),
        "PageSize": (_u32(header, 352), _u32(header, 356)),
        "Tumble": _u32(header, 368),
        "Width": _u32(header, 372),
        "Height": _u32(header, 376),
        "BitsPerColor": _u32(header, 384),
        "BitsPerPixel": _u32(header, 388),
        "BytesPerLine": _u32(header, 392),
        "ColorOrder": _u32(header, 396),
        "ColorSpace": _u32(header, 400),
        "NumColors": _u32(header, 420),
        "TotalPageCount": _u32(header, 452),
        "CrossFeedTransform": _i32(header, 456),
        "FeedTransform": _i32(header, 460),
        "ImageBox": tuple(_u32(header, 464 + 4 * i) for i in range(4)),
        "AlternatePrimary": _u32(header, 480),
        "PrintQuality": _u32(header, 484),
        "VendorIdentifier": _u32(header, 508),
        "VendorLength": _u32(header, 512),
        "VendorData": header[516:1604],
        "RenderingIntent": _cstr(header, 1668),
        "PageSizeName": _cstr(header, 1732),
    }


@dataclass
class Page:
    header: dict
    image: Image.Image


def _decode_bitmap(data: bytes, pos: int, header: dict) -> tuple[bytes, int]:
    bpp = header["BitsPerPixel"] // 8
    line_len = header["BytesPerLine"]
    assert line_len == header["Width"] * bpp
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
                raise ValueError("octet 128 is not defined by PWG 5102.4")
            if code < 128:
                count = code + 1
                pixel = data[pos : pos + bpp]
                pos += bpp
                line += pixel * count
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
    """Decode a whole PWG Raster stream into pages."""
    if data[:4] != SYNC:
        raise ValueError("bad sync word")
    pos = 4
    pages = []
    while pos < len(data):
        header = parse_header(data[pos : pos + HEADER_SIZE])
        pos += HEADER_SIZE
        pixels, pos = _decode_bitmap(data, pos, header)
        mode = {1: "L", 3: "RGB"}[header["NumColors"]]
        size = (header["Width"], header["Height"])
        pages.append(Page(header, Image.frombytes(mode, size, pixels)))
    return pages
