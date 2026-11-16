"""Tests for the history page preview endpoint."""

import io
from datetime import timedelta

from homeassistant.components.http.auth import async_sign_path
from PIL import Image

from .common import make_entry, setup_entry
from .convert.samples import blank_pdf

OTHER_UUID = "11111111-2222-3333-4444-555555555555"


def url(entry_id: str, record_id: str, page) -> str:
    return f"/api/home_print/history/{entry_id}/{record_id}/page/{page}"


async def _record(hass, entry, data, mime="application/pdf", name="a.pdf"):
    record = entry.runtime_data.history.add(
        file_name=name, user=None, job_id=1, state="sent", pages=None,
        converted_to=None, error=None, data=data, mime=mime,
    )  # fmt: skip
    await hass.async_block_till_done()
    return record


def _png(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (10, 200, 30)).save(out, "PNG")
    return out.getvalue()


async def test_pdf_pages_render_as_jpeg(hass, mock_client, hass_client):
    entry = await setup_entry(hass)
    record = await _record(hass, entry, blank_pdf(2))
    client = await hass_client()
    for page in (1, 2):
        resp = await client.get(url(entry.entry_id, record["id"], page))
        assert resp.status == 200
        assert resp.content_type == "image/jpeg"
        assert resp.headers["Cache-Control"] == "private, max-age=300"
        image = Image.open(io.BytesIO(await resp.read()))
        assert image.format == "JPEG"
        # A4 at 100 dpi (PDFium rounds the bitmap size up)
        assert image.width in (826, 827)
    resp = await client.get(url(entry.entry_id, record["id"], 3))
    assert resp.status == 404
    resp = await client.get(url(entry.entry_id, record["id"], 0))
    assert resp.status == 404


async def test_wide_pdf_page_is_capped_at_1200_px(hass, mock_client, hass_client):
    entry = await setup_entry(hass)
    record = await _record(hass, entry, blank_pdf(1, (1700, 600)))
    client = await hass_client()
    resp = await client.get(url(entry.entry_id, record["id"], 1))
    assert resp.status == 200
    assert Image.open(io.BytesIO(await resp.read())).width == 1200


async def test_image_preview_is_shrunk(hass, mock_client, hass_client):
    entry = await setup_entry(hass)
    record = await _record(hass, entry, _png(3000, 1000), "image/png", "p.png")
    client = await hass_client()
    resp = await client.get(url(entry.entry_id, record["id"], 1))
    assert resp.status == 200
    image = Image.open(io.BytesIO(await resp.read()))
    assert image.format == "JPEG"
    assert image.size == (1200, 400)
    resp = await client.get(url(entry.entry_id, record["id"], 2))
    assert resp.status == 404


async def test_requires_auth(hass, mock_client, hass_client_no_auth):
    entry = await setup_entry(hass)
    record = await _record(hass, entry, blank_pdf(1))
    client = await hass_client_no_auth()
    resp = await client.get(url(entry.entry_id, record["id"], 1))
    assert resp.status == 401


async def test_signed_path_works(
    hass, mock_client, hass_client_no_auth, hass_access_token
):
    entry = await setup_entry(hass)
    record = await _record(hass, entry, blank_pdf(1))
    refresh = hass.auth.async_validate_access_token(hass_access_token)
    signed = async_sign_path(
        hass,
        url(entry.entry_id, record["id"], 1),
        timedelta(minutes=5),
        refresh_token_id=refresh.id,
    )
    client = await hass_client_no_auth()
    resp = await client.get(signed)
    assert resp.status == 200
    assert resp.content_type == "image/jpeg"


async def test_other_entrys_record_not_found(hass, mock_client, hass_client):
    entry = await setup_entry(hass)
    other = await setup_entry(hass, make_entry(OTHER_UUID))
    record = await _record(hass, entry, blank_pdf(1))
    client = await hass_client()
    resp = await client.get(url(other.entry_id, record["id"], 1))
    assert resp.status == 404


async def test_bad_ids_not_found(hass, mock_client, hass_client):
    entry = await setup_entry(hass)
    record = await _record(hass, entry, blank_pdf(1))
    client = await hass_client()
    for record_id in (record["id"].upper(), record["id"][:-1], "%2E%2E"):
        resp = await client.get(url(entry.entry_id, record_id, 1))
        assert resp.status == 404, record_id
    # HA's security filter answers traversal attempts with 400 first.
    resp = await client.get(url(entry.entry_id, "..%2F..%2F" + record["id"][:22], 1))
    assert resp.status in (400, 404)
    for entry_id in ("nope", "%2E%2E"):
        resp = await client.get(url(entry_id, record["id"], 1))
        assert resp.status == 404, entry_id
    resp = await client.get(url(entry.entry_id, record["id"], "x"))
    assert resp.status == 404


async def test_missing_file_not_found(hass, mock_client, hass_client):
    entry = await setup_entry(hass)
    record = await _record(hass, entry, None, None)
    client = await hass_client()
    resp = await client.get(url(entry.entry_id, record["id"], 1))
    assert resp.status == 404

    kept = await _record(hass, entry, blank_pdf(1))
    entry.runtime_data.history.file_path(kept["id"]).unlink()
    resp = await client.get(url(entry.entry_id, kept["id"], 1))
    assert resp.status == 404


async def test_unloaded_entry_not_found(hass, mock_client, hass_client):
    entry = await setup_entry(hass)
    record = await _record(hass, entry, blank_pdf(1))
    await hass.config_entries.async_unload(entry.entry_id)
    client = await hass_client()
    resp = await client.get(url(entry.entry_id, record["id"], 1))
    assert resp.status == 404
