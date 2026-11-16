#!/usr/bin/env python3
"""Home Print uzaktan kontrol: kağıda bakmadan yazıcıyı ve HA'yı test eder.

Kullanım:
    python3 scripts/remote_check.py --printer HOST [--port 631] [--path /ipp/print]
        [--tls] [--ha URL --token TOKEN] [--print] [--json OUT.json]
    python3 scripts/remote_check.py --printer HOST --scan-info [--scan]

Varsayılan olarak HİÇ baskı yapmaz. Validate-Job ile yazıcıya "bu işi
basabilir miydin?" diye sorar; yazıcı iş oluşturmaz. Örnek bir PDF'i
bilgisayarda dönüştürüp sayfalarını sayar, yazıcıya göndermez. Gerçek baskı
sadece ``--print`` ile: 2 iş, en fazla 2 kağıt (önce çift yüzlü dönüştürülmüş
PDF, sonra JPEG tek sayfa; JPEG sadece PDF'in 1 kağıt kullandığı kesinse gider).

Tarayıcı kontrolü: ``--scan-info`` yazıcının adresinde eSCL tarayıcıyı bulur,
yeteneklerini yazdırır, ham XML'i ``escl_capabilities.xml`` ve
``escl_status.xml`` olarak kaydeder (``--json`` verilmişse onun klasörüne,
yoksa bulunduğun klasöre). Kağıt harcamaz. Bu kipte yazıcı (IPP) kontrolleri
çalışmaz; ``--json`` yalnızca çıktı klasörünü belirler, ``--ha``/``--token``
yok sayılır. Kaydedilen XML cihaz kimlikleri (seri no, UUID) içerir, herkese
açık yerde paylaşma. ``--scan`` ek olarak camdan 75 dpi gri tek sayfa tarar ve
``scan_test.jpg`` kaydeder; ScanJobs durum kodunu, ham ``Location``
başlığını, her NextDocument durum kodunu ve yönlendirmelerden sonraki son
adresi yazdırır (HP tuhaflıkları için). ``--print`` ile birlikte kullanılamaz.

Bağımlılıklar: ``pyipp==0.17.0 aiohttp pypdfium2==5.15.2 Pillow==12.0.0
numpy==2.3.2``. Repo içinden çalıştırılır (``scripts/`` ile
``custom_components/`` yan yana): dönüştürme kodu (``models.py``,
``ipp_parse.py``, ``convert/``) dosya yolundan, ``home_print_standalone`` adlı
sahte bir paket olarak yüklenir. Home Assistant'ı ve integration'ın
``__init__.py``'sini hiç çalıştırmaz. Dönüştürme yüklenemezse (dosyalar yok ya
da paket eksik) ilgili kontroller ATLANDI olur, JPEG baskısı yine çalışır.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import importlib
import importlib.machinery
import importlib.util
import io
import json
import re
import socket
import struct
import sys
import time
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:
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
except ImportError as _missing:  # clean message instead of a traceback
    sys.stderr.write(
        f"❌ {_missing.name or _missing} yüklü değil. Sanal ortama kur:\n"
        "  ~/homeprint-venv/bin/pip install pyipp==0.17.0 aiohttp "
        "pypdfium2==5.15.2 Pillow==12.0.0 numpy==2.3.2\n"
        "(Python 3.11 ya da üstü lazım; ayrıntı: docs/testing/plan-1-manual.md)\n"
    )
    raise SystemExit(1) from None

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
IDLE_WAIT = 60
JOB_NAME = "Home Print uzaktan test"
# Sent in this order: the duplex PDF (7b) first, then the JPEG (7a).
JOB_NAME_1 = "Home Print test 1/2 — PDF çift taraf"
JOB_NAME_2 = "Home Print test 2/2 — JPEG"
USER_NAME = "HomePrint"
HIDDEN = "<gizlendi>"
FORMAT_SKIP = "yazıcı bu formatı desteklemiyor — Plan 3"
MAX_SHEETS = 2  # --print never uses more paper than this
PDF_FMT = "application/pdf"
JPEG_FMT = "image/jpeg"
PWG_FMT = "image/pwg-raster"
URF_FMT = "image/urf"
LONG_EDGE = "two-sided-long-edge"

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_DIR = REPO_ROOT / "custom_components" / "home_print"
STANDALONE = "home_print_standalone"
CONVERT_MISSING = "convert modülleri bulunamadı"
PIP_HINT = (
    "pip install pyipp==0.17.0 aiohttp pypdfium2==5.15.2 Pillow==12.0.0 numpy==2.3.2"
)
_NEEDED_FILES = (
    "models.py",
    "ipp_parse.py",
    "convert/__init__.py",
    "convert/errors.py",
    "convert/render.py",
    "convert/pwg.py",
    "convert/urf.py",
    "convert/pipeline.py",
)


# --- conversion code, loaded from the repo without Home Assistant -------------


@dataclass
class Convert:
    """The integration's pure modules, loaded as ``home_print_standalone``."""

    models: Any
    ipp_parse: Any
    pipeline: Any

    def capabilities(self, attrs: dict[str, Any]) -> Any:
        """Same parsing as the integration (``ipp_parse.parse_printer``)."""
        return self.ipp_parse.parse_printer(attrs).capabilities

    def options(self, **kwargs: Any) -> Any:
        return self.models.PrintOptions(**kwargs)

    def safe_capabilities(self, attrs: dict[str, Any]) -> tuple[Any, str]:
        """(caps, "") or (None, reason): odd attributes must not crash the run."""
        try:
            return self.capabilities(attrs), ""
        except Exception as err:  # noqa: BLE001 - report, never crash
            return None, f"yazıcı özellikleri okunamadı: {type(err).__name__}: {err}"


