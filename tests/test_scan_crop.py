"""Cropping a stored scan page (issue #9)."""

from __future__ import annotations

import io

import pypdfium2 as pdfium
import pytest
from PIL import Image

from custom_components.home_print.const import CONF_ADMIN_ONLY
from custom_components.home_print.convert.errors import InvalidDocument
from custom_components.home_print.convert.scan_doc import (
    build_pdf,
    crop_page,
    valid_crop_box,
)
from custom_components.home_print.scanning import ScanJobState

from .common import scan_jpeg, setup_scanner_entry

BOX = {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5}


def _page_with_square(mode="L", size=(300, 400)) -> bytes:
    """A white page with a black square in the middle quarter."""
    image = Image.new(mode, size, 255 if mode == "L" else (255, 255, 255))
    w, h = size
    image.paste(
        0 if mode == "L" else (0, 0, 0), (w // 4, h // 4, 3 * w // 4, 3 * h // 4)
    )
    out = io.BytesIO()
    image.save(out, "JPEG", quality=95)
    return out.getvalue()


def _pdf_images(data: bytes) -> list[Image.Image]:
    pdf = pdfium.PdfDocument(data)
    try:
        images = []
        for page in pdf:
            [obj] = list(page.get_objects(filter=(3,), max_depth=1))
            images.append(obj.get_bitmap(render=False).to_pil())
        return images
    finally:
        pdf.close()


def test_valid_crop_box():
    assert valid_crop_box((0, 0, 1, 1))
    assert valid_crop_box((0.1, 0.2, 0.5, 0.5))
    assert not valid_crop_box((0, 0, 0.01, 1))
    assert not valid_crop_box((0.6, 0, 0.5, 1))
    assert not valid_crop_box((-0.1, 0, 0.5, 1))


def test_crop_one_pdf_page_keeps_the_others():
    pdf = build_pdf([_page_with_square(), scan_jpeg(size=(60, 80))], 100)
    out, pages = crop_page(pdf, 1, (0.25, 0.25, 0.5, 0.5), 100)

    assert pages == 2
    first, second = _pdf_images(out)
    assert first.size == (150, 200)
    assert first.mode == "L"
    # Only the black square is left; the white margin is gone from the file.
    assert max(first.getdata()) < 60
    assert second.size == (60, 80)
    doc = pdfium.PdfDocument(out)
    try:
        # 150 px at 100 dpi is 108 pt: the page keeps its scale.
        assert [round(v) for v in doc[0].get_size()] == [108, 144]
    finally:
        doc.close()


def test_crop_a_jpeg_scan():
    data = _page_with_square("RGB")
    out, pages = crop_page(data, 1, (0.25, 0.25, 0.5, 0.5), 300)
    image = Image.open(io.BytesIO(out))
    assert pages == 1
    assert image.format == "JPEG"
    assert image.size == (150, 200)
    with pytest.raises(InvalidDocument):
        crop_page(data, 2, (0, 0, 1, 1), 300)


def test_crop_follows_jpeg_orientation():
    """The box is drawn on the upright preview, so it applies after rotating."""
    image = Image.new("RGB", (400, 300), (255, 255, 255))
    image.paste((0, 0, 0), (0, 0, 200, 300))  # left half black as stored
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° clockwise to view
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif)
    cropped, _ = crop_page(out.getvalue(), 1, (0, 0, 1, 0.5), 300)
    result = Image.open(io.BytesIO(cropped))
    # Upright it is 300 x 400; the top half is the stored left half: black.
    assert result.size == (300, 200)
    assert max(result.convert("L").getdata()) < 60


def test_bad_box_and_page():
    pdf = build_pdf([scan_jpeg()], 300)
    with pytest.raises(ValueError):
        crop_page(pdf, 1, (0, 0, 0.001, 1), 300)
    with pytest.raises(InvalidDocument):
        crop_page(pdf, 3, (0, 0, 1, 1), 300)


@pytest.fixture
async def entry(hass, tmp_path, mock_client, mock_escl, mock_find_scanner):
    return await setup_scanner_entry(hass, tmp_path, mock_find_scanner)


async def _add(entry, data=None, mime="application/pdf", pages=1):
    data = data or build_pdf([_page_with_square()], 100)
    return await entry.runtime_data.scanner.archive.async_add(
        name="crop", data=data, mime=mime, pages=pages, user=None,
        source="platen", color_mode="gray", resolution=100,
    )  # fmt: skip


async def send(hass, hass_ws_client, token=None, **data):
    ws = await hass_ws_client(hass, token) if token else await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "home_print/scans/crop", **data})
    return await ws.receive_json()


async def test_ws_crop_rewrites_the_file(hass, entry, hass_ws_client):
    record = await _add(entry)
    msg = await send(
        hass, hass_ws_client, entry_id=entry.entry_id,
        scan_record_id=record["id"], page=1, box=BOX,
    )  # fmt: skip
    assert msg["success"], msg
    updated = msg["result"]["entry"]
    path = await entry.runtime_data.scanner.archive.async_file_path(record["id"])
    data = path.read_bytes()
    assert updated["size"] == len(data) != record["size"]
    assert updated["pages"] == 1
    [image] = _pdf_images(data)
    assert image.size == (150, 200)


async def test_ws_crop_errors(hass, entry, hass_ws_client):
    record = await _add(entry)
    base = {"entry_id": entry.entry_id, "scan_record_id": record["id"], "page": 1}

    msg = await send(hass, hass_ws_client, **base, box={**BOX, "width": 0.001})
    assert msg["error"]["code"] == "invalid_crop"
    msg = await send(hass, hass_ws_client, **base, box={**BOX, "x": 0.8})
    assert msg["error"]["code"] == "invalid_crop"
    msg = await send(hass, hass_ws_client, **{**base, "page": 5}, box=BOX)
    assert msg["error"]["code"] == "not_found"
    msg = await send(
        hass, hass_ws_client, **{**base, "scan_record_id": "f" * 32}, box=BOX
    )
    assert msg["error"]["code"] == "not_found"

    entry.runtime_data.scanner.active = ScanJobState(scan_id="s", state="saving")
    msg = await send(hass, hass_ws_client, **base, box=BOX)
    assert msg["error"]["code"] == "scan_running"


async def test_ws_crop_needs_permission(
    hass, tmp_path, mock_client, mock_escl, mock_find_scanner, hass_ws_client,
    hass_read_only_access_token,
):  # fmt: skip
    entry = await setup_scanner_entry(
        hass, tmp_path, mock_find_scanner, **{CONF_ADMIN_ONLY: True}
    )
    record = await _add(entry)
    msg = await send(
        hass, hass_ws_client, hass_read_only_access_token,
        entry_id=entry.entry_id, scan_record_id=record["id"], page=1, box=BOX,
    )  # fmt: skip
    assert msg["error"]["code"] == "unauthorized"
