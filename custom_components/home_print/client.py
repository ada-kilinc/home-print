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
from pyipp.parser import parse_ieee1284_device_id
from pyipp.tags import ATTRIBUTE_TAG_MAP

from .models import (
    Capabilities,
    JobResult,
    Marker,
    PrinterInfo,
    PrintOptions,
    normalize_uuid,
)

# pyipp's serializer silently drops attributes it has no tag for.
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
]

_PRINTER_STATES = {3: "idle", 4: "processing", 5: "stopped"}
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


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _marker_level(value: Any) -> int | None:
    if isinstance(value, int) and 0 <= value <= 100:
        return value
    return None


def parse_printer(data: dict[str, Any]) -> PrinterInfo:
    """Build PrinterInfo from one pyipp-parsed ``printers`` entry."""
    names = _as_list(data.get("marker-names"))
    colors = _as_list(data.get("marker-colors"))
    levels = _as_list(data.get("marker-levels"))
    kinds = _as_list(data.get("marker-types"))
    markers = tuple(
        Marker(
            name=name,
            color=(colors[i] if i < len(colors) and colors[i] != "none" else None),
            level=_marker_level(levels[i]) if i < len(levels) else None,
            kind=kinds[i] if i < len(kinds) else "unknown",
        )
        for i, name in enumerate(names)
    )

    try:
        serial = parse_ieee1284_device_id(data.get("printer-device-id", "")).get("SN")
    except ValueError:
        serial = None

    copies = _as_list(data.get("copies-supported"))
    capabilities = Capabilities(
        document_formats=frozenset(_as_list(data.get("document-format-supported"))),
        sides=frozenset(_as_list(data.get("sides-supported"))),
        color_modes=frozenset(_as_list(data.get("print-color-mode-supported"))),
        copies_max=int(copies[-1]) if copies else 1,
        page_ranges=bool(data.get("page-ranges-supported", False)),
    )
    return PrinterInfo(
        uuid=normalize_uuid(str(data.get("printer-uuid", ""))),
        make_model=data.get("printer-make-and-model", ""),
        serial=serial or None,
        state=_PRINTER_STATES.get(int(data.get("printer-state", 3)), "idle"),
        state_reasons=tuple(_as_list(data.get("printer-state-reasons"))),
        markers=markers,
        capabilities=capabilities,
    )


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
        self._ipp = IPP(
            host=host,
            port=port,
            base_path=base_path,
            tls=tls,
            verify_ssl=verify_ssl,
            session=session,
        )

    async def _execute(
        self, operation: IppOperation, message: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            return await self._ipp.execute(operation, message)
        except (IPPConnectionError, IPPConnectionUpgradeRequired) as err:
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
    ) -> JobResult:
        """Submit a Print-Job after validating options against capabilities."""
        caps = (await self.get_printer()).capabilities
        if options.page_ranges and not caps.page_ranges:
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
        if options.page_ranges:
            job_attrs["page-ranges"] = _parse_page_ranges(options.page_ranges)

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
        )
        job = next(iter(response.get("jobs") or []), {})
        if "job-id" not in job:
            raise HomePrintError("Printer did not return a job id")
        return JobResult(
            job_id=int(job["job-id"]),
            state=_JOB_STATES.get(int(job.get("job-state", 3)), "pending"),
        )