def _purge_standalone() -> None:
    for name in list(sys.modules):
        if name == STANDALONE or name.startswith(STANDALONE + "."):
            del sys.modules[name]


def load_convert(pkg_dir: Path | None = None) -> tuple[Convert | None, str]:
    """Load models/ipp_parse/convert from ``pkg_dir`` as a synthetic package.

    The package module is created by hand (no loader), so
    ``custom_components/home_print/__init__.py`` — which imports Home
    Assistant — never runs, while ``from ..models import X`` inside
    ``convert/`` still resolves. Returns ``(None, reason)`` on any problem.
    """
    pkg_dir = Path(PKG_DIR if pkg_dir is None else pkg_dir)
    missing = [name for name in _NEEDED_FILES if not (pkg_dir / name).is_file()]
    if missing:
        return None, (
            f"{CONVERT_MISSING} ({pkg_dir}); betiği repo içinden çalıştır "
            "(scripts/ ile custom_components/ yan yana)"
        )
    _purge_standalone()
    spec = importlib.machinery.ModuleSpec(STANDALONE, None, is_package=True)
    spec.submodule_search_locations = [str(pkg_dir)]
    sys.modules[STANDALONE] = importlib.util.module_from_spec(spec)
    try:
        models = importlib.import_module(f"{STANDALONE}.models")
        ipp_parse = importlib.import_module(f"{STANDALONE}.ipp_parse")
        pipeline = importlib.import_module(f"{STANDALONE}.convert.pipeline")
    except ModuleNotFoundError as err:
        _purge_standalone()
        if (err.name or "").startswith(STANDALONE):
            return None, f"{CONVERT_MISSING} ({err.name})"
        return None, f"{err.name} yüklü değil; şunu çalıştır: {PIP_HINT}"
    except Exception as err:  # noqa: BLE001 - report, never crash
        _purge_standalone()
        return None, f"convert modülleri yüklenemedi: {type(err).__name__}: {err}"
    return Convert(models, ipp_parse, pipeline), ""


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


# --- sample pages for the real prints (Pillow) ----------------------------------

_FONT_FILES = (
    "Arial Unicode.ttf",
    "Arial.ttf",
    "Helvetica.ttc",
    "DejaVuSans.ttf",
    "LiberationSans-Regular.ttf",
)
_A4_150DPI = (1240, 1754)
_MISSING_CHAR = "\U0010fffd"


def _font(size: int) -> Any:
    from PIL import ImageFont

    for name in _FONT_FILES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - Pillow without FreeType
        return ImageFont.load_default()


def _glyph(font: Any, char: str) -> tuple[Any, bytes]:
    from PIL import Image, ImageDraw

    box = font.getbbox(char)
    image = Image.new("L", (max(box[2], 1) + 2, max(box[3], 1) + 2), 0)
    ImageDraw.Draw(image).text((0, 0), char, font=font, fill=255)
    return image.size, image.tobytes()


def _shown(font: Any, text: str, fallback: str) -> str:
    """``text`` if the font has every glyph, else the ASCII ``fallback``."""
    try:
        missing = _glyph(font, _MISSING_CHAR)
        if any(_glyph(font, c) == missing for c in set(text) - {" "}):
            return fallback
    except Exception:  # noqa: BLE001 - bitmap fonts raise on non-latin-1
        return fallback
    return text


