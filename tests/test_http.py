"""Tests for the authenticated upload endpoint."""

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import aiohttp
import pytest
from aiohttp import BodyPartReader
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.home_print.client import (
    CannotConnect,
    PrintTimeout,
    UnsupportedOption,
    parse_printer,
)
from custom_components.home_print.const import (
    CONF_ADMIN_ONLY,
    CONF_MAX_FILE_MB,
    EVENT_JOB,
)
from custom_components.home_print.http import CHUNK_SIZE

from .common import PDF, PNG, make_entry, setup_entry
from .convert.samples import blank_pdf

MB = 1024 * 1024
DESKJET = parse_printer(
    json.loads(
        (Path(__file__).parent / "fixtures/printer_hp_deskjet_4670.json").read_text()
    )
)


def _with_formats(*formats: str):
    caps = replace(DESKJET.capabilities, document_formats=frozenset(formats))
    return replace(DESKJET, capabilities=caps)


def form(
    data: bytes = PDF, file_name: str = "report.pdf", **fields
) -> aiohttp.FormData:
    # Browsers send UTF-8 file names raw, not percent-encoded.
    body = aiohttp.FormData(quote_fields=False)
    for key, value in fields.items():
        body.add_field(key, str(value))
    body.add_field(
        "file", data, filename=file_name, content_type="application/octet-stream"
    )
    return body


def url(entry_id: str) -> str:
    return f"/api/home_print/upload/{entry_id}"


async def test_upload_requires_auth(hass, mock_client, hass_client_no_auth):
    entry = await setup_entry(hass)
    client = await hass_client_no_auth()
    resp = await client.post(url(entry.entry_id), data=form())
    assert resp.status == 401
    mock_client.print_job.assert_not_called()


async def test_upload_prints_pdf(hass, mock_client, hass_client, hass_admin_user):
    entry = await setup_entry(hass)
    events = async_capture_events(hass, EVENT_JOB)
    client = await hass_client()
    resp = await client.post(
        url(entry.entry_id),
        data=form(file_name="öğrenci_belgesi.pdf", copies=2, page_ranges="1-3,5"),
    )
    assert resp.status == 200
    assert await resp.json() == {"job_id": 42}

    args, kwargs = mock_client.print_job.call_args
    assert args == (PDF,)
    assert kwargs["job_name"] == "öğrenci_belgesi.pdf"
    assert kwargs["user_name"] == hass_admin_user.name
    assert kwargs["options"].copies == 2
    assert kwargs["options"].page_ranges == "1-3,5"
    await hass.async_block_till_done()
    assert events[0].data["user_id"] == hass_admin_user.id
    assert "data" not in events[0].data


async def test_upload_admin_only_blocks_non_admin(
    hass, mock_client, hass_client, hass_read_only_access_token
):
    entry = await setup_entry(hass, make_entry(**{CONF_ADMIN_ONLY: True}))
    client = await hass_client(hass_read_only_access_token)
    resp = await client.post(url(entry.entry_id), data=form())
    assert resp.status == 403
    assert (await resp.json())["error"] == "admin_required"
    mock_client.print_job.assert_not_called()


async def test_upload_admin_only_allows_admin(hass, mock_client, hass_client):
    entry = await setup_entry(hass, make_entry(**{CONF_ADMIN_ONLY: True}))
    client = await hass_client()
    resp = await client.post(url(entry.entry_id), data=form())
    assert resp.status == 200


async def test_upload_non_admin_allowed_by_default(
    hass, mock_client, hass_client, hass_read_only_access_token
):
    entry = await setup_entry(hass)
    client = await hass_client(hass_read_only_access_token)
    resp = await client.post(url(entry.entry_id), data=form())
    assert resp.status == 200


async def test_upload_unknown_entry(hass, mock_client, hass_client):
    await setup_entry(hass)
    client = await hass_client()
    resp = await client.post(url("does-not-exist"), data=form())
    assert resp.status == 404
    assert (await resp.json())["error"] == "entry_not_found"


async def test_upload_other_domain_entry(hass, mock_client, hass_client):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    await setup_entry(hass)
    other = MockConfigEntry(domain="other_domain")
    other.add_to_hass(hass)
    client = await hass_client()
    resp = await client.post(url(other.entry_id), data=form())
    assert resp.status == 404


async def test_upload_unloaded_entry(hass, mock_client, hass_client):
    entry = await setup_entry(hass)
    await hass.config_entries.async_unload(entry.entry_id)
    client = await hass_client()
    resp = await client.post(url(entry.entry_id), data=form())
    assert resp.status == 404


