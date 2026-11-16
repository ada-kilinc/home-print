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
from .convert.scan_doc import append_pdf, build_pdf, normalize_page
from .escl.errors import EsclError, ScannerBusy
from .escl.models import ScannerCaps, ScanSettings
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

    def as_dict(self) -> dict[str, Any]:
        """The state without internal bookkeeping."""
        data = asdict(self)
        del data["finished_at"]
        return data


def scan_mime(caps: ScannerCaps, source: str) -> str:
    """Page image type to ask the scanner for: JPEG if offered, else PNG."""
    return MIME_JPEG if MIME_JPEG in caps.sources[source].formats else MIME_PNG


def validate_request(
    caps: ScannerCaps, req: ScanRequest, archive: ScanArchive | None = None
) -> ScanSettings:
    """Check a request against the scanner; raise ``ScanOptionError``.

    With ``archive`` the ``append_to`` record is checked too: unknown is
    ``not_found``, a record that is not a PDF is an invalid option.
    """
    src = caps.sources.get(req.source)
    if (
        req.format not in FORMATS
        or src is None
        or req.color_mode not in src.color_modes
        or req.resolution not in src.resolutions
    ):
        raise ScanOptionError
    if req.append_to is not None:
        if req.format != "pdf":
            raise ScanOptionError
        if archive is not None:
            record = archive.record(req.append_to)
            if record is None or archive.file_path(req.append_to) is None:
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
    archive = runtime.archive
    base_pdf = None
    previous: dict[str, Any] | None = None
    if req.append_to is not None:
        previous = archive.record(req.append_to)
        path = archive.file_path(req.append_to)
        if previous is None or path is None:
            raise ScanError("not_found")
        base_pdf = await hass.async_add_executor_job(_read, path)
    data, mime = await hass.async_add_executor_job(
        _build_document, pages, req.format, req.resolution, base_pdf
    )
    if previous is not None:
        record = await archive.async_replace_file(
            previous["id"], data, previous["pages"] + len(pages)
        )
        if record is None:
            raise ScanError("not_found")
        return record
    return await archive.async_add(
        name=req.name,
        data=data,
        mime=mime,
        pages=len(pages),
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
        state.error = "scan_failed" if _is_cancel(err) else _error_code(err)
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
    resolution = (
        min(src.resolutions, key=lambda r: abs(r - PREFERRED_RESOLUTION))
        if src.resolutions
        else PREFERRED_RESOLUTION
    )
    return {
        "source": source,
        "color_mode": "color" if "color" in src.color_modes else src.color_modes[0],
        "resolution": resolution,
        "format": "pdf",
    }
