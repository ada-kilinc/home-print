#!/usr/bin/env python3
"""Home Print uzaktan kontrol: kağıda bakmadan yazıcıyı ve HA'yı test eder.

Kullanım:
    python3 remote_check.py --printer HOST [--port 631] [--path /ipp/print]
        [--tls] [--ha URL --token TOKEN] [--print] [--json OUT.json]

Varsayılan olarak HİÇ baskı yapmaz. Validate-Job ile yazıcıya "bu işi
basabilir miydin?" diye sorar; yazıcı iş oluşturmaz. Gerçek baskı sadece
``--print`` ile, tek sayfalık tek bir iş olarak gönderilir.

Bağımlılıklar sadece ``pyipp==0.17.0`` ve ``aiohttp``. Home Assistant'ı ya da
``custom_components.home_print``'i import etmez; gereken küçük parçalar
``custom_components/home_print/client.py``'den kopyalandı.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import re
import socket
import struct
import sys
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp
from pyipp import IPP
from pyipp.enums import IppOperation, IppStatus, IppTag
from pyipp.exceptions import (
    IPPConnectionError,
    IPPConnectionUpgradeRequired,
    IPPError,
    IPPResponseError,
)
from pyipp.parser import parse as parse_ipp
from pyipp.tags import ATTRIBUTE_TAG_MAP

# Same as custom_components/home_print/client.py: pyipp's serializer silently
# drops attributes it has no tag for, so register the ones we send.
ATTRIBUTE_TAG_MAP.setdefault("sides", IppTag.KEYWORD)
ATTRIBUTE_TAG_MAP.setdefault("print-color-mode", IppTag.KEYWORD)
ATTRIBUTE_TAG_MAP.setdefault("page-ranges", IppTag.RANGE)

PASS = "pass"
FAIL = "fail"
SKIP = "skip"
LABELS = {PASS: "✅ GEÇTİ", FAIL: "❌ KALDI", SKIP: "⏭ ATLANDI"}

CONNECT_TIMEOUT = 5
IPP_TIMEOUT = 15
PRINT_TIMEOUT = 120
POLL_INTERVAL = 3
POLL_LIMIT = 180
HA_TIMEOUT = 10
JOB_NAME = "Home Print uzaktan test"
USER_NAME = "HomePrint"
HIDDEN = "<gizlendi>"
FORMAT_SKIP = "yazıcı bu formatı desteklemiyor — Plan 3"


# --- test documents (no Pillow needed) ---------------------------------------


def _make_pdf() -> bytes:
    """Smallest valid one-page A4 PDF with one line of text."""
    stream = b"BT /F1 24 Tf 72 720 Td (Home Print test) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def _make_png() -> bytes:
    """1x1 white RGB PNG."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\xff\xff")
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", pixels)
        + chunk(b"IEND", b"")
    )


# 8x8 white baseline JPEG (made once with Pillow, hardcoded here).
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABALDA4MChAODQ4SERATGCgaGBYWGDEjJR0oOjM9PDkz"
    "ODdASFxOQERXRTc4UG1RV19iZ2hnPk1xeXBkeFxlZ2P/2wBDARESEhgVGC8aGi9jQjhCY2NjY2Nj"
    "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2P/wAARCAAIAAgD"
    "ASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUF"
    "BAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0"
    "NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKj"
    "pKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QA"
    "HwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEE"
    "BSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZH"
    "SElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0"
    "tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD0"
    "CiiigD//2Q=="
)
PDF = _make_pdf()
PNG = _make_png()
DOCUMENTS = {"application/pdf": PDF, "image/jpeg": JPEG, "image/png": PNG}


# --- small IPP helpers ---------------------------------------------------------


class IppRange(str):
    """rangeOfInteger value (copy of ``_IppRange`` in client.py).

    pyipp's serializer can only encode strings (it calls ``.encode``), so this
    str subclass encodes itself as the two big-endian int32 of the range.
    """

    lower: int
    upper: int

    def __new__(cls, lower: int, upper: int) -> IppRange:
        obj = super().__new__(cls, f"{lower}-{upper}")
        obj.lower = lower
        obj.upper = upper
        return obj

    def encode(self, *_args: Any, **_kwargs: Any) -> bytes:  # type: ignore[override]
        return struct.pack(">ii", self.lower, self.upper)


