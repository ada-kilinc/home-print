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
CAPS_XML = (FIX / "deskjet4670_capabilities.xml").read_bytes()
SETTINGS = ScanSettings("platen", "color", 300, "image/jpeg")
ADF_CAPS_XML = (FIX / "synthetic_capabilities_duplex.xml").read_bytes()
ADF = ScanSettings("adf", "color", 300, "image/jpeg")


class FakeScanner:
    """Scripted fake: ``pages`` is a list of status ints or bytes per NextDocument.

    ``create`` is the ScanJobs status, or a list of statuses for successive
    POSTs (201 once the list runs out).
    """

    def __init__(self, pages, *, create=201, location="/eSCL/ScanJobs/abc") -> None:
        self.pages = list(pages)
        self.create = create
        self.location = location
        self.deleted: list[str] = []
        self.posted: list[bytes] = []
        self.next_calls = 0
        self.next_paths: list[str] = []
        self.caps_body = CAPS_XML
        self.status_body = (FIX / "deskjet4670_status_idle.xml").read_bytes()
        self.page_delay = 0.0
        self.stall_body = False
        self.app = web.Application()
        self.app.router.add_get("/eSCL/ScannerCapabilities", self.h_caps)
        self.app.router.add_get("/eSCL/ScannerStatus", self.h_status)
        self.app.router.add_post("/eSCL/ScanJobs", self.h_create)
        self.app.router.add_get("/{job:.*}/NextDocument", self.h_next)
        self.app.router.add_delete("/{job:.*}", self.h_delete)

    async def h_caps(self, request):
        return web.Response(body=self.caps_body)

    async def h_status(self, request):
        return web.Response(body=self.status_body)

    async def h_create(self, request):
        self.posted.append(await request.read())
        if isinstance(self.create, list):
            status = self.create.pop(0) if self.create else 201
        else:
            status = self.create
        if status == 201 or 300 <= status < 400:
            return web.Response(status=status, headers={"Location": self.location})
        return web.Response(status=status)

    async def h_next(self, request):
        self.next_calls += 1
        self.next_paths.append(request.path_qs)
        if self.page_delay:
            await asyncio.sleep(self.page_delay)
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
        if self.stall_body:
            resp = web.StreamResponse(headers={"Content-Type": "image/jpeg"})
            resp.content_length = len(item) + 100
            await resp.prepare(request)
            await resp.write(item)
            await asyncio.sleep(5)
            return resp
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
    fake.caps_body = ADF_CAPS_XML
    client, _ = await env(fake)
    caps = parse_capabilities(ADF_CAPS_XML)
    seen: list[int] = []
    pages = await client.scan(caps, ADF, on_page=seen.append)
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
    pages = await client.scan(parse_capabilities(ADF_CAPS_XML), ADF)
    assert pages == [b"p1"]
    assert fake.deleted == ["/eSCL/ScanJobs/abc"]


async def test_scan_first_page_404_raises_bad_response(env):
    fake = FakeScanner([404])
    client, _ = await env(fake)
    with pytest.raises(EsclError) as err:
        await client.scan(parse_capabilities(CAPS_XML), SETTINGS)
    assert err.value.code == "bad_response"
    assert fake.deleted == ["/eSCL/ScanJobs/abc"]


async def test_scan_foreign_location_rewritten_to_base_origin(env):
    fake = FakeScanner([b"p1"])
    client, server = await env(fake)
    fake.location = f"http://192.0.2.1:{server.port + 1}/eSCL/ScanJobs/abc"
    pages = await client.scan(parse_capabilities(CAPS_XML), SETTINGS)
    assert pages == [b"p1"]
    assert fake.next_paths == ["/eSCL/ScanJobs/abc/NextDocument"]
    assert fake.deleted == ["/eSCL/ScanJobs/abc"]


@pytest.mark.parametrize(
    "location",
    [
        "/other/ScanJobs/abc",
        "/eSCL/../admin/abc",
        "/eSCLx/abc",
        "/eSCL/%2e%2e/admin",
        "/eSCL/%2E%2E/admin",
        "/eSCL/ScanJobs/%2e%2e/%2e%2e/admin",
    ],
)
async def test_scan_location_outside_base_path_rejected(env, location):
    """No request at all goes to a path outside the eSCL base (not even DELETE)."""
    fake = FakeScanner([b"p1"], location=location)
    client, _ = await env(fake)
    with pytest.raises(EsclError) as err:
        await client.scan(parse_capabilities(CAPS_XML), SETTINGS)
    assert err.value.code == "bad_response"
    assert fake.next_calls == 0
    assert fake.deleted == []


async def test_cancel_during_job_post_closes_created_job(env):
    """A scan cancelled while ScanJobs is in flight still closes that job."""
    fake = FakeScanner([b"p1"])
    client, _ = await env(fake)
    posted = asyncio.Event()
    client_mod_post = client._post_job

    async def post(body):
        posted.set()
        await asyncio.sleep(0.2)
        return await client_mod_post(body)

    client._post_job = post
    task = asyncio.create_task(client.scan(parse_capabilities(CAPS_XML), SETTINGS))
    await posted.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(50):
        if fake.deleted:
            break
        await asyncio.sleep(0.02)
    assert fake.deleted == ["/eSCL/ScanJobs/abc"]
    assert fake.next_calls == 0


