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

import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PIL import Image, UnidentifiedImageError

from ..models import JpegLimits, MediaCaps
from .errors import InvalidDocument, TooManyPages

PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"

DEFAULT_DPI = 300
DEFAULT_MAX_PAGES = 200
# Explicit cap, well below Pillow's own decompression-bomb limits. 25 MP is
# an A4 sheet at ~570 dpi; a decoded RGBA image this size is ~100 MB, which
# is as much as we want to hold on a small Home Assistant host.
MAX_IMAGE_PIXELS = 25_000_000

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


def _open_image(data: bytes, formats: list[str]) -> Image.Image:
    """Open (header only) an image of one of the Pillow ``formats``."""
    try:
        image = Image.open(io.BytesIO(data), formats=formats)
    except Image.DecompressionBombError as err:
        raise InvalidDocument("too_large") from err
    except UnidentifiedImageError as err:
        raise InvalidDocument(_unidentified_reason(data)) from err
    except (OSError, ValueError, SyntaxError) as err:
        raise InvalidDocument("corrupt") from err
    if image.width * image.height > MAX_IMAGE_PIXELS:
        image.close()
        raise InvalidDocument("too_large")
    return image


def _unidentified_reason(data: bytes) -> str:
    """``unsupported_format`` if Pillow knows the image at all, else corrupt."""
    try:
        Image.open(io.BytesIO(data)).close()
    except Exception:  # noqa: BLE001 - any failure means "not an image"
        return "corrupt"
    return "unsupported_format"


def count_pages(data: bytes) -> int:
    """Number of pages: from the PDF, or 1 for an image."""
    if _is_pdf(data):
        with _PDFIUM_LOCK:
            pdf = _open_pdf(data)
            try:
                return len(pdf)
            finally:
                pdf.close()
    _open_image(data, ["PNG", "JPEG"]).close()
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

    Checked before this returns: format, PDF structure and encryption,
    page selection (``InvalidDocument``, ``TooManyPages``), and for images
    the header (format, pixel cap). Pages are rendered lazily, one per
    ``next()``, so a corrupt PDF page or truncated image data only raises
    ``InvalidDocument("corrupt")`` from the ``next()`` that reaches it.
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
        image = _open_image(data, ["PNG" if fmt == PNG else "JPEG"])
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
                content, rotated = _render_pdf_page(
                    pdf, number - 1, box_w, box_h, spec.gray
                )
            yield _compose(content, spec, rotated)
            del content
    finally:
        with _PDFIUM_LOCK:
            pdf.close()


def _render_pdf_page(
    pdf: pdfium.PdfDocument, index: int, box_w: int, box_h: int, gray: bool
) -> tuple[Image.Image, bool]:
    """Render a page scaled to fit the box, rotated if orientations differ.

    Returns the image and whether it was rotated.
    """
    try:
        page = pdf[index]
    except pdfium.PdfiumError as err:
        raise InvalidDocument("corrupt") from err
    try:
        width, height = page.get_size()  # points, page /Rotate applied
        if width <= 0 or height <= 0:
            raise InvalidDocument("corrupt")
        # Duplex back-side transforms are applied by the encoders (Tasks 3/4).
        rotate = _needs_rotation(width, height, box_w, box_h)
        if rotate:
            width, height = height, width
        scale = min(box_w / width, box_h / height)
        try:
            bitmap = page.render(
                scale=scale,
                rotation=270 if rotate else 0,  # PDFium is clockwise; 270 = CCW
                grayscale=gray,
                rev_byteorder=True,
                fill_color=(255, 255, 255, 255),
            )
        except pdfium.PdfiumError as err:
            raise InvalidDocument("corrupt") from err
        try:
            # copy() detaches the image from the bitmap's ctypes buffer.
            image = bitmap.to_pil().copy()
        finally:
            bitmap.close()
    finally:
        page.close()
    return image, rotate


def _image_pages(image: Image.Image, spec: PageSpec) -> Iterator[Image.Image]:
    left, top, right, bottom = spec.printable
    box_w, box_h = right - left, bottom - top
    # Either orientation may end up on the sheet, so shrink into a square of
    # the long side: never below what the final fit needs.
    longest = max(box_w, box_h)
    try:
        try:
            if image.format == "JPEG":
                # Let libjpeg decode at a reduced scale when the photo is huge.
                image.draft(spec.mode, (longest, longest))
            flat = _flatten(image, (longest, longest))
        except (OSError, ValueError, SyntaxError) as err:
            raise InvalidDocument("corrupt") from err
    finally:
        image.close()
    # Duplex back-side transforms are applied by the encoders (Tasks 3/4).
    rotated = _needs_rotation(flat.width, flat.height, box_w, box_h)
    if rotated:
        flat = flat.transpose(Image.Transpose.ROTATE_90)  # counter-clockwise
    size = _fit_size(flat.width, flat.height, box_w, box_h)
    if size != flat.size:
        flat = flat.resize(size, Image.Resampling.LANCZOS)
    yield _compose(flat, spec, rotated)


