"""Tests for choosing a target format and preparing a job's bytes."""

from __future__ import annotations

import io
import json
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from custom_components.home_print.client import parse_printer
from custom_components.home_print.convert.errors import (
    InvalidDocument,
    NoConversionRoute,
    TooManyPages,
)
from custom_components.home_print.convert.pipeline import (
    PreparedJob,
    choose_target,
    prepare,
)
from custom_components.home_print.models import (
    Capabilities,
    JpegLimits,
    PrintOptions,
    RasterCaps,
)

from . import pwg_decoder, urf_decoder
from .samples import blank_pdf, image_bytes, page_image, pdf_from_images

FIXTURES = Path(__file__).parent.parent / "fixtures"
PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"
PWG = "image/pwg-raster"
URF = "image/urf"


def _caps(name: str) -> Capabilities:
    data = json.loads((FIXTURES / f"{name}.json").read_text())
    return parse_printer(data).capabilities


DESKJET = _caps("printer_hp_deskjet_4670")
GENERIC = _caps("printer_generic")


def _only(*formats: str, raster: RasterCaps | None = None) -> Capabilities:
    return Capabilities(
        document_formats=frozenset(formats),
        sides=frozenset({"one-sided"}),
        color_modes=frozenset(),
        copies_max=1,
        page_ranges=False,
        raster=raster,
    )


def test_choose_target_deskjet():
    assert choose_target(PDF, DESKJET) == PWG
    assert choose_target(PNG, DESKJET) == JPEG
    assert choose_target(JPEG, DESKJET) == JPEG


def test_choose_target_pdf_native_printer():
    assert choose_target(PDF, GENERIC) == PDF


def test_choose_target_urf_only_printer():
    caps = _only(URF)
    assert choose_target(PDF, caps) == URF
    assert choose_target(PNG, caps) == URF
    assert choose_target(JPEG, caps) == URF


def test_choose_target_none():
    caps = _only("application/vnd.hp-PCL")
    assert choose_target(PDF, caps) is None
    assert choose_target(PNG, caps) is None
    with pytest.raises(NoConversionRoute):
        prepare(blank_pdf(1), PDF, caps, PrintOptions())


def test_choose_target_unknown_formats_passes_through():
    # A printer that lists no formats: send as-is (previous behaviour).
    assert choose_target(PDF, _only()) == PDF


def test_choose_target_pwg_without_needed_type_falls_back_to_urf():
    raster = RasterCaps(
        pwg_types=frozenset({"srgb_8"}),
        pwg_resolutions=(300,),
        pwg_sheet_back=None,
        urf=frozenset({"W8", "SRGB24", "RS300"}),
    )
    caps = _only(PWG, URF, raster=raster)
    assert choose_target(PDF, caps) == PWG
    assert choose_target(PDF, caps, gray=True) == URF
    no_urf = _only(PWG, raster=replace(raster, urf=frozenset()))
    assert choose_target(PDF, no_urf, gray=True) is None


def test_prepare_pdf_to_pwg_gray_duplex_pages():
    pdf = pdf_from_images([page_image(595, 842) for _ in range(3)])
    job = prepare(
        pdf,
        PDF,
        DESKJET,
        PrintOptions(
            copies=3,
            sides="two-sided-long-edge",
            color_mode="monochrome",
            page_ranges="2-3",
        ),
    )
    assert isinstance(job, PreparedJob)
    assert job.document_format == PWG
    assert job.send_page_ranges is False
    assert job.page_count == 2
    assert isinstance(job.data, bytes)

    pages = pwg_decoder.decode(job.data)
    assert len(pages) == 2  # even, so no blank back page
    for page in pages:
        header = page.header
        assert header["ColorSpace"] == 18  # sgray
        assert header["BitsPerPixel"] == 8
        assert header["Duplex"] == 1
        assert header["Tumble"] == 0
        assert header["NumCopies"] == 1  # copies go as the IPP attribute
        assert header["TotalPageCount"] == 2
        assert header["HWResolution"] == (300, 300)
        assert header["PageSizeName"] == "iso_a4_210x297mm"
        assert (header["Width"], header["Height"]) == (2480, 3508)


