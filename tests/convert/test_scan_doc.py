"""Tests for building scanned PDFs."""

import io

import pypdfium2 as pdfium
import pytest
from PIL import Image

from custom_components.home_print.convert import scan_doc
from custom_components.home_print.convert.errors import InvalidDocument, TooManyPages
from custom_components.home_print.convert.render import count_pages


def _img(size=(2550, 3300), mode="RGB", fmt="JPEG") -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, "white").save(out, fmt)
    return out.getvalue()


def _page_width_pt(pdf: bytes, index: int = 0) -> float:
    doc = pdfium.PdfDocument(pdf)
    try:
        return doc[index].get_size()[0]
    finally:
        doc.close()


def test_build_pdf_page_size():
    pdf = scan_doc.build_pdf([_img()], 300)
    assert pdf.startswith(b"%PDF-")
    assert count_pages(pdf) == 1
    assert abs(_page_width_pt(pdf) - 612) <= 1


def test_build_pdf_two_pages():
    pdf = scan_doc.build_pdf([_img((600, 800)), _img((600, 800))], 150)
    assert count_pages(pdf) == 2


def test_build_pdf_no_pages_raises():
    with pytest.raises(InvalidDocument, match="no_pages"):
        scan_doc.build_pdf([], 300)


def test_append_pdf_adds_pages():
    first = scan_doc.build_pdf([_img()], 300)
    out = scan_doc.append_pdf(first, [_img((600, 800)), _img((600, 800))], 150)
    assert count_pages(out) == 3
    assert abs(_page_width_pt(out, 0) - 612) <= 1
    assert abs(_page_width_pt(out, 1) - 288) <= 1  # 600 px / 150 dpi = 4 in


def test_normalize_jpeg_unchanged():
    data = _img((100, 100))
    assert scan_doc.normalize_page(data) == data


def test_normalize_png_to_jpeg():
    out = scan_doc.normalize_page(_img((100, 100), fmt="PNG"))
    assert out.startswith(b"\xff\xd8")


def test_normalize_rgba_png_to_rgb_jpeg():
    out = scan_doc.normalize_page(_img((50, 50), mode="RGBA", fmt="PNG"))
    assert Image.open(io.BytesIO(out)).mode == "RGB"


def test_normalize_gray_keeps_mode_L():
    out = scan_doc.normalize_page(_img((100, 100), mode="L", fmt="PNG"))
    assert out.startswith(b"\xff\xd8")
    assert Image.open(io.BytesIO(out)).mode == "L"


def test_normalize_bad_bytes_raises():
    with pytest.raises(InvalidDocument, match="bad_scan"):
        scan_doc.normalize_page(b"not an image")


def test_normalize_truncated_raises():
    with pytest.raises(InvalidDocument, match="bad_scan"):
        scan_doc.normalize_page(_img((400, 400), fmt="PNG")[:60])


def test_normalize_too_large(monkeypatch):
    monkeypatch.setattr(scan_doc, "SCAN_MAX_PIXELS", 100)
    with pytest.raises(InvalidDocument, match="too_large"):
        scan_doc.normalize_page(_img((20, 20)))
    with pytest.raises(InvalidDocument, match="too_large"):
        scan_doc.normalize_page(_img((20, 20), fmt="PNG"))


def test_scan_limit_is_above_print_limit():
    # 600 dpi full platen (~36 MP) must not be rejected as a scan.
    assert scan_doc.SCAN_MAX_PIXELS == 100_000_000
    assert 6800 * 5100 < scan_doc.SCAN_MAX_PIXELS


def test_build_pdf_embeds_jpeg_verbatim():
    jpeg = _img((300, 200))
    pdf = scan_doc.build_pdf([jpeg], 300)
    assert jpeg in pdf
    assert b"/DCTDecode" in pdf
    assert b"/DeviceRGB" in pdf


def test_build_pdf_gray_stays_device_gray():
    pdf = scan_doc.build_pdf([_img((100, 100), mode="L")], 300)
    assert b"/DeviceGray" in pdf
    assert b"/DeviceRGB" not in pdf


def test_build_pdf_cmyk_decode_array():
    pdf = scan_doc.build_pdf([_img((50, 50), mode="CMYK")], 300)
    assert b"/DeviceCMYK" in pdf
    assert b"/Decode [1 0 1 0 1 0 1 0]" in pdf


def test_build_pdf_renders_with_pdfium():
    doc_bytes = scan_doc.build_pdf([_img((600, 800), mode="L")], 300)
    doc = pdfium.PdfDocument(doc_bytes)
    try:
        img = doc[0].render(scale=0.5).to_pil()
        assert img.getpixel((10, 10))[0] > 240  # white page
    finally:
        doc.close()


def test_build_pdf_keeps_jpeg_bytes_not_reencoded():
    # A noisy JPEG at quality 95 would shrink if re-encoded at 75.
    out = io.BytesIO()
    Image.effect_noise((200, 200), 60).save(out, "JPEG", quality=95)
    jpeg = out.getvalue()
    assert jpeg in scan_doc.build_pdf([jpeg], 300)


def test_build_pdf_too_many_pages():
    page = _img((10, 10))
    with pytest.raises(TooManyPages):
        scan_doc.build_pdf([page] * 201, 300)


def test_normalize_truncated_jpeg_raises():
    jpeg = _img((400, 400))
    with pytest.raises(InvalidDocument, match="bad_scan"):
        scan_doc.normalize_page(jpeg[: len(jpeg) // 2])


def test_normalize_jpeg_trailing_padding_ok():
    jpeg = _img((100, 100))
    padded = jpeg + b"\x00\x00\n "
    assert scan_doc.normalize_page(padded) == padded


@pytest.mark.parametrize("dpi", [0, -300])
def test_bad_dpi_raises(dpi):
    with pytest.raises(ValueError):
        scan_doc.build_pdf([_img((10, 10))], dpi)
    base = scan_doc.build_pdf([_img((10, 10))], 300)
    with pytest.raises(ValueError):
        scan_doc.append_pdf(base, [_img((10, 10))], dpi)


def test_append_pdf_enforces_combined_page_limit():
    page = _img((10, 10))
    base = scan_doc.build_pdf([page] * 150, 300)
    with pytest.raises(TooManyPages):
        scan_doc.append_pdf(base, [page] * 51, 300)
    assert count_pages(scan_doc.append_pdf(base, [page] * 50, 300)) == 200


def test_append_pdf_mixed_modes():
    base = scan_doc.build_pdf([_img((100, 100)), _img((100, 100), mode="L")], 300)
    out = scan_doc.append_pdf(base, [_img((100, 100), mode="L"), _img((100, 100))], 300)
    assert count_pages(out) == 4
