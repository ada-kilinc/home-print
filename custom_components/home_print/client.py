"""Thin IPP client used by every other Home Print module."""

from __future__ import annotations

import struct
from typing import Any

import aiohttp
from pyipp import IPP
from pyipp.enums import IppOperation, IppStatus, IppTag
from pyipp.exceptions import (
    IPPConnectionError,
    IPPConnectionUpgradeRequired,
    IPPError,
    IPPParseError,
    IPPResponseError,
)
from pyipp.tags import ATTRIBUTE_TAG_MAP

from .const import PRINT_TIMEOUT
from .ipp_parse import parse_printer
from .models import JobResult, PrinterInfo, PrintOptions

# pyipp's serializer silently drops attributes it has no tag for.
# This mutates pyipp's module-level map, so it is process-wide; that is
# intentional and additive (setdefault never overrides an existing tag).
ATTRIBUTE_TAG_MAP.setdefault("sides", IppTag.KEYWORD)
ATTRIBUTE_TAG_MAP.setdefault("print-color-mode", IppTag.KEYWORD)
ATTRIBUTE_TAG_MAP.setdefault("page-ranges", IppTag.RANGE)

REQUESTED_ATTRIBUTES = [
    "printer-uuid",
    "printer-make-and-model",
    "printer-device-id",
    "printer-state",
    "printer-state-reasons",
    "marker-names",
    "marker-colors",
    "marker-levels",
    "marker-types",
    "document-format-supported",
    "sides-supported",
    "print-color-mode-supported",
    "copies-supported",
    "page-ranges-supported",
    "pwg-raster-document-type-supported",
    "pwg-raster-document-resolution-supported",
    "pwg-raster-document-sheet-back",
    "urf-supported",
    "media-default",
    "media-col-default",
    "jpeg-x-dimension-supported",
    "jpeg-y-dimension-supported",
    "jpeg-k-octets-supported",
]

_JOB_STATES = {
    3: "pending",
    4: "held",
    5: "processing",
    6: "stopped",
    7: "canceled",
    8: "aborted",
    9: "completed",
}


class HomePrintError(Exception):
    """Base error for Home Print."""


class CannotConnect(HomePrintError):
    """The printer could not be reached."""


class PrintTimeout(HomePrintError):
    """The Print-Job request timed out after it was sent.

    The printer answered Get-Printer-Attributes just before, so the job may
    still have been received and printed.
    """


class PrinterRejected(HomePrintError):
    """The printer answered with an IPP error status."""

    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


