"""Build scanned PDFs from raw scanner page images.

Synchronous and CPU-heavy; callers run it in an executor. Pages come from
an eSCL scanner (usually JPEG, sometimes PNG), all at one dpi.
"""

from __future__ import annotations

import io

from PIL import Image

from .errors import InvalidDocument
from .render import _PDFIUM_LOCK, MAX_IMAGE_PIXELS, _encode_jpeg, _flatten, _open_pdf

JPEG_QUALITY = 90


def normalize_page(data: bytes) -> bytes:
    """A JPEG as-is; PNG or anything else Pillow reads becomes RGB/L JPEG.

    Unreadable data raises ``InvalidDocument("bad_scan")``; images over the
    pixel cap raise ``InvalidDocument("too_large")`` (the reason code
    render.py already uses for the same limit).
    """
    try:
        image = Image.open(io.BytesIO(data))
    except Image.DecompressionBombError as err:
        raise InvalidDocument("too_large") from err
    except (OSError, ValueError, SyntaxError) as err:  # incl. UnidentifiedImageError
        raise InvalidDocument("bad_scan") from err
    try:
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise InvalidDocument("too_large")
        try:
            if image.format == "JPEG":
                image.load()  # surface truncated data now, not in the PDF step
                return data
            flat = _flatten(image)
        except (OSError, ValueError, SyntaxError) as err:
            raise InvalidDocument("bad_scan") from err
    finally:
        image.close()
    return _encode_jpeg(flat, JPEG_QUALITY)


def build_pdf(pages: list[bytes], dpi: int) -> bytes:
    """One PDF page per image; page size is pixels / ``dpi`` inches."""
    if not pages:
        raise InvalidDocument("no_pages")
    images: list[Image.Image] = []
    try:
        for data in pages:
            image = Image.open(io.BytesIO(normalize_page(data)))
            image.load()
            images.append(image)
        out = io.BytesIO()
        images[0].save(
            out, "PDF", save_all=True, append_images=images[1:], resolution=dpi
        )
        return out.getvalue()
    finally:
        for image in images:
            image.close()


def append_pdf(pdf: bytes, pages: list[bytes], dpi: int) -> bytes:
    """``pdf`` with ``pages`` added at the end; existing pages are kept."""
    extra = build_pdf(pages, dpi)
    with _PDFIUM_LOCK:
        base = _open_pdf(pdf)
        try:
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
