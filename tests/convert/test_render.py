"""Tests for rendering PDFs and images to print pages."""

from __future__ import annotations

import io

import numpy as np
import pypdfium2 as pdfium
import pytest
from PIL import Image

from custom_components.home_print.convert.errors import (
    ConvertError,
    InvalidDocument,
    TooManyPages,
)
from custom_components.home_print.convert.render import (
    PageSpec,
    count_pages,
    fit_jpeg,
    iter_pages,
    page_spec_for,
    parse_page_ranges,
    png_to_jpeg,
)
from custom_components.home_print.models import JpegLimits, MediaCaps

from . import samples

PDF = "application/pdf"
A4_300 = page_spec_for(None, 300, gray=False)
# A low resolution keeps the pixel-inspection tests fast.
A4_100 = page_spec_for(None, 100, gray=False)


def _is_red(pixel) -> bool:
    r, g, b = pixel
    return r > 200 and g < 60 and b < 60


def _is_white(pixel) -> bool:
    return all(c > 245 for c in pixel)


def _printable_box(spec: PageSpec) -> tuple[int, int, int, int]:
    top, right, bottom, left = spec.margins_px
    return left, top, spec.width_px - right, spec.height_px - bottom


def test_page_spec_defaults_to_a4_with_3mm_margins():
    assert A4_300 == PageSpec(
        width_px=2480, height_px=3508, dpi=300, margins_px=(35, 35, 35, 35), gray=False
    )


def test_page_spec_from_media_caps():
    letter = MediaCaps("na_letter_8.5x11in", 21590, 27940, (300, 300, 300, 600))
    spec = page_spec_for(letter, 300, gray=True)
    assert spec == PageSpec(2550, 3300, 300, (35, 35, 35, 71), True)


def test_count_pages_pdf_and_image():
    assert count_pages(samples.blank_pdf(3)) == 3
    png = samples.image_bytes(samples.page_image(40, 60), "PNG")
    jpeg = samples.image_bytes(samples.page_image(40, 60), "JPEG")
    assert count_pages(png) == 1
    assert count_pages(jpeg) == 1


@pytest.mark.parametrize(("gray", "mode"), [(True, "L"), (False, "RGB")])
def test_iter_pages_size_and_mode(gray, mode):
    spec = page_spec_for(None, 300, gray=gray)
    pdf = samples.pdf_from_images([samples.page_image(*samples.A4_PT)])
    png = samples.image_bytes(samples.page_image(300, 200), "PNG")
    for data, fmt in ((pdf, PDF), (png, "image/png")):
        pages = list(iter_pages(data, fmt, spec, None))
        assert len(pages) == 1
        assert pages[0].size == (2480, 3508)
        assert pages[0].mode == mode


def test_landscape_page_rotated_to_fit():
    portrait = samples.page_image(*samples.A4_PT)
    landscape = samples.page_image(*reversed(samples.A4_PT))
    pdf = samples.pdf_from_images([portrait, landscape])

    first, second = list(iter_pages(pdf, PDF, A4_100, None))

    left, top, right, bottom = _printable_box(A4_100)
    inset = 8  # stay clear of centring offsets and edge antialiasing
    top_left = (left + inset, top + inset)
    bottom_left = (left + inset, bottom - inset)

    # Portrait page: mark stays top-left.
    assert _is_red(first.getpixel(top_left))
    assert _is_white(first.getpixel(bottom_left))
    # Landscape page, rotated 90° counter-clockwise: its top-left corner
    # ends up bottom-left on the portrait sheet.
    assert second.size == (A4_100.width_px, A4_100.height_px)
    assert _is_red(second.getpixel(bottom_left))
    assert _is_white(second.getpixel(top_left))