async def test_scan_location_query_is_kept(env):
    fake = FakeScanner([b"p1"], location="/eSCL/ScanJobs/abc?s=1")
    client, _ = await env(fake)
    assert await client.scan(parse_capabilities(CAPS_XML), SETTINGS) == [b"p1"]
    assert fake.next_paths == ["/eSCL/ScanJobs/abc/NextDocument?s=1"]
    assert fake.deleted == ["/eSCL/ScanJobs/abc"]


async def test_scan_create_redirect_is_not_followed(env):
    fake = FakeScanner([b"p1"], create=307, location="/eSCL/ScanJobs")
    client, _ = await env(fake)
    with pytest.raises(EsclError) as err:
        await client.scan(parse_capabilities(CAPS_XML), SETTINGS)
    assert err.value.code == "bad_response"
    assert len(fake.posted) == 1
    assert fake.next_calls == 0


async def test_create_job_503_retried_until_ready(env):
    fake = FakeScanner([b"p1"], create=[503, 503])
    client, _ = await env(fake)
    assert await client.scan(parse_capabilities(CAPS_XML), SETTINGS) == [b"p1"]
    assert len(fake.posted) == 3


async def test_create_job_409_adf_empty(env):
    fake = FakeScanner([], create=409)  # status_idle: ScannerAdfEmpty
    client, _ = await env(fake)
    with pytest.raises(AdfEmpty):
        await client.scan(parse_capabilities(ADF_CAPS_XML), ADF)


async def test_create_job_409_adf_loaded_is_busy(env):
    fake = FakeScanner([], create=409)
    fake.status_body = (FIX / "status_adf_loaded.xml").read_bytes()
    client, _ = await env(fake)
    with pytest.raises(ScannerBusy):
        await client.scan(parse_capabilities(ADF_CAPS_XML), ADF)


async def test_create_job_409_platen_is_busy(env):
    fake = FakeScanner([], create=409)
    client, _ = await env(fake)
    with pytest.raises(ScannerBusy):
        await client.scan(parse_capabilities(CAPS_XML), SETTINGS)


async def test_platen_stops_after_first_page(env):
    fake = FakeScanner([b"p1", b"p2", 404])
    client, _ = await env(fake)
    assert await client.scan(parse_capabilities(CAPS_XML), SETTINGS) == [b"p1"]
    assert fake.next_calls == 1
    assert fake.deleted == ["/eSCL/ScanJobs/abc"]


async def test_adf_reads_until_404(env):
    fake = FakeScanner([b"p1", b"p2", b"p3", 404])
    client, _ = await env(fake)
    pages = await client.scan(parse_capabilities(ADF_CAPS_XML), ADF)
    assert pages == [b"p1", b"p2", b"p3"]
    assert fake.next_calls == 4


async def test_page_headers_may_take_longer_than_body_timeout(env, monkeypatch):
    monkeypatch.setattr(client_mod, "BODY_READ_TIMEOUT", 0.1)
    fake = FakeScanner([b"p1"])
    fake.page_delay = 0.3
    client, _ = await env(fake)
    assert await client.scan(parse_capabilities(CAPS_XML), SETTINGS) == [b"p1"]


async def test_stalled_page_body_times_out(env, monkeypatch):
    monkeypatch.setattr(client_mod, "BODY_READ_TIMEOUT", 0.1)
    fake = FakeScanner([b"p1"])
    fake.stall_body = True
    client, _ = await env(fake)
    with pytest.raises(ScannerUnavailable):
        await asyncio.wait_for(
            client.scan(parse_capabilities(CAPS_XML), SETTINGS), timeout=2
        )
    assert fake.deleted == ["/eSCL/ScanJobs/abc"]


async def test_page_wait_includes_503_retries(env, monkeypatch):
    monkeypatch.setattr(client_mod, "PAGE_WAIT", 0.2)
    fake = FakeScanner([503] * 10000)
    client, _ = await env(fake)
    with pytest.raises(ScannerUnavailable):
        await asyncio.wait_for(
            client.scan(parse_capabilities(CAPS_XML), SETTINGS), timeout=2
        )
    assert fake.deleted == ["/eSCL/ScanJobs/abc"]


async def test_scan_cancel_mid_wait_still_deletes(env):
    fake = FakeScanner([503] * 10000)
    client, _ = await env(fake)
    task = asyncio.ensure_future(client.scan(parse_capabilities(CAPS_XML), SETTINGS))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.2)
    assert fake.deleted == ["/eSCL/ScanJobs/abc"]


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


async def test_create_job_503_raises_busy(env, monkeypatch):
    monkeypatch.setattr(client_mod, "CREATE_BUSY_WAIT", 0.1)
    fake = FakeScanner([], create=503)
    client, _ = await env(fake)
    with pytest.raises(ScannerBusy) as err:
        await client.scan(parse_capabilities(CAPS_XML), SETTINGS)
    assert err.value.code == "scanner_busy"


