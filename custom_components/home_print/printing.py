"""Shared print path used by the ``print_file`` service and the upload view."""

from __future__ import annotations

import logging
import posixpath
import re
import unicodedata
from typing import TYPE_CHECKING, Any

from homeassistant.auth.models import User
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util

from .client import (
    CannotConnect,
    HomePrintError,
    PrinterRejected,
    PrintTimeout,
    UnsupportedOption,
)
from .const import (
    CONF_DEFAULT_COLOR_MODE,
    CONF_DEFAULT_SIDES,
    CONF_MAX_FILE_MB,
    DEFAULT_MAX_FILE_MB,
    DOMAIN,
    EVENT_JOB,
    PRINT_TIMEOUT,
    PRINT_TIMEOUT_PER_PAGE,
)
from .convert import pipeline
from .convert.errors import (
    InvalidDocument,
    NoConversionRoute,
    OutputTooLarge,
    TooManyPages,
)
from .convert.render import MAX_IMAGE_PIXELS
from .models import JobResult, LastJob, PrinterInfo, PrintOptions

if TYPE_CHECKING:
    from . import HomePrintConfigEntry

_LOGGER = logging.getLogger(__name__)

SIDES = ("one-sided", "two-sided-long-edge", "two-sided-short-edge")
COLOR_MODES = ("auto", "color", "monochrome")
COLOR_AUTO = "auto"  # printer default: send no print-color-mode
DEFAULT_USER_NAME = "Home Assistant"
MAX_JOB_NAME_BYTES = 255  # IPP name(MAX)
MAX_PAGE_NUMBER = 9999  # keeps page-ranges well inside IPP's int32

_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)
_PAGE_RANGES_RE = re.compile(r"^\d+(-\d+)?(,\d+(-\d+)?)*$")


class PrintError(HomeAssistantError):
    """A print request failed. ``key`` doubles as the translation key."""

    key = "print_failed"
    http_status = 502

    def __init__(self, **placeholders: Any) -> None:
        super().__init__(
            translation_domain=DOMAIN,
            translation_key=self.key,
            translation_placeholders={k: str(v) for k, v in placeholders.items()},
        )


class FileTooLarge(PrintError):
    """The file is larger than the configured limit."""

    key = "file_too_large"
    http_status = 413


class UnsupportedFileType(PrintError):
    """The file is not a PDF, JPEG or PNG."""

    key = "unsupported_file_type"
    http_status = 400


class FormatNotSupportedByPrinter(PrintError):
    """The printer does not accept this document format."""

    key = "format_not_supported"
    http_status = 422


class OptionNotSupportedByPrinter(PrintError):
    """The printer does not support a requested option."""

    key = "option_not_supported"
    http_status = 422


class PrinterRejectedJob(PrintError):
    """The printer answered the job with an IPP error status."""

    key = "printer_rejected"
    http_status = 422


class PrinterUnavailable(PrintError):
    """The printer could not be reached."""

    key = "printer_unavailable"
    http_status = 502


class PrintTimedOut(PrintError):
    """The printer did not answer the job in time; it may still print."""

    key = "print_timeout"
    http_status = 504


class InvalidPrintOption(PrintError, ServiceValidationError):
    """A print option has an invalid value."""

    key = "invalid_option"
    http_status = 400


class InvalidDocumentError(PrintError, ServiceValidationError):
    """The document is corrupt, encrypted or empty."""

    key = "invalid_document"
    http_status = 400


class TooManyPagesError(PrintError, ServiceValidationError):
    """The document has more pages than we convert."""

    key = "too_many_pages"
    http_status = 400


class ImageTooLargeError(PrintError, ServiceValidationError):
    """The image has more pixels than we convert."""

    key = "image_too_large"
    http_status = 400


class OutputTooLargeError(PrintError, ServiceValidationError):
    """The converted document grew past the output budget."""

    key = "output_too_large"
    http_status = 413


# InvalidDocument reasons that come from the page selection, not the file.
_PAGE_SELECTION_REASONS = frozenset({"no_pages", "invalid_page_ranges"})


def sniff_format(data: bytes) -> str | None:
    """Detect the document format from the file's first bytes."""
    for magic, mime in _MAGIC:
        if data.startswith(magic):
            return mime
    return None


