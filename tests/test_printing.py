"""Tests for the shared printing path."""

from dataclasses import replace

import pytest
from homeassistant.core import Event
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.home_print.client import (
    CannotConnect,
    PrinterRejected,
    PrintTimeout,
    UnsupportedOption,
)
from custom_components.home_print.const import (
    CONF_DEFAULT_COLOR_MODE,
    CONF_DEFAULT_SIDES,
    CONF_MAX_FILE_MB,
    EVENT_JOB,
)
from custom_components.home_print.models import PrintOptions
from custom_components.home_print.printing import (
    FileTooLarge,
    FormatNotSupportedByPrinter,
    InvalidPrintOption,
    OptionNotSupportedByPrinter,
    PrinterRejectedJob,
    PrintError,
    PrinterUnavailable,
    PrintTimedOut,
    UnsupportedFileType,
    async_print,
    build_options,
    sniff_format,
)

from .common import JPEG, PDF, PNG, make_entry, setup_entry


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
    caps = replace(
        coordinator.data.capabilities, document_formats=frozenset({"image/urf"})
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


async def test_async_print_skips_format_check_when_offline(hass, mock_client):
    entry = await setup_entry(hass)
    # Last poll failed: the cached capabilities may be stale, so skip the
    # local check and let the client report the real problem.
    entry.runtime_data.coordinator.last_update_success = False
    mock_client.print_job.side_effect = CannotConnect("offline")

    with pytest.raises(PrinterUnavailable):
        await async_print(
            hass, entry, PNG, file_name="a.png", options=PrintOptions(), user=None
        )
    mock_client.print_job.assert_called_once()


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
