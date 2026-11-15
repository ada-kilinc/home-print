"""Tests for scripts/remote_check.py (loaded by path; scripts/ is no package)."""

from __future__ import annotations

import importlib.util
import json
import struct
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pyipp import IPP
from pyipp.enums import IppOperation
from pyipp.serializer import encode_dict

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "remote_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("remote_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["remote_check"] = module
    spec.loader.exec_module(module)
    return module


rc = _load()


# --- tiny IPP response encoder (only what these tests need) -----------------


def _value(tag: int, value: Any) -> bytes:
    if tag in (0x21, 0x23):
        return struct.pack(">hi", 4, value)
    if tag == 0x22:
        return struct.pack(">h?", 1, value)
    raw = value.encode()
    return struct.pack(">h", len(raw)) + raw


def _attr(name: str, value: Any) -> bytes:
    values = value if isinstance(value, list) else [value]
    out = b""
    for i, item in enumerate(values):
        if isinstance(item, bool):
            tag = 0x22
        elif isinstance(item, int):
            tag = 0x21
        else:
            tag = 0x44  # keyword
        key = name.encode() if i == 0 else b""
        out += struct.pack(">bh", tag, len(key)) + key + _value(tag, item)
    return out


def ipp_response(
    status: int,
    printer: dict[str, Any] | None = None,
    unsupported: dict[str, Any] | None = None,
    job: dict[str, Any] | None = None,
) -> bytes:
    out = struct.pack(">bbhi", 1, 1, status, 1)
    out += b"\x01" + _attr("attributes-charset", "utf-8")
    if unsupported:
        out += b"\x05" + b"".join(_attr(k, v) for k, v in unsupported.items())
    if job:
        out += b"\x02" + b"".join(_attr(k, v) for k, v in job.items())
    if printer:
        out += b"\x04" + b"".join(_attr(k, v) for k, v in printer.items())
    return out + b"\x03"


PRINTER = {
    "printer-make-and-model": "HP DeskJet 2700 series",
    "printer-state": 3,
    "printer-state-reasons": "none",
    "document-format-supported": ["application/pdf", "image/jpeg", "image/urf"],
    "sides-supported": ["one-sided", "two-sided-long-edge"],
    "print-color-mode-supported": ["monochrome", "color"],
    "page-ranges-supported": True,
    "marker-names": ["Black", "Tri-color"],
    "marker-levels": [40, 70],
    "marker-colors": ["#000000", "#00FFFF"],
    "operations-supported": [2, 4, 9, 11],
}


class FakeIPP:
    """Records every request sent through ``IPP.raw`` / ``IPP.execute``."""

    def __init__(self, printer=PRINTER, validate_status=0x0000, by_format=None):
        self.ops: list[IppOperation] = []
        self.messages: list[dict[str, Any]] = []
        self.printer = printer
        self.validate_status = validate_status
        self.by_format = by_format or {}

    async def raw(self, ipp_self, operation, message):
        self.ops.append(operation)
        self.messages.append(message)
        # make sure the real serializer can encode what the script built
        encode_dict(ipp_self._message(operation, message))
        if operation == IppOperation.GET_PRINTER_ATTRIBUTES:
            return ipp_response(0, printer=self.printer)
        if operation == IppOperation.VALIDATE_JOB:
            fmt = message["operation-attributes-tag"]["document-format"]
            return ipp_response(self.by_format.get(fmt, self.validate_status))
        if operation == IppOperation.PRINT_JOB:
            return ipp_response(0, job={"job-id": 7, "job-state": 3})
        if operation == IppOperation.GET_JOB_ATTRIBUTES:
            return ipp_response(0, job={"job-id": 7, "job-state": 9})
        raise AssertionError(operation)


@pytest.fixture
def fake_ipp():
    fake = FakeIPP()

    async def raw(self, operation, message):
        return await fake.raw(self, operation, message)

    execute = AsyncMock(side_effect=AssertionError("execute not expected"))
    with (
        patch.object(IPP, "raw", raw),
        patch.object(IPP, "execute", execute),
        patch.object(
            rc,
            "check_tcp",
            AsyncMock(return_value=rc.Result("1", "Erişim", rc.PASS, "açık")),
        ),
        patch.object(rc, "check_escl", AsyncMock(return_value=[])),
    ):
        fake.execute = execute
        yield fake


# --- argument parsing -------------------------------------------------------


