"""Render PDFs and images to full-page bitmaps for raster printing.

Everything here is synchronous and CPU-heavy; callers run it in an executor.
Pages are produced one at a time so only one page bitmap is alive at once.
"""

from __future__ import annotations

import io
import re
import threading
from collections.abc import Iterator
from dataclasses import dataclass

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PIL import Image, ImageOps, UnidentifiedImageError

from ..models import JpegLimits, MediaCaps
from .errors import InvalidDocument, TooManyPages

PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"

DEFAULT_DPI = 300
DEFAULT_MAX_PAGES = 200

_A4_HMM = (21000, 29700)
_DEFAULT_MARGIN_HMM = 300  # 3 mm
_HMM_PER_INCH = 2540
_WHITE_RGB = (255, 255, 255)

# PDFium is not thread-safe; executor jobs may overlap.
_PDFIUM_LOCK = threading.RLock()


@dataclass(frozen=True)
class PageSpec:
    """A full sheet in device pixels, margins included."""

    width_px: int
    height_px: int
    dpi: int
    margins_px: tuple[int, int, int, int]  # top, right, bottom, left
    gray: bool

    @property
    def mode(self) -> str:
        return "L" if self.gray else "RGB"

    @property
    def printable(self) -> tuple[int, int, int, int]:
        """Printable area as a (left, top, right, bottom) box."""
        top, right, bottom, left = self.margins_px
        return left, top, self.width_px - right, self.height_px - bottom


def _hmm_to_px(value: int, dpi: int) -> int:
    return round(value * dpi / _HMM_PER_INCH)


def page_spec_for(media: MediaCaps | None, dpi: int, gray: bool) -> PageSpec:
    """The sheet for ``media``, or A4 with 3 mm margins when unknown."""
    if media is None:
        width, height = _A4_HMM
        margins = (_DEFAULT_MARGIN_HMM,) * 4
    else:
        width, height = media.width_hmm, media.height_hmm
        margins = media.margins_hmm
    return PageSpec(
        width_px=_hmm_to_px(width, dpi),
        height_px=_hmm_to_px(height, dpi),
        dpi=dpi,
        margins_px=tuple(_hmm_to_px(m, dpi) for m in margins),
        gray=gray,
    )


# --- documents ----------------------------------------------------------------


def _is_pdf(data: bytes) -> bool:
    # PDFium accepts a header anywhere in the first 1 KiB.
    return b"%PDF-" in data[:1024]


def _open_pdf(data: bytes) -> pdfium.PdfDocument:
    """Open a PDF; never tries passwords. Call with ``_PDFIUM_LOCK`` held."""
    try:
        return pdfium.PdfDocument(data)
    except pdfium.PdfiumError as err:
        if err.err_code in (pdfium_c.FPDF_ERR_PASSWORD, pdfium_c.FPDF_ERR_SECURITY):
            raise InvalidDocument("encrypted") from err
        if err.err_code == pdfium_c.FPDF_ERR_SUCCESS:
            raise InvalidDocument("empty") from err  # loaded, but zero pages
        raise InvalidDocument("corrupt") from err


def _open_image(data: bytes) -> Image.Image:
    try:
        return Image.open(io.BytesIO(data))
    except Image.DecompressionBombError as err:
        raise InvalidDocument("too_large") from err
    except (UnidentifiedImageError, OSError, ValueError) as err:
        raise InvalidDocument("corrupt") from err


def count_pages(data: bytes) -> int:
    """Number of pages: from the PDF, or 1 for an image."""
    if _is_pdf(data):
        with _PDFIUM_LOCK:
            pdf = _open_pdf(data)
            try:
                return len(pdf)
            finally:
                pdf.close()
    _open_image(data).close()
    return 1


def _select(pages: list[int] | None, count: int, max_pages: int) -> list[int]:
    """1-based page numbers to print, validated against ``count``."""
    if pages is None:
        selected = list(range(1, count + 1))
    else:
        selected = sorted({p for p in pages if 1 <= p <= count})
    if not selected:
        raise InvalidDocument("no_pages")
    if len(selected) > max_pages:
        raise TooManyPages(len(selected), max_pages)
    return selected