def sample_page(lines: list[tuple[str, str, int]]) -> Any:
    """A4 page at 150 dpi: ``↑ ÜST`` on top, then big centered lines.

    ``lines`` is (text, ASCII fallback, font size) per line.
    """
    from PIL import Image, ImageDraw

    width, height = _A4_150DPI
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, width - 41, height - 41), outline="black", width=6)
    rows = [("↑ ÜST", "^ UST", 130), *lines]
    y = 120
    for index, (text, fallback, size) in enumerate(rows):
        font = _font(size)
        shown = _shown(font, text, fallback)
        box = draw.textbbox((0, 0), shown, font=font)
        draw.text(((width - (box[2] - box[0])) // 2, y), shown, font=font, fill="black")
        y += (box[3] - box[1]) + (420 if index == 0 else 80)
    return image


def sample_jpeg() -> bytes:
    """The page for print 2/2; the tiny white JPEG if Pillow is missing."""
    try:
        page = sample_page(
            [("Home Print test", "Home Print test", 120), ("2/2", "2/2", 260)]
        )
    except ImportError:
        return JPEG
    out = io.BytesIO()
    page.save(out, "JPEG", quality=85)
    return out.getvalue()


def sample_pdf(pages: list[list[tuple[str, str, int]]]) -> bytes:
    """A PDF with one :func:`sample_page` per entry (needs Pillow)."""
    images = [sample_page(lines) for lines in pages]
    out = io.BytesIO()
    images[0].save(
        out, "PDF", resolution=150.0, save_all=True, append_images=images[1:]
    )
    return out.getvalue()


def duplex_test_pdf(*, front_only: bool = False) -> bytes:
    """The pages of print 1/2: front and back of one sheet (or just front)."""
    pages = [
        [
            ("Home Print test", "Home Print test", 120),
            ("1/2 — ön yüz", "1/2 - ON YUZ", 150),
        ],
        [
            ("Home Print test", "Home Print test", 120),
            ("1/2 — arka yüz", "1/2 - ARKA YUZ", 150),
        ],
    ]
    return sample_pdf(pages[:1] if front_only else pages)


def conversion_test_pdf(count: int = 3) -> bytes:
    """``count`` pages for the no-print conversion check."""
    return sample_pdf(
        [
            [
                ("Dönüştürme testi", "Donusturme testi", 110),
                (f"{n}/{count}", f"{n}/{count}", 260),
            ]
            for n in range(1, count + 1)
        ]
    )


# --- count pages in converted output -------------------------------------------

_PWG_SYNC = b"RaS2"
_PWG_HEADER = 1796
_URF_MAGIC = b"UNIRAST\0"
_URF_HEADER = 32


def _skip_bitmap(
    data: bytes, pos: int, width: int, height: int, bpp: int, *, urf: bool
) -> int:
    """Walk one compressed page (PWG 5102.4 4.4 / URF), return the end offset."""
    y = 0
    while y < height:
        repeat = data[pos] + 1
        pos += 1
        x = 0
        while x < width:
            code = data[pos]
            pos += 1
            if code == 128:
                if not urf:
                    raise ValueError("PWG'de tanımsız 128 kodu")
                x = width  # URF: rest of the line is white
            elif code < 128:
                x += code + 1
                pos += bpp
            else:
                x += 257 - code
                pos += (257 - code) * bpp
        if x > width:
            raise ValueError(f"satır {y} taşıyor")
        y += repeat
    if y != height or pos > len(data):
        raise ValueError("sayfa verisi eksik ya da taşıyor")
    return pos


def count_raster_pages(data: bytes, document_format: str) -> int:
    """Decode-count the pages of a PWG raster or URF stream."""
    pages = 0
    try:
        if document_format == PWG_FMT:
            if data[:4] != _PWG_SYNC:
                raise ValueError("RaS2 senkron kelimesi yok")
            pos = 4
            while pos < len(data):
                width, height = struct.unpack_from(">II", data, pos + 372)
                (bits,) = struct.unpack_from(">I", data, pos + 388)
                pos = _skip_bitmap(
                    data, pos + _PWG_HEADER, width, height, bits // 8, urf=False
                )
                pages += 1
            return pages
        if document_format == URF_FMT:
            if data[:8] != _URF_MAGIC:
                raise ValueError("UNIRAST başlığı yok")
            (declared,) = struct.unpack_from(">I", data, 8)
            pos = 12
            while pos < len(data):
                bits = data[pos]
                width, height = struct.unpack_from(">II", data, pos + 12)
                pos = _skip_bitmap(
                    data, pos + _URF_HEADER, width, height, bits // 8, urf=True
                )
                pages += 1
            if declared != pages:
                raise ValueError(f"başlık {declared} sayfa diyor, {pages} bulundu")
            return pages
    except (IndexError, struct.error) as err:
        raise ValueError(f"veri kesik ({err})") from err
    raise ValueError(f"{document_format} çözülemiyor")


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
        f"printer-is-accepting-jobs: {show('printer-is-accepting-jobs')}",
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
        lines.append("PDF listede yok: dönüştürülüp gönderilecek (4m-4p, 6, 7b)")
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


# --- scanner check (--scan-info / --scan) ------------------------------------------

ESCL_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "home_print"
SCAN_TEST_DPI = 75


ESCL_PACKAGE = "home_print_standalone_escl"


def load_escl() -> Any | None:
    """Import the integration's HA-free ``escl`` package by path, or None.

    It is loaded under a unique name (``ESCL_PACKAGE``) so it never shadows
    or picks up another top-level ``escl`` module; ``sys.path`` is untouched.
    Returns the package with ``client``, ``models`` and ``parse`` loaded.
    """
    init = ESCL_DIR / "escl" / "__init__.py"
    if not (ESCL_DIR / "escl" / "client.py").is_file() or not init.is_file():
        return None
    if ESCL_PACKAGE in sys.modules:
        return sys.modules[ESCL_PACKAGE]
    spec = importlib.util.spec_from_file_location(
        ESCL_PACKAGE, init, submodule_search_locations=[str(init.parent)]
    )
    if spec is None or spec.loader is None:
        return None
    package = importlib.util.module_from_spec(spec)
    sys.modules[ESCL_PACKAGE] = package
    try:
        spec.loader.exec_module(package)
        for name in ("errors", "models", "parse", "client"):
            importlib.import_module(f"{ESCL_PACKAGE}.{name}")
    except ImportError:
        for name in [m for m in sys.modules if m.split(".")[0] == ESCL_PACKAGE]:
            del sys.modules[name]
        return None
    return package


def _escl_trace() -> aiohttp.TraceConfig:
    """Print every eSCL job request's status (diagnostics for HP quirks)."""
    trace = aiohttp.TraceConfig()

    async def on_redirect(session, ctx, params) -> None:  # noqa: ANN001
        print(
            f"   [eSCL] {params.method} {params.url} -> HTTP "
            f"{params.response.status} yönlendirme: "
            f"{params.response.headers.get('Location')}",
            flush=True,
        )

    async def on_end(session, ctx, params) -> None:  # noqa: ANN001
        path = params.url.path
        resp = params.response
        if params.method == "POST" and path.endswith("/ScanJobs"):
            print(
                f"   [eSCL] POST ScanJobs -> HTTP {resp.status}, "
                f"Location: {resp.headers.get('Location')}",
                flush=True,
            )
        elif path.endswith("/NextDocument"):
            print(f"   [eSCL] GET NextDocument -> HTTP {resp.status}", flush=True)
        elif params.method == "DELETE":
            print(f"   [eSCL] DELETE {path} -> HTTP {resp.status}", flush=True)

    trace.on_request_redirect.append(on_redirect)
    trace.on_request_end.append(on_end)
    return trace


def _scan_out_dir(args: argparse.Namespace) -> Path:
    if args.json:
        return Path(args.json).expanduser().resolve().parent
    return Path.cwd()


def _inches(length: int) -> str:
    return f"{length / 300:.1f}".rstrip("0").rstrip(".")


async def run_scan_check(args: argparse.Namespace) -> int:
    escl = load_escl()
    if escl is None:
        print(
            "❌ eSCL kodu yüklenemedi. Scripti repo klasöründen çalıştır "
            "(scripts/ ile custom_components/ yan yana olmalı).",
            flush=True,
        )
        return 1
    EsclClient = escl.client.EsclClient  # noqa: N806
    EsclError = escl.client.EsclError  # noqa: N806
    find_scanner = escl.client.find_scanner
    ScanSettings = escl.models.ScanSettings  # noqa: N806
    parse_capabilities = escl.parse.parse_capabilities
    parse_status = escl.parse.parse_status

    out_dir = _scan_out_dir(args)
    # A status file from an earlier run must not pass for this device's.
    (out_dir / "escl_status.xml").unlink(missing_ok=True)
    timeout = aiohttp.ClientTimeout(total=PRINT_TIMEOUT)
    traces = [_escl_trace()] if args.scan else []
    async with aiohttp.ClientSession(timeout=timeout, trace_configs=traces) as session:
        found = await find_scanner(session, args.printer, args.tls, False)
        base = found[0] if found is not None else None
        if base is None:
            print(
                f"❌ {args.printer} adresinde tarayıcı bulunamadı "
                "(eSCL yanıt vermedi). Yazıcı açık mı, adres doğru mu?",
                flush=True,
            )
            return 1
        client = EsclClient(base, session, False)
        try:
            caps_xml = await client._get_xml("ScannerCapabilities")  # noqa: SLF001
            caps = parse_capabilities(caps_xml)
        except EsclError as err:
            print(f"❌ Tarayıcı yetenekleri okunamadı: {err}", flush=True)
            return 1
        (out_dir / "escl_capabilities.xml").write_bytes(caps_xml)
        print(f"✅ Tarayıcı bulundu: {base}", flush=True)
        print(f"   Son adres (yönlendirmelerden sonra): {base}", flush=True)
        print(f"   Model: {caps.make_model or '?'}  (eSCL {caps.version})", flush=True)
        names = {"platen": "cam", "adf": "belge besleyici", "adf_duplex": "çift yüzlü"}
        for key, src in caps.sources.items():
            print(
                f"   {names.get(key, key)}: renk {'/'.join(src.color_modes)}; "
                f"çözünürlük {'/'.join(map(str, src.resolutions))} dpi; "
                f"biçim {'/'.join(src.formats)}; "
                f"en büyük alan {_inches(src.max_width)}x{_inches(src.max_height)} inç",
                flush=True,
            )
        try:
            status_xml = await client._get_xml("ScannerStatus")  # noqa: SLF001
            status = parse_status(status_xml)
            (out_dir / "escl_status.xml").write_bytes(status_xml)
            adf = {True: "dolu", False: "boş", None: "bilinmiyor"}[status.adf_loaded]
            print(f"   Durum: {status.state}; besleyici: {adf}", flush=True)
        except EsclError as err:
            print(f"⚠ Durum okunamadı: {err}", flush=True)
        print(f"   XML dosyaları: {out_dir}", flush=True)
        print(
            "   Not: XML dosyaları cihaz kimlikleri (seri no, UUID) içerir; "
            "herkese açık paylaşma.",
            flush=True,
        )

        if not args.scan:
            return 0
        src = caps.sources.get("platen")
        if src is None or "gray" not in src.color_modes:
            print("❌ Camdan gri tarama desteklenmiyor, deneme yapılamadı.", flush=True)
            return 1
        dpi = (
            SCAN_TEST_DPI
            if SCAN_TEST_DPI in src.resolutions
            else min(src.resolutions, default=SCAN_TEST_DPI)
        )
        print(f"Tarıyor: cam, gri, {dpi} dpi (tek sayfa)...", flush=True)
        try:
            pages = await client.scan(
                caps, ScanSettings("platen", "gray", dpi, "image/jpeg")
            )
        except EsclError as err:
            print(f"❌ Tarama başarısız: {err}", flush=True)
            return 1
        target = out_dir / "scan_test.jpg"
        target.write_bytes(pages[0])
        try:
            from PIL import Image

            with Image.open(io.BytesIO(pages[0])) as img:
                size = f"{img.width}x{img.height} piksel"
        except Exception:  # noqa: BLE001
            size = f"{len(pages[0])} bayt (boyut okunamadı)"
        print(f"✅ Tarama tamam: {target} ({size}, {len(pages)} sayfa)", flush=True)
        return 0


# --- 4. Validate-Job ---------------------------------------------------------------


def build_validate_message(
    document_format: str, job_attrs: dict[str, Any], job_name: str = JOB_NAME
) -> dict[str, Any]:
    """Validate-Job request. RFC 8011 4.2.3: no document data is sent."""
    return {
        "operation-attributes-tag": {
            "requesting-user-name": USER_NAME,
            "job-name": job_name,
            "document-format": document_format,
        },
        "job-attributes-tag": dict(job_attrs),
    }


Case = tuple[str, str, str, dict[str, Any], str]


def _sides_skip(attrs: dict[str, Any]) -> str:
    if LONG_EDGE in _as_list(attrs.get("sides-supported")):
        return ""
    return "sides-supported içinde two-sided-long-edge yok"


def _color_skip(attrs: dict[str, Any]) -> str:
    if "color" in _as_list(attrs.get("print-color-mode-supported")):
        return ""
    return "print-color-mode-supported içinde color yok"


def _copies_skip(attrs: dict[str, Any]) -> str:
    copies = _as_list(attrs.get("copies-supported"))
    if copies and isinstance(copies[-1], int) and copies[-1] < 2:
        return "copies-supported en fazla 1"
    return ""


def _cases(
    attrs: dict[str, Any],
    conv: Convert | None = None,
    conv_reason: str = "dönüştürme yüklenmedi",
) -> list[Case]:
    """(num, title, format, job attributes, skip reason or "")."""
    pdf = PDF_FMT
    jpeg = JPEG_FMT
    cases: list[Case] = [
        ("4a", "Validate-Job PDF varsayılan", pdf, {}, ""),
        (
            "4b",
            "Validate-Job PDF çift yüz",
            pdf,
            {"sides": LONG_EDGE},
            _sides_skip(attrs),
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
            _color_skip(attrs),
        ),
        (
            "4e",
            "Validate-Job PDF sayfa 1-1",
            pdf,
            {"page-ranges": [IppRange(1, 1)]},
            "" if attrs.get("page-ranges-supported") is True else "page-ranges yok",
        ),
        ("4f", "Validate-Job JPEG", jpeg, {}, ""),
        ("4g", "Validate-Job PNG", "image/png", {}, ""),
        ("4h", "Validate-Job PDF 2 kopya", pdf, {"copies": 2}, _copies_skip(attrs)),
        (
            "4i",
            "Validate-Job JPEG çift yüz",
            jpeg,
            {"sides": LONG_EDGE},
            _sides_skip(attrs),
        ),
        (
            "4j",
            "Validate-Job JPEG siyah-beyaz",
            jpeg,
            {"print-color-mode": "monochrome"},
            "",
        ),
        (
            "4k",
            "Validate-Job JPEG renkli",
            jpeg,
            {"print-color-mode": "color"},
            _color_skip(attrs),
        ),
        ("4l", "Validate-Job JPEG 2 kopya", jpeg, {"copies": 2}, _copies_skip(attrs)),
    ]
    converted = [
        ("4m", "varsayılan", {}, "", False),
        ("4n", "çift yüz", {"sides": LONG_EDGE}, _sides_skip(attrs), False),
        ("4o", "siyah-beyaz", {"print-color-mode": "monochrome"}, "", True),
        ("4p", "renkli", {"print-color-mode": "color"}, _color_skip(attrs), False),
    ]
    caps, caps_error = (None, conv_reason)
    if conv is not None:
        caps, caps_error = conv.safe_capabilities(attrs)
    for num, label, job_attrs, skip, gray in converted:
        title = f"Validate-Job dönüştürülmüş PDF {label}"
        target = None
        if conv is None or caps is None:
            skip = skip or caps_error
        else:
            target = conv.pipeline.choose_target(pdf, caps, gray=gray)
            if target is None:
                skip = skip or "PDF için dönüştürme yolu yok (PDF/PWG/URF yok)"
            elif target == pdf:
                skip = skip or "yazıcı PDF'i doğrudan alıyor, dönüştürme gerekmiyor"
            else:
                title = f"Validate-Job {target} (PDF'ten) {label}"
        cases.append((num, title, target or pdf, job_attrs, skip))
    return cases


async def check_printer_jobs(
    args: argparse.Namespace,
    attrs: dict[str, Any] | None = None,
    session: aiohttp.ClientSession | None = None,
    conv: Convert | None = None,
    conv_reason: str = "dönüştürme yüklenmedi",
) -> list[Result]:
    own = session is None
    session = session or aiohttp.ClientSession()
    try:
        if attrs is None:
            _, attrs = await get_printer_attributes(args, session)
            if attrs is None:
                return [Result("4", "Validate-Job", SKIP, "yazıcı özellikleri yok")]
        return await _validate_all(
            make_ipp(args, session, IPP_TIMEOUT),
            _cases(attrs, conv, conv_reason),
            attrs,
        )
    finally:
        if own:
            await session.close()


def _validate_outcome(response: dict[str, Any]) -> tuple[str, str]:
    """(status, "keyword (desteklenmeyen: ...)") of a Validate-Job answer."""
    status, name = interpret_status(response.get("status-code", -1))
    unsupported = sorted(
        {k for group in response.get("unsupported-attributes") or [] for k in group}
    )
    if unsupported:
        name += f" (desteklenmeyen: {', '.join(unsupported)})"
    return status, name


async def _validate_all(
    ipp: IPP, cases: list[Case], attrs: dict[str, Any]
) -> list[Result]:
    formats = _as_list(attrs.get("document-format-supported"))
    ops = _as_list(attrs.get("operations-supported"))
    results = []
    for num, title, fmt, job_attrs, skip in cases:
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
        status, detail = _validate_outcome(response)
        name = status_name(response.get("status-code", -1))
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


# --- 6. conversion (no print) --------------------------------------------------


async def check_conversion(
    attrs: dict[str, Any], conv: Convert | None, conv_reason: str
) -> Result:
    """Convert a 3-page sample PDF like the integration would, count pages.

    Monochrome and long-edge duplex (when supported), so an odd page count
    gets a blank back page: 3 pages -> 4 in the output.
    """
    title = "Dönüştürme denemesi (3 sayfa PDF, baskısız)"
    if conv is None:
        return Result("6", title, SKIP, conv_reason)
    caps, caps_error = conv.safe_capabilities(attrs)
    if caps is None:
        return Result("6", title, FAIL, caps_error)
    duplex = LONG_EDGE in caps.sides
    options = conv.options(
        sides=LONG_EDGE if duplex else "one-sided", color_mode="monochrome"
    )
    target = conv.pipeline.choose_target(PDF_FMT, caps, gray=True)
    if target is None:
        return Result("6", title, FAIL, "PDF için dönüştürme yolu yok (PDF/PWG/URF)")
    if target == PDF_FMT:
        return Result(
            "6", title, SKIP, "yazıcı PDF'i doğrudan alıyor, dönüştürme gerekmiyor"
        )
    try:
        data = conversion_test_pdf(3)
        started = time.perf_counter()
        prepared = await asyncio.to_thread(
            conv.pipeline.prepare, data, PDF_FMT, caps, options
        )
        elapsed = time.perf_counter() - started
    except Exception as err:  # noqa: BLE001 - report, never crash
        return Result(
            "6", title, FAIL, f"prepare hata verdi: {type(err).__name__}: {err}"
        )
    try:
        pages = count_raster_pages(prepared.data, prepared.document_format)
    except ValueError as err:
        return Result("6", title, FAIL, f"{prepared.document_format} çözülemedi: {err}")
    expected = 3 + (1 if duplex else 0)
    detail = (
        f"{prepared.document_format}, {len(prepared.data) / 1024:.0f} KB, "
        f"{elapsed:.1f} sn, {pages} sayfa (beklenen {expected}"
        f"{', 3 + boş arka yüz' if duplex else ''})"
    )
    ok = pages == expected and prepared.page_count == 3
    return Result("6", title, PASS if ok else FAIL, detail)


# --- 7. real prints (only with --print) --------------------------------------------


@dataclass
class PlannedJob:
    num: str
    title: str
    job_name: str
    document_format: str
    data: bytes
    job_attrs: dict[str, Any]
    sheets: int
    expect_impressions: int | None = None


def _plan_jpeg_job(attrs: dict[str, Any], conv: Convert | None) -> PlannedJob | Result:
    num, title = "7a", "Gerçek baskı 2/2: JPEG tek sayfa"
    data = sample_jpeg()
    caps = conv.safe_capabilities(attrs)[0] if conv is not None else None
    if conv is not None and caps is not None:
        try:
            prepared = conv.pipeline.prepare(data, JPEG_FMT, caps, conv.options())
        except Exception as err:  # noqa: BLE001 - NoConversionRoute etc.
            return Result(num, title, SKIP, f"JPEG hazırlanamadı: {type(err).__name__}")
        fmt, data = prepared.document_format, prepared.data
    else:
        formats = _as_list(attrs.get("document-format-supported"))
        if formats and JPEG_FMT not in formats:
            return Result(num, title, SKIP, "yazıcı JPEG almıyor, dönüştürme de yok")
        fmt = JPEG_FMT
    return PlannedJob(num, title, JOB_NAME_2, fmt, data, {"copies": 1}, sheets=1)


def _plan_duplex_job(
    attrs: dict[str, Any],
    conv: Convert | None,
    conv_reason: str,
    *,
    front_only_reason: str = "",
) -> PlannedJob | Result:
    """Print 1/2: both pages on one sheet, or only the front page.

    Without long-edge duplex (not advertised, or the printer ignores
    ``sides``) only page 1 is sent, so 1/2 should take 1 sheet. A printer
    could still print it one-sided, so it goes first and the JPEG waits for
    its sheet count (:func:`sheets_used`).
    """
    num, title = "7b", "Gerçek baskı 1/2: PDF çift yüz, siyah-beyaz"
    if conv is None:
        return Result(num, title, SKIP, conv_reason)
    caps, caps_error = conv.safe_capabilities(attrs)
    if caps is None:
        return Result(num, title, SKIP, caps_error)
    if not front_only_reason and LONG_EDGE not in caps.sides:
        front_only_reason = "sides-supported içinde two-sided-long-edge yok"
    duplex = not front_only_reason
    mono = "monochrome" in caps.color_modes
    options = conv.options(
        sides=LONG_EDGE if duplex else "one-sided",
        color_mode="monochrome" if mono else None,
    )
    document = duplex_test_pdf() if duplex else duplex_test_pdf(front_only=True)
    try:
        prepared = conv.pipeline.prepare(document, PDF_FMT, caps, options)
    except Exception as err:  # noqa: BLE001 - NoConversionRoute etc.
        return Result(
            num, title, SKIP, f"PDF hazırlanamadı: {type(err).__name__}: {err}"
        )
    job_attrs: dict[str, Any] = {"copies": 1}
    if duplex:
        job_attrs["sides"] = LONG_EDGE
    if mono:
        job_attrs["print-color-mode"] = "monochrome"
    side_text = (
        "çift yüz" if duplex else f"sadece ön yüz, 1 kağıt ({front_only_reason})"
    )
    title = (
        f"Gerçek baskı 1/2: PDF → {prepared.document_format}, {side_text}"
        f"{', siyah-beyaz' if mono else ''}"
    )
    return PlannedJob(
        num,
        title,
        JOB_NAME_1,
        prepared.document_format,
        prepared.data,
        job_attrs,
        sheets=1,
        expect_impressions=2 if duplex else 1,
    )


async def _printer_not_ready(ipp: IPP) -> str:
    """ "" when idle and accepting jobs; waits up to IDLE_WAIT while busy."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + IDLE_WAIT
    while True:
        try:
            response = await ipp_call(
                ipp,
                IppOperation.GET_PRINTER_ATTRIBUTES,
                {
                    "operation-attributes-tag": {
                        "requested-attributes": [
                            "printer-state",
                            "printer-state-reasons",
                            "printer-is-accepting-jobs",
                        ]
                    }
                },
            )
        except IppCallError as err:
            return f"yazıcı durumu okunamadı ({err})"
        printer = next(iter(response.get("printers") or []), None)
        if printer is None:
            return "yazıcı durumu okunamadı (boş cevap)"
        if printer.get("printer-is-accepting-jobs") is False:
            return "yazıcı iş kabul etmiyor (printer-is-accepting-jobs = false)"
        state = printer.get("printer-state", 3)
        if state == 3:
            return ""
        if state != 4 or loop.time() >= deadline:
            reasons = ", ".join(
                map(str, _as_list(printer.get("printer-state-reasons")))
            )
            waited = f", {IDLE_WAIT} sn beklendi" if state == 4 else ""
            return (
                f"yazıcı boşta değil: {_PRINTER_STATES.get(state, state)}; "
                f"nedenler: {reasons or '-'}{waited}"
            )
        await asyncio.sleep(POLL_INTERVAL)


async def _validate_planned(ipp: IPP, job: PlannedJob) -> tuple[str, str, set[str]]:
    """(status, detail, unsupported names) of Validate-Job for the job."""
    try:
        response = await ipp_call(
            ipp,
            IppOperation.VALIDATE_JOB,
            build_validate_message(job.document_format, job.job_attrs, job.job_name),
        )
    except IppCallError as err:
        return FAIL, str(err), set()
    status, detail = _validate_outcome(response)
    unsupported = {
        k for group in response.get("unsupported-attributes") or [] for k in group
    }
    return status, detail, unsupported


def sheets_used(job: PlannedJob, last: dict[str, Any]) -> int | None:
    """Sheets a finished job took, or ``None`` when that is not certain.

    ``job-media-sheets-completed`` when the printer reports it. Otherwise
    impressions: one-sided, one impression is one sheet; two-sided, more
    than one impression may be one sheet or several (a printer that quietly
    printed one-sided), so it is unknown. A job that has not finished may
    still print more: unknown too.
    """

    def count(key: str) -> int | None:
        value = last.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value

    if int(last.get("job-state", 3)) not in _JOB_DONE:
        return None
    sheets = count("job-media-sheets-completed")
    if sheets is not None:
        return sheets
    impressions = count("job-impressions-completed")
    if impressions is None:
        return None
    duplex = job.job_attrs.get("sides", "one-sided") != "one-sided"
    if duplex and impressions > 1:
        return None
    return impressions


async def _send_and_wait(
    args: argparse.Namespace, session: aiohttp.ClientSession, job: PlannedJob
) -> tuple[Result, int | None]:
    """Send the job and follow it; also returns :func:`sheets_used`.

    ``None`` sheets: not certain (also when the job may have been sent but
    its answer was lost).
    """
    try:
        response = await ipp_call(
            make_ipp(args, session, PRINT_TIMEOUT),
            IppOperation.PRINT_JOB,
            {
                "operation-attributes-tag": {
                    "requesting-user-name": USER_NAME,
                    "job-name": job.job_name,
                    "document-format": job.document_format,
                },
                "job-attributes-tag": dict(job.job_attrs),
                "data": job.data,
            },
        )
    except IppCallError as err:
        return Result(
            job.num,
            job.title,
            FAIL,
            f"Print-Job: {err}. İş yine de gitmiş olabilir; tekrar çalıştırmadan "
            "önce yazıcının durumuna bak",
        ), None
    status, name = interpret_status(response.get("status-code", -1))
    sent = next(iter(response.get("jobs") or []), {})
    if status != PASS or "job-id" not in sent:
        rejected = Result(job.num, job.title, FAIL, f"Print-Job reddedildi: {name}")
        return rejected, (0 if status != PASS else None)
    job_id = int(sent["job-id"])
    print(
        f"      • {job.num}: iş numarası {job_id}, bitmesi bekleniyor "
        f"(en fazla {POLL_LIMIT} sn)",
        flush=True,
    )

    ipp = make_ipp(args, session, IPP_TIMEOUT)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + POLL_LIMIT
    last: dict[str, Any] = sent
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

    impressions = last.get("job-impressions-completed", "?")
    detail = (
        f"iş {job_id}: {_JOB_STATES.get(state, state)}; nedenler: "
        f"{', '.join(map(str, _as_list(last.get('job-state-reasons')))) or '-'}; "
        f"impressions: {impressions}, "
        f"sheets: {last.get('job-media-sheets-completed', '?')}"
    )
    if job.expect_impressions is not None:
        detail += f" (beklenen impressions {job.expect_impressions}"
        if isinstance(impressions, int) and impressions != job.expect_impressions:
            detail += ", FARKLI"
        detail += ")"
    if state not in _JOB_DONE:
        detail += f" ({POLL_LIMIT} sn içinde bitmedi)"
    result = Result(job.num, job.title, PASS if state == 9 else FAIL, detail)
    return result, sheets_used(job, last)


async def run_print_tests(
    args: argparse.Namespace,
    attrs: dict[str, Any],
    session: aiohttp.ClientSession,
    conv: Convert | None,
    conv_reason: str,
    report: dict[str, Any],
) -> None:
    """All real prints in one go: at most 2 jobs, at most MAX_SHEETS sheets.

    The duplex PDF (7b) goes first. The JPEG (7a) follows only if 7b surely
    took at most one sheet; an unknown count is taken as 2.
    """
    planned = [
        _plan_duplex_job(attrs, conv, conv_reason),
        _plan_jpeg_job(attrs, conv),
    ]
    jobs = [j for j in planned if isinstance(j, PlannedJob)]
    sheets = min(sum(j.sheets for j in jobs), MAX_SHEETS)
    print(
        f"⚠️  DİKKAT: --print verildi. {len(jobs)} iş, en fazla {sheets} kağıt "
        "gerçekten basılacak:",
        flush=True,
    )
    for job in jobs:
        print(
            f"      • {job.num}: '{job.job_name}' ({job.document_format}, "
            f"{len(job.data) / 1024:.0f} KB, {job.sheets} kağıt)",
            flush=True,
        )
    ipp = make_ipp(args, session, IPP_TIMEOUT)
    ops = _as_list(attrs.get("operations-supported"))
    used = 0
    used_note = ""  # why ``used`` is what it is, for the skip message
    for job in planned:
        if isinstance(job, Result):
            emit(report, job)
            continue
        reason = await _printer_not_ready(ipp)
        if reason:
            emit(report, Result(job.num, job.title, SKIP, f"gönderilmedi: {reason}"))
            continue
        note = ""
        if ops and IppOperation.VALIDATE_JOB not in ops:
            note = " (yazıcı Validate-Job bildirmiyor, kontrolsüz gönderildi)"
        else:
            status, detail, unsupported = await _validate_planned(ipp, job)
            if status == PASS and "sides" in unsupported and "sides" in job.job_attrs:
                # successful-ok-ignored: duplex would silently become 2 sheets
                replanned = _plan_duplex_job(
                    attrs,
                    conv,
                    conv_reason,
                    front_only_reason="yazıcı sides'ı yok saydı",
                )
                if isinstance(replanned, Result):
                    emit(report, replanned)
                    continue
                job = replanned
                status, detail, unsupported = await _validate_planned(ipp, job)
            if status == FAIL:
                emit(
                    report,
                    Result(
                        job.num,
                        job.title,
                        SKIP,
                        f"gönderilmedi: Validate-Job kabul etmedi ({detail})",
                    ),
                )
                continue
            if status == SKIP:
                note = f" (Validate-Job uygulanmıyor: {detail})"
        if used + job.sheets > MAX_SHEETS:
            emit(
                report,
                Result(
                    job.num,
                    job.title,
                    SKIP,
                    f"gönderilmedi: {used_note}en fazla {MAX_SHEETS} kağıt "
                    "sınırı aşılabilirdi",
                ),
            )
            continue
        result, sheets = await _send_and_wait(args, session, job)
        result.detail += note
        emit(report, result)
        if sheets is None:
            used += MAX_SHEETS  # not certain: assume the worst
            used_note = f"{job.num} işinin kaç kağıt kullandığı bilinmiyor; "
        else:
            used += sheets
            used_note = f"{job.num} işi {sheets} kağıt kullandı; "


# --- main --------------------------------------------------------------------------


async def run(args: argparse.Namespace) -> int:
    if args.scan_info:
        return await run_scan_check(args)
    report: dict[str, Any] = {"results": [], "printer_attributes": None, "ha": {}}
    attrs: dict[str, Any] | None = None
    unreachable = "yazıcıya erişilemedi"
    conv, conv_reason = load_convert()

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
            emit(
                report,
                *await check_printer_jobs(args, attrs, session, conv, conv_reason),
            )
        else:
            emit(report, Result("4", "Validate-Job", SKIP, unreachable))

        if args.ha and args.token:
            emit(report, *await check_ha(args, report))
        else:
            emit(report, Result("5", "Home Assistant", SKIP, "--ha ve --token yok"))

        if attrs is None:
            emit(report, Result("6", "Dönüştürme denemesi", SKIP, unreachable))
        else:
            emit(report, await check_conversion(attrs, conv, conv_reason))

        if not args.print:
            emit(report, Result("7", "Gerçek baskı", SKIP, "--print verilmedi"))
        elif attrs is None:
            emit(report, Result("7", "Gerçek baskı", SKIP, unreachable))
        else:
            await run_print_tests(args, attrs, session, conv, conv_reason, report)

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
        help="GERÇEKTEN bas: 2 iş, en fazla 2 kağıt (yoksa hiç baskı yapılmaz)",
    )
    p.add_argument(
        "--scan-info",
        action="store_true",
        help=(
            "yalnızca tarayıcıyı bul ve özetle (kağıt harcamaz, IPP kontrolü yok); "
            "bu kipte --json yalnızca çıktı klasörünü belirler, --ha/--token "
            "yok sayılır"
        ),
    )
    p.add_argument(
        "--scan",
        action="store_true",
        help="--scan-info + camdan 75 dpi gri tek sayfa tara (scan_test.jpg)",
    )
    p.add_argument(
        "--json", metavar="OUT.json", help="sonuçları JSON dosyasına yaz (gizlenmiş)"
    )
    args = p.parse_args(argv)
    if args.scan:
        args.scan_info = True
    if args.scan_info and args.print:
        p.error("--scan-info/--scan ile --print birlikte kullanılamaz")
    return args


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    sys.exit(main())
