"""Tests for the shared printing path."""

import json
import time
import tracemalloc
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.core import Event
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from PIL import Image
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.home_print.client import (
    CannotConnect,
    PrinterRejected,
    PrintTimeout,
    UnsupportedOption,
    parse_printer,
)
from custom_components.home_print.const import (
    CONF_DEFAULT_COLOR_MODE,
    CONF_DEFAULT_SIDES,
    CONF_MAX_FILE_MB,
    EVENT_JOB,
)
from custom_components.home_print.convert import pipeline
from custom_components.home_print.models import PrintOptions
from custom_components.home_print.printing import (
    FileTooLarge,
    FormatNotSupportedByPrinter,
    ImageTooLargeError,
    InvalidDocumentError,
    InvalidPrintOption,
    OptionNotSupportedByPrinter,
    OutputTooLargeError,
    PrinterRejectedJob,
    PrintError,
    PrinterUnavailable,
    PrintTimedOut,
    TooManyPagesError,
    UnsupportedFileType,
    async_print,
    build_options,
    sniff_format,
)

from .common import JPEG, PDF, PNG, make_entry, setup_entry
from .convert import pwg_decoder
from .convert.samples import (
    blank_pdf,
    image_bytes,
    noisy_pdf,
    page_image,
    pdf_from_images,
)

DESKJET = parse_printer(
    json.loads(
        (Path(__file__).parent / "fixtures/printer_hp_deskjet_4670.json").read_text()
    )
)
PWG = "image/pwg-raster"
A4_300DPI_RGB_BYTES = 2480 * 3508 * 3


def test_sniff_format():
    assert sniff_format(PDF) == "application/pdf"
    assert sniff_format(JPEG) == "image/jpeg"
    assert sniff_format(PNG) == "image/png"
    assert sniff_format(b"hello world") is None
    assert sniff_format(b"") is None
    # Only the content decides: a "report.pdf" holding PNG bytes is PNG.
    fake_pdf_named_file = PNG
    assert sniff_format(fake_pdf_named_file) == "image/png"


async def test_async_print_rejects_too_large(hass, mock_client):
    entry = await setup_entry(hass, make_entry(**{CONF_MAX_FILE_MB: 1}))
    events = async_capture_events(hass, EVENT_JOB)
    data = PDF + b"\x00" * (1024 * 1024 + 1 - len(PDF))

    with pytest.raises(FileTooLarge) as exc:
        await async_print(
            hass, entry, data, file_name="big.pdf", options=PrintOptions(), user=None
        )
    await hass.async_block_till_done()

    assert exc.value.translation_placeholders == {"max": "1"}
    mock_client.print_job.assert_not_called()
    assert len(events) == 1
    assert events[0].data["result"] == "error"
    assert events[0].data["error"] == "file_too_large"
    assert events[0].data["job_id"] is None


async def test_async_print_rejects_unknown_type(hass, mock_client):
    entry = await setup_entry(hass)
    with pytest.raises(UnsupportedFileType):
        await async_print(
            hass,
            entry,
            b"plain text",
            file_name="notes.txt",
            options=PrintOptions(),
            user=None,
        )
    mock_client.print_job.assert_not_called()


async def test_async_print_rejects_format_not_supported_by_printer(hass, mock_client):
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data.coordinator
    # No route: the printer takes neither the file's format nor a raster one.
    caps = replace(
        coordinator.data.capabilities,
        document_formats=frozenset({"application/vnd.hp-PCL"}),
    )
    coordinator.async_set_updated_data(replace(coordinator.data, capabilities=caps))

    with pytest.raises(FormatNotSupportedByPrinter):
        await async_print(
            hass, entry, PDF, file_name="a.pdf", options=PrintOptions(), user=None
        )
    mock_client.print_job.assert_not_called()


async def test_async_print_offline_raises_unavailable(hass, mock_client):
    entry = await setup_entry(hass)
    events = async_capture_events(hass, EVENT_JOB)
    mock_client.print_job.side_effect = CannotConnect("timeout")

    with pytest.raises(PrinterUnavailable):
        await async_print(
            hass, entry, PDF, file_name="a.pdf", options=PrintOptions(), user=None
        )
    await hass.async_block_till_done()
    assert events[0].data["error"] == "printer_unavailable"
    assert entry.runtime_data.coordinator.last_job.state == "error"


