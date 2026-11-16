"""Build scanned PDFs from raw scanner page images.

Synchronous and CPU-heavy; callers run it in an executor. Pages come from
an eSCL scanner (usually JPEG, sometimes PNG), all at one dpi.
"""

from __future__ import annotations

import io

from PIL import Image

from .errors import InvalidDocument, TooManyPages
from .render import (
    _PDFIUM_LOCK,
    DEFAULT_MAX_PAGES,
    _encode_jpeg,
    _flatten,
    _open_pdf,
)

JPEG_QUALITY = 90
# Scanner output is bigger than a print job: 600 dpi full platen is ~36 MP and
# legal-size ADF ~43 MP, so the 25 MP print cap would reject real scans.
SCAN_MAX_PIXELS = 100_000_000


def normalize_page(data: bytes) -> bytes:
    """A JPEG as-is; PNG or anything else Pillow reads becomes RGB/L JPEG.

    Unreadable data raises ``InvalidDocument("bad_scan")``; images over the
    pixel cap raise ``InvalidDocument("too_large")`` (same reason code as
    render.py, but a higher cap: ``SCAN_MAX_PIXELS``).
    """
    try:
        image = Image.open(io.BytesIO(data))
    except Image.DecompressionBombError as err:
        raise InvalidDocument("too_large") from err
    except (OSError, ValueError, SyntaxError) as err:  # incl. UnidentifiedImageError
        raise InvalidDocument("bad_scan") from err
    try:
        if image.width * image.height > SCAN_MAX_PIXELS:
            raise InvalidDocument("too_large")
        try:
            if image.format == "JPEG":
                # Scanner JPEGs are embedded verbatim, not decoded; a cut-off
                # transfer is caught by the missing end-of-image marker.
                if not data.rstrip(b"\x00 \t\r\n").endswith(b"\xff\xd9"):
                    raise InvalidDocument("bad_scan")
                return data
            flat = _flatten(image)
        except (OSError, ValueError, SyntaxError) as err:
            raise InvalidDocument("bad_scan") from err
    finally:
        image.close()
    return _encode_jpeg(flat, JPEG_QUALITY)


def _jpeg_info(jpeg: bytes) -> tuple[int, int, str]:
    """(width, height, mode) from the JPEG header; no pixel decoding."""
    with Image.open(io.BytesIO(jpeg)) as image:
        return image.width, image.height, image.mode


_COLOR_SPACE = {
    "L": b"/DeviceGray",
    "RGB": b"/DeviceRGB",
    # Adobe-style inverted CMYK, as Pillow writes it.
    "CMYK": b"/DeviceCMYK /Decode [1 0 1 0 1 0 1 0]",
}


def _fmt_pt(value: float) -> bytes:
    return f"{value:.3f}".rstrip("0").rstrip(".").encode()


def build_pdf(pages: list[bytes], dpi: int) -> bytes:
    """One PDF page per image; page size is pixels / ``dpi`` inches.

    Each page's normalized JPEG is embedded byte for byte (DCTDecode), so
    nothing is re-encoded and no pixels are decoded here.
    """
    if dpi < 1:
        raise ValueError("dpi must be at least 1")
    if not pages:
        raise InvalidDocument("no_pages")
    if len(pages) > DEFAULT_MAX_PAGES:
        raise TooManyPages(len(pages), DEFAULT_MAX_PAGES)
    jpegs = [normalize_page(data) for data in pages]

    # Objects: 1 catalog, 2 page tree, then (page, content, image) per scan.
    objects: dict[int, bytes] = {1: b"<< /Type /Catalog /Pages 2 0 R >>"}
    kids = []
    for index, jpeg in enumerate(jpegs):
        width, height, mode = _jpeg_info(jpeg)
        space = _COLOR_SPACE.get(mode)
        if space is None:
            raise InvalidDocument("bad_scan")
        page_id = 3 + index * 3
        content_id, image_id = page_id + 1, page_id + 2
        kids.append(b"%d 0 R" % page_id)
        w_pt, h_pt = width / dpi * 72, height / dpi * 72
        objects[page_id] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %s %s] "
            b"/Resources << /XObject << /Im0 %d 0 R >> >> /Contents %d 0 R >>"
            % (_fmt_pt(w_pt), _fmt_pt(h_pt), image_id, content_id)
        )
        draw = b"q %s 0 0 %s 0 0 cm /Im0 Do Q" % (_fmt_pt(w_pt), _fmt_pt(h_pt))
        objects[content_id] = b"<< /Length %d >>\nstream\n%s\nendstream" % (
            len(draw),
            draw,
        )
        objects[image_id] = (
            b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
            b"/BitsPerComponent 8 /ColorSpace %b /Filter /DCTDecode "
            b"/Length %d >>\nstream\n"
            % (width, height, space, len(jpeg))
            + jpeg
            + b"\nendstream"
        )
    objects[2] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(kids),
        len(kids),
    )

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for number in sorted(objects):
        offsets[number] = out.tell()
        out.write(b"%d 0 obj\n%s\nendobj\n" % (number, objects[number]))
    xref = out.tell()
    count = len(objects) + 1
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % count)
    for number in range(1, count):
        out.write(b"%010d 00000 n \n" % offsets[number])
    out.write(
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (count, xref)
    )
    return out.getvalue()


def append_pdf(pdf: bytes, pages: list[bytes], dpi: int) -> bytes:
    """``pdf`` with ``pages`` added at the end; existing pages are kept."""
    extra = build_pdf(pages, dpi)
    with _PDFIUM_LOCK:
        base = _open_pdf(pdf)
        try:
            total = len(base) + len(pages)
            if total > DEFAULT_MAX_PAGES:
                raise TooManyPages(total, DEFAULT_MAX_PAGES)
            addition = _open_pdf(extra)
            try:
                base.import_pages(addition)
            finally:
                addition.close()
            out = io.BytesIO()
            base.save(out)
        finally:
            base.close()
    return out.getvalue()