@pytest.fixture
def read_counter():
    """Count bytes the view pulls from the multipart body."""
    counter = {"bytes": 0}
    original = BodyPartReader.read_chunk

    async def read_chunk(self, size=BodyPartReader.chunk_size):
        chunk = await original(self, size)
        counter["bytes"] += len(chunk)
        return chunk

    with patch.object(BodyPartReader, "read_chunk", read_chunk):
        yield counter


async def test_upload_too_large_rejected_without_full_read(
    hass, mock_client, hass_client, read_counter
):
    entry = await setup_entry(hass, make_entry(**{CONF_MAX_FILE_MB: 1}))
    client = await hass_client()

    # With Content-Length: rejected before the body is touched.
    with patch("aiohttp.web_request.BaseRequest.multipart") as multipart:
        resp = await client.post(url(entry.entry_id), data=form(PDF + b"\0" * 3 * MB))
        assert resp.status == 413
        body = await resp.json()
        assert body["error"] == "file_too_large"
        multipart.assert_not_called()

    # Without Content-Length (chunked): stop as soon as the limit is crossed.
    big = PDF + b"\0" * (5 * MB)
    boundary = "homeprintboundary"

    async def chunked_body():
        yield (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="big.pdf"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
        ).encode()
        for i in range(0, len(big), 64 * 1024):
            yield big[i : i + 64 * 1024]
        yield f"\r\n--{boundary}--\r\n".encode()

    try:
        resp = await client.post(
            url(entry.entry_id),
            data=chunked_body(),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        assert resp.status == 413
    except aiohttp.ClientError:
        # The server may close the connection on the unread rest of the body.
        pass
    assert 0 < read_counter["bytes"] <= 1 * MB + CHUNK_SIZE
    mock_client.print_job.assert_not_called()


async def test_upload_exactly_at_limit_ok(hass, mock_client, hass_client):
    entry = await setup_entry(hass, make_entry(**{CONF_MAX_FILE_MB: 1}))
    client = await hass_client()
    data = PDF + b"\0" * (MB - len(PDF))
    resp = await client.post(url(entry.entry_id), data=form(data))
    assert resp.status == 200


async def test_upload_printer_offline(hass, mock_client, hass_client):
    entry = await setup_entry(hass)
    mock_client.print_job.side_effect = CannotConnect("timeout")
    client = await hass_client()
    resp = await client.post(url(entry.entry_id), data=form())
    assert resp.status == 502
    body = await resp.json()
    assert body["error"] == "printer_unavailable"
    assert body["message"]


async def test_upload_print_timeout(hass, mock_client, hass_client):
    entry = await setup_entry(hass)
    mock_client.print_job.side_effect = PrintTimeout("slow")
    client = await hass_client()
    resp = await client.post(url(entry.entry_id), data=form())
    assert resp.status == 504
    body = await resp.json()
    assert body["error"] == "print_timeout"
    assert "may still" in body["message"]


async def test_upload_format_not_supported_by_printer(hass, mock_client, hass_client):
    # Neither PNG nor anything it converts to (JPEG, PWG, URF).
    mock_client.get_printer.return_value = _with_formats("application/vnd.hp-PCL")
    entry = await setup_entry(hass)
    client = await hass_client()
    resp = await client.post(url(entry.entry_id), data=form(PNG, "photo.png"))
    assert resp.status == 422
    assert (await resp.json())["error"] == "format_not_supported"


async def test_upload_option_not_supported(hass, mock_client, hass_client):
    entry = await setup_entry(hass)
    mock_client.print_job.side_effect = UnsupportedOption("color_mode")
    client = await hass_client()
    resp = await client.post(url(entry.entry_id), data=form())
    assert resp.status == 422
    assert (await resp.json())["error"] == "option_not_supported"


@pytest.mark.parametrize(
    "fields",
    [
        {"copies": "zero"},
        {"copies": "0"},
        {"sides": "sideways"},
        {"color_mode": "rainbow"},
        {"page_ranges": "3-1"},
        {"page_ranges": "1-99999999999"},
        {"unexpected": "x"},
    ],
)
async def test_upload_invalid_option(hass, mock_client, hass_client, fields):
    entry = await setup_entry(hass)
    client = await hass_client()
    resp = await client.post(url(entry.entry_id), data=form(**fields))
    assert resp.status == 400
    assert (await resp.json())["error"] == "invalid_option"
    mock_client.print_job.assert_not_called()


async def test_upload_unknown_file_type(hass, mock_client, hass_client):
    entry = await setup_entry(hass)
    client = await hass_client()
    resp = await client.post(url(entry.entry_id), data=form(b"MZ\x90\x00", "a.pdf"))
    assert resp.status == 400
    assert (await resp.json())["error"] == "unsupported_file_type"


async def test_upload_missing_file(hass, mock_client, hass_client):
    entry = await setup_entry(hass)
    client = await hass_client()
    body = aiohttp.FormData()
    body.add_field("copies", "1")
    body.add_field("dummy", b"x", filename="x")  # force multipart encoding
    resp = await client.post(url(entry.entry_id), data=body)
    assert resp.status == 400


async def test_upload_not_multipart(hass, mock_client, hass_client):
    entry = await setup_entry(hass)
    client = await hass_client()
    resp = await client.post(url(entry.entry_id), json={"file": "x"})
    assert resp.status == 400
    assert (await resp.json())["error"] == "invalid_request"


async def test_upload_message_in_turkish(hass, mock_client, hass_client):
    entry = await setup_entry(hass, make_entry(**{CONF_MAX_FILE_MB: 1}))
    client = await hass_client()
    resp = await client.post(
        url(entry.entry_id),
        data=form(PDF + b"\0" * 2 * MB),
        headers={"Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8"},
    )
    assert resp.status == 413
    assert (await resp.json())["message"] == (
        "Dosya çok büyük. En fazla 1 MB gönderebilirsin."
    )


async def test_two_entries_register_view_once(hass, mock_client, hass_client):
    first = await setup_entry(hass)
    second = make_entry(unique_id="other-printer")
    await setup_entry(hass, second)
    client = await hass_client()
    for entry in (first, second):
        resp = await client.post(url(entry.entry_id), data=form())
        assert resp.status == 200


async def test_upload_pdf_converted_for_deskjet(hass, mock_client, hass_client):
    mock_client.get_printer.return_value = DESKJET
    entry = await setup_entry(hass)
    events = async_capture_events(hass, EVENT_JOB)
    client = await hass_client()
    resp = await client.post(
        url(entry.entry_id),
        data=form(blank_pdf(3), "a.pdf", page_ranges="1-2", copies=2),
    )
    assert resp.status == 200

    (data,), kwargs = mock_client.print_job.call_args
    assert data.startswith(b"RaS2")
    assert kwargs["document_format"] == "image/pwg-raster"
    assert kwargs["send_page_ranges"] is False
    assert kwargs["options"].copies == 2
    await hass.async_block_till_done()
    assert events[0].data["converted_to"] == "image/pwg-raster"
    assert events[0].data["pages"] == 2


async def test_upload_corrupt_pdf_invalid_document(hass, mock_client, hass_client):
    mock_client.get_printer.return_value = DESKJET
    entry = await setup_entry(hass)
    client = await hass_client()
    resp = await client.post(url(entry.entry_id), data=form(PDF, "a.pdf"))
    assert resp.status == 400
    body = await resp.json()
    assert body["error"] == "invalid_document"
    assert body["message"] == (
        "The file couldn't be opened. It may be damaged or password protected."
    )
    mock_client.print_job.assert_not_called()


async def test_upload_too_many_pages(hass, mock_client, hass_client):
    mock_client.get_printer.return_value = DESKJET
    entry = await setup_entry(hass)
    client = await hass_client()
    resp = await client.post(
        url(entry.entry_id),
        data=form(blank_pdf(201), "long.pdf"),
        headers={"Accept-Language": "tr-TR,tr;q=0.9"},
    )
    assert resp.status == 400
    body = await resp.json()
    assert body["error"] == "too_many_pages"
    assert body["message"] == ("Bu belge çok uzun. En fazla 200 sayfa yazdırabilirsin.")
    mock_client.print_job.assert_not_called()


async def test_upload_invalid_document_in_turkish(hass, mock_client, hass_client):
    mock_client.get_printer.return_value = DESKJET
    entry = await setup_entry(hass)
    client = await hass_client()
    resp = await client.post(
        url(entry.entry_id),
        data=form(PDF, "a.pdf"),
        headers={"Accept-Language": "tr-TR,tr;q=0.9"},
    )
    assert (await resp.json())["message"] == (
        "Dosya açılamadı. Bozuk ya da parola korumalı olabilir."
    )
