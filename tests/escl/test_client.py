"""Tests for the eSCL client against a real local aiohttp fake scanner."""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from custom_components.home_print.escl import client as client_mod
from custom_components.home_print.escl.client import (
    AdfEmpty,
    EsclClient,
    EsclError,
    ScannerBusy,
    ScannerUnavailable,
    find_scanner,
)
from custom_components.home_print.escl.models import ScanSettings
from custom_components.home_print.escl.parse import parse_capabilities

FIX = Path(__file__).parent.parent / "fixtures" / "escl"
CAPS_XML = (FIX / "hp_capabilities_platen.xml").read_bytes()
SETTINGS = ScanSettings("platen", "color", 300, "image/jpeg")


class FakeScanner:
    """Scripted fake: ``pages`` is a list of status ints or bytes per NextDocument."""

    def __init__(self, pages, *, create=201, location="/eSCL/ScanJobs/abc") -> None:
        self.pages = list(pages)
        self.create = create
        self.location = location
        self.deleted: list[str] = []
        self.posted: list[bytes] = []
        self.next_calls = 0
        self.caps_body = CAPS_XML
        self.app = web.Application()
        self.app.router.add_get("/eSCL/ScannerCapabilities", self.h_caps)
        self.app.router.add_get("/eSCL/ScannerStatus", self.h_status)
        self.app.router.add_post("/eSCL/ScanJobs", self.h_create)
        self.app.router.add_get("/eSCL/ScanJobs/abc/NextDocument", self.h_next)
        self.app.router.add_delete("/eSCL/ScanJobs/abc", self.h_delete)

    async def h_caps(self, request):
        return web.Response(body=self.caps_body)

    async def h_status(self, request):
        return web.Response(body=(FIX / "status_idle.xml").read_bytes())

    async def h_create(self, request):
        self.posted.append(await request.read())
        if self.create != 201:
            return web.Response(status=self.create)
        return web.Response(status=201, headers={"Location": self.location})

    async def h_next(self, request):
        self.next_calls += 1
        # "drop" is sticky: aiohttp retries idempotent GETs after a disconnect.
        if self.pages and self.pages[0] == "drop":
            item = "drop"
        else:
            item = self.pages.pop(0) if self.pages else 404
        if item == "drop":
            request.transport.abort()
            await asyncio.sleep(0.1)
            raise web.HTTPInternalServerError
        if isinstance(item, int):
            return web.Response(status=item)
        return web.Response(body=item, content_type="image/jpeg")

    async def h_delete(self, request):
        self.deleted.append(request.path)
        return web.Response(status=200)


@pytest.fixture(autouse=True)
def fast_retry(monkeypatch):
    monkeypatch.setattr(client_mod, "RETRY_DELAY", 0.01)


async def _make(fake: FakeScanner):
    server = TestServer(fake.app)
    await server.start_server()
    session = aiohttp.ClientSession()
    client = EsclClient(str(server.make_url("/eSCL")), session, False)
    return server, session, client


@pytest.fixture
async def env():
    opened = []

    async def factory(fake):
        server, session, client = await _make(fake)
        opened.append((server, session))
        return client, server

    yield factory
    for server, session in opened:
        await session.close()
        await server.close()


async def test_capabilities_and_status(env):
    fake = FakeScanner([])
    client, _ = await env(fake)
    caps = await client.capabilities()
    assert "platen" in caps.sources
    assert (await client.status()).state == "idle"
    assert client.base_url.endswith("/eSCL")


async def test_scan_two_pages_then_404(env):
    fake = FakeScanner([b"p1", b"p2", 404])
    client, _ = await env(fake)
    caps = parse_capabilities(CAPS_XML)
    seen: list[int] = []
    pages = await client.scan(caps, SETTINGS, on_page=seen.append)
    assert pages == [b"p1", b"p2"]
    assert seen == [1, 2]
    assert fake.deleted == ["/eSCL/ScanJobs/abc"]
    assert b"RGB24" in fake.posted[0]


async def test_scan_retries_503(env):
    fake = FakeScanner([503, 503, b"p1", 404])
    client, _ = await env(fake)
    pages = await client.scan(parse_capabilities(CAPS_XML), SETTINGS)
    assert pages == [b"p1"]


async def test_scan_first_page_409_raises_adf_empty(env):
    fake = FakeScanner([409])
    client, _ = await env(fake)
    with pytest.raises(AdfEmpty) as err:
        await client.scan(parse_capabilities(CAPS_XML), SETTINGS)
    assert err.value.code == "adf_empty"
    assert fake.deleted == ["/eSCL/ScanJobs/abc"]


async def test_scan_409_after_page_returns_pages(env):
    fake = FakeScanner([b"p1", 409])
    client, _ = await env(fake)
    pages = await client.scan(parse_capabilities(CAPS_XML), SETTINGS)
    assert pages == [b"p1"]


async def test_scan_deletes_job_on_error(env):
    fake = FakeScanner(["drop"])
    client, _ = await env(fake)
    with pytest.raises(ScannerUnavailable) as err:
        await client.scan(parse_capabilities(CAPS_XML), SETTINGS)
    assert err.value.code == "scanner_unavailable"
    assert fake.deleted == ["/eSCL/ScanJobs/abc"]


@pytest.mark.parametrize("kind", ["relative", "absolute"])
async def test_scan_relative_and_absolute_location(env, kind):
    fake = FakeScanner([b"p1", 404])
    client, server = await env(fake)
    if kind == "relative":
        fake.location = "ScanJobs/abc"
    else:
        fake.location = str(server.make_url("/eSCL/ScanJobs/abc"))
    pages = await client.scan(parse_capabilities(CAPS_XML), SETTINGS)
    assert pages == [b"p1"]
    assert fake.deleted == ["/eSCL/ScanJobs/abc"]


async def test_create_job_503_raises_busy(env):
    fake = FakeScanner([], create=503)
    client, _ = await env(fake)
    with pytest.raises(ScannerBusy) as err:
        await client.scan(parse_capabilities(CAPS_XML), SETTINGS)
    assert err.value.code == "scanner_busy"


async def test_find_scanner_https_then_http(env):
    fake = FakeScanner([])
    _, server = await env(fake)
    async with aiohttp.ClientSession() as session:
        base = await find_scanner(session, f"127.0.0.1:{server.port}", True, False)
    assert base == f"http://127.0.0.1:{server.port}/eSCL"


async def test_find_scanner_none(env):
    fake = FakeScanner([])
    fake.caps_body = b"<not xml"
    _, server = await env(fake)
    async with aiohttp.ClientSession() as session:
        assert (
            await find_scanner(session, f"127.0.0.1:{server.port}", False, False)
            is None
        )


async def test_oversized_response_rejected(env, monkeypatch):
    monkeypatch.setattr(client_mod, "MAX_PAGE_BYTES", 10)
    fake = FakeScanner([b"x" * 100])
    client, _ = await env(fake)
    with pytest.raises(EsclError) as err:
        await client.scan(parse_capabilities(CAPS_XML), SETTINGS)
    assert err.value.code == "bad_response"
    assert fake.deleted == ["/eSCL/ScanJobs/abc"]


async def test_oversized_xml_rejected(env, monkeypatch):
    monkeypatch.setattr(client_mod, "MAX_XML_BYTES", 10)
    client, _ = await env(FakeScanner([]))
    with pytest.raises(EsclError) as err:
        await client.capabilities()
    assert err.value.code == "bad_response"