def test_prepare_pdf_odd_duplex_counts_selected_pages():
    job = prepare(
        blank_pdf(3),
        PDF,
        DESKJET,
        PrintOptions(sides="two-sided-short-edge"),
    )
    assert job.page_count == 3
    pages = pwg_decoder.decode(job.data)
    assert len(pages) == 4  # blank back page added by the encoder
    assert pages[0].header["TotalPageCount"] == 4
    assert pages[0].header["Tumble"] == 1
    assert pages[0].header["ColorSpace"] == 19  # srgb: no color mode = colour


def test_prepare_passthrough_jpeg_keeps_page_ranges_flag():
    data = image_bytes(page_image(200, 300), "JPEG")
    job = prepare(data, JPEG, DESKJET, PrintOptions(page_ranges="1"))
    assert job == PreparedJob(
        data=data, document_format=JPEG, send_page_ranges=True, page_count=None
    )


def test_prepare_passthrough_jpeg_is_fitted_to_limits():
    data = image_bytes(page_image(400, 300), "JPEG")
    caps = replace(DESKJET, jpeg=JpegLimits(max_x=100, max_y=100, max_kb=None))
    job = prepare(data, JPEG, caps, PrintOptions())
    assert job.document_format == JPEG
    assert job.send_page_ranges is True
    assert Image.open(io.BytesIO(job.data)).size == (100, 75)


def test_prepare_passthrough_pdf_is_untouched():
    data = b"%PDF-1.7\nnot parsed at all"
    job = prepare(data, PDF, GENERIC, PrintOptions(page_ranges="1-2"))
    assert job == PreparedJob(
        data=data, document_format=PDF, send_page_ranges=True, page_count=None
    )


def test_prepare_png_to_jpeg_on_deskjet():
    png = image_bytes(Image.new("RGBA", (50, 40), (0, 0, 0, 0)), "PNG")
    job = prepare(png, PNG, DESKJET, PrintOptions())
    assert job.document_format == JPEG
    assert job.send_page_ranges is False
    assert job.page_count == 1
    image = Image.open(io.BytesIO(job.data))
    assert image.format == "JPEG"
    assert image.convert("RGB").getpixel((25, 20)) == (255, 255, 255)


def test_prepare_pdf_to_urf_gray_uses_dm_and_resolution():
    raster = RasterCaps(
        pwg_types=frozenset(),
        pwg_resolutions=(),
        pwg_sheet_back=None,
        urf=frozenset({"W8-16", "SRGB24", "RS150-600", "dm4", "V1.4"}),
    )
    caps = _only(URF, raster=raster)
    job = prepare(
        blank_pdf(3),
        PDF,
        caps,
        PrintOptions(sides="two-sided-long-edge", color_mode="process-monochrome"),
    )
    assert job.document_format == URF
    assert job.send_page_ranges is False
    assert job.page_count == 3
    pages = urf_decoder.decode(job.data)
    assert len(pages) == 4
    assert pages[0].header["Resolution"] == 150  # of 150 and 600, closest to 300
    assert pages[0].header["BitsPerPixel"] == 8
    assert pages[0].header["ColorSpace"] == 0  # sgray
    assert pages[0].header["Duplex"] == 3  # long edge


def test_prepare_picks_resolution_closest_to_300():
    raster = RasterCaps(
        pwg_types=frozenset({"sgray_8", "srgb_8"}),
        pwg_resolutions=(600, 200),
        pwg_sheet_back=None,
        urf=frozenset(),
    )
    job = prepare(blank_pdf(1), PDF, _only(PWG, raster=raster), PrintOptions())
    assert pwg_decoder.decode(job.data)[0].header["HWResolution"] == (200, 200)


def test_prepare_invalid_pdf_raises():
    with pytest.raises(InvalidDocument):
        prepare(b"%PDF-1.7\ngarbage", PDF, DESKJET, PrintOptions())


def test_prepare_too_many_pages_raises():
    with pytest.raises(TooManyPages) as exc:
        prepare(blank_pdf(4), PDF, DESKJET, PrintOptions(), max_pages=3)
    assert exc.value.limit == 3
    # A range that selects few enough pages is fine.
    job = prepare(
        blank_pdf(4), PDF, DESKJET, PrintOptions(page_ranges="1-3"), max_pages=3
    )
    assert job.page_count == 3
