"""Tests for rendering PDFs and images to print pages."""

from __future__ import annotations

import io

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