def max_file_bytes(entry: HomePrintConfigEntry) -> int:
    """Return the entry's upload limit in bytes."""
    return int(entry.options.get(CONF_MAX_FILE_MB, DEFAULT_MAX_FILE_MB)) * 1024 * 1024


def max_file_mb(entry: HomePrintConfigEntry) -> int:
    """Return the entry's upload limit in MB."""
    return int(entry.options.get(CONF_MAX_FILE_MB, DEFAULT_MAX_FILE_MB))


def validate_options(options: PrintOptions) -> None:
    """Raise InvalidPrintOption for values no printer could accept."""
    if not isinstance(options.copies, int) or options.copies < 1:
        raise InvalidPrintOption(option="copies")
    if options.sides not in SIDES:
        raise InvalidPrintOption(option="sides")
    if options.color_mode is not None and options.color_mode not in COLOR_MODES:
        raise InvalidPrintOption(option="color_mode")
    if options.page_ranges is not None:
        value = options.page_ranges.replace(" ", "")
        if not _PAGE_RANGES_RE.match(value):
            raise InvalidPrintOption(option="page_ranges")
        for part in value.split(","):
            low, _, high = part.partition("-")
            first, last = int(low), int(high or low)
            if first < 1 or last < first or last > MAX_PAGE_NUMBER:
                raise InvalidPrintOption(option="page_ranges")


def build_options(
    entry: HomePrintConfigEntry,
    *,
    copies: int | None = None,
    sides: str | None = None,
    color_mode: str | None = None,
    page_ranges: str | None = None,
) -> PrintOptions:
    """Build validated PrintOptions, filling gaps from the entry's defaults."""
    if sides is None:
        sides = entry.options.get(CONF_DEFAULT_SIDES) or "one-sided"
    if color_mode is None:
        color_mode = entry.options.get(CONF_DEFAULT_COLOR_MODE)
    if color_mode == COLOR_AUTO:
        color_mode = None
    options = PrintOptions(
        copies=1 if copies is None else copies,
        sides=sides,
        color_mode=color_mode,
        page_ranges=page_ranges.replace(" ", "") if page_ranges else None,
    )
    validate_options(options)
    return options


def clean_file_name(file_name: str) -> str:
    """Strip directories and control characters, keep it within IPP limits."""
    name = posixpath.basename(file_name.replace("\\", "/"))
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C").strip()
    encoded = name.encode()
    if len(encoded) > MAX_JOB_NAME_BYTES:
        name = encoded[:MAX_JOB_NAME_BYTES].decode(errors="ignore")
    return name or "document"


def _user_name(user: User | None) -> str:
    return (user.name if user and user.name else None) or DEFAULT_USER_NAME


def async_report_result(
    hass: HomeAssistant,
    entry: HomePrintConfigEntry,
    *,
    file_name: str,
    user: User | None,
    result: JobResult | None = None,
    error: PrintError | None = None,
    prepared: pipeline.PreparedJob | None = None,
) -> None:
    """Fire EVENT_JOB and update the last job. Never includes file contents."""
    user_name = _user_name(user)
    converted_to = (
        prepared.document_format if prepared and not prepared.send_page_ranges else None
    )
    hass.bus.async_fire(
        EVENT_JOB,
        {
            "entry_id": entry.entry_id,
            "file_name": file_name,
            "user_id": user.id if user else None,
            "user_name": user_name,
            "job_id": result.job_id if result else None,
            "result": "sent" if error is None else "error",
            "error": error.key if error else None,
            "converted_to": converted_to,
            "pages": prepared.page_count if prepared else None,
        },
    )
    entry.runtime_data.history.add(
        file_name=file_name,
        user=user_name,
        job_id=result.job_id if result else None,
        state="sent" if error is None else "error",
        pages=prepared.page_count if prepared else None,
        converted_to=converted_to,
        error=error.key if error else None,
    )
    entry.runtime_data.coordinator.async_set_last_job(
        LastJob(
            file_name=file_name,
            job_id=result.job_id if result else None,
            state=result.state if result else "error",
            user=user_name,
            time=dt_util.utcnow(),
        )
    )