async def test_async_print_after_failed_poll_rechecks_printer(hass, mock_client):
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data.coordinator
    # The coordinator keeps its old data after a failed poll, so "no data"
    # never tells us the printer is gone; one quick status request does.
    coordinator.last_update_success = False
    mock_client.get_printer.reset_mock()
    mock_client.print_job.side_effect = CannotConnect("offline")

    with pytest.raises(PrinterUnavailable):
        await async_print(
            hass, entry, PDF, file_name="a.pdf", options=PrintOptions(), user=None
        )
    mock_client.get_printer.assert_awaited_once()
    mock_client.print_job.assert_called_once()
    assert coordinator.last_update_success  # the fresh answer was kept


@pytest.mark.parametrize("data_cached", [True, False])
async def test_async_print_unreachable_after_failed_poll_skips_conversion(
    hass, mock_client, data_cached
):
    entry = await setup_entry(hass)
    events = async_capture_events(hass, EVENT_JOB)
    coordinator = entry.runtime_data.coordinator
    coordinator.last_update_success = False
    if not data_cached:
        coordinator.data = None  # defensive: setup always fetches data
    mock_client.get_printer.side_effect = CannotConnect("offline")

    with (
        patch.object(pipeline, "prepare", wraps=pipeline.prepare) as prepare,
        patch.object(coordinator, "async_set_last_job"),
        pytest.raises(PrinterUnavailable),
    ):
        await async_print(
            hass, entry, PDF, file_name="a.pdf", options=PrintOptions(), user=None
        )
    await hass.async_block_till_done()
    prepare.assert_not_called()
    mock_client.print_job.assert_not_called()
    assert events[0].data["error"] == "printer_unavailable"


async def test_async_print_maps_unsupported_option(hass, mock_client):
    entry = await setup_entry(hass)
    mock_client.print_job.side_effect = UnsupportedOption("sides")
    with pytest.raises(OptionNotSupportedByPrinter) as exc:
        await async_print(
            hass, entry, PDF, file_name="a.pdf", options=PrintOptions(), user=None
        )
    assert exc.value.translation_placeholders == {"option": "sides"}


async def test_async_print_maps_printer_rejected(hass, mock_client):
    entry = await setup_entry(hass)
    mock_client.print_job.side_effect = PrinterRejected("client-error-not-possible")
    with pytest.raises(PrinterRejectedJob) as exc:
        await async_print(
            hass, entry, PDF, file_name="a.pdf", options=PrintOptions(), user=None
        )
    assert exc.value.translation_placeholders == {"status": "client-error-not-possible"}
    assert isinstance(exc.value, HomeAssistantError)


@pytest.mark.parametrize(
    "options",
    [
        PrintOptions(copies=0),
        PrintOptions(page_ranges="3-1"),
        PrintOptions(page_ranges="0-2"),
        PrintOptions(page_ranges="1-x"),
        PrintOptions(page_ranges="1,,2"),
        PrintOptions(page_ranges="-3"),
        PrintOptions(page_ranges="1-99999999999"),
        PrintOptions(page_ranges="10000"),
    ],
)
async def test_async_print_rejects_invalid_options(hass, mock_client, options):
    entry = await setup_entry(hass)
    with pytest.raises(InvalidPrintOption) as exc:
        await async_print(
            hass, entry, PDF, file_name="a.pdf", options=options, user=None
        )
    assert isinstance(exc.value, ServiceValidationError)
    mock_client.print_job.assert_not_called()


async def test_async_print_fires_event_and_sets_last_job(
    hass, mock_client, hass_admin_user
):
    entry = await setup_entry(hass)
    events = async_capture_events(hass, EVENT_JOB)

    result = await async_print(
        hass,
        entry,
        PDF,
        file_name="report.pdf",
        options=PrintOptions(copies=2),
        user=hass_admin_user,
    )
    await hass.async_block_till_done()

    assert result.job_id == 42
    kwargs = mock_client.print_job.call_args.kwargs
    assert mock_client.print_job.call_args.args == (PDF,)
    assert kwargs["document_format"] == "application/pdf"
    assert kwargs["user_name"] == hass_admin_user.name
    assert kwargs["options"].copies == 2

    event: Event = events[0]
    assert event.data == {
        "entry_id": entry.entry_id,
        "file_name": "report.pdf",
        "user_id": hass_admin_user.id,
        "user_name": hass_admin_user.name,
        "job_id": 42,
        "result": "sent",
        "error": None,
        "converted_to": None,
        "pages": None,
    }
    last = entry.runtime_data.coordinator.last_job
    assert last.file_name == "report.pdf"
    assert last.job_id == 42
    assert last.state == "pending"
    assert last.user == hass_admin_user.name


async def test_async_print_without_user_uses_home_assistant(hass, mock_client):
    entry = await setup_entry(hass)
    events = async_capture_events(hass, EVENT_JOB)
    await async_print(
        hass, entry, PDF, file_name="a.pdf", options=PrintOptions(), user=None
    )
    await hass.async_block_till_done()
    assert mock_client.print_job.call_args.kwargs["user_name"] == "Home Assistant"
    assert events[0].data["user_id"] is None