class UnsupportedOption(HomePrintError):
    """A requested print option is not supported by the printer."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


class _IppRange(str):
    """rangeOfInteger value.

    pyipp's serializer can only encode strings (it calls ``.encode``), so this
    str subclass encodes itself as the two big-endian int32 of the range.
    """

    lower: int
    upper: int

    def __new__(cls, lower: int, upper: int) -> _IppRange:
        obj = super().__new__(cls, f"{lower}-{upper}" if lower != upper else str(lower))
        obj.lower = lower
        obj.upper = upper
        return obj

    def encode(self, *_args: Any, **_kwargs: Any) -> bytes:  # type: ignore[override]
        return struct.pack(">ii", self.lower, self.upper)


def _parse_page_ranges(value: str) -> list[_IppRange]:
    ranges = []
    try:
        for part in value.split(","):
            lo, _, hi = part.strip().partition("-")
            low, high = int(lo), int(hi or lo)
            if low < 1 or high < low:
                raise ValueError
            ranges.append(_IppRange(low, high))
    except ValueError:
        raise ValueError(f"Invalid page range: {value!r}") from None
    return ranges


def _status_name(code: int) -> str:
    try:
        name = IppStatus(code).name.lower().replace("_", "-")
    except ValueError:
        return f"0x{code:04x}"
    if 0x400 <= code < 0x500:
        return f"client-{name}"
    if code >= 0x500:
        return f"server-{name}"
    return name


class HomePrintClient:
    """Async IPP client for one printer."""

    def __init__(
        self,
        host: str,
        port: int,
        base_path: str,
        tls: bool,
        verify_ssl: bool,
        session: aiohttp.ClientSession,
    ) -> None:
        def ipp(request_timeout: int | None = None) -> IPP:
            client = IPP(
                host=host,
                port=port,
                base_path=base_path,
                tls=tls,
                verify_ssl=verify_ssl,
                session=session,
            )
            if request_timeout is not None:
                client.request_timeout = request_timeout
            return client

        # Status polls keep pyipp's short default timeout; the Print-Job
        # timeout covers the whole upload, so it gets its own long one.
        self._ipp = ipp()
        self._print_ipp = ipp(PRINT_TIMEOUT)

    async def _execute(
        self, operation: IppOperation, message: dict[str, Any], ipp: IPP | None = None
    ) -> dict[str, Any]:
        try:
            return await (ipp or self._ipp).execute(operation, message)
        except IPPConnectionError as err:
            if ipp is self._print_ipp and isinstance(err.__cause__, TimeoutError):
                raise PrintTimeout(str(err)) from err
            raise CannotConnect(str(err)) from err
        except IPPConnectionUpgradeRequired as err:
            raise CannotConnect(str(err)) from err
        except IPPResponseError as err:
            status = err.args[1].get("status-code") if len(err.args) > 1 else None
            raise PrinterRejected(f"http-{status}") from err
        except IPPParseError as err:
            raise HomePrintError("Invalid response from printer") from err
        except IPPError as err:
            code = err.args[1].get("status-code") if len(err.args) > 1 else None
            if code is None:
                raise HomePrintError(str(err)) from err
            raise PrinterRejected(_status_name(code)) from err

    async def get_printer(self) -> PrinterInfo:
        """Fetch identity, state, supplies and capabilities."""
        response = await self._execute(
            IppOperation.GET_PRINTER_ATTRIBUTES,
            {
                "operation-attributes-tag": {
                    "requested-attributes": REQUESTED_ATTRIBUTES
                }
            },
        )
        printers = response.get("printers") or []
        if not printers:
            raise HomePrintError("Printer returned no attributes")
        return parse_printer(printers[0])

    async def print_job(
        self,
        data: bytes,
        *,
        document_format: str,
        job_name: str,
        user_name: str,
        options: PrintOptions,
        send_page_ranges: bool = True,
    ) -> JobResult:
        """Submit a Print-Job after validating options against capabilities.

        ``send_page_ranges=False`` is for converted jobs, whose data already
        holds only the selected pages: ``page-ranges`` is then neither checked
        nor sent.
        """
        caps = (await self.get_printer()).capabilities
        page_ranges = options.page_ranges if send_page_ranges else None
        if page_ranges and not caps.page_ranges:
            raise UnsupportedOption("page_ranges")
        if caps.sides and options.sides not in caps.sides:
            raise UnsupportedOption("sides")
        if options.color_mode and options.color_mode not in caps.color_modes:
            raise UnsupportedOption("color_mode")
        if options.copies > caps.copies_max:
            raise UnsupportedOption("copies")

        job_attrs: dict[str, Any] = {"copies": options.copies, "sides": options.sides}
        if options.color_mode:
            job_attrs["print-color-mode"] = options.color_mode
        if page_ranges:
            job_attrs["page-ranges"] = _parse_page_ranges(page_ranges)

        response = await self._execute(
            IppOperation.PRINT_JOB,
            {
                "operation-attributes-tag": {
                    "document-format": document_format,
                    "job-name": job_name,
                    "requesting-user-name": user_name,
                },
                "job-attributes-tag": job_attrs,
                "data": data,
            },
            self._print_ipp,
        )
        job = next(iter(response.get("jobs") or []), {})
        if "job-id" not in job:
            raise HomePrintError("Printer did not return a job id")
        return JobResult(
            job_id=int(job["job-id"]),
            state=_JOB_STATES.get(int(job.get("job-state", 3)), "pending"),
        )