def test_landscape_image_rotated_to_fit():
    jpeg = samples.image_bytes(samples.page_image(600, 400), "JPEG", quality=95)
    (page,) = iter_pages(jpeg, "image/jpeg", A4_100, None)
    left, top, right, bottom = _printable_box(A4_100)
    # 600x400 rotated -> 400x600, fitted to the printable area and centred;
    # the mark (top-left of the landscape image) lands bottom-left.
    scale = min((right - left) / 400, (bottom - top) / 600)
    content_w, content_h = round(400 * scale), round(600 * scale)
    content_left = left + (right - left - content_w) // 2
    content_top = top + (bottom - top - content_h) // 2
    assert _is_red(page.getpixel((content_left + 8, content_top + content_h - 8)))
    assert _is_white(page.getpixel((content_left + 8, content_top + 8)))
    assert _is_white(page.getpixel((content_left + content_w - 8, content_top + 8)))


def test_content_fits_inside_margins():
    black = samples.page_image(*samples.A4_PT, background=(0, 0, 0), mark=False)
    pdf = samples.pdf_from_images([black])
    (page,) = iter_pages(pdf, PDF, A4_100, None)
    left, top, right, bottom = _printable_box(A4_100)
    w, h = page.size
    for box in ((0, 0, w, top), (0, bottom, w, h), (0, 0, left, h), (right, 0, w, h)):
        assert page.crop(box).convert("L").getextrema() == (255, 255), box
    # The content itself reaches the printable area.
    assert page.crop((left, top, right, bottom)).convert("L").getextrema()[0] < 10


def test_page_selection():
    red = samples.page_image(*samples.A4_PT, background=samples.RED, mark=False)
    white = samples.page_image(*samples.A4_PT, mark=False)
    pdf = samples.pdf_from_images([white, red, white])
    pages = list(iter_pages(pdf, PDF, A4_100, [2]))
    assert len(pages) == 1
    centre = (A4_100.width_px // 2, A4_100.height_px // 2)
    assert _is_red(pages[0].getpixel(centre))


def test_page_selection_out_of_range_raises():
    with pytest.raises(InvalidDocument, match="no_pages"):
        iter_pages(samples.blank_pdf(2), PDF, A4_100, [5])


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(bytes(range(256)) * 8, id="random"),
        pytest.param(b"%PDF-1.4\n" + bytes(range(256)) * 8, id="corrupt-pdf"),
        pytest.param(samples.encrypted_pdf(), id="encrypted"),
    ],
)
def test_encrypted_or_corrupt_pdf_raises_invalid_document(data):
    with pytest.raises(InvalidDocument):
        count_pages(data)
    with pytest.raises(InvalidDocument):
        iter_pages(data, PDF, A4_100, None)


def test_encrypted_pdf_reason():
    with pytest.raises(InvalidDocument, match="encrypted"):
        count_pages(samples.encrypted_pdf())


def test_corrupt_image_raises_invalid_document():
    with pytest.raises(InvalidDocument):
        iter_pages(b"\x89PNG\r\n\x1a\nnot really", "image/png", A4_100, None)


def test_too_many_pages():
    with pytest.raises(TooManyPages) as err:
        iter_pages(samples.blank_pdf(201), PDF, A4_100, None)
    assert (err.value.count, err.value.limit) == (201, 200)
    assert isinstance(err.value, ConvertError)
    # Selecting few enough pages is fine; so is exactly the limit.
    assert len(list(iter_pages(samples.blank_pdf(201), PDF, A4_100, [1]))) == 1
    assert sum(1 for _ in iter_pages(samples.blank_pdf(3), PDF, A4_100, None, 3)) == 3


