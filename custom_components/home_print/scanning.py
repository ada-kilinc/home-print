"""Run a scan in the background and archive the result."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from homeassistant.core import HomeAssistant

from .const import EVENT_SCAN
from .convert.errors import InvalidDocument, TooManyPages
from .convert.scan_doc import SCAN_MAX_PIXELS, append_pdf, build_pdf, normalize_page
from .escl.errors import EsclError, ScannerBusy
from .escl.models import ScannerCaps, ScanSettings, SourceCaps
from .scans import ScanArchive

if TYPE_CHECKING:
    from . import HomePrintConfigEntry
    from .scanner import ScannerRuntime

_LOGGER = logging.getLogger(__name__)

FORMATS = ("pdf", "jpeg")
SOURCES = ("platen", "adf", "adf_duplex")
COLOR_MODES = ("color", "gray", "bw")
MIME_JPEG = "image/jpeg"
MIME_PNG = "image/png"
MIME_PDF = "application/pdf"
# A finished state stays readable this long (a card that was closed can still
# find out how its scan ended).
RETAIN_SECONDS = 600
PREFERRED_RESOLUTION = 300

_RUNNING = ("scanning", "saving")
_KNOWN_ERRORS = frozenset(
    {
        "scanner_busy",
        "scanner_unavailable",
        "adf_empty",
        "invalid_option",
        "bad_scan",
        "too_large",
        "too_many_pages",
        "not_found",
    }
)


class ScanError(Exception):
    """A scan request that can't be carried out; ``code`` is stable."""

    code = "scan_failed"

    def __init__(self, code: str | None = None) -> None:
        if code is not None:
            self.code = code
        super().__init__(self.code)


class ScanOptionError(ScanError):
    """The scanner does not support a requested option."""

    code = "invalid_option"


@dataclass
class ScanRequest:
    """What the user asked for."""

    source: str
    color_mode: str
    resolution: int
    format: str
    name: str | None = None
    append_to: str | None = None


@dataclass
class ScanJobState:
    """Progress of one scan, as the card polls it."""

    scan_id: str
    state: str  # "scanning" | "saving" | "done" | "error"
    pages: int = 0
    error: str | None = None
    record: dict[str, Any] | None = None
    user: str | None = None
    finished_at: float | None = None  # monotonic; None while running
    cancel_requested: bool = False  # set by async_cancel_scan

    def as_dict(self) -> dict[str, Any]:
        """The state without internal bookkeeping."""
        data = asdict(self)
        del data["finished_at"]
        del data["cancel_requested"]
        return data


def scan_mime(caps: ScannerCaps, source: str) -> str:
    """Page image type to ask the scanner for: JPEG if offered, else PNG."""
    return MIME_JPEG if MIME_JPEG in caps.sources[source].formats else MIME_PNG


def allowed_resolutions(src: SourceCaps) -> tuple[int, ...]:
    """Resolutions whose full-area page stays within ``SCAN_MAX_PIXELS``.

    Higher ones would scan fine but be rejected as too large when saved.
    """
    return tuple(
        r
        for r in src.resolutions
        if src.max_width * src.max_height * (r / 300) ** 2 <= SCAN_MAX_PIXELS
    )


def validate_request(
    caps: ScannerCaps, req: ScanRequest, archive: ScanArchive | None = None
) -> ScanSettings:
    """Check a request against the scanner; raise ``ScanOptionError``.

    With ``archive`` the ``append_to`` record is checked too: unknown is
    ``not_found``, a record that is not a PDF is an invalid option. (Whether
    its file still exists is checked by ``async_start_scan``, off the loop.)
    """
    src = caps.sources.get(req.source)
    if (
        req.format not in FORMATS
        or src is None
        or req.color_mode not in src.color_modes
        or req.resolution not in allowed_resolutions(src)
    ):
        raise ScanOptionError
    if req.append_to is not None:
        if req.format != "pdf":
            raise ScanOptionError
        if archive is not None:
            record = archive.record(req.append_to)
            if record is None:
                raise ScanError("not_found")
            if record["mime"] != MIME_PDF:
                raise ScanOptionError
    return ScanSettings(
        source=req.source,
        color_mode=req.color_mode,
        resolution=req.resolution,
        mime=scan_mime(caps, req.source),
    )


def active_state(runtime: ScannerRuntime) -> ScanJobState | None:
    """The running or recently finished scan; None once it is stale."""
    state = runtime.active
    if (
        state is not None
        and state.finished_at is not None
        and time.monotonic() - state.finished_at > RETAIN_SECONDS
    ):
        runtime.active = None
        return None
    return state


def _is_running(runtime: ScannerRuntime) -> bool:
    state = active_state(runtime)
    return state is not None and state.state in _RUNNING


def _build_document(
    pages: list[bytes], fmt: str, dpi: int, base_pdf: bytes | None
) -> tuple[bytes, str]:
    """Normalize pages and make the file to store. Runs in the executor."""
    if base_pdf is not None:
        return append_pdf(base_pdf, pages, dpi), MIME_PDF
    if fmt == "jpeg" and len(pages) == 1:
        return normalize_page(pages[0]), MIME_JPEG
    return build_pdf(pages, dpi), MIME_PDF


def _read(path: Any) -> bytes:
    return path.read_bytes()


def _error_code(err: BaseException) -> str:
    if isinstance(err, ScanError | EsclError):
        code = err.code
    elif isinstance(err, InvalidDocument):
        code = str(err)
    elif isinstance(err, TooManyPages):
        code = "too_many_pages"
    else:
        code = ""
    if code in _KNOWN_ERRORS:
        return code
    _LOGGER.warning("Scan failed", exc_info=err)
    return "scan_failed"