# RFC 8011 names for the codes a printer is likely to answer with.
_STATUS_NAMES = {
    0x0000: "successful-ok",
    0x0001: "successful-ok-ignored-or-substituted-attributes",
    0x0002: "successful-ok-conflicting-attributes",
    0x0400: "client-error-bad-request",
    0x0401: "client-error-forbidden",
    0x0402: "client-error-not-authenticated",
    0x0403: "client-error-not-authorized",
    0x0404: "client-error-not-possible",
    0x0405: "client-error-timeout",
    0x0406: "client-error-not-found",
    0x0407: "client-error-gone",
    0x0408: "client-error-request-entity-too-large",
    0x0409: "client-error-request-value-too-long",
    0x040A: "client-error-document-format-not-supported",
    0x040B: "client-error-attributes-or-values-not-supported",
    0x040C: "client-error-uri-scheme-not-supported",
    0x040D: "client-error-charset-not-supported",
    0x040E: "client-error-conflicting-attributes",
    0x040F: "client-error-compression-not-supported",
    0x0410: "client-error-compression-error",
    0x0411: "client-error-document-format-error",
    0x0412: "client-error-document-access-error",
    0x0500: "server-error-internal-error",
    0x0501: "server-error-operation-not-supported",
    0x0502: "server-error-service-unavailable",
    0x0503: "server-error-version-not-supported",
    0x0504: "server-error-device-error",
    0x0505: "server-error-temporary-error",
    0x0506: "server-error-not-accepting-jobs",
    0x0507: "server-error-busy",
    0x0508: "server-error-job-canceled",
    0x0509: "server-error-multiple-document-jobs-not-supported",
}
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
_JOB_DONE = {7, 8, 9}


def status_name(code: int) -> str:
    """IPP status code -> RFC 8011 keyword."""
    if code in _STATUS_NAMES:
        return _STATUS_NAMES[code]
    try:
        name = IppStatus(code).name.lower().replace("_", "-")
    except ValueError:
        return f"0x{code:04x}"
    if 0x400 <= code < 0x500:
        return f"client-{name}"
    if code >= 0x500:
        return f"server-{name}"
    return name


def interpret_status(code: int) -> tuple[str, str]:
    """Map an IPP status code to (PASS/FAIL/SKIP, status keyword)."""
    name = status_name(code)
    if 0 <= code < 0x0100:
        return PASS, name
    if code == IppStatus.ERROR_OPERATION_NOT_SUPPORTED:
        return SKIP, name
    return FAIL, name


class IppCallError(Exception):
    """The request did not get an IPP answer (network, HTTP, parse)."""


async def ipp_call(
    ipp: IPP, operation: IppOperation, message: dict[str, Any]
) -> dict[str, Any]:
    """Send one request and return the parsed answer, whatever its status.

    ``IPP.execute`` raises on any non-ok status and throws away the response
    (and its unsupported-attributes group), so this uses ``raw`` + the parser.
    """
    try:
        raw = await ipp.raw(operation, message)
    except IPPConnectionError as err:
        cause = err.__cause__
        if isinstance(cause, (asyncio.TimeoutError, TimeoutError)):  # noqa: UP041
            raise IppCallError("zaman aşımı (yazıcı cevap vermedi)") from err
        raise IppCallError(f"bağlantı hatası: {cause or err}") from err
    except IPPConnectionUpgradeRequired as err:
        raise IppCallError("yazıcı TLS istiyor, --tls ile dene") from err
    except IPPResponseError as err:
        info = err.args[1] if len(err.args) > 1 else {}
        raise IppCallError(f"HTTP {info.get('status-code', '?')}") from err
    except IPPError as err:
        raise IppCallError(f"IPP hatası: {err}") from err
    try:
        return parse_ipp(raw)
    except Exception as err:  # noqa: BLE001 - pyipp raises struct errors etc.
        raise IppCallError(f"yazıcının cevabı okunamadı: {err}") from err