async def test_find_scanner_https_then_http(env):
    fake = FakeScanner([])
    _, server = await env(fake)
    async with aiohttp.ClientSession() as session:
        found = await find_scanner(session, f"127.0.0.1:{server.port}", True, False)
    assert found is not None
    base, caps = found
    assert base == f"http://127.0.0.1:{server.port}/eSCL"
    assert "platen" in caps.sources


async def test_find_scanner_none(env):
    fake = FakeScanner([])
    fake.caps_body = b"<not xml"
    _, server = await env(fake)
    async with aiohttp.ClientSession() as session:
        assert (
            await find_scanner(session, f"127.0.0.1:{server.port}", False, False)
            is None
        )


async def test_find_scanner_uses_url_after_redirect(env):
    fake = FakeScanner([])
    _, target = await env(fake)
    final = target.make_url("/eSCL/ScannerCapabilities")

    async def redirect(request):
        raise web.HTTPFound(str(final))

    app = web.Application()
    app.router.add_get("/eSCL/ScannerCapabilities", redirect)
    server = TestServer(app)
    await server.start_server()
    try:
        async with aiohttp.ClientSession() as session:
            found = await find_scanner(
                session, f"127.0.0.1:{server.port}", False, False
            )
    finally:
        await server.close()
    assert found is not None
    assert found[0] == f"http://127.0.0.1:{target.port}/eSCL"


async def test_find_scanner_rejects_redirect_to_other_host(env):
    fake = FakeScanner([])
    _, target = await env(fake)
    final = f"http://localhost:{target.port}/eSCL/ScannerCapabilities"

    async def redirect(request):
        raise web.HTTPFound(final)

    app = web.Application()
    app.router.add_get("/eSCL/ScannerCapabilities", redirect)
    server = TestServer(app)
    await server.start_server()
    try:
        async with aiohttp.ClientSession() as session:
            found = await find_scanner(
                session, f"127.0.0.1:{server.port}", False, False
            )
    finally:
        await server.close()
    assert found is None


@pytest.mark.parametrize(("verify", "expected"), [(True, True), (False, False)])
async def test_ssl_argument_is_a_bool(monkeypatch, verify, expected):
    """aiohttp deprecates ssl=None; pass True (verify) or False (don't)."""
    seen = []

    class Session:
        def get(self, url, **kw):
            seen.append(kw["ssl"])
            raise aiohttp.ClientError

    await find_scanner(Session(), "h", False, verify)
    client = EsclClient("http://h/eSCL", Session(), verify)
    with pytest.raises(ScannerUnavailable):
        await client.status()
    assert seen and all(v is expected for v in seen)


@pytest.mark.parametrize(
    ("ssl", "expected"),
    [
        (True, ["https://h/eSCL", "http://h/eSCL"]),
        (False, ["http://h/eSCL", "https://h/eSCL"]),
    ],
)
async def test_find_scanner_candidate_order(monkeypatch, ssl, expected):
    tried = []

    async def probe(session, base, verify_ssl, timeout):
        tried.append((base, verify_ssl, timeout))
        raise ScannerUnavailable()

    monkeypatch.setattr(client_mod, "_probe", probe)
    assert await find_scanner(None, "h", ssl, False, timeout=5) is None
    assert tried == [(url, False, 5) for url in expected]


@pytest.mark.parametrize(
    ("host", "url"),
    [
        ("fe80::1", "http://[fe80::1]/eSCL"),
        ("[fe80::1]", "http://[fe80::1]/eSCL"),
        ("192.168.1.20", "http://192.168.1.20/eSCL"),
        ("printer.local", "http://printer.local/eSCL"),
    ],
)
async def test_find_scanner_brackets_ipv6(monkeypatch, host, url):
    tried = []

    async def probe(session, base, verify_ssl, timeout):
        tried.append(base)
        raise ScannerUnavailable()

    monkeypatch.setattr(client_mod, "_probe", probe)
    await find_scanner(None, host, False, True)
    assert tried[0] == url


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


@pytest.mark.parametrize(
    ("base", "other", "same"),
    [
        ("http://10.0.0.5/eSCL", "http://10.0.0.5:80/eSCL/ScanJobs/x", True),
        ("https://10.0.0.5/eSCL", "https://10.0.0.5:443/eSCL/ScanJobs/x", True),
        ("http://Printer.local/eSCL", "HTTP://printer.LOCAL/eSCL/ScanJobs/x", True),
        ("http://10.0.0.5/eSCL", "https://10.0.0.5/eSCL/ScanJobs/x", False),
        ("http://10.0.0.5/eSCL", "http://10.0.0.5:8080/eSCL/ScanJobs/x", False),
        ("http://10.0.0.5/eSCL", "http://10.0.0.6/eSCL/ScanJobs/x", False),
    ],
)
def test_same_origin(base, other, same):
    assert client_mod._same_origin(base, other) is same