async def _save(
    hass: HomeAssistant,
    runtime: ScannerRuntime,
    req: ScanRequest,
    pages: list[bytes],
    state: ScanJobState,
) -> dict[str, Any]:
    """Store the pages: appended to ``req.append_to``, or as a new record.

    If the append target was deleted while scanning, the pages become a new
    record instead of being lost.
    """
    archive = runtime.archive
    base_pdf = None
    previous: dict[str, Any] | None = None
    if req.append_to is not None:
        previous = archive.record(req.append_to)
        path = await archive.async_file_path(req.append_to)
        if previous is not None and path is not None:
            try:
                base_pdf = await hass.async_add_executor_job(_read, path)
            except OSError:
                base_pdf = None
        if base_pdf is None:
            _LOGGER.info("Scan to append to is gone; saving the pages as a new scan")
            previous = None
    data, mime = await hass.async_add_executor_job(
        _build_document, pages, req.format, req.resolution, base_pdf
    )
    total = len(pages)
    if previous is not None:
        total = previous["pages"] + len(pages)
        record = await archive.async_replace_file(previous["id"], data, total)
        if record is not None:
            return record
        _LOGGER.info("Scan to append to is gone; saving the pages as a new scan")
    return await archive.async_add(
        name=req.name,
        data=data,
        mime=mime,
        pages=total,
        user=state.user,
        source=req.source,
        color_mode=req.color_mode,
        resolution=req.resolution,
    )


async def _run(
    hass: HomeAssistant,
    entry: HomePrintConfigEntry,
    runtime: ScannerRuntime,
    req: ScanRequest,
    settings: ScanSettings,
    state: ScanJobState,
) -> None:
    def on_page(count: int) -> None:
        state.pages = count

    name: str | None = req.name
    try:
        pages = await runtime.client.scan(runtime.caps, settings, on_page=on_page)
        state.pages = len(pages)
        state.state = "saving"
        record = await _save(hass, runtime, req, pages, state)
        state.record = record
        name = record["name"]
        state.state = "done"
    except BaseException as err:
        state.state = "error"
        if _is_cancel(err):
            state.error = "canceled" if state.cancel_requested else "scan_failed"
        else:
            state.error = _error_code(err)
        if _is_cancel(err):
            raise
    finally:
        state.finished_at = time.monotonic()
        hass.bus.async_fire(
            EVENT_SCAN,
            {
                "entry_id": entry.entry_id,
                "user": state.user,
                "name": name,
                "pages": state.record["pages"] if state.record else state.pages,
                "result": "done" if state.state == "done" else "error",
            },
        )


def _is_cancel(err: BaseException) -> bool:
    return not isinstance(err, Exception)


async def async_start_scan(
    hass: HomeAssistant,
    entry: HomePrintConfigEntry,
    req: ScanRequest,
    user: str | None,
) -> ScanJobState:
    """Validate and start a scan in the background; return its state.

    Raises ``ScanError`` (``no_scanner``, ``invalid_option``, ``not_found``)
    or ``ScannerBusy``.
    """
    runtime = entry.runtime_data.scanner
    if runtime is None:
        raise ScanError("no_scanner")
    settings = validate_request(runtime.caps, req, runtime.archive)
    if (
        req.append_to is not None
        and await runtime.archive.async_file_path(req.append_to) is None
    ):
        raise ScanError("not_found")
    if _is_running(runtime):
        raise ScannerBusy
    state = ScanJobState(scan_id=uuid4().hex, state="scanning", user=user)
    runtime.active = state
    runtime.task = entry.async_create_background_task(
        hass,
        _run(hass, entry, runtime, req, settings, state),
        f"home_print scan {entry.entry_id}",
    )
    return state


async def async_cancel_scan(
    entry: HomePrintConfigEntry, scan_id: str
) -> ScanJobState | None:
    """Cancel a running scan and wait until it has stopped; None if unknown.

    The eSCL client closes the scanner job (DELETE) on the way out and the
    state ends as ``error`` / ``canceled``. A scan that is already saving is
    left to finish (stopping it then could leave a stray file); a finished
    scan is returned as it is.
    """
    runtime = entry.runtime_data.scanner
    state = active_state(runtime) if runtime is not None else None
    if runtime is None or state is None or state.scan_id != scan_id:
        return None
    task = runtime.task
    if task is not None and not task.done():
        if state.state == "scanning":
            state.cancel_requested = True
            task.cancel()
        await asyncio.wait({task})
    return state


async def async_scan_and_wait(
    hass: HomeAssistant,
    entry: HomePrintConfigEntry,
    req: ScanRequest,
    user: str | None,
) -> ScanJobState:
    """Start a scan and wait until it is done or failed."""
    state = await async_start_scan(hass, entry, req, user)
    task = entry.runtime_data.scanner.task  # type: ignore[union-attr]
    if task is not None:
        # wait() neither raises the scan's cancellation nor cancels the scan
        # when the service call itself is cancelled.
        await asyncio.wait({task})
    return state


def scan_defaults(caps: ScannerCaps) -> dict[str, Any]:
    """Defaults for the card: 300 dpi (or the closest), color, platen, PDF."""
    source = "platen" if "platen" in caps.sources else next(iter(caps.sources))
    src = caps.sources[source]
    resolutions = allowed_resolutions(src)
    resolution = (
        min(resolutions, key=lambda r: abs(r - PREFERRED_RESOLUTION))
        if resolutions
        else PREFERRED_RESOLUTION
    )
    return {
        "source": source,
        "color_mode": "color" if "color" in src.color_modes else src.color_modes[0],
        "resolution": resolution,
        "format": "pdf",
    }