async def test_async_print_turkish_file_name(hass, mock_client):
    entry = await setup_entry(hass)
    events = async_capture_events(hass, EVENT_JOB)
    await async_print(
        hass,
        entry,
        PDF,
        file_name="öğrenci_belgesi.pdf",
        options=PrintOptions(),
        user=None,
    )
    await hass.async_block_till_done()
    assert mock_client.print_job.call_args.kwargs["job_name"] == "öğrenci_belgesi.pdf"
    assert events[0].data["file_name"] == "öğrenci_belgesi.pdf"


async def test_async_print_sanitizes_file_name(hass, mock_client):
    entry = await setup_entry(hass)
    await async_print(
        hass,
        entry,
        PDF,
        file_name="../../etc/x\n\x00y.pdf",
        options=PrintOptions(),
        user=None,
    )
    assert mock_client.print_job.call_args.kwargs["job_name"] == "xy.pdf"


async def test_build_options_applies_entry_defaults(hass, mock_client):
    entry = await setup_entry(
        hass,
        make_entry(
            **{
                CONF_DEFAULT_SIDES: "two-sided-long-edge",
                CONF_DEFAULT_COLOR_MODE: "monochrome",
            }
        ),
    )
    assert build_options(entry) == PrintOptions(
        copies=1, sides="two-sided-long-edge", color_mode="monochrome"
    )
    assert build_options(entry, sides="one-sided", color_mode="color") == (
        PrintOptions(copies=1, sides="one-sided", color_mode="color")
    )
    # "auto" means: let the printer decide, send nothing.
    assert build_options(entry, color_mode="auto").color_mode is None
    with pytest.raises(InvalidPrintOption):
        build_options(entry, sides="sideways")


async def test_async_print_timeout_maps_to_print_timeout(hass, mock_client):
    entry = await setup_entry(hass)
    events = async_capture_events(hass, EVENT_JOB)
    mock_client.print_job.side_effect = PrintTimeout("slow")

    with pytest.raises(PrintTimedOut) as exc:
        await async_print(
            hass, entry, PDF, file_name="a.pdf", options=PrintOptions(), user=None
        )
    await hass.async_block_till_done()
    assert exc.value.key == "print_timeout"
    assert exc.value.http_status == 504
    assert events[0].data["error"] == "print_timeout"


async def test_async_print_accepts_max_page_number(hass, mock_client):
    entry = await setup_entry(hass)
    await async_print(
        hass,
        entry,
        PDF,
        file_name="a.pdf",
        options=PrintOptions(page_ranges="1-9999"),
        user=None,
    )
    mock_client.print_job.assert_called_once()


async def test_async_print_unexpected_error_still_reports(hass, mock_client):
    entry = await setup_entry(hass)
    events = async_capture_events(hass, EVENT_JOB)
    mock_client.print_job.side_effect = RuntimeError("bug")

    with pytest.raises(PrintError) as exc:
        await async_print(
            hass, entry, PDF, file_name="a.pdf", options=PrintOptions(), user=None
        )
    await hass.async_block_till_done()
    assert type(exc.value) is PrintError
    assert exc.value.key == "print_failed"
    assert events[0].data["result"] == "error"
    assert events[0].data["error"] == "print_failed"
    assert entry.runtime_data.coordinator.last_job.state == "error"


# --- conversion -----------------------------------------------------------------


async def _deskjet_entry(hass, mock_client):
    mock_client.get_printer.return_value = DESKJET
    return await setup_entry(hass)


async def test_async_print_converts_pdf_for_deskjet(hass, mock_client):
    entry = await _deskjet_entry(hass, mock_client)
    events = async_capture_events(hass, EVENT_JOB)
    options = PrintOptions(copies=2, sides="two-sided-long-edge", page_ranges="2-3")

    await async_print(
        hass, entry, blank_pdf(3), file_name="a.pdf", options=options, user=None
    )
    await hass.async_block_till_done()

    (data,), kwargs = mock_client.print_job.call_args
    assert kwargs["document_format"] == PWG
    assert kwargs["send_page_ranges"] is False
    # Options go through unchanged: copies and sides are still IPP attributes.
    assert kwargs["options"] == options
    # 2 pages sent: 300 s for the upload plus 15 s per page.
    assert kwargs["timeout"] == 300 + 15 * 2
    assert isinstance(data, (bytes, bytearray))
    pages = pwg_decoder.decode(data)
    assert len(pages) == 2
    assert pages[0].header["NumCopies"] == 1
    assert events[0].data["converted_to"] == PWG
    assert events[0].data["pages"] == 2
    assert events[0].data["result"] == "sent"


