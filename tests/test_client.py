"""Tests for the IPP client."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pyipp import IPPConnectionError, IPPError
from pyipp.enums import IppOperation

from custom_components.home_print.client import (
    CannotConnect,
    HomePrintClient,
    HomePrintError,
    PrinterRejected,
    PrintTimeout,
    UnsupportedOption,
    parse_printer,
)
from custom_components.home_print.const import PRINT_TIMEOUT
from custom_components.home_print.models import (
    JobResult,
    JobStatus,
    JpegLimits,
    MediaCaps,
    PrintOptions,
    normalize_uuid,
)

FIXTURE = Path(__file__).parent / "fixtures" / "printer_generic.json"
DESKJET_FIXTURE = Path(__file__).parent / "fixtures" / "printer_hp_deskjet_4670.json"


def _client(execute: AsyncMock) -> HomePrintClient:
    client = HomePrintClient(
        host="printer.local",
        port=631,
        base_path="/ipp/print",
        tls=False,
        verify_ssl=False,
        session=MagicMock(),
    )
    client._ipp.execute = execute
    client._print_ipp.execute = execute
    return client


def _printer_response() -> dict:
    return {"status-code": 0, "printers": [json.loads(FIXTURE.read_text())]}


async def test_get_printer_parses_fixture():
    client = _client(AsyncMock(return_value=_printer_response()))
    info = await client.get_printer()
    assert info.make_model == "Generic IPPE-4000 series"
    assert info.uuid == "0a1b2c3d-4e5f-6789-abcd-0123456789ef"
    assert info.serial == "ABC123456789"
    assert info.state == "idle"
    assert info.state_reasons == ("none",)
    assert "application/pdf" in info.capabilities.document_formats
    assert info.capabilities.copies_max == 99
    assert info.capabilities.page_ranges is True
    assert "monochrome" in info.capabilities.color_modes
    levels = {m.name: m.level for m in info.markers}
    assert levels["Black ink"] == 80
    assert levels["Cyan ink"] == 55
    assert info.markers[0].kind == "ink-cartridge"
    assert info.markers[0].color == "#000000"


def test_parse_deskjet_4670_fixture():
    info = parse_printer(json.loads(DESKJET_FIXTURE.read_text()))
    assert info.make_model == "HP DeskJet 4670 series"
    caps = info.capabilities
    for fmt in ("image/pwg-raster", "image/urf", "image/jpeg"):
        assert fmt in caps.document_formats
    assert "application/pdf" not in caps.document_formats
    assert caps.raster is not None
    assert {"sgray_8", "srgb_8"} <= caps.raster.pwg_types
    assert caps.raster.pwg_resolutions == (300,)
    assert caps.raster.pwg_sheet_back == "rotated"
    assert {"DM3", "W8-16", "SRGB24"} <= caps.raster.urf
    assert caps.media == MediaCaps(
        "iso_a4_210x297mm", 21000, 29700, (296, 296, 296, 296)
    )
    assert caps.jpeg == JpegLimits(8192, 8192, 12288)
    assert [m.level for m in info.markers] == [20, 40]


def test_parse_generic_fixture_still_works():
    info = parse_printer(json.loads(FIXTURE.read_text()))
    assert info.make_model == "Generic IPPE-4000 series"
    assert "application/pdf" in info.capabilities.document_formats
    assert info.capabilities.copies_max == 99


def test_pwg_resolutions_accepts_list_of_lists():
    data = json.loads(DESKJET_FIXTURE.read_text())
    data["pwg-raster-document-resolution-supported"] = [[300, 300, 3], [600, 600, 3]]
    assert parse_printer(data).capabilities.raster.pwg_resolutions == (300, 600)


def test_marker_unknown_level_is_none():
    info = parse_printer(json.loads(FIXTURE.read_text()))
    yellow = next(m for m in info.markers if m.name == "Yellow ink")
    assert yellow.level is None


@pytest.mark.parametrize(
    ("raw", "state"), [(3, "idle"), (4, "processing"), (5, "stopped")]
)
def test_state_mapping(raw, state):
    data = json.loads(FIXTURE.read_text()) | {"printer-state": raw}
    assert parse_printer(data).state == state


def test_normalize_uuid():
    assert normalize_uuid("urn:uuid:ABC-DEF") == "abc-def"
    assert normalize_uuid("  URN:UUID:ABC-DEF ") == "abc-def"
    assert normalize_uuid("ABC-DEF") == "abc-def"


async def test_print_job_sends_attributes():
    execute = AsyncMock(
        side_effect=[
            _printer_response(),
            {"status-code": 0, "jobs": [{"job-id": 42, "job-state": 3}]},
        ]
    )
    client = _client(execute)
    result = await client.print_job(
        b"%PDF-1.4",
        document_format="application/pdf",
        job_name="Test",
        user_name="ada",
        options=PrintOptions(
            copies=2,
            sides="two-sided-long-edge",
            color_mode="color",
            page_ranges="1-3,5",
        ),
    )
    assert result == JobResult(job_id=42, state="pending")
    operation, message = execute.await_args_list[-1].args
    assert operation == IppOperation.PRINT_JOB
    op_attrs = message["operation-attributes-tag"]
    assert op_attrs["document-format"] == "application/pdf"
    assert op_attrs["job-name"] == "Test"
    assert op_attrs["requesting-user-name"] == "ada"
    job_attrs = message["job-attributes-tag"]
    assert job_attrs["copies"] == 2
    assert job_attrs["sides"] == "two-sided-long-edge"
    assert job_attrs["print-color-mode"] == "color"
    assert [(str(r), r.encode()) for r in job_attrs["page-ranges"]] == [
        ("1-3", b"\x00\x00\x00\x01\x00\x00\x00\x03"),
        ("5", b"\x00\x00\x00\x05\x00\x00\x00\x05"),
    ]
    assert message["data"] == b"%PDF-1.4"


async def test_print_job_omits_unset_color_mode_and_page_ranges():
    execute = AsyncMock(
        side_effect=[
            _printer_response(),
            {"status-code": 0, "jobs": [{"job-id": 7, "job-state": 5}]},
        ]
    )
    client = _client(execute)
    result = await client.print_job(
        b"x",
        document_format="application/pdf",
        job_name="j",
        user_name="u",
        options=PrintOptions(),
    )
    assert result == JobResult(job_id=7, state="processing")
    job_attrs = execute.await_args_list[-1].args[1]["job-attributes-tag"]
    assert "print-color-mode" not in job_attrs
    assert "page-ranges" not in job_attrs


async def test_print_job_without_page_ranges_for_converted_job():
    # Converted jobs carry only the selected pages: page-ranges is neither
    # checked against page-ranges-supported nor sent.
    response = _printer_response()
    response["printers"][0]["page-ranges-supported"] = False
    execute = AsyncMock(
        side_effect=[
            response,
            {"status-code": 0, "jobs": [{"job-id": 7, "job-state": 3}]},
        ]
    )
    client = _client(execute)
    await client.print_job(
        b"RaS2",
        document_format="image/pwg-raster",
        job_name="j",
        user_name="u",
        options=PrintOptions(copies=2, page_ranges="2-3"),
        send_page_ranges=False,
    )
    job_attrs = execute.await_args_list[-1].args[1]["job-attributes-tag"]
    assert "page-ranges" not in job_attrs
    assert job_attrs["copies"] == 2


@pytest.mark.parametrize(
    ("options", "name"),
    [
        (PrintOptions(page_ranges="1-2"), "page_ranges"),
        (PrintOptions(sides="bogus"), "sides"),
        (PrintOptions(color_mode="sepia"), "color_mode"),
        (PrintOptions(copies=100), "copies"),
    ],
)
async def test_print_job_skips_unsupported_option(options, name):
    response = _printer_response()
    if name == "page_ranges":
        response["printers"][0]["page-ranges-supported"] = False
    execute = AsyncMock(return_value=response)
    client = _client(execute)
    with pytest.raises(UnsupportedOption) as exc:
        await client.print_job(
            b"x",
            document_format="application/pdf",
            job_name="j",
            user_name="u",
            options=options,
        )
    assert exc.value.name == name
    assert execute.await_count == 1  # only Get-Printer-Attributes, nothing sent


async def test_connection_error_raises_cannot_connect():
    client = _client(AsyncMock(side_effect=IPPConnectionError("boom")))
    with pytest.raises(CannotConnect):
        await client.get_printer()


async def test_ipp_error_status_raises_rejected():
    execute = AsyncMock(
        side_effect=[
            _printer_response(),
            IPPError("Unexpected printer status code", {"status-code": 0x040A}),
        ]
    )
    client = _client(execute)
    with pytest.raises(PrinterRejected) as exc:
        await client.print_job(
            b"x",
            document_format="application/pdf",
            job_name="j",
            user_name="u",
            options=PrintOptions(),
        )
    assert exc.value.status == "client-error-document-format-not-supported"


def test_print_job_message_serializes_all_attributes():
    """Real pyipp serializer must keep sides/color-mode/page-ranges."""
    from pyipp.serializer import encode_dict

    from custom_components.home_print.client import _parse_page_ranges

    raw = encode_dict(
        {
            "version": (2, 0),
            "operation": IppOperation.PRINT_JOB,
            "request-id": 1,
            "operation-attributes-tag": {"job-name": "j"},
            "job-attributes-tag": {
                "copies": 1,
                "sides": "one-sided",
                "print-color-mode": "color",
                "page-ranges": _parse_page_ranges("1-3,5"),
            },
            "data": b"DATA",
        }
    )
    assert b"sides" in raw
    assert b"print-color-mode" in raw
    assert b"page-ranges" in raw
    assert b"\x00\x00\x00\x01\x00\x00\x00\x03" in raw
    assert raw.endswith(b"\x03DATA")


async def test_mock_client_fixture(mock_client):
    info = await mock_client.get_printer()
    assert info.state == "idle"
    job = await mock_client.print_job(
        b"x",
        document_format="application/pdf",
        job_name="j",
        user_name="u",
        options=PrintOptions(),
    )
    assert job == JobResult(job_id=42, state="pending")


async def test_print_job_uses_long_timeout():
    client = _client(AsyncMock())
    status = AsyncMock(return_value=_printer_response())
    job = AsyncMock(return_value={"status-code": 0, "jobs": [{"job-id": 1}]})
    client._ipp.execute = status
    client._print_ipp.execute = job
    assert client._ipp.request_timeout == 8
    assert client._print_ipp.request_timeout == PRINT_TIMEOUT == 300
    await client.print_job(
        b"%PDF-1.4",
        document_format="application/pdf",
        job_name="j",
        user_name="u",
        options=PrintOptions(),
    )
    assert status.await_args.args[0] == IppOperation.GET_PRINTER_ATTRIBUTES
    assert job.await_args.args[0] == IppOperation.PRINT_JOB


async def test_print_job_timeout_raises_print_timeout():
    timeout = IPPConnectionError("Timeout occurred while connecting to IPP server.")
    timeout.__cause__ = TimeoutError()
    client = _client(AsyncMock(side_effect=[_printer_response(), timeout]))
    with pytest.raises(PrintTimeout):
        await client.print_job(
            b"%PDF-1.4",
            document_format="application/pdf",
            job_name="j",
            user_name="u",
            options=PrintOptions(),
        )


async def test_status_timeout_still_cannot_connect():
    timeout = IPPConnectionError("Timeout occurred while connecting to IPP server.")
    timeout.__cause__ = TimeoutError()
    client = _client(AsyncMock(side_effect=timeout))
    with pytest.raises(CannotConnect):
        await client.get_printer()


async def test_print_job_timeout_override_reaches_the_print_request(monkeypatch):
    from pyipp import IPP

    client = _client(AsyncMock())
    client._ipp.execute = AsyncMock(return_value=_printer_response())
    seen: list[tuple[IppOperation, float]] = []

    async def execute(self, operation, message):
        seen.append((operation, self.request_timeout))
        return {"status-code": 0, "jobs": [{"job-id": 1}]}

    monkeypatch.setattr(IPP, "execute", execute)
    args = {
        "document_format": "image/pwg-raster",
        "job_name": "j",
        "user_name": "u",
        "options": PrintOptions(),
    }
    del client._print_ipp.execute  # use the class method patched above
    await client.print_job(b"RaS2", timeout=465, **args)
    await client.print_job(b"RaS2", **args)
    assert seen == [
        (IppOperation.PRINT_JOB, 465),
        (IppOperation.PRINT_JOB, PRINT_TIMEOUT),
    ]
    assert client._print_ipp.request_timeout == PRINT_TIMEOUT  # not mutated


async def test_print_job_timeout_override_still_raises_print_timeout(monkeypatch):
    from pyipp import IPP

    timeout = IPPConnectionError("Timeout occurred while connecting to IPP server.")
    timeout.__cause__ = TimeoutError()
    client = _client(AsyncMock())
    client._ipp.execute = AsyncMock(return_value=_printer_response())
    monkeypatch.setattr(IPP, "execute", AsyncMock(side_effect=timeout))
    with pytest.raises(PrintTimeout):
        await client.print_job(
            b"RaS2",
            document_format="image/pwg-raster",
            job_name="j",
            user_name="u",
            options=PrintOptions(),
            timeout=400,
        )


@pytest.mark.parametrize(
    ("code", "name"),
    [
        (3, "pending"),
        (4, "held"),
        (5, "processing"),
        (6, "stopped"),
        (7, "canceled"),
        (8, "aborted"),
        (9, "completed"),
    ],
)
async def test_get_job_maps_states(code, name):
    execute = AsyncMock(
        return_value={
            "status-code": 0,
            "jobs": [
                {
                    "job-id": 42,
                    "job-state": code,
                    "job-state-reasons": "none",
                    "job-impressions-completed": 3,
                    "job-media-sheets-completed": 2,
                }
            ],
        }
    )
    client = _client(execute)
    job = await client.get_job(42)
    assert job == JobStatus(job_id=42, state=name, reasons=(), impressions=3, sheets=2)
    operation, message = execute.await_args.args
    assert operation == IppOperation.GET_JOB_ATTRIBUTES
    op_attrs = message["operation-attributes-tag"]
    assert op_attrs["job-id"] == 42
    assert set(op_attrs["requested-attributes"]) == {
        "job-state",
        "job-state-reasons",
        "job-impressions-completed",
        "job-media-sheets-completed",
    }


async def test_get_job_reasons_and_missing_counters():
    execute = AsyncMock(
        return_value={
            "status-code": 0,
            "jobs": [
                {
                    "job-id": 7,
                    "job-state": 8,
                    "job-state-reasons": ["job-canceled-by-user", "aborted-by-system"],
                }
            ],
        }
    )
    job = await _client(execute).get_job(7)
    assert job.reasons == ("job-canceled-by-user", "aborted-by-system")
    assert job.impressions is None
    assert job.sheets is None


async def test_get_job_uses_short_timeout_and_maps_connection_error():
    execute = AsyncMock(side_effect=IPPConnectionError("down"))
    client = _client(execute)
    with pytest.raises(CannotConnect):
        await client.get_job(1)
    assert client._ipp.execute is execute  # status client, not the print one


async def test_get_job_no_job_in_response():
    execute = AsyncMock(return_value={"status-code": 0, "jobs": []})
    with pytest.raises(HomePrintError):
        await _client(execute).get_job(1)