def test_parse_args_defaults():
    args = rc.parse_args(["--printer", "10.0.0.5"])
    assert args.printer == "10.0.0.5"
    assert args.port == 631
    assert args.path == "/ipp/print"
    assert args.tls is False
    assert args.ha is None
    assert args.token is None
    assert args.print is False
    assert args.json is None


def test_parse_args_requires_printer():
    with pytest.raises(SystemExit):
        rc.parse_args([])


# --- no print without --print -----------------------------------------------


async def test_no_print_job_without_print_flag(fake_ipp, capsys):
    code = await rc.run(rc.parse_args(["--printer", "10.0.0.5"]))
    assert IppOperation.PRINT_JOB not in fake_ipp.ops
    assert IppOperation.VALIDATE_JOB in fake_ipp.ops
    fake_ipp.execute.assert_not_called()
    out = capsys.readouterr().out
    assert "Özet" in out
    assert code == 0


async def test_print_flag_sends_exactly_one_job(fake_ipp, capsys):
    with patch.object(rc, "POLL_INTERVAL", 0):
        code = await rc.run(rc.parse_args(["--printer", "10.0.0.5", "--print"]))
    assert fake_ipp.ops.count(IppOperation.PRINT_JOB) == 1
    assert code == 0
    assert "completed" in capsys.readouterr().out


# --- Validate-Job request ----------------------------------------------------


def test_validate_message_attributes():
    msg = rc.build_validate_message(
        "application/pdf", {"sides": "two-sided-long-edge", "copies": 2}
    )
    assert msg["operation-attributes-tag"]["document-format"] == "application/pdf"
    assert msg["job-attributes-tag"] == {"sides": "two-sided-long-edge", "copies": 2}
    assert "data" not in msg  # Validate-Job carries no document


def test_validate_message_encodes_job_attributes():
    msg = rc.build_validate_message(
        "application/pdf",
        {
            "sides": "two-sided-long-edge",
            "print-color-mode": "monochrome",
            "page-ranges": [rc.IppRange(1, 1)],
        },
    )
    raw = encode_dict(IPP(host="h")._message(IppOperation.VALIDATE_JOB, msg))
    assert raw[2:4] == b"\x00\x04"  # operation id
    assert b"two-sided-long-edge" in raw
    assert b"print-color-mode" in raw
    assert b"page-ranges" + struct.pack(">hii", 8, 1, 1) in raw


async def test_validate_cases_send_expected_attributes(fake_ipp):
    await rc.run(rc.parse_args(["--printer", "10.0.0.5"]))
    sent = [
        (m["operation-attributes-tag"]["document-format"], m["job-attributes-tag"])
        for op, m in zip(fake_ipp.ops, fake_ipp.messages, strict=True)
        if op == IppOperation.VALIDATE_JOB
    ]
    assert ("application/pdf", {}) in sent
    assert ("application/pdf", {"sides": "two-sided-long-edge"}) in sent
    assert ("application/pdf", {"print-color-mode": "monochrome"}) in sent
    assert ("application/pdf", {"print-color-mode": "color"}) in sent
    assert ("application/pdf", {"copies": 2}) in sent
    assert ("image/jpeg", {}) in sent
    assert ("image/png", {}) in sent
    ranges = [a["page-ranges"] for _, a in sent if "page-ranges" in a]
    assert [(r.lower, r.upper) for r in ranges[0]] == [(1, 1)]


async def test_unsupported_capability_is_skipped_not_sent(fake_ipp):
    fake_ipp.printer = {
        **PRINTER,
        "sides-supported": "one-sided",
        "page-ranges-supported": False,
    }
    results = await rc.check_printer_jobs(rc.parse_args(["--printer", "h"]))
    by_num = {r.num: r for r in results}
    assert by_num["4b"].status == rc.SKIP
    assert by_num["4e"].status == rc.SKIP
    sent = [
        m["job-attributes-tag"]
        for op, m in zip(fake_ipp.ops, fake_ipp.messages, strict=True)
        if op == IppOperation.VALIDATE_JOB
    ]
    assert not any("sides" in a or "page-ranges" in a for a in sent)


# --- status interpretation ----------------------------------------------------


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (0x0000, "pass"),
        (0x0001, "pass"),
        (0x0400, "fail"),
        (0x040B, "fail"),
        (0x0501, "skip"),
        (0x0500, "fail"),
    ],
)
def test_interpret_status(code, expected):
    status, detail = rc.interpret_status(code)
    assert status == {"pass": rc.PASS, "fail": rc.FAIL, "skip": rc.SKIP}[expected]
    if expected == "fail":
        assert detail.startswith(("client-error-", "server-error-"))


