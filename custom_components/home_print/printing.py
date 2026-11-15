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

from .client import CannotConnect, HomePrintError, PrinterRejected, UnsupportedOption
from .const import (
    CONF_DEFAULT_COLOR_MODE,
    CONF_DEFAULT_SIDES,
    CONF_MAX_FILE_MB,
    DEFAULT_MAX_FILE_MB,
    DOMAIN,
    EVENT_JOB,
)
from .models import JobResult, LastJob, PrintOptions

if TYPE_CHECKING:
    from . import HomePrintConfigEntry

_LOGGER = logging.getLogger(__name__)

SIDES = ("one-sided", "two-sided-long-edge", "two-sided-short-edge")
COLOR_MODES = ("auto", "color", "monochrome")
COLOR_AUTO = "auto"  # printer default: send no print-color-mode
DEFAULT_USER_NAME = "Home Assistant"
MAX_JOB_NAME_BYTES = 255  # IPP name(MAX)

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


class InvalidPrintOption(PrintError, ServiceValidationError):
    """A print option has an invalid value."""

    key = "invalid_option"
    http_status = 400


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
            if int(low) < 1 or int(high or low) < int(low):
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
) -> None:
    """Fire EVENT_JOB and update the last job. Never includes file contents."""
    user_name = _user_name(user)
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
        },
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
        result = await _async_send(hass, entry, data, file_name, options, user)
    except PrintError as err:
        async_report_result(hass, entry, file_name=file_name, user=user, error=err)
        raise
    async_report_result(hass, entry, file_name=file_name, user=user, result=result)
    return result


async def _async_send(
    hass: HomeAssistant,
    entry: HomePrintConfigEntry,
    data: bytes,
    file_name: str,
    options: PrintOptions,
    user: User | None,
) -> JobResult:
    if len(data) > max_file_bytes(entry):
        raise FileTooLarge(max=max_file_mb(entry))
    validate_options(options)

    document_format = sniff_format(data)
    if document_format is None:
        raise UnsupportedFileType()

    # When the printer is offline there is nothing to check against; the
    # client call below then surfaces CannotConnect.
    coordinator = entry.runtime_data.coordinator
    info = coordinator.data
    if info is not None and coordinator.last_update_success:
        formats = info.capabilities.document_formats
        if formats and document_format not in formats:
            raise FormatNotSupportedByPrinter(format=document_format)

    try:
        return await entry.runtime_data.client.print_job(
            data,
            document_format=document_format,
            job_name=file_name,
            user_name=_user_name(user),
            options=options,
        )
    except CannotConnect as err:
        raise PrinterUnavailable() from err
    except UnsupportedOption as err:
        raise OptionNotSupportedByPrinter(option=err.name) from err
    except PrinterRejected as err:
        raise PrinterRejectedJob(status=err.status) from err
    except HomePrintError as err:
        _LOGGER.warning("Printing %s failed: %s", file_name, err)
        raise PrintError() from err