async def test_async_print_passthrough_sends_page_ranges(hass, mock_client):
    entry = await setup_entry(hass)
    events = async_capture_events(hass, EVENT_JOB)
    await async_print(
        hass,
        entry,
        PDF,
        file_name="a.pdf",
        options=PrintOptions(page_ranges="1-2"),
        user=None,
    )
    await hass.async_block_till_done()
    kwargs = mock_client.print_job.call_args.kwargs
    assert kwargs["document_format"] == "application/pdf"
    assert kwargs["send_page_ranges"] is True
    assert kwargs["timeout"] is None  # the client's PRINT_TIMEOUT
    assert events[0].data["converted_to"] is None
    assert events[0].data["pages"] is None


async def test_async_print_prepares_in_executor(hass, mock_client):
    entry = await _deskjet_entry(hass, mock_client)
    with patch.object(
        hass, "async_add_executor_job", wraps=hass.async_add_executor_job
    ) as executor:
        await async_print(
            hass,
            entry,
            blank_pdf(1),
            file_name="a.pdf",
            options=PrintOptions(),
            user=None,
        )
    targets = [call.args[0] for call in executor.call_args_list]
    assert pipeline.prepare in targets


async def test_async_print_corrupt_pdf_is_invalid_document(hass, mock_client):
    entry = await _deskjet_entry(hass, mock_client)
    events = async_capture_events(hass, EVENT_JOB)
    with pytest.raises(InvalidDocumentError) as exc:
        await async_print(
            hass, entry, PDF, file_name="a.pdf", options=PrintOptions(), user=None
        )
    await hass.async_block_till_done()
    assert exc.value.key == "invalid_document"
    assert exc.value.http_status == 400
    mock_client.print_job.assert_not_called()
    assert events[0].data["error"] == "invalid_document"
    assert events[0].data["converted_to"] is None


async def test_async_print_too_many_pages(hass, mock_client):
    entry = await _deskjet_entry(hass, mock_client)
    with pytest.raises(TooManyPagesError) as exc:
        await async_print(
            hass,
            entry,
            blank_pdf(201),
            file_name="long.pdf",
            options=PrintOptions(),
            user=None,
        )
    assert exc.value.key == "too_many_pages"
    assert exc.value.http_status == 400
    assert exc.value.translation_placeholders == {"limit": "200"}
    mock_client.print_job.assert_not_called()


async def test_async_print_page_range_past_end_is_invalid_option(hass, mock_client):
    entry = await _deskjet_entry(hass, mock_client)
    with pytest.raises(InvalidPrintOption) as exc:
        await async_print(
            hass,
            entry,
            blank_pdf(2),
            file_name="a.pdf",
            options=PrintOptions(page_ranges="5-6"),
            user=None,
        )
    assert exc.value.translation_placeholders == {"option": "page_ranges"}


async def test_async_print_no_route_is_format_not_supported(hass, mock_client):
    info = replace(
        DESKJET,
        capabilities=replace(
            DESKJET.capabilities,
            document_formats=frozenset({"application/vnd.hp-PCL"}),
        ),
    )
    mock_client.get_printer.return_value = info
    entry = await setup_entry(hass)
    with pytest.raises(FormatNotSupportedByPrinter) as exc:
        await async_print(
            hass,
            entry,
            blank_pdf(1),
            file_name="a.pdf",
            options=PrintOptions(),
            user=None,
        )
    assert exc.value.http_status == 422
    assert exc.value.translation_placeholders == {"format": "application/pdf"}


async def _traced_print(
    hass, entry, pdf, **kwargs
) -> tuple[int, float, PrintError | None]:
    """Print ``pdf``; return tracemalloc's peak, the time and any PrintError."""
    error = None
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        start = time.monotonic()
        try:
            await async_print(hass, entry, pdf, user=None, **kwargs)
        except PrintError as err:
            error = err
        elapsed = time.monotonic() - start
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak, elapsed, error


async def test_async_print_large_pdf_end_to_end(hass, mock_client):
    """Review Focus 5: 150 pages, one page bitmap in memory at a time.

    tracemalloc sees Python and numpy buffers (numpy reports its data
    allocations to it); Pillow's and PDFium's own C heaps are invisible to
    it. The bound includes everything it sees: the output buffer too.
    """
    entry = await _deskjet_entry(hass, mock_client)
    pdf = pdf_from_images([page_image(595, 842)] * 150)

    peak, elapsed, error = await _traced_print(
        hass, entry, pdf, file_name="big.pdf", options=PrintOptions()
    )
    assert error is None

    (data,), kwargs = mock_client.print_job.call_args
    assert kwargs["document_format"] == PWG
    assert kwargs["timeout"] == 300 + 15 * 150
    assert pwg_decoder.parse_header(data[4 : 4 + 1796])["TotalPageCount"] == 150
    assert elapsed < 60
    assert peak < 3 * A4_300DPI_RGB_BYTES