def test_png_alpha_becomes_white():
    image = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    image.paste((0, 0, 255, 255), (40, 40, 60, 60))
    png = samples.image_bytes(image, "PNG")

    jpeg = Image.open(io.BytesIO(png_to_jpeg(png)))
    assert jpeg.format == "JPEG"
    assert _is_white(jpeg.getpixel((5, 5)))
    r, g, b = jpeg.getpixel((50, 50))
    assert b > 200 and r < 60 and g < 60

    (page,) = iter_pages(png, "image/png", A4_100, None)
    assert _is_white(page.getpixel((A4_100.width_px // 2, 60)))
    centre = page.getpixel((A4_100.width_px // 2, A4_100.height_px // 2))
    assert centre[2] > 200 and centre[0] < 60


def test_fit_jpeg_respects_limits():
    wide = samples.image_bytes(Image.new("RGB", (9000, 100), (10, 120, 200)), "JPEG")
    limits = JpegLimits(max_x=8192, max_y=8192, max_kb=None)
    out = Image.open(io.BytesIO(fit_jpeg(wide, limits)))
    assert out.format == "JPEG"
    assert out.width <= 8192 and out.height <= 8192
    assert out.width == 8192 and abs(out.height - 91) <= 1  # aspect kept

    small = samples.image_bytes(samples.page_image(200, 100), "JPEG")
    assert fit_jpeg(small, limits) is small
    assert fit_jpeg(small, None) is small


def test_fit_jpeg_respects_size_limit():
    noisy = Image.effect_noise((1200, 1200), 100).convert("RGB")
    data = samples.image_bytes(noisy, "JPEG", quality=95)
    assert len(data) > 200 * 1024
    out = fit_jpeg(data, JpegLimits(max_x=None, max_y=None, max_kb=200))
    assert len(out) <= 200 * 1024
    assert Image.open(io.BytesIO(out)).format == "JPEG"


@pytest.mark.parametrize(
    ("value", "count", "expected"),
    [
        (None, 5, None),
        ("", 5, None),
        ("  ", 5, None),
        ("1-3,5", 10, [1, 2, 3, 5]),
        ("5, 1-2, 2", 10, [1, 2, 5]),
        ("3-", 5, [3, 4, 5]),
        ("4-9", 5, [4, 5]),
        ("0-2", 5, [1, 2]),
        ("7", 7, [7]),
    ],
)
def test_parse_page_ranges(value, count, expected):
    assert parse_page_ranges(value, count) == expected


@pytest.mark.parametrize("value", ["8-9", "6", "0"])
def test_parse_page_ranges_empty_raises(value):
    with pytest.raises(InvalidDocument, match="no_pages"):
        parse_page_ranges(value, 5)


@pytest.mark.parametrize("value", ["abc", "3-1", "1--2", "1,,2", "-"])
def test_parse_page_ranges_invalid_raises(value):
    with pytest.raises(InvalidDocument, match="invalid_page_ranges"):
        parse_page_ranges(value, 5)


def test_iter_pages_is_lazy(monkeypatch):
    calls = []
    original = pdfium.PdfPage.render

    def counting_render(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pdfium.PdfPage, "render", counting_render)
    pages = iter_pages(samples.blank_pdf(3), PDF, A4_100, None)
    assert calls == []
    next(pages)
    assert len(calls) == 1
    next(pages)
    assert len(calls) == 2


def test_convert_package_does_not_import_homeassistant():
    import ast
    from pathlib import Path

    package = Path(__file__).parents[2] / "custom_components/home_print/convert"
    for path in package.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    assert node.level == 1 or node.module == "models", path
                names = [node.module or ""]
            else:
                continue
            assert not any(n.startswith("homeassistant") for n in names), path


def test_corrupt_pdf_page_raises_invalid_document_lazily():
    data = samples.pdf_with_broken_second_page()
    assert count_pages(data) == 2
    pages = iter_pages(data, PDF, A4_100, None)
    first = next(pages)
    assert first.size == (A4_100.width_px, A4_100.height_px)
    with pytest.raises(InvalidDocument, match="corrupt"):
        next(pages)


@pytest.mark.parametrize("pil_format", ["GIF", "BMP"])
def test_other_image_formats_are_unsupported(pil_format):
    data = samples.image_bytes(samples.page_image(40, 60), pil_format)
    with pytest.raises(InvalidDocument, match="unsupported_format"):
        count_pages(data)
    for fmt in ("image/png", "image/jpeg"):
        with pytest.raises(InvalidDocument, match="unsupported_format"):
            iter_pages(data, fmt, A4_100, None)
    with pytest.raises(InvalidDocument, match="unsupported_format"):
        png_to_jpeg(data)


def test_declared_format_must_match_image():
    png = samples.image_bytes(samples.page_image(40, 60), "PNG")
    with pytest.raises(InvalidDocument, match="unsupported_format"):
        iter_pages(png, "image/jpeg", A4_100, None)


def test_image_pixel_cap(monkeypatch):
    from custom_components.home_print.convert import render

    assert render.MAX_IMAGE_PIXELS == 25_000_000
    # 5000x5001 = 25.005 MP: just over the cap, far below Pillow's own bomb
    # check (~89 MP warning). Only the header is read.
    big = Image.new("L", (5000, 5001), 255)
    png = samples.image_bytes(big, "PNG")
    with pytest.raises(InvalidDocument, match="too_large"):
        iter_pages(png, "image/png", A4_100, None)
    with pytest.raises(InvalidDocument, match="too_large"):
        count_pages(png)
    monkeypatch.setattr(render, "MAX_IMAGE_PIXELS", 10_000)
    small = samples.image_bytes(Image.new("L", (101, 100), 255), "JPEG")
    with pytest.raises(InvalidDocument, match="too_large"):
        fit_jpeg(small, JpegLimits(max_x=None, max_y=None, max_kb=None))


def test_square_content_is_not_rotated():
    from custom_components.home_print.convert.render import _needs_rotation

    assert not _needs_rotation(500, 500, 800, 600)
    assert not _needs_rotation(500, 500, 600, 800)
    assert _needs_rotation(600, 500, 600, 800)


def test_pages_record_whether_content_was_rotated():
    """Encoders need this for duplex back sides (Ruling O)."""
    portrait = samples.page_image(*samples.A4_PT)
    landscape = samples.page_image(*reversed(samples.A4_PT))
    pdf = samples.pdf_from_images([portrait, landscape])
    first, second = iter_pages(pdf, PDF, A4_100, None)
    assert first.info["home_print_rotated"] is False
    assert second.info["home_print_rotated"] is True

    for size, rotated in (((600, 400), True), ((400, 600), False)):
        png = samples.image_bytes(samples.page_image(*size), "PNG")
        (page,) = iter_pages(png, "image/png", A4_100, None)
        assert page.info["home_print_rotated"] is rotated


# --- high bit depth (I5) ----------------------------------------------------


def _gradient16() -> Image.Image:
    """A 0..65535 top-to-bottom gradient in mode I;16 (mean ~ half scale)."""
    column = np.linspace(0, 65535, 256).astype(np.uint16)
    return Image.fromarray(np.tile(column[:, None], (1, 64)))


def _mean(image: Image.Image) -> float:
    return float(np.asarray(image.convert("L"), dtype=np.float64).mean())


def test_16bit_gray_png_is_not_blank():
    png = samples.image_bytes(_gradient16(), "PNG")
    assert Image.open(io.BytesIO(png)).mode == "I;16"

    jpeg = Image.open(io.BytesIO(png_to_jpeg(png)))
    assert abs(_mean(jpeg) - 127) <= 10

    spec = page_spec_for(None, 100, gray=True)
    (page,) = iter_pages(png, "image/png", spec, None)
    left, top, right, bottom = spec.printable
    # The portrait gradient fills the printable height; sample down its middle.
    band = page.crop((page.width // 2 - 5, top, page.width // 2 + 5, bottom))
    assert abs(_mean(band) - 127) <= 10


@pytest.mark.parametrize(
    ("array", "mode"),
    [
        (np.linspace(0, 65535, 256).astype(np.int32), "I"),
        (np.linspace(0, 65535, 256).astype(np.float32), "F"),
        (np.linspace(0, 1, 256).astype(np.float32), "F"),
    ],
)
def test_flatten_scales_wide_gray_modes_to_8_bit(array, mode):
    from custom_components.home_print.convert.render import _flatten

    image = Image.fromarray(np.tile(array, (16, 1)))
    assert image.mode == mode
    flat = _flatten(image)
    assert flat.mode == "L"
    assert abs(_mean(flat) - 127) <= 10


# --- big images (I6) --------------------------------------------------------


def _watch_full_size_work(monkeypatch, limit: int) -> list[tuple[int, int]]:
    """Record alpha_composite / RGBA convert sizes; fail any over ``limit``."""
    seen: list[tuple[int, int]] = []
    real_composite = Image.alpha_composite
    real_convert = Image.Image.convert

    def composite(im1, im2):
        seen.append(im2.size)
        assert max(im2.size) <= limit, f"full-size composite {im2.size}"
        return real_composite(im1, im2)

    def convert(self, mode=None, *args, **kwargs):
        if mode == "RGBA":
            seen.append(self.size)
            assert max(self.size) <= limit, f"full-size RGBA copy {self.size}"
        return real_convert(self, mode, *args, **kwargs)

    monkeypatch.setattr(Image, "alpha_composite", composite)
    monkeypatch.setattr(Image.Image, "convert", convert)
    return seen


def test_big_rgba_png_is_downscaled_before_compositing(monkeypatch):
    image = Image.new("RGBA", (7000, 3500), (0, 0, 255, 128))
    png = samples.image_bytes(image, "PNG", compress_level=1)
    left, top, right, bottom = A4_300.printable
    limit = max(right - left, bottom - top)
    seen = _watch_full_size_work(monkeypatch, limit)

    (page,) = iter_pages(png, "image/png", A4_300, None)
    assert page.size == (A4_300.width_px, A4_300.height_px)
    assert seen  # the alpha path really ran

    seen.clear()
    jpeg = Image.open(io.BytesIO(png_to_jpeg(png, max_size=(limit, limit))))
    assert max(jpeg.size) <= limit
    assert seen


def test_fit_jpeg_drafts_big_photos(monkeypatch):
    photo = samples.image_bytes(Image.new("RGB", (6000, 4000), (10, 120, 200)), "JPEG")
    from PIL import JpegImagePlugin

    drafted: list[tuple[int, int]] = []
    real_draft = JpegImagePlugin.JpegImageFile.draft

    def draft(self, mode, size):
        result = real_draft(self, mode, size)
        drafted.append(self.size)
        return result

    monkeypatch.setattr(JpegImagePlugin.JpegImageFile, "draft", draft)
    out = fit_jpeg(photo, JpegLimits(max_x=1000, max_y=1000, max_kb=None))
    assert Image.open(io.BytesIO(out)).size == (1000, 667)
    assert drafted and max(drafted[0]) < 6000  # decoded at a reduced scale


def test_exif_orientation_applied_after_downscale():
    from custom_components.home_print.convert.render import _flatten

    image = samples.page_image(400, 200)
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° clockwise to display
    jpeg = samples.image_bytes(image, "JPEG", exif=exif)
    flat = _flatten(Image.open(io.BytesIO(jpeg)), (100, 100))
    assert flat.size == (50, 100)
    assert _is_red(flat.getpixel((45, 3)))  # top-left mark now top-right


def test_preview_jpeg_max_pixels(monkeypatch):
    from custom_components.home_print.convert import render

    monkeypatch.setattr(render, "MAX_IMAGE_PIXELS", 1000)
    jpeg = samples.image_bytes(Image.new("RGB", (60, 80), "white"), "JPEG")
    with pytest.raises(InvalidDocument, match="too_large"):
        render.preview_jpeg(jpeg, 1)
    assert render.preview_jpeg(jpeg, 1, max_pixels=10_000).startswith(b"\xff\xd8")
    with pytest.raises(InvalidDocument, match="too_large"):
        render.preview_jpeg(jpeg, 1, max_pixels=100)