def iter_pages(
    data: bytes,
    fmt: str,
    spec: PageSpec,
    pages: list[int] | None,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> Iterator[Image.Image]:
    """Yield one full sheet per selected page, in ``spec`` size and mode.

    The document is validated before this returns (``InvalidDocument``,
    ``TooManyPages``); rendering happens lazily, one page per ``next()``.
    """
    if fmt == PDF:
        with _PDFIUM_LOCK:
            pdf = _open_pdf(data)
            try:
                count = len(pdf)
            finally:
                pdf.close()
        return _pdf_pages(data, spec, _select(pages, count, max_pages))
    if fmt in (PNG, JPEG):
        _select(pages, 1, max_pages)
        image = _open_image(data)
        return _image_pages(image, spec)
    raise InvalidDocument("unsupported_format")


def _pdf_pages(
    data: bytes, spec: PageSpec, selected: list[int]
) -> Iterator[Image.Image]:
    left, top, right, bottom = spec.printable
    box_w, box_h = right - left, bottom - top
    with _PDFIUM_LOCK:
        pdf = _open_pdf(data)
    try:
        for number in selected:
            with _PDFIUM_LOCK:
                content = _render_pdf_page(pdf, number - 1, box_w, box_h, spec.gray)
            yield _compose(content, spec)
            del content
    finally:
        with _PDFIUM_LOCK:
            pdf.close()


def _render_pdf_page(
    pdf: pdfium.PdfDocument, index: int, box_w: int, box_h: int, gray: bool
) -> Image.Image:
    """Render a page scaled to fit the box, rotated if orientations differ."""
    page = pdf[index]
    try:
        width, height = page.get_size()  # points, page /Rotate applied
        if width <= 0 or height <= 0:
            raise InvalidDocument("corrupt")
        rotate = _needs_rotation(width, height, box_w, box_h)
        if rotate:
            width, height = height, width
        scale = min(box_w / width, box_h / height)
        bitmap = page.render(
            scale=scale,
            rotation=270 if rotate else 0,  # PDFium turns clockwise; 270 = CCW 90°
            grayscale=gray,
            rev_byteorder=True,
            fill_color=(255, 255, 255, 255),
        )
        # copy() detaches the image from the bitmap's ctypes buffer.
        image = bitmap.to_pil().copy()
        bitmap.close()
    finally:
        page.close()
    return image


def _image_pages(image: Image.Image, spec: PageSpec) -> Iterator[Image.Image]:
    left, top, right, bottom = spec.printable
    box_w, box_h = right - left, bottom - top
    try:
        try:
            if image.format == "JPEG":
                # Let libjpeg decode at a reduced scale when the photo is huge.
                image.draft(spec.mode, (max(box_w, box_h),) * 2)
            flat = _flatten(image)
        except (OSError, ValueError, SyntaxError) as err:
            raise InvalidDocument("corrupt") from err
    finally:
        image.close()
    if _needs_rotation(flat.width, flat.height, box_w, box_h):
        flat = flat.transpose(Image.Transpose.ROTATE_90)  # counter-clockwise
    size = _fit_size(flat.width, flat.height, box_w, box_h)
    if size != flat.size:
        flat = flat.resize(size, Image.Resampling.LANCZOS)
    yield _compose(flat, spec)


def _needs_rotation(width: float, height: float, box_w: int, box_h: int) -> bool:
    """True when content and printable area differ in orientation."""
    return (width > height) != (box_w > box_h)


def _fit_size(width: int, height: int, box_w: int, box_h: int) -> tuple[int, int]:
    scale = min(box_w / width, box_h / height)
    return (
        max(1, min(box_w, round(width * scale))),
        max(1, min(box_h, round(height * scale))),
    )


def _compose(content: Image.Image, spec: PageSpec) -> Image.Image:
    """Centre ``content`` in the printable area of a white sheet."""
    left, top, right, bottom = spec.printable
    box_w, box_h = right - left, bottom - top
    if content.mode != spec.mode:
        content = content.convert(spec.mode)
    if content.width > box_w or content.height > box_h:
        # PDFium rounds bitmap sizes up; trim the stray pixel row/column.
        content = content.crop(
            (0, 0, min(content.width, box_w), min(content.height, box_h))
        )
    sheet = Image.new(spec.mode, (spec.width_px, spec.height_px), "white")
    sheet.paste(
        content,
        (left + (box_w - content.width) // 2, top + (box_h - content.height) // 2),
    )
    return sheet


# --- images -------------------------------------------------------------------


def _flatten(image: Image.Image) -> Image.Image:
    """Upright image in ``L`` or ``RGB``, with any transparency on white."""
    image = ImageOps.exif_transpose(image)
    gray = image.mode in ("1", "L", "LA", "I", "I;16", "F")
    has_alpha = image.mode in ("RGBA", "LA", "PA", "RGBa", "La") or (
        "transparency" in image.info
    )
    if has_alpha:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, _WHITE_RGB + (255,))
        image = Image.alpha_composite(background, rgba)
    target = "L" if gray else "RGB"
    return image if image.mode == target else image.convert(target)


def png_to_jpeg(data: bytes, quality: int = 90) -> bytes:
    """Re-encode an image as JPEG, transparency flattened onto white."""
    image = _open_image(data)
    try:
        flat = _flatten(image)
    except (OSError, ValueError, SyntaxError) as err:
        raise InvalidDocument("corrupt") from err
    finally:
        image.close()
    return _encode_jpeg(flat, quality)


def _encode_jpeg(image: Image.Image, quality: int) -> bytes:
    out = io.BytesIO()
    image.save(out, "JPEG", quality=quality)
    return out.getvalue()


def fit_jpeg(data: bytes, limits: JpegLimits | None) -> bytes:
    """Shrink a JPEG to the printer's limits; unchanged bytes if it fits."""
    if limits is None:
        return data
    image = _open_image(data)
    max_x = limits.max_x or image.width
    max_y = limits.max_y or image.height
    max_bytes = limits.max_kb * 1024 if limits.max_kb else None
    if (
        image.width <= max_x
        and image.height <= max_y
        and (max_bytes is None or len(data) <= max_bytes)
    ):
        image.close()
        return data

    try:
        flat = _flatten(image)
    except (OSError, ValueError, SyntaxError) as err:
        raise InvalidDocument("corrupt") from err
    finally:
        image.close()
    max_x = limits.max_x or flat.width
    max_y = limits.max_y or flat.height
    if flat.width > max_x or flat.height > max_y:
        flat = flat.resize(
            _fit_size(flat.width, flat.height, max_x, max_y), Image.Resampling.LANCZOS
        )
    while True:
        for quality in (90, 80, 70, 60, 50):
            encoded = _encode_jpeg(flat, quality)
            if max_bytes is None or len(encoded) <= max_bytes:
                return encoded
        if min(flat.size) <= 16:
            return encoded  # cannot reasonably go smaller
        flat = flat.resize(
            (max(1, flat.width * 3 // 4), max(1, flat.height * 3 // 4)),
            Image.Resampling.LANCZOS,
        )


# --- page ranges --------------------------------------------------------------

_RANGE = re.compile(r"^(\d*)-(\d*)$")


def parse_page_ranges(value: str | None, page_count: int) -> list[int] | None:
    """Parse ``"1-3,5"`` into ``[1, 2, 3, 5]``; ``None`` / blank means all.

    Supports ``N``, ``N-M``, ``N-`` (to the end) and ``-M`` (from the start).
    Pages outside ``1..page_count`` are dropped.
    """
    if value is None or not value.strip():
        return None
    selected: set[int] = set()
    for token in value.split(","):
        token = token.replace(" ", "")
        if token.isdigit():
            first = last = int(token)
        elif (match := _RANGE.match(token)) and any(match.groups()):
            first = int(match.group(1) or 1)
            if match.group(2):
                last = int(match.group(2))
                if last < first:
                    raise InvalidDocument("invalid_page_ranges")
            else:
                last = page_count
        else:
            raise InvalidDocument("invalid_page_ranges")
        selected.update(range(max(first, 1), min(last, page_count) + 1))
    if not selected:
        raise InvalidDocument("no_pages")
    return sorted(selected)