def make_ipp(
    args: argparse.Namespace, session: aiohttp.ClientSession, timeout: int
) -> IPP:
    ipp = IPP(
        host=args.printer,
        port=args.port,
        base_path=args.path,
        tls=args.tls,
        verify_ssl=False,
        session=session,
    )
    ipp.request_timeout = timeout
    return ipp


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def jsonable(value: Any) -> Any:
    """Make parsed IPP / HA values JSON serialisable."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


_SERIAL_RE = re.compile(r"(?i)\b(SN|SERN)\s*:[^;]*")


def scrub(attrs: dict[str, Any]) -> dict[str, Any]:
    """Copy of printer attributes with serial, location and uuid hidden."""
    out = jsonable(attrs)
    if isinstance(out.get("printer-device-id"), str):
        out["printer-device-id"] = _SERIAL_RE.sub(
            lambda m: f"{m.group(1)}:{HIDDEN}", out["printer-device-id"]
        )
    for key in ("printer-location", "printer-uuid", "printer-serial-number"):
        if key in out:
            out[key] = HIDDEN
    return out


# --- results -------------------------------------------------------------------


@dataclass
class Result:
    num: str
    title: str
    status: str
    detail: str = ""
    info: list[str] = field(default_factory=list)

    def line(self) -> str:
        text = f"{LABELS[self.status]}  {self.num}. {self.title}"
        return f"{text} — {self.detail}" if self.detail else text


def emit(report: dict[str, Any], *results: Result) -> None:
    for result in results:
        report["results"].append(result)
        print(result.line(), flush=True)
        for item in result.info:
            print(f"      • {item}", flush=True)


# --- 1. TCP ----------------------------------------------------------------------


async def check_tcp(host: str, port: int) -> Result:
    title = "Yazıcıya erişim (TCP)"
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), CONNECT_TIMEOUT
        )
    except (asyncio.TimeoutError, TimeoutError):  # noqa: UP041 - py3.10
        return Result(
            "1", title, FAIL, f"{host}:{port} {CONNECT_TIMEOUT} sn'de açılmadı"
        )
    except socket.gaierror as err:
        return Result("1", title, FAIL, f"{host} adı çözülemedi ({err})")
    except ConnectionRefusedError:
        return Result(
            "1", title, FAIL, f"{host}:{port} bağlantıyı reddetti (port kapalı)"
        )
    except OSError as err:
        reason = err.strerror or str(err)
        return Result("1", title, FAIL, f"{host}:{port} bağlanılamadı ({reason})")
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return Result("1", title, PASS, f"{host}:{port} açık")


# --- 2. Get-Printer-Attributes ---------------------------------------------------


async def get_printer_attributes(
    args: argparse.Namespace, session: aiohttp.ClientSession | None = None
) -> tuple[Result, dict[str, Any] | None]:
    title = "Get-Printer-Attributes"
    own = session is None
    session = session or aiohttp.ClientSession()
    try:
        response = await ipp_call(
            make_ipp(args, session, IPP_TIMEOUT),
            IppOperation.GET_PRINTER_ATTRIBUTES,
            {"operation-attributes-tag": {"requested-attributes": ["all"]}},
        )
    except IppCallError as err:
        return Result("2", title, FAIL, str(err)), None
    finally:
        if own:
            await session.close()
    code = response.get("status-code", -1)
    status, name = interpret_status(code)
    printers = response.get("printers") or []
    if status != PASS or not printers:
        return Result("2", title, FAIL, name if status != PASS else "boş cevap"), None
    attrs = printers[0]
    return Result("2", title, PASS, name, describe_printer(attrs)), attrs


def describe_printer(attrs: dict[str, Any]) -> list[str]:
    formats = _as_list(attrs.get("document-format-supported"))
    state = attrs.get("printer-state")
    names = _as_list(attrs.get("marker-names"))
    levels = _as_list(attrs.get("marker-levels"))
    colors = _as_list(attrs.get("marker-colors"))
    markers = []
    for i, name in enumerate(names):
        level = levels[i] if i < len(levels) else "?"
        color = colors[i] if i < len(colors) else "?"
        markers.append(f"{name} %{level} ({color})")

    def show(key: str) -> str:
        values = _as_list(attrs.get(key))
        return ", ".join(str(jsonable(v)) for v in values) if values else "yok"

    has = {fmt: ("var" if fmt in formats else "YOK") for fmt in DOCUMENTS}
    lines = [
        f"model: {attrs.get('printer-make-and-model', '?')}",
        f"durum: {_PRINTER_STATES.get(state, state)}; nedenler: "
        f"{show('printer-state-reasons')}",
        f"formatlar: {show('document-format-supported')}",
        "PDF: {application/pdf}, JPEG: {image/jpeg}, PNG: {image/png}".format(**has),
        f"sides-supported: {show('sides-supported')}",
        f"print-color-mode-supported: {show('print-color-mode-supported')}",
        f"page-ranges-supported: {show('page-ranges-supported')}",
        f"copies-supported: {show('copies-supported')}",
        f"mürekkep: {'; '.join(markers) if markers else 'yok'}",
        f"urf-supported: {show('urf-supported')}",
        "pwg-raster-document-resolution-supported: "
        f"{show('pwg-raster-document-resolution-supported')}",
    ]
    if "application/pdf" not in formats:
        lines.append("PDF listede yok: Plan 3'teki dönüştürme gerekecek")
    return lines


# --- 3. eSCL ----------------------------------------------------------------------


async def check_escl(host: str, tls: bool) -> list[Result]:
    title = "eSCL tarayıcı (bilgi, Plan 4)"
    urls = [f"http://{host}/eSCL/ScannerCapabilities"]
    if tls:
        urls.append(f"https://{host}/eSCL/ScannerCapabilities")
    found = []
    tried = []
    timeout = aiohttp.ClientTimeout(total=CONNECT_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for url in urls:
            try:
                async with session.get(url, ssl=False) as resp:
                    body = await resp.read()
                    if resp.status == 200 and b"ScannerCapabilities" in body:
                        found.append(url)
                    tried.append(f"{url} -> HTTP {resp.status}")
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:  # noqa: UP041
                tried.append(f"{url} -> {type(err).__name__}")
    if found:
        return [Result("3", title, PASS, "var: " + ", ".join(found))]
    return [Result("3", title, SKIP, "bulunamadı; " + "; ".join(tried))]


# --- 4. Validate-Job ---------------------------------------------------------------


def build_validate_message(
    document_format: str, job_attrs: dict[str, Any]
) -> dict[str, Any]:
    """Validate-Job request. RFC 8011 4.2.3: no document data is sent."""
    return {
        "operation-attributes-tag": {
            "requesting-user-name": USER_NAME,
            "job-name": JOB_NAME,
            "document-format": document_format,
        },
        "job-attributes-tag": dict(job_attrs),
    }


def _cases(attrs: dict[str, Any]) -> list[tuple[str, str, str, dict[str, Any], str]]:
    """(num, title, format, job attributes, skip reason or "")."""
    sides = _as_list(attrs.get("sides-supported"))
    colors = _as_list(attrs.get("print-color-mode-supported"))
    copies = _as_list(attrs.get("copies-supported"))
    pdf = "application/pdf"
    return [
        ("4a", "Validate-Job PDF varsayılan", pdf, {}, ""),
        (
            "4b",
            "Validate-Job PDF çift yüz",
            pdf,
            {"sides": "two-sided-long-edge"},
            ""
            if "two-sided-long-edge" in sides
            else "sides-supported içinde two-sided-long-edge yok",
        ),
        (
            "4c",
            "Validate-Job PDF siyah-beyaz",
            pdf,
            {"print-color-mode": "monochrome"},
            "",
        ),
        (
            "4d",
            "Validate-Job PDF renkli",
            pdf,
            {"print-color-mode": "color"},
            "" if "color" in colors else "print-color-mode-supported içinde color yok",
        ),
        (
            "4e",
            "Validate-Job PDF sayfa 1-1",
            pdf,
            {"page-ranges": [IppRange(1, 1)]},
            "" if attrs.get("page-ranges-supported") is True else "page-ranges yok",
        ),
        ("4f", "Validate-Job JPEG", "image/jpeg", {}, ""),
        ("4g", "Validate-Job PNG", "image/png", {}, ""),
        (
            "4h",
            "Validate-Job PDF 2 kopya",
            pdf,
            {"copies": 2},
            "copies-supported en fazla 1"
            if copies and isinstance(copies[-1], int) and copies[-1] < 2
            else "",
        ),
    ]


async def check_printer_jobs(
    args: argparse.Namespace,
    attrs: dict[str, Any] | None = None,
    session: aiohttp.ClientSession | None = None,
) -> list[Result]:
    own = session is None
    session = session or aiohttp.ClientSession()
    try:
        if attrs is None:
            _, attrs = await get_printer_attributes(args, session)
            if attrs is None:
                return [Result("4", "Validate-Job", SKIP, "yazıcı özellikleri yok")]
        return await _validate_all(make_ipp(args, session, IPP_TIMEOUT), attrs)
    finally:
        if own:
            await session.close()


async def _validate_all(ipp: IPP, attrs: dict[str, Any]) -> list[Result]:
    formats = _as_list(attrs.get("document-format-supported"))
    ops = _as_list(attrs.get("operations-supported"))
    results = []
    for num, title, fmt, job_attrs, skip in _cases(attrs):
        if ops and IppOperation.VALIDATE_JOB not in ops:
            results.append(Result(num, title, SKIP, "yazıcı Validate-Job bildirmiyor"))
            continue
        if skip:
            results.append(Result(num, title, SKIP, skip))
            continue
        try:
            response = await ipp_call(
                ipp, IppOperation.VALIDATE_JOB, build_validate_message(fmt, job_attrs)
            )
        except IppCallError as err:
            results.append(Result(num, title, FAIL, str(err)))
            continue
        status, name = interpret_status(response.get("status-code", -1))
        unsupported = sorted(
            {k for group in response.get("unsupported-attributes") or [] for k in group}
        )
        detail = name
        if unsupported:
            detail += f" (desteklenmeyen: {', '.join(unsupported)})"
        if status == SKIP:
            detail = f"yazıcı Validate-Job uygulamıyor ({name})"
        elif fmt not in formats:
            if status == PASS:
                detail += " (format listede yoktu ama kabul edildi)"
            else:
                status, detail = SKIP, f"{FORMAT_SKIP} ({name})"
        results.append(Result(num, title, status, detail))
    return results


# --- 5. Home Assistant ------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


async def _ha_get(
    session: aiohttp.ClientSession, url: str, token: str
) -> tuple[int, Any]:
    async with session.get(url, headers={"Authorization": f"Bearer {token}"}) as r:
        try:
            body = await r.json(content_type=None)
        except (ValueError, aiohttp.ContentTypeError):
            body = None
        return r.status, body


async def check_ha(args: argparse.Namespace, report: dict[str, Any]) -> list[Result]:
    base = args.ha.rstrip("/")
    token = args.token
    results: list[Result] = []
    ha_data: dict[str, Any] = report.setdefault("ha", {})
    timeout = aiohttp.ClientTimeout(total=HA_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            status, body = await _ha_get(session, f"{base}/api/", token)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:  # noqa: UP041
            return [Result("5a", "HA API", FAIL, f"{base} bağlanılamadı ({err})")]
        message = body.get("message") if isinstance(body, dict) else None
        if status != 200:
            hint = " (token yanlış ya da silinmiş)" if status == 401 else ""
            return [Result("5a", "HA API", FAIL, f"HTTP {status}{hint}")]
        results.append(Result("5a", "HA API", PASS, f"HTTP 200, {message!r}"))

        entries: list[dict[str, Any]] | None = None
        try:
            status, body = await _ha_get(
                session,
                f"{base}/api/config/config_entries/entry?domain=home_print",
                token,
            )
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:  # noqa: UP041
            status, body = -1, str(err)
        title = "Home Print kaydı (config entry)"
        if status == 200 and isinstance(body, list):
            entries = [e for e in body if e.get("domain", "home_print") == "home_print"]
            ha_data["entries"] = [
                {k: e.get(k) for k in ("entry_id", "title", "state")} for e in entries
            ]
            shown = ", ".join(f"{e.get('title')} ({e.get('state')})" for e in entries)
            if any(e.get("state") == "loaded" for e in entries):
                results.append(Result("5b", title, PASS, shown))
            elif entries:
                results.append(Result("5b", title, FAIL, f"yüklenmemiş: {shown}"))
            else:
                results.append(Result("5b", title, FAIL, "home_print kaydı yok"))
        else:
            results.append(
                Result(
                    "5b",
                    title,
                    SKIP,
                    f"uç nokta kullanılamadı (HTTP {status}); sadece durumlara "
                    "bakılacak",
                )
            )

        results.append(await _check_entities(session, base, token, entries, ha_data))

        loaded = [e for e in entries or [] if e.get("state") == "loaded"]
        entry_id = loaded[0]["entry_id"] if loaded else None
        results.extend(await _check_upload(session, base, token, entry_id))
    return results


async def _check_entities(
    session: aiohttp.ClientSession,
    base: str,
    token: str,
    entries: list[dict[str, Any]] | None,
    ha_data: dict[str, Any],
) -> Result:
    title = "Home Print varlıkları"
    ids: set[str] | None = None
    try:
        async with session.post(
            f"{base}/api/template",
            headers={"Authorization": f"Bearer {token}"},
            json={"template": "{{ integration_entities('home_print') | tojson }}"},
        ) as r:
            if r.status == 200:
                ids = set(json.loads(await r.text()))
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError):  # noqa: UP041
        ids = None
    try:
        status, states = await _ha_get(session, f"{base}/api/states", token)
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:  # noqa: UP041
        return Result("5c", title, FAIL, f"/api/states okunamadı ({err})")
    if status != 200 or not isinstance(states, list):
        return Result("5c", title, FAIL, f"/api/states HTTP {status}")

    if ids is None:
        slugs = [_slug(e.get("title") or "") for e in entries or []]
        slugs = [s for s in slugs if s]

        def ours(entity_id: str) -> bool:
            domain, _, obj = entity_id.partition(".")
            if "home_print" in entity_id:
                return True
            return domain in ("sensor", "binary_sensor") and any(
                obj.startswith(s) for s in slugs
            )

        found = [s for s in states if ours(s["entity_id"])]
        how = "tahmin (entity_id)"
    else:
        found = [s for s in states if s["entity_id"] in ids]
        how = "integration_entities"
    ha_data["entities"] = [
        {
            "entity_id": s["entity_id"],
            "state": s.get("state"),
            "attributes": jsonable(s.get("attributes", {})),
        }
        for s in found
    ]
    if not found:
        return Result("5c", title, FAIL, f"hiç varlık bulunamadı ({how})")
    info = []
    for s in found:
        attrs = s.get("attributes", {})
        if attrs.get("options") == ["idle", "processing", "stopped"]:
            info.append(f"durum: {s['entity_id']} = {s.get('state')}")
        elif attrs.get("unit_of_measurement") == "%":
            name = attrs.get("friendly_name", s["entity_id"])
            info.append(f"mürekkep: {name} = %{s.get('state')}")
        else:
            info.append(f"{s['entity_id']} = {s.get('state')}")
    return Result("5c", title, PASS, f"{len(found)} varlık ({how})", info)


async def _check_upload(
    session: aiohttp.ClientSession, base: str, token: str, entry_id: str | None
) -> list[Result]:
    results = []
    url = f"{base}/api/home_print/upload/{entry_id or 'kontrol'}"
    title = "Yükleme ucu token'sız reddediyor"
    try:
        async with session.post(url, data=b"") as r:
            status = r.status
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:  # noqa: UP041
        results.append(Result("5d", title, FAIL, f"istek gitmedi ({err})"))
    else:
        results.append(
            Result("5d", title, PASS if status == 401 else FAIL, f"HTTP {status}")
        )

    title = "Yükleme ucu dosyasız isteği reddediyor"
    if entry_id is None:
        results.append(Result("5e", title, SKIP, "yüklü bir home_print kaydı yok"))
        return results
    try:
        async with session.post(
            url, headers={"Authorization": f"Bearer {token}"}, data=b""
        ) as r:
            status = r.status
            body = await r.text()
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:  # noqa: UP041
        results.append(Result("5e", title, FAIL, f"istek gitmedi ({err})"))
        return results
    if status == 400:
        results.append(Result("5e", title, PASS, f"HTTP 400 {body[:80]}"))
    elif status == 403:
        results.append(
            Result("5e", title, SKIP, "HTTP 403: sadece yöneticiler yazdırabilir açık")
        )
    else:
        results.append(Result("5e", title, FAIL, f"HTTP {status} {body[:80]}"))
    return results


# --- 6. real print ------------------------------------------------------------------


async def print_test_page(
    args: argparse.Namespace, attrs: dict[str, Any], session: aiohttp.ClientSession
) -> Result:
    title = "Gerçek baskı (tek sayfa)"
    formats = _as_list(attrs.get("document-format-supported"))
    fmt = next((f for f in DOCUMENTS if f in formats), None)
    if fmt is None:
        return Result("6", title, SKIP, "yazıcı PDF/JPEG/PNG kabul etmiyor — Plan 3")
    print(
        f"⚠️  DİKKAT: --print verildi. Yazıcıya TEK sayfalık gerçek bir iş "
        f"gönderiliyor ({fmt}, '{JOB_NAME}').",
        flush=True,
    )
    try:
        response = await ipp_call(
            make_ipp(args, session, PRINT_TIMEOUT),
            IppOperation.PRINT_JOB,
            {
                "operation-attributes-tag": {
                    "requesting-user-name": USER_NAME,
                    "job-name": JOB_NAME,
                    "document-format": fmt,
                },
                "data": DOCUMENTS[fmt],
            },
        )
    except IppCallError as err:
        return Result(
            "6",
            title,
            FAIL,
            f"Print-Job: {err}. İş yine de gitmiş olabilir; tekrar çalıştırmadan "
            "önce yazıcının durumuna bak",
        )
    status, name = interpret_status(response.get("status-code", -1))
    job = next(iter(response.get("jobs") or []), {})
    if status != PASS or "job-id" not in job:
        return Result("6", title, FAIL, f"Print-Job reddedildi: {name}")
    job_id = int(job["job-id"])
    print(f"      • iş numarası {job_id}, bitmesi bekleniyor (en fazla 180 sn)")

    ipp = make_ipp(args, session, IPP_TIMEOUT)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + POLL_LIMIT
    last: dict[str, Any] = job
    while True:
        try:
            resp = await ipp_call(
                ipp,
                IppOperation.GET_JOB_ATTRIBUTES,
                {
                    "operation-attributes-tag": {
                        "job-id": job_id,
                        "requested-attributes": [
                            "job-state",
                            "job-state-reasons",
                            "job-impressions-completed",
                            "job-media-sheets-completed",
                        ],
                    }
                },
            )
            last = next(iter(resp.get("jobs") or []), last)
        except IppCallError as err:
            print(f"      • Get-Job-Attributes: {err}", flush=True)
        state = int(last.get("job-state", 3))
        if state in _JOB_DONE or loop.time() >= deadline:
            break
        await asyncio.sleep(POLL_INTERVAL)

    detail = (
        f"iş {job_id}: {_JOB_STATES.get(state, state)}; nedenler: "
        f"{', '.join(map(str, _as_list(last.get('job-state-reasons')))) or '-'}; "
        f"impressions: {last.get('job-impressions-completed', '?')}, "
        f"sheets: {last.get('job-media-sheets-completed', '?')}"
    )
    if state not in _JOB_DONE:
        detail += f" ({POLL_LIMIT} sn içinde bitmedi)"
    return Result("6", title, PASS if state == 9 else FAIL, detail)


# --- main --------------------------------------------------------------------------


async def run(args: argparse.Namespace) -> int:
    report: dict[str, Any] = {"results": [], "printer_attributes": None, "ha": {}}
    attrs: dict[str, Any] | None = None
    unreachable = "yazıcıya erişilemedi"

    tcp = await check_tcp(args.printer, args.port)
    emit(report, tcp)
    async with aiohttp.ClientSession() as session:
        if tcp.status == PASS:
            gpa, attrs = await get_printer_attributes(args, session)
        else:
            gpa = Result("2", "Get-Printer-Attributes", SKIP, unreachable)
        emit(report, gpa)
        emit(report, *await check_escl(args.printer, args.tls))
        if attrs is not None:
            report["printer_attributes"] = scrub(attrs)
            emit(report, *await check_printer_jobs(args, attrs, session))
        else:
            emit(report, Result("4", "Validate-Job", SKIP, unreachable))

        if args.ha and args.token:
            emit(report, *await check_ha(args, report))
        else:
            emit(report, Result("5", "Home Assistant", SKIP, "--ha ve --token yok"))

        if not args.print:
            emit(report, Result("6", "Gerçek baskı", SKIP, "--print verilmedi"))
        elif attrs is None:
            emit(report, Result("6", "Gerçek baskı", SKIP, unreachable))
        else:
            emit(report, await print_test_page(args, attrs, session))

    counts = {s: sum(r.status == s for r in report["results"]) for s in LABELS}
    print(
        f"\nÖzet: {counts[PASS]} geçti, {counts[FAIL]} kaldı, {counts[SKIP]} atlandı",
        flush=True,
    )
    if args.json:
        write_json(args, report)
    return 1 if counts[FAIL] else 0


def write_json(args: argparse.Namespace, report: dict[str, Any]) -> None:
    data = {
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "args": {
            "printer": args.printer,
            "port": args.port,
            "path": args.path,
            "tls": args.tls,
            "ha": args.ha,
            "print": args.print,
        },
        "results": [asdict(r) for r in report["results"]],
        "printer_attributes": report["printer_attributes"],
        "ha": report.get("ha", {}),
    }
    path = Path(args.json).expanduser()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"JSON yazıldı: {path}", flush=True)


class _TurkishHelp(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):  # noqa: ANN001
        super().add_usage(usage, actions, groups, prefix or "kullanım: ")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="remote_check.py",
        description=(
            "Home Print uzaktan kontrol. Yazıcıyı ve Home Assistant'ı ağ "
            "üzerinden test eder; varsayılan olarak hiçbir şey basmaz."
        ),
        epilog="Çıkış kodu: hiç ❌ yoksa 0, varsa 1.",
        formatter_class=_TurkishHelp,
        add_help=False,
    )
    p._optionals.title = "seçenekler"
    p.add_argument("-h", "--help", action="help", help="bu yardımı göster ve çık")
    p.add_argument("--printer", required=True, metavar="HOST", help="yazıcının IP'si")
    p.add_argument("--port", type=int, default=631, help="IPP portu (varsayılan 631)")
    p.add_argument(
        "--path", default="/ipp/print", help="IPP yolu (varsayılan /ipp/print)"
    )
    p.add_argument("--tls", action="store_true", help="ipps (TLS) kullan")
    p.add_argument("--ha", metavar="URL", help="HA adresi, örn. http://100.x.y.z:8123")
    p.add_argument("--token", help="HA uzun ömürlü erişim token'ı")
    p.add_argument(
        "--print",
        action="store_true",
        help="GERÇEKTEN tek sayfa bas (yoksa hiç baskı yapılmaz)",
    )
    p.add_argument(
        "--json", metavar="OUT.json", help="sonuçları JSON dosyasına yaz (gizlenmiş)"
    )
    return p.parse_args(argv)


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    sys.exit(main())
