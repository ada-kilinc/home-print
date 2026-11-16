"""Tests for building scanned PDFs."""

import io

import pypdfium2 as pdfium
import pytest
from PIL import Image

from custom_components.home_print.convert import scan_doc
from custom_components.home_print.convert.errors import InvalidDocument
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
    monkeypatch.setattr(scan_doc, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(InvalidDocument, match="too_large"):
        scan_doc.normalize_page(_img((20, 20)))
    with pytest.raises(InvalidDocument, match="too_large"):
        scan_doc.normalize_page(_img((20, 20), fmt="PNG"))
