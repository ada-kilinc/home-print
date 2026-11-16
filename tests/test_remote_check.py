"""Tests for scripts/remote_check.py (loaded by path; scripts/ is no package)."""

from __future__ import annotations

import copy
import importlib.util
import json
import struct
import subprocess
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


# Real Get-Printer-Attributes answer of Ada's printer (pyipp-parsed form):
# no PDF/PNG, takes JPEG, PWG raster and URF.
DESKJET = json.loads(
    (Path(__file__).parent / "fixtures" / "printer_hp_deskjet_4670.json").read_text()
)
_PARSED = b"<parsed printer attributes>"
LONG_EDGE = "two-sided-long-edge"


class FakeIPP:
    """Records every request sent through ``IPP.raw`` / ``IPP.execute``."""

    def __init__(self, printer=PRINTER, validate_status=0x0000, by_format=None):
        self.ops: list[IppOperation] = []
        self.messages: list[dict[str, Any]] = []
        self.printer = printer
        self.parsed = False  # True: hand ``printer`` to the script as parsed
        self.validate_status = validate_status
        self.by_format = by_format or {}
        self.unsupported_by_format: dict[str, dict[str, Any]] = {}
        self.next_job_id = 7
        self.duplex_jobs: set[int] = set()
        # job-media-sheets-completed per finished job; None: not reported
        self.sheets_reported: int | None = 1

    def use_deskjet(self) -> None:
        self.printer = copy.deepcopy(DESKJET)
        self.parsed = True

    async def raw(self, ipp_self, operation, message):
        self.ops.append(operation)
        self.messages.append(message)
        # make sure the real serializer can encode what the script built
        encode_dict(ipp_self._message(operation, message))
        if operation == IppOperation.GET_PRINTER_ATTRIBUTES:
            if self.parsed:  # collections etc. that ipp_response can't encode
                return _PARSED
            return ipp_response(0, printer=self.printer)
        if operation == IppOperation.VALIDATE_JOB:
            fmt = message["operation-attributes-tag"]["document-format"]
            return ipp_response(
                self.by_format.get(fmt, self.validate_status),
                unsupported=self.unsupported_by_format.get(fmt),
            )
        if operation == IppOperation.PRINT_JOB:
            job_id = self.next_job_id
            self.next_job_id += 1
            if message["job-attributes-tag"].get("sides", "one-sided") != "one-sided":
                self.duplex_jobs.add(job_id)
            return ipp_response(0, job={"job-id": job_id, "job-state": 3})
        if operation == IppOperation.GET_JOB_ATTRIBUTES:
            job_id = message["operation-attributes-tag"]["job-id"]
            job = {
                "job-id": job_id,
                "job-state": 9,
                "job-impressions-completed": 2 if job_id in self.duplex_jobs else 1,
            }
            if self.sheets_reported is not None:
                job["job-media-sheets-completed"] = self.sheets_reported
            return ipp_response(0, job=job)
        raise AssertionError(operation)

    def sent(self, operation):
        return [
            m for op, m in zip(self.ops, self.messages, strict=True) if op == operation
        ]

    def validated(self):
        return [
            (m["operation-attributes-tag"]["document-format"], m["job-attributes-tag"])
            for m in self.sent(IppOperation.VALIDATE_JOB)
        ]


def _by_num(out: str) -> dict[str, str]:
    """Result lines of the script's output keyed by check number."""
    lines = {}
    for line in out.splitlines():
        if line.startswith(tuple(rc.LABELS.values())):
            lines[line.split(".")[0].split()[-1]] = line
    return lines