def test_status_names():
    assert rc.status_name(0x0000) == "successful-ok"
    assert rc.status_name(0x040B) == "client-error-attributes-or-values-not-supported"
    assert rc.status_name(0x0501) == "server-error-operation-not-supported"


async def test_client_error_fails_with_status_and_unsupported(fake_ipp):
    async def raw(self, operation, message):
        if operation == IppOperation.VALIDATE_JOB:
            return ipp_response(0x040B, unsupported={"sides": "two-sided-long-edge"})
        return await fake_ipp.raw(self, operation, message)

    with patch.object(IPP, "raw", raw):
        results = await rc.check_printer_jobs(rc.parse_args(["--printer", "h"]))
    first = next(r for r in results if r.num == "4a")
    assert first.status == rc.FAIL
    assert "client-error-attributes-or-values-not-supported" in first.detail
    assert "sides" in first.detail


async def test_operation_not_supported_skips_every_case(fake_ipp):
    fake_ipp.validate_status = 0x0501
    results = await rc.check_printer_jobs(rc.parse_args(["--printer", "h"]))
    cases = [r for r in results if r.num.startswith("4")]
    assert cases
    assert all(r.status == rc.SKIP for r in cases)
    assert "server-error-operation-not-supported" in cases[0].detail


# --- format not supported -----------------------------------------------------


async def test_format_not_in_list_is_skipped_on_reject(fake_ipp):
    fake_ipp.by_format = {"image/png": 0x040A}
    results = await rc.check_printer_jobs(rc.parse_args(["--printer", "h"]))
    png = next(r for r in results if r.num == "4g")
    assert png.status == rc.SKIP
    assert "yazıcı bu formatı desteklemiyor — Plan 3" in png.detail
    jpeg = next(r for r in results if r.num == "4f")
    assert jpeg.status == rc.PASS


# --- scrubbing ------------------------------------------------------------------


def test_scrub_hides_serial_location_uuid():
    attrs = {
        "printer-device-id": "MFG:HP;MDL:DeskJet 2700;SN:CN12345;SERN:XYZ9;CMD:PDF;",
        "printer-location": "Salon",
        "printer-uuid": "urn:uuid:1234-abcd",
        "printer-make-and-model": "HP DeskJet 2700 series",
    }
    out = rc.scrub(attrs)
    assert out["printer-location"] == "<gizlendi>"
    assert out["printer-uuid"] == "<gizlendi>"
    assert "CN12345" not in out["printer-device-id"]
    assert "XYZ9" not in out["printer-device-id"]
    assert "SN:<gizlendi>" in out["printer-device-id"]
    assert "MDL:DeskJet 2700" in out["printer-device-id"]
    assert out["printer-make-and-model"] == "HP DeskJet 2700 series"
    assert attrs["printer-location"] == "Salon"  # input untouched


async def test_json_output_is_scrubbed(fake_ipp, tmp_path):
    fake_ipp.printer = {
        **PRINTER,
        "printer-device-id": "MFG:HP;SN:CN12345;",
        "printer-location": "Salon",
        "printer-uuid": "urn:uuid:gizli-uuid-77",
    }
    out = tmp_path / "out.json"
    await rc.run(rc.parse_args(["--printer", "h", "--json", str(out)]))
    data = json.loads(out.read_text())
    text = out.read_text()
    assert "CN12345" not in text and "Salon" not in text and "gizli-uuid-77" not in text
    assert data["printer_attributes"]["printer-uuid"] == "<gizlendi>"
    assert data["results"][0]["num"] == "1"


# --- unreachable printer ----------------------------------------------------------


async def test_unreachable_printer_fails_check_1_and_skips_ipp(capsys):
    refused = AsyncMock(side_effect=ConnectionRefusedError(111, "Connection refused"))
    with (
        patch.object(rc.asyncio, "open_connection", refused),
        patch.object(rc, "check_escl", AsyncMock(return_value=[])),
    ):
        code = await rc.run(rc.parse_args(["--printer", "127.0.0.1", "--port", "1"]))
    out = capsys.readouterr().out
    assert code == 1
    assert out.splitlines()[0].startswith("❌ KALDI")
    assert "reddetti" in out.splitlines()[0]
    assert "⏭ ATLANDI  2." in out
