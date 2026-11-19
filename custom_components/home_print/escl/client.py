"""Async eSCL (AirScan) client."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from collections.abc import Callable
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

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
PAGE_WAIT = 180  # seconds, total wait for one page's headers (incl. 503 retries)
BODY_READ_TIMEOUT = 60  # seconds without data while a page body is read
RETRY_DELAY = 1.0  # seconds between 503 retries
CREATE_BUSY_WAIT = 30  # seconds of 503 retries when creating a job
_FEEDER_SOURCES = ("adf", "adf_duplex")
_CAPS_PATH = "/ScannerCapabilities"


async def _read_limited(
    resp: aiohttp.ClientResponse, limit: int, idle_timeout: float | None = None
) -> bytes:
    """Read a body, failing with bad_response past ``limit`` bytes.

    With ``idle_timeout`` each chunk must arrive within that many seconds
    (``TimeoutError`` otherwise).
    """
    if resp.content_length is not None and resp.content_length > limit:
        raise EsclError("bad_response")
    data = bytearray()
    while True:
        async with asyncio.timeout(idle_timeout):
            chunk = await resp.content.read(64 * 1024)
        if not chunk:
            break
        data += chunk
        if len(data) > limit:
            raise EsclError("bad_response")
    return bytes(data)


def _origin(url: str) -> tuple[str, str, int | None]:
    """Normalised (scheme, host, effective port) of a URL."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    try:
        port = parts.port or {"http": 80, "https": 443}.get(scheme)
    except ValueError:
        port = None
    return scheme, (parts.hostname or "").lower(), port


def _same_origin(a: str, b: str) -> bool:
    return _origin(a) == _origin(b)


def _with_suffix(url: str, suffix: str) -> str:
    """``url`` with ``/suffix`` appended to its path; the query is kept."""
    parts = urlsplit(url)
    return urlunsplit(
        parts._replace(path=f"{parts.path.rstrip('/')}/{suffix}", fragment="")
    )