@pytest.fixture
def fake_ipp():
    fake = FakeIPP()
    real_parse = rc.parse_ipp

    async def raw(self, operation, message):
        return await fake.raw(self, operation, message)

    def parse(data):
        if data == _PARSED:
            return {"status-code": 0, "printers": [copy.deepcopy(fake.printer)]}
        return real_parse(data)

    execute = AsyncMock(side_effect=AssertionError("execute not expected"))
    with (
        patch.object(IPP, "raw", raw),
        patch.object(IPP, "execute", execute),
        patch.object(rc, "parse_ipp", parse),
        patch.object(rc, "POLL_INTERVAL", 0),
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


async def test_print_flag_sends_exactly_two_jobs(fake_ipp, capsys):
    code = await rc.run(rc.parse_args(["--printer", "10.0.0.5", "--print"]))
    jobs = fake_ipp.sent(IppOperation.PRINT_JOB)
    assert len(jobs) == 2
    formats = [j["operation-attributes-tag"]["document-format"] for j in jobs]
    # Duplex PDF first: the JPEG only goes once its sheet count is known.
    assert formats == ["application/pdf", "image/jpeg"]  # PDF printer: as is
    assert code == 0
    assert "completed" in capsys.readouterr().out


async def test_deskjet_no_print_flag_sends_no_job(fake_ipp):
    fake_ipp.use_deskjet()
    code = await rc.run(rc.parse_args(["--printer", "10.0.0.5"]))
    assert IppOperation.PRINT_JOB not in fake_ipp.ops
    fake_ipp.execute.assert_not_called()
    assert code == 0


async def test_deskjet_print_sends_converted_duplex_pdf_then_jpeg(fake_ipp, capsys):
    fake_ipp.use_deskjet()
    code = await rc.run(rc.parse_args(["--printer", "10.0.0.5", "--print"]))
    out = capsys.readouterr().out
    jobs = fake_ipp.sent(IppOperation.PRINT_JOB)
    assert len(jobs) == 2
    first, second = jobs
    op1, op2 = first["operation-attributes-tag"], second["operation-attributes-tag"]
    assert op1["document-format"] == "image/pwg-raster"
    assert op1["job-name"] == "Home Print test 1/2 — PDF çift taraf"
    attrs1 = first["job-attributes-tag"]
    assert attrs1["sides"] == "two-sided-long-edge"
    assert attrs1["print-color-mode"] == "monochrome"
    assert attrs1["copies"] == 1
    assert first["data"][:4] == b"RaS2"
    assert "page-ranges" not in attrs1
    assert op2["document-format"] == "image/jpeg"
    assert op2["job-name"] == "Home Print test 2/2 — JPEG"
    assert second["data"][:2] == b"\xff\xd8"
    assert second["job-attributes-tag"]["copies"] == 1
    # validated with the same attributes right before sending
    assert ("image/pwg-raster", attrs1) in fake_ipp.validated()
    assert "2 iş" in out and "en fazla 2 kağıt" in out
    assert out.index("2 iş") < out.index("7b.") < out.index("7a.")
    results = _by_num(out)
    assert "✅ GEÇTİ" in results["7a"]
    assert "✅ GEÇTİ" in results["7b"]
    assert "impressions: 2" in results["7b"]
    assert code == 0


async def test_deskjet_jpeg_validate_variants(fake_ipp):
    fake_ipp.use_deskjet()
    await rc.run(rc.parse_args(["--printer", "10.0.0.5"]))
    sent = fake_ipp.validated()
    assert ("image/jpeg", {}) in sent
    assert ("image/jpeg", {"sides": "two-sided-long-edge"}) in sent
    assert ("image/jpeg", {"print-color-mode": "monochrome"}) in sent
    assert ("image/jpeg", {"print-color-mode": "color"}) in sent
    assert ("image/jpeg", {"copies": 2}) in sent


async def test_deskjet_converted_format_validate_cases(fake_ipp, capsys):
    fake_ipp.use_deskjet()
    await rc.run(rc.parse_args(["--printer", "10.0.0.5"]))
    sent = fake_ipp.validated()
    pwg = "image/pwg-raster"
    assert (pwg, {}) in sent
    assert (pwg, {"sides": "two-sided-long-edge"}) in sent
    assert (pwg, {"print-color-mode": "monochrome"}) in sent
    assert (pwg, {"print-color-mode": "color"}) in sent
    assert all("data" not in m for m in fake_ipp.sent(IppOperation.VALIDATE_JOB))
    assert "image/pwg-raster" in capsys.readouterr().out


async def test_deskjet_conversion_check_counts_four_pages(fake_ipp, tmp_path):
    fake_ipp.use_deskjet()
    out = tmp_path / "out.json"
    await rc.run(rc.parse_args(["--printer", "h", "--json", str(out)]))
    results = {r["num"]: r for r in json.loads(out.read_text())["results"]}
    check = results["6"]
    assert check["status"] == rc.PASS, check
    assert "4 sayfa" in check["detail"]
    assert "image/pwg-raster" in check["detail"]


async def test_convert_modules_missing_skips_but_jpeg_still_prints(
    fake_ipp, tmp_path, capsys
):
    fake_ipp.use_deskjet()
    with patch.object(rc, "PKG_DIR", tmp_path / "yok"):
        code = await rc.run(rc.parse_args(["--printer", "h", "--print"]))
    out = capsys.readouterr().out
    jobs = fake_ipp.sent(IppOperation.PRINT_JOB)
    assert len(jobs) == 1
    assert jobs[0]["operation-attributes-tag"]["document-format"] == "image/jpeg"
    lines = _by_num(out)
    assert lines["6"].startswith("⏭ ATLANDI")
    assert "convert modülleri bulunamadı" in lines["6"]
    assert lines["7b"].startswith("⏭ ATLANDI")
    assert lines["7a"].startswith("✅ GEÇTİ")
    assert not any(f == "image/pwg-raster" for f, _ in fake_ipp.validated())
    assert code == 0


def test_load_convert_does_not_run_package_init():
    conv, reason = rc.load_convert()
    assert conv is not None, reason
    package = sys.modules[rc.STANDALONE]
    assert not hasattr(package, "async_setup_entry")
    caps = conv.capabilities(DESKJET)
    assert conv.pipeline.choose_target("application/pdf", caps) == "image/pwg-raster"


def test_load_convert_missing_dir(tmp_path):
    conv, reason = rc.load_convert(tmp_path)
    assert conv is None
    assert "convert modülleri bulunamadı" in reason


async def test_stopped_printer_gets_no_print_job(fake_ipp, capsys):
    fake_ipp.use_deskjet()
    fake_ipp.printer["printer-state"] = 5
    await rc.run(rc.parse_args(["--printer", "h", "--print"]))
    assert IppOperation.PRINT_JOB not in fake_ipp.ops
    out = capsys.readouterr().out
    assert "⏭ ATLANDI  7a." in out
    assert "⏭ ATLANDI  7b." in out


async def test_not_accepting_jobs_gets_no_print_job(fake_ipp):
    fake_ipp.use_deskjet()
    fake_ipp.printer["printer-is-accepting-jobs"] = False
    await rc.run(rc.parse_args(["--printer", "h", "--print"]))
    assert IppOperation.PRINT_JOB not in fake_ipp.ops


async def test_failed_validate_skips_that_print_job(fake_ipp, capsys):
    fake_ipp.use_deskjet()
    fake_ipp.by_format = {"image/pwg-raster": 0x040B}
    await rc.run(rc.parse_args(["--printer", "h", "--print"]))
    jobs = fake_ipp.sent(IppOperation.PRINT_JOB)
    assert [j["operation-attributes-tag"]["document-format"] for j in jobs] == [
        "image/jpeg"
    ]
    assert "⏭ ATLANDI  7b." in capsys.readouterr().out


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


def test_load_convert_missing_dependency_names_it():
    with patch.dict(sys.modules, {"pypdfium2": None}):
        conv, reason = rc.load_convert()
        assert rc.STANDALONE not in sys.modules  # half-loaded package removed
    assert conv is None
    assert "pypdfium2 yüklü değil" in reason


def _duplex_job_pages(fake_ipp) -> int:
    jobs = fake_ipp.sent(IppOperation.PRINT_JOB)
    assert len(jobs) == 2
    pdf_job = jobs[0]  # 7b goes first
    assert "sides" not in pdf_job["job-attributes-tag"]
    assert pdf_job["operation-attributes-tag"]["document-format"] == "image/pwg-raster"
    return rc.count_raster_pages(pdf_job["data"], "image/pwg-raster")


async def test_no_duplex_advertised_prints_front_page_only(fake_ipp, capsys):
    fake_ipp.use_deskjet()
    fake_ipp.printer["sides-supported"] = ["one-sided"]
    code = await rc.run(rc.parse_args(["--printer", "h", "--print"]))
    out = capsys.readouterr().out
    assert _duplex_job_pages(fake_ipp) == 1  # 1 sheet, never 2
    assert "en fazla 2 kağıt" in out
    assert "sadece ön yüz" in _by_num(out)["7b"]
    assert code == 0


async def test_sides_ignored_by_validate_prints_front_page_only(fake_ipp, capsys):
    fake_ipp.use_deskjet()
    fake_ipp.by_format = {"image/pwg-raster": 0x0001}
    fake_ipp.unsupported_by_format = {"image/pwg-raster": {"sides": LONG_EDGE}}
    await rc.run(rc.parse_args(["--printer", "h", "--print"]))
    out = capsys.readouterr().out
    assert _duplex_job_pages(fake_ipp) == 1
    line = _by_num(out)["7b"]
    assert line.startswith("✅ GEÇTİ")
    assert "sadece ön yüz" in line


async def test_capabilities_error_does_not_crash_run(fake_ipp, tmp_path, capsys):
    fake_ipp.use_deskjet()
    out_json = tmp_path / "out.json"

    def broken(self, attrs):
        raise ValueError("garip özellik")

    with patch.object(rc.Convert, "capabilities", broken):
        code = await rc.run(
            rc.parse_args(["--printer", "h", "--print", "--json", str(out_json)])
        )
    out = capsys.readouterr().out
    assert "Özet" in out
    results = {r["num"]: r for r in json.loads(out_json.read_text())["results"]}
    assert results["6"]["status"] == rc.FAIL
    assert "garip özellik" in results["6"]["detail"]
    assert results["4m"]["status"] == rc.SKIP
    assert results["7b"]["status"] == rc.SKIP
    jobs = fake_ipp.sent(IppOperation.PRINT_JOB)
    assert [j["operation-attributes-tag"]["document-format"] for j in jobs] == [
        "image/jpeg"
    ]
    assert code == 1


def test_missing_pyipp_gives_clean_turkish_error():
    code = (
        "import runpy, sys; sys.modules['pyipp'] = None; "
        f"sys.argv = ['remote_check.py', '--help']; runpy.run_path({str(SCRIPT)!r})"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert "pyipp yüklü değil" in proc.stderr
    assert "pip install" in proc.stderr


# --- the 2-sheet guarantee (M5) ---------------------------------------------


@pytest.mark.parametrize(
    ("sheets", "why"),
    [
        (2, "2 kağıt kullandı"),  # printer said OK to duplex, printed simplex
        (None, "kaç kağıt kullandığı bilinmiyor"),  # duplex: 2 impressions = ?
    ],
)
async def test_jpeg_skipped_unless_duplex_job_used_one_sheet(
    fake_ipp, capsys, sheets, why
):
    fake_ipp.use_deskjet()
    fake_ipp.sheets_reported = sheets
    code = await rc.run(rc.parse_args(["--printer", "h", "--print"]))
    out = capsys.readouterr().out
    jobs = fake_ipp.sent(IppOperation.PRINT_JOB)
    assert [j["operation-attributes-tag"]["document-format"] for j in jobs] == [
        "image/pwg-raster"
    ]
    line = _by_num(out)["7a"]
    assert line.startswith("⏭ ATLANDI")
    assert why in line
    assert "en fazla 2 kağıt" in line
    assert code == 0


async def test_front_only_job_without_sheet_count_uses_impressions(fake_ipp, capsys):
    fake_ipp.use_deskjet()
    fake_ipp.printer["sides-supported"] = ["one-sided"]
    fake_ipp.sheets_reported = None  # 1 impression on a one-sided job: 1 sheet
    await rc.run(rc.parse_args(["--printer", "h", "--print"]))
    formats = [
        j["operation-attributes-tag"]["document-format"]
        for j in fake_ipp.sent(IppOperation.PRINT_JOB)
    ]
    assert formats == ["image/pwg-raster", "image/jpeg"]
    assert _by_num(capsys.readouterr().out)["7a"].startswith("✅ GEÇTİ")


def test_sheets_used():
    duplex = rc.PlannedJob("7b", "t", "n", "f", b"", {"sides": LONG_EDGE}, sheets=1)
    simplex = rc.PlannedJob("7b", "t", "n", "f", b"", {"copies": 1}, sheets=1)
    done = {"job-state": 9}
    assert rc.sheets_used(duplex, {**done, "job-media-sheets-completed": 1}) == 1
    assert rc.sheets_used(duplex, {**done, "job-media-sheets-completed": 2}) == 2
    assert rc.sheets_used(duplex, {**done, "job-impressions-completed": 1}) == 1
    # 2 impressions may be 1 duplex sheet or 2 simplex ones: unknown.
    assert rc.sheets_used(duplex, {**done, "job-impressions-completed": 2}) is None
    assert rc.sheets_used(simplex, {**done, "job-impressions-completed": 1}) == 1
    assert rc.sheets_used(simplex, done) is None  # unknown
    # Not finished: it may still print more.
    running = {"job-state": 5, "job-media-sheets-completed": 0}
    assert rc.sheets_used(duplex, running) is None