async def async_print(
    hass: HomeAssistant,
    entry: HomePrintConfigEntry,
    data: bytes,
    *,
    file_name: str,
    options: PrintOptions,
    user: User | None,
) -> JobResult:
    """Validate and send ``data`` to the entry's printer."""
    file_name = clean_file_name(file_name)
    try:
        result, prepared = await _async_send(
            hass, entry, data, file_name, options, user
        )
    except PrintError as err:
        async_report_result(hass, entry, file_name=file_name, user=user, error=err)
        raise
    except Exception as err:
        _LOGGER.exception("Unexpected error printing %s", file_name)
        error = PrintError()
        async_report_result(hass, entry, file_name=file_name, user=user, error=error)
        raise error from err
    async_report_result(
        hass, entry, file_name=file_name, user=user, result=result, prepared=prepared
    )
    return result


async def _async_send(
    hass: HomeAssistant,
    entry: HomePrintConfigEntry,
    data: bytes,
    file_name: str,
    options: PrintOptions,
    user: User | None,
) -> tuple[JobResult, pipeline.PreparedJob]:
    if len(data) > max_file_bytes(entry):
        raise FileTooLarge(max=max_file_mb(entry))
    validate_options(options)

    document_format = sniff_format(data)
    if document_format is None:
        raise UnsupportedFileType()

    info = await _async_printer_info(entry)
    prepared = await _async_prepare(hass, data, document_format, info, options)

    try:
        result = await entry.runtime_data.client.print_job(
            prepared.data,
            document_format=prepared.document_format,
            job_name=file_name,
            user_name=_user_name(user),
            options=options,
            send_page_ranges=prepared.send_page_ranges,
            timeout=_print_timeout(prepared),
        )
    except PrintTimeout as err:
        raise PrintTimedOut() from err
    except CannotConnect as err:
        raise PrinterUnavailable() from err
    except UnsupportedOption as err:
        raise OptionNotSupportedByPrinter(option=err.name) from err
    except PrinterRejected as err:
        raise PrinterRejectedJob(status=err.status) from err
    except HomePrintError as err:
        _LOGGER.warning("Printing %s failed: %s", file_name, err)
        raise PrintError() from err
    return result, prepared


async def _async_printer_info(entry: HomePrintConfigEntry) -> PrinterInfo:
    """The printer's capabilities for conversion.

    The coordinator keeps its last data after a failed poll, so cached data
    says nothing about whether the printer is there. After a failed poll
    (or with no data at all) one quick Get-Printer-Attributes decides: if it
    fails too, give up before spending time on conversion.
    """
    coordinator = entry.runtime_data.coordinator
    if coordinator.data is not None and coordinator.last_update_success:
        return coordinator.data
    try:
        info = await entry.runtime_data.client.get_printer()
    except HomePrintError as err:
        raise PrinterUnavailable() from err
    coordinator.async_set_updated_data(info)
    return info


def _print_timeout(prepared: pipeline.PreparedJob) -> float | None:
    """Print-Job timeout: the default, plus per-page time for converted jobs."""
    if prepared.send_page_ranges or prepared.pages_sent is None:
        return None  # passthrough: the client's PRINT_TIMEOUT
    return PRINT_TIMEOUT + PRINT_TIMEOUT_PER_PAGE * prepared.pages_sent


async def _async_prepare(
    hass: HomeAssistant,
    data: bytes,
    document_format: str,
    info: PrinterInfo,
    options: PrintOptions,
) -> pipeline.PreparedJob:
    """Convert in the executor and map conversion errors to PrintErrors."""
    try:
        return await hass.async_add_executor_job(
            pipeline.prepare, data, document_format, info.capabilities, options
        )
    except NoConversionRoute as err:
        raise FormatNotSupportedByPrinter(format=document_format) from err
    except TooManyPages as err:
        raise TooManyPagesError(limit=err.limit) from err
    except OutputTooLarge as err:
        raise OutputTooLargeError(limit=err.limit_mb) from err
    except InvalidDocument as err:
        reason = str(err)
        if reason in _PAGE_SELECTION_REASONS:
            raise InvalidPrintOption(option="page_ranges") from err
        if reason == "too_large":
            raise ImageTooLargeError(limit=MAX_IMAGE_PIXELS // 1_000_000) from err
        if reason == "unsupported_format":
            raise UnsupportedFileType() from err
        raise InvalidDocumentError() from err