def _needs_rotation(width: float, height: float, box_w: int, box_h: int) -> bool:
    """True when content and printable area differ in orientation.

    Square content (or a square area) is never rotated.
    """
    if width == height or box_w == box_h:
        return False
    return (width > height) != (box_w > box_h)


def _fit_size(width: int, height: int, box_w: int, box_h: int) -> tuple[int, int]:
    scale = min(box_w / width, box_h / height)
    return (
        max(1, min(box_w, round(width * scale))),
        max(1, min(box_h, round(height * scale))),
    )


# Set on every sheet from iter_pages: True when the content was turned 90°
# to fit (landscape content on portrait paper). Encoders use it to pick the
# duplex back-side transform (the binding edge swaps with the content).
ROTATED_INFO_KEY = "home_print_rotated"


def _compose(content: Image.Image, spec: PageSpec, rotated: bool) -> Image.Image:
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
    sheet.info[ROTATED_INFO_KEY] = rotated
    return sheet


# --- images -------------------------------------------------------------------


# EXIF orientation -> transpose, as in ImageOps.exif_transpose.
_EXIF_ORIENTATION = 0x0112
_ORIENTATION_TRANSPOSE = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}
_WIDE_GRAY_MODES = ("I", "F")  # plus I;16, I;16B, I;16L, I;16N


def _to_8bit_gray(image: Image.Image) -> Image.Image:
    """Scale a 16-bit, 32-bit integer or float gray image to ``L``.

    Pillow's own ``convert("L")`` clips at 255, so a 16-bit scan would print
    almost white. 16-bit data is shifted down; ``I``/``F`` values are scaled
    from the smallest range that holds them (0..1, 0..255, 0..65535, or 0..max).
    """
    arr = np.asarray(image)
    if image.mode.startswith("I;16"):
        return Image.fromarray((arr.astype(np.uint16) >> 8).astype(np.uint8))
    top = float(arr.max()) if arr.size else 0.0
    if image.mode == "F" and top <= 1.0:
        scale = 255.0
    elif top <= 255:
        scale = 1.0
    elif top <= 65535:
        scale = 255.0 / 65535.0
    else:
        scale = 255.0 / top
    out = np.clip(arr.astype(np.float32) * scale, 0, 255)
    return Image.fromarray(np.rint(out).astype(np.uint8))


def _flatten(
    image: Image.Image, max_size: tuple[int, int] | None = None
) -> Image.Image:
    """Upright image in ``L`` or ``RGB``, with any transparency on white.

    With ``max_size``, the decoded image is shrunk to fit it first, so the
    RGBA copy and the composite are only ever made at the reduced size.
    """
    source = image
    orientation = image.getexif().get(_EXIF_ORIENTATION, 1)
    has_alpha = image.mode in ("RGBA", "LA", "PA", "RGBa", "La") or (
        "transparency" in image.info
    )
    gray = image.mode in ("1", "L", "LA", "La", "I", "F") or image.mode.startswith(
        "I;16"
    )
    # Resizing these would fall back to nearest-neighbour; widen them first.
    if image.mode == "1":
        image = image.convert("L")
    elif image.mode == "P":
        image = image.convert("RGBA" if has_alpha else "RGB")
    elif image.mode in _WIDE_GRAY_MODES or image.mode.startswith("I;16"):
        image = _to_8bit_gray(image)
    if max_size is not None and (
        image.width > max_size[0] or image.height > max_size[1]
    ):
        image = image.resize(
            _fit_size(image.width, image.height, *max_size),
            Image.Resampling.LANCZOS,
            reducing_gap=3.0,
        )
    if (method := _ORIENTATION_TRANSPOSE.get(orientation)) is not None:
        image = image.transpose(method)
    if has_alpha:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, _WHITE_RGB + (255,))
        image = Image.alpha_composite(background, rgba)
    target = "L" if gray else "RGB"
    if image.mode != target:
        return image.convert(target)
    # Callers close the file image; hand back pixels that outlive it.
    return image.copy() if image is source else image


def png_to_jpeg(
    data: bytes, quality: int = 90, max_size: tuple[int, int] | None = None
) -> bytes:
    """Re-encode an image as JPEG, transparency flattened onto white.

    ``max_size`` (width, height) shrinks a bigger image to fit, aspect kept.
    """
    image = _open_image(data, ["PNG"])
    try:
        flat = _flatten(image, max_size)
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
    image = _open_image(data, ["JPEG"])
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
        # Decode at a reduced scale (libjpeg) and shrink before flattening.
        image.draft(None, (max_x, max_y))
        flat = _flatten(image, (max_x, max_y))
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