async def test_async_print_colour_scan_output_is_bounded(
    hass, mock_client, monkeypatch
):
    """C1: incompressible pages stop at the output budget, memory included."""
    entry = await _deskjet_entry(hass, mock_client)
    events = async_capture_events(hass, EVENT_JOB)
    budget = 60 * 1024 * 1024  # ~2 colour pages at 300 dpi (~25 MB each)
    monkeypatch.setattr(pipeline, "MAX_OUTPUT_BYTES", budget)
    pdf = noisy_pdf(4, dpi=300)

    peak, _, error = await _traced_print(
        hass, entry, pdf, file_name="scan.pdf", options=PrintOptions()
    )
    await hass.async_block_till_done()

    assert isinstance(error, OutputTooLargeError)
    assert error.key == "output_too_large"
    assert error.http_status == 413
    assert error.translation_placeholders == {"limit": "60"}
    mock_client.print_job.assert_not_called()
    assert events[0].data["error"] == "output_too_large"
    # Everything traced, output included: the budget, plus the input and a
    # few page buffers (bitmap, its numpy copy, the encoded page).
    assert peak < budget + len(pdf) + 3 * A4_300DPI_RGB_BYTES


async def test_async_print_too_large_image_has_its_own_error(hass, mock_client):
    """M1: not "damaged or password protected"."""
    entry = await _deskjet_entry(hass, mock_client)
    events = async_capture_events(hass, EVENT_JOB)
    png = image_bytes(Image.new("L", (5000, 5001), 255), "PNG")
    with pytest.raises(ImageTooLargeError) as exc:
        await async_print(
            hass, entry, png, file_name="huge.png", options=PrintOptions(), user=None
        )
    await hass.async_block_till_done()
    assert exc.value.key == "image_too_large"
    assert exc.value.http_status == 400
    assert exc.value.translation_placeholders == {"limit": "25"}
    assert events[0].data["error"] == "image_too_large"


async def test_async_print_unsupported_image_format_is_unsupported_type(
    hass, mock_client
):
    """M1: a format Pillow knows but we don't print is a file-type error."""
    entry = await _deskjet_entry(hass, mock_client)
    gif = image_bytes(Image.new("L", (10, 10), 255), "GIF")
    with (
        patch(
            "custom_components.home_print.printing.sniff_format",
            return_value="image/png",
        ),
        pytest.raises(UnsupportedFileType) as exc,
    ):
        await async_print(
            hass, entry, gif, file_name="a.png", options=PrintOptions(), user=None
        )
    assert exc.value.key == "unsupported_file_type"
    assert exc.value.http_status == 400


@pytest.mark.parametrize("lang", ["en", "tr"])
def test_new_error_messages_are_translated(lang):
    root = Path(__file__).parent.parent / "custom_components" / "home_print"
    strings = json.loads((root / "strings.json").read_text())["exceptions"]
    messages = json.loads((root / f"translations/{lang}.json").read_text())[
        "exceptions"
    ]
    assert set(messages) == set(strings)
    assert "{limit}" in messages["output_too_large"]["message"]
    assert "{limit}" in messages["image_too_large"]["message"]


async def test_async_print_success_adds_history(hass, mock_client, hass_admin_user):
    entry = await setup_entry(hass)
    await async_print(
        hass,
        entry,
        PDF,
        file_name="report.pdf",
        options=PrintOptions(),
        user=hass_admin_user,
    )
    [record] = entry.runtime_data.history.entries()
    assert record["file_name"] == "report.pdf"
    assert record["user"] == hass_admin_user.name
    assert record["job_id"] == 42
    assert record["state"] == "sent"
    assert record["error"] is None


async def test_async_print_error_adds_history(hass, mock_client):
    entry = await setup_entry(hass)
    with pytest.raises(UnsupportedFileType):
        await async_print(
            hass,
            entry,
            b"nope",
            file_name="a.txt",
            options=PrintOptions(),
            user=None,
        )
    [record] = entry.runtime_data.history.entries()
    assert record["state"] == "error"
    assert record["error"] == "unsupported_file_type"
    assert record["job_id"] is None
    assert record["user"] == "Home Assistant"
