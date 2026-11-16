"""Async eSCL (AirScan) client."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit

import aiohttp

from .errors import AdfEmpty, EsclError, ScannerBusy, ScannerUnavailable
from .models import ScannerCaps, ScannerStatus, ScanSettings
from .parse import build_settings, parse_capabilities, parse_status

__all__ = [
    "AdfEmpty",
    "EsclClient",
    "EsclError",
    "ScannerBusy",
    "ScannerUnavailable",
    "find_scanner",
]

_LOGGER = logging.getLogger(__name__)

MAX_XML_BYTES = 1024 * 1024
MAX_PAGE_BYTES = 64 * 1024 * 1024
REQUEST_TIMEOUT = 10  # seconds, for XML requests and job control
PAGE_WAIT = 180  # seconds, total wait for one page (includes scanning)
RETRY_DELAY = 1.0  # seconds between 503 retries


async def _read_limited(resp: aiohttp.ClientResponse, limit: int) -> bytes:
    """Read a body, failing with bad_response past ``limit`` bytes."""
    if resp.content_length is not None and resp.content_length > limit:
        raise EsclError("bad_response")
    data = bytearray()
    async for chunk in resp.content.iter_chunked(64 * 1024):
        data += chunk
        if len(data) > limit:
            raise EsclError("bad_response")
    return bytes(data)


class EsclClient:
    """Client for one scanner's eSCL endpoint."""

    def __init__(
        self, base_url: str, session: aiohttp.ClientSession, verify_ssl: bool
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = session
        self._ssl: bool | None = None if verify_ssl else False

    @property
    def base_url(self) -> str:
        return self._base_url

    async def _get_xml(self, path: str) -> bytes:
        try:
            async with self._session.get(
                f"{self._base_url}/{path}",
                ssl=self._ssl,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    raise EsclError("bad_response")
                return await _read_limited(resp, MAX_XML_BYTES)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ScannerUnavailable() from err

    async def capabilities(self) -> ScannerCaps:
        return parse_capabilities(await self._get_xml("ScannerCapabilities"))

    async def status(self) -> ScannerStatus:
        return parse_status(await self._get_xml("ScannerStatus"))

    async def _create_job(self, body: bytes) -> str:
        try:
            async with self._session.post(
                f"{self._base_url}/ScanJobs",
                data=body,
                headers={"Content-Type": "text/xml"},
                ssl=self._ssl,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status in (503, 409):
                    raise ScannerBusy()
                location = resp.headers.get("Location")
                if resp.status != 201 or not location:
                    raise EsclError("bad_response")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ScannerUnavailable() from err
        job_url = urljoin(self._base_url + "/", location).rstrip("/")
        base, job = urlsplit(self._base_url), urlsplit(job_url)
        if (base.scheme, base.netloc) != (job.scheme, job.netloc):
            raise EsclError("bad_response")
        return job_url

    async def _close_job(self, job_url: str) -> None:
        """Best-effort DELETE; never raises."""
        try:
            async with self._session.delete(
                job_url,
                ssl=self._ssl,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ):
                pass
        except (aiohttp.ClientError, TimeoutError):
            _LOGGER.debug("Could not close scan job %s", job_url)

    async def _next_page(self, job_url: str, first: bool) -> bytes | None:
        """Fetch the next page; None when no pages remain."""
        deadline = time.monotonic() + PAGE_WAIT
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ScannerUnavailable()
            try:
                async with self._session.get(
                    f"{job_url}/NextDocument",
                    ssl=self._ssl,
                    timeout=aiohttp.ClientTimeout(total=remaining),
                ) as resp:
                    if resp.status == 200:
                        return await _read_limited(resp, MAX_PAGE_BYTES)
                    if resp.status == 404:
                        return None
                    if resp.status == 409:
                        if first:
                            raise AdfEmpty()
                        return None
                    if resp.status != 503:
                        raise EsclError("bad_response")
            except (aiohttp.ClientError, TimeoutError) as err:
                raise ScannerUnavailable() from err
            await asyncio.sleep(RETRY_DELAY)

    async def scan(
        self,
        caps: ScannerCaps,
        settings: ScanSettings,
        on_page: Callable[[int], None] | None = None,
    ) -> list[bytes]:
        """Run a scan job and return the page images in order."""
        job_url = await self._create_job(build_settings(caps, settings))
        pages: list[bytes] = []
        try:
            while True:
                page = await self._next_page(job_url, first=not pages)
                if page is None:
                    break
                pages.append(page)
                if on_page is not None:
                    on_page(len(pages))
            if not pages:
                raise EsclError("bad_response")
        finally:
            await asyncio.shield(self._close_job(job_url))
        return pages


async def find_scanner(
    session: aiohttp.ClientSession, host: str, ssl: bool, verify_ssl: bool
) -> str | None:
    """Return the eSCL base URL for ``host`` or None if it has no scanner."""
    schemes = ("https", "http") if ssl else ("http",)
    for scheme in schemes:
        base = f"{scheme}://{host}/eSCL"
        try:
            await EsclClient(base, session, verify_ssl).capabilities()
        except (EsclError, aiohttp.ClientError, TimeoutError):
            continue
        return base
    return None