class EsclClient:
    """Client for one scanner's eSCL endpoint."""

    def __init__(
        self, base_url: str, session: aiohttp.ClientSession, verify_ssl: bool
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = session
        # True verifies with the default context; False skips verification.
        # (aiohttp 3.13 deprecates ``ssl=None``.)
        self._ssl = bool(verify_ssl)

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

    async def raw_xml(self, name: str) -> bytes:
        """A raw answer such as ``ScannerCapabilities`` (for diagnostics)."""
        return await self._get_xml(name)

    async def capabilities(self) -> ScannerCaps:
        return parse_capabilities(await self._get_xml("ScannerCapabilities"))

    async def status(self) -> ScannerStatus:
        return parse_status(await self._get_xml("ScannerStatus"))

    def _job_url(self, location: str) -> str | None:
        """The job URL on our own origin; None when it is outside the base path.

        Only the path and query of ``Location`` are used: some scanners name
        another host or scheme (e.g. their own https address) for the job.
        The path is checked after percent-decoding, because the HTTP client
        resolves ``%2e%2e`` before sending.
        """
        parts = urlsplit(urljoin(self._base_url + "/", location))
        base = urlsplit(self._base_url)
        base_path = base.path.rstrip("/")
        decoded = unquote(parts.path)
        segments = decoded.split("/")
        if (
            not decoded.startswith(base_path + "/")
            or ".." in segments
            or "." in segments
            or "\\" in decoded
            or decoded.rstrip("/") == base_path
        ):
            return None
        return urlunsplit(
            (base.scheme, base.netloc, parts.path.rstrip("/"), parts.query, "")
        )

    async def _post_job(self, body: bytes) -> tuple[int, str | None]:
        try:
            async with self._session.post(
                f"{self._base_url}/ScanJobs",
                data=body,
                headers={"Content-Type": "text/xml"},
                ssl=self._ssl,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                return resp.status, resp.headers.get("Location")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ScannerUnavailable() from err

    async def _post_job_shielded(self, body: bytes) -> tuple[int, str | None]:
        """``_post_job`` that survives cancellation.

        If the caller is cancelled while the POST is in flight, the scanner
        may still create the job; it is closed once the reply arrives, so the
        next scan doesn't find the scanner busy.
        """
        post = asyncio.ensure_future(self._post_job(body))
        try:
            return await asyncio.shield(post)
        except asyncio.CancelledError:
            await asyncio.shield(self._discard_job(post))
            raise

    async def _discard_job(self, post: asyncio.Future[tuple[int, str | None]]) -> None:
        try:
            status, location = await post
        except Exception:  # noqa: BLE001 - nothing was created
            return
        if status == 201 and location:
            job_url = self._job_url(location)
            if job_url is not None:
                await self._close_job(job_url)

    async def _create_job(self, body: bytes, source: str) -> str:
        deadline = time.monotonic() + CREATE_BUSY_WAIT
        while True:
            status, location = await self._post_job_shielded(body)
            if status != 503:
                break
            if time.monotonic() + RETRY_DELAY > deadline:
                raise ScannerBusy()
            await asyncio.sleep(RETRY_DELAY)
        if status == 409:
            if source in _FEEDER_SOURCES:
                try:
                    adf_loaded = (await self.status()).adf_loaded
                except EsclError:
                    adf_loaded = None
                if adf_loaded is False:
                    raise AdfEmpty()
            raise ScannerBusy()
        if 300 <= status < 400:
            _LOGGER.debug("Scanner redirected ScanJobs (%s) to %s", status, location)
            raise EsclError("bad_response")
        if status != 201 or not location:
            raise EsclError("bad_response")
        job_url = self._job_url(location)
        if job_url is None:
            # Nothing is sent to a path outside the eSCL base, not even DELETE.
            _LOGGER.debug("Scanner gave an unexpected job location %s", location)
            raise EsclError("bad_response")
        return job_url

    async def _close_job(self, job_url: str) -> None:
        """Best-effort DELETE; never raises."""
        try:
            async with self._session.delete(
                job_url,
                ssl=self._ssl,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ):
                pass
        except (aiohttp.ClientError, TimeoutError):
            _LOGGER.debug("Could not close scan job %s", job_url)

    async def _next_page(self, job_url: str, first: bool) -> bytes | None:
        """Fetch the next page; None when no pages remain.

        Headers must arrive within ``PAGE_WAIT`` (503 retries included);
        the body then only has to keep flowing (``BODY_READ_TIMEOUT``).
        """
        url = _with_suffix(job_url, "NextDocument")
        deadline = time.monotonic() + PAGE_WAIT
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ScannerUnavailable()
            try:
                async with asyncio.timeout(remaining):
                    resp = await self._session.get(
                        url,
                        ssl=self._ssl,
                        timeout=aiohttp.ClientTimeout(total=None),
                    )
                try:
                    if resp.status == 200:
                        return await _read_limited(
                            resp, MAX_PAGE_BYTES, BODY_READ_TIMEOUT
                        )
                    if resp.status == 404:
                        return None
                    if resp.status == 409:
                        if first:
                            raise AdfEmpty()
                        return None
                    if resp.status != 503:
                        raise EsclError("bad_response")
                finally:
                    resp.release()
            except (aiohttp.ClientError, TimeoutError) as err:
                raise ScannerUnavailable() from err
            await asyncio.sleep(RETRY_DELAY)

    async def scan(
        self,
        caps: ScannerCaps,
        settings: ScanSettings,
        on_page: Callable[[int], None] | None = None,
    ) -> list[bytes]:
        """Run a scan job and return the page images in order.

        The platen gives one page; feeders are read until the scanner says
        there are no more. A created job is always closed (DELETE).
        """
        body = build_settings(caps, settings)
        job_url: str | None = None
        pages: list[bytes] = []
        try:
            job_url = await self._create_job(body, settings.source)
            while True:
                page = await self._next_page(job_url, first=not pages)
                if page is None:
                    break
                pages.append(page)
                if on_page is not None:
                    on_page(len(pages))
                if settings.source not in _FEEDER_SOURCES:
                    break
            if not pages:
                raise EsclError("bad_response")
        finally:
            if job_url is not None:
                await asyncio.shield(self._close_job(job_url))
        return pages


def _url_host(host: str) -> str:
    """``host`` for a URL: IPv6 literals get brackets."""
    bare = host.strip("[]")
    try:
        if ipaddress.ip_address(bare).version == 6:
            return f"[{bare}]"
    except ValueError:
        pass
    return host


async def _probe(
    session: aiohttp.ClientSession, base: str, verify_ssl: bool, timeout: float
) -> tuple[str, ScannerCaps]:
    """Read capabilities at ``base``; return the base after redirects too.

    A redirect may change the scheme or port (HP: http to https) but not the
    host: a scanner that sends us elsewhere is not used.
    """
    try:
        async with session.get(
            f"{base}{_CAPS_PATH}",
            ssl=bool(verify_ssl),
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status != 200:
                raise EsclError("bad_response")
            caps = parse_capabilities(await _read_limited(resp, MAX_XML_BYTES))
            final = str(resp.url.with_query(None).with_fragment(None))
    except (aiohttp.ClientError, TimeoutError) as err:
        raise ScannerUnavailable() from err
    final_host = (urlsplit(final).hostname or "").lower()
    if final_host != (urlsplit(base).hostname or "").lower():
        _LOGGER.debug("Scanner at %s redirected to another host: %s", base, final)
        raise EsclError("bad_response")
    if final.endswith(_CAPS_PATH):
        base = final[: -len(_CAPS_PATH)]
    return base, caps


async def find_scanner(
    session: aiohttp.ClientSession,
    host: str,
    ssl: bool,
    verify_ssl: bool,
    timeout: float = REQUEST_TIMEOUT,
) -> tuple[str, ScannerCaps] | None:
    """Return the eSCL base URL and capabilities for ``host``, or None.

    Both schemes are tried (the printer's own first): HP printers may only
    answer eSCL over https, or redirect http there. The base URL is taken
    from the final URL after redirects. ``timeout`` applies per candidate.
    """
    schemes = ("https", "http") if ssl else ("http", "https")
    url_host = _url_host(host)
    for scheme in schemes:
        try:
            return await _probe(
                session, f"{scheme}://{url_host}/eSCL", verify_ssl, timeout
            )
        except (EsclError, aiohttp.ClientError, TimeoutError):
            continue
    return None
