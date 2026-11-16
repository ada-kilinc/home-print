"""Download and preview views for archived scans."""

import io
from urllib.parse import quote

import pytest
from PIL import Image

from .common import make_entry, scan_jpeg, setup_scanner_entry
from .convert.samples import blank_pdf

OTHER_UUID = "11111111-2222-3333-4444-555555555555"


def file_url(entry_id, record_id):
    return f"/api/home_print/scans/{entry_id}/{record_id}/file"


def page_url(entry_id, record_id, page):
    return f"/api/home_print/scans/{entry_id}/{record_id}/page/{page}"


@pytest.fixture
async def entry(hass, tmp_path, mock_client, mock_escl, mock_find_scanner):
    return await setup_scanner_entry(hass, tmp_path, mock_find_scanner)


async def _add(entry, name="doc", data=None, mime="application/pdf"):
    return await entry.runtime_data.scanner.archive.async_add(
        name=name, data=data or blank_pdf(2), mime=mime, pages=2, user=None,
        source="platen", color_mode="color", resolution=300,
    )  # fmt: skip


async def test_download_headers_turkish_name(hass, entry, hass_client):
    data = blank_pdf(2)
    record = await _add(entry, name="tarama_ğüş", data=data)
    client = await hass_client()
    resp = await client.get(file_url(entry.entry_id, record["id"]))
    assert resp.status == 200
    assert resp.content_type == "application/pdf"
    assert await resp.read() == data
    assert resp.headers["Content-Disposition"] == (
        'attachment; filename="tarama____.pdf"; '
        f"filename*=UTF-8''{quote('tarama_ğüş.pdf', safe='')}"
    )
    assert resp.headers["Cache-Control"] == "private, no-store"


async def test_download_jpeg_extension_and_type(hass, entry, hass_client):
    record = await _add(entry, name="foto", data=scan_jpeg(), mime="image/jpeg")
    client = await hass_client()
    resp = await client.get(file_url(entry.entry_id, record["id"]))
    assert resp.content_type == "image/jpeg"
    assert 'filename="foto.jpg"' in resp.headers["Content-Disposition"]


async def test_page_preview_jpeg(hass, entry, hass_client):
    record = await _add(entry)
    client = await hass_client()
    for page in (1, 2):
        resp = await client.get(page_url(entry.entry_id, record["id"], page))
        assert resp.status == 200
        assert resp.content_type == "image/jpeg"
        assert resp.headers["Cache-Control"] == "private, max-age=300"
        assert Image.open(io.BytesIO(await resp.read())).format == "JPEG"
    for page in (3, 0, "x"):
        resp = await client.get(page_url(entry.entry_id, record["id"], page))
        assert resp.status == 404


async def test_jpeg_scan_preview(hass, entry, hass_client):
    record = await _add(entry, data=scan_jpeg(), mime="image/jpeg")
    client = await hass_client()
    resp = await client.get(page_url(entry.entry_id, record["id"], 1))
    assert resp.status == 200


async def test_unauthenticated_401(hass, entry, hass_client_no_auth):
    record = await _add(entry)
    client = await hass_client_no_auth()
    assert (await client.get(file_url(entry.entry_id, record["id"]))).status == 401
    assert (await client.get(page_url(entry.entry_id, record["id"], 1))).status == 401


async def test_other_entry_record_404(
    hass, entry, hass_client, mock_escl, mock_find_scanner
):
    record = await _add(entry)
    from .common import setup_entry

    other = await setup_entry(hass, make_entry(unique_id=OTHER_UUID))
    client = await hass_client()
    for url in (
        file_url(other.entry_id, record["id"]),
        page_url(other.entry_id, record["id"], 1),
        file_url("nope", record["id"]),
        file_url(entry.entry_id, "z" * 32),
        file_url(entry.entry_id, "../x"),
    ):
        assert (await client.get(url)).status == 404, url


async def test_missing_file_404(hass, tmp_path, entry, hass_client):
    record = await _add(entry)
    (tmp_path / "media" / record["path"]).unlink()
    client = await hass_client()
    assert (await client.get(file_url(entry.entry_id, record["id"]))).status == 404
    assert (await client.get(page_url(entry.entry_id, record["id"], 1))).status == 404
