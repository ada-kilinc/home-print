"""Tests for the scan runner."""

import asyncio

import pytest
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.home_print import scanning
from custom_components.home_print.const import DOMAIN, EVENT_SCAN
from custom_components.home_print.escl.errors import (
    AdfEmpty,
    EsclError,
    ScannerBusy,
    ScannerUnavailable,
)
from custom_components.home_print.escl.models import ScannerCaps, SourceCaps
from custom_components.home_print.scanning import (
    ScanError,
    ScanOptionError,
    ScanRequest,
    async_start_scan,
    validate_request,
)

from .common import CAPS, scan_jpeg, setup_scanner_entry

ADF_CAPS = ScannerCaps(
    "2.0",
    None,
    None,
    {
        "platen": CAPS.sources["platen"],
        "adf": SourceCaps(0, 2550, 0, 3507, ("color",), (300,), ("image/jpeg",)),
    },
)

REQ = ScanRequest(source="platen", color_mode="color", resolution=300, format="pdf")


async def _run(hass, entry, req=REQ, user="Ada"):
    state = await async_start_scan(hass, entry, req, user)
    await entry.runtime_data.scanner.task
    return state


@pytest.fixture
async def entry(hass, tmp_path, mock_client, mock_escl, mock_find_scanner):
    mock_escl.client.scan.return_value = [scan_jpeg()]
    return await setup_scanner_entry(hass, tmp_path, mock_find_scanner)


async def test_scan_creates_pdf_record(hass, tmp_path, entry, mock_escl):
    state = await _run(hass, entry, ScanRequest("platen", "color", 300, "pdf", "doc"))
    assert state.state == "done"
    assert state.error is None
    assert state.pages == 1
    assert len(state.scan_id) == 32
    record = state.record
    assert record["mime"] == "application/pdf"
    assert record["name"] == "doc"
    assert record["user"] == "Ada"
    assert record["pages"] == 1
    data = (tmp_path / "media" / record["path"]).read_bytes()
    assert data.startswith(b"%PDF-")
    settings = mock_escl.client.scan.call_args.args[1]
    assert (settings.source, settings.mime) == ("platen", "image/jpeg")
    assert entry.runtime_data.scanner.archive.entries() == [record]


async def test_scan_jpeg_single_page(hass, tmp_path, entry):
    jpeg = scan_jpeg()
    entry.runtime_data.scanner.client.scan.return_value = [jpeg]
    state = await _run(hass, entry, ScanRequest("platen", "color", 300, "jpeg"))
    assert state.record["mime"] == "image/jpeg"
    assert state.record["path"].endswith(".jpg")
    assert (tmp_path / "media" / state.record["path"]).read_bytes() == jpeg


async def test_adf_multi_page_jpeg_becomes_pdf(
    hass, tmp_path, mock_client, mock_escl, mock_find_scanner
):
    mock_escl.client.scan.return_value = [scan_jpeg(), scan_jpeg()]
    entry = await setup_scanner_entry(hass, tmp_path, mock_find_scanner, ADF_CAPS)
    state = await _run(hass, entry, ScanRequest("adf", "color", 300, "jpeg"))
    assert mock_escl.client.scan.call_args.args[1].source == "adf"
    assert state.record["mime"] == "application/pdf"
    assert state.record["pages"] == 2
    assert state.record["source"] == "adf"


async def test_pages_follow_on_page_callback(hass, entry):
    seen = []

    async def scan(caps, settings, on_page=None):
        on_page(1)
        seen.append(entry.runtime_data.scanner.active.pages)
        on_page(2)
        seen.append(entry.runtime_data.scanner.active.pages)
        return [scan_jpeg(), scan_jpeg()]

    entry.runtime_data.scanner.client.scan = scan
    await _run(hass, entry)
    assert seen == [1, 2]


async def test_append_adds_pages_to_record(hass, tmp_path, entry):
    first = await _run(hass, entry, ScanRequest("platen", "color", 300, "pdf", "doc"))
    entry.runtime_data.scanner.client.scan.return_value = [scan_jpeg(), scan_jpeg()]
    second = await _run(
        hass,
        entry,
        ScanRequest("platen", "color", 300, "pdf", append_to=first.record["id"]),
    )
    assert second.state == "done"
    assert second.record["id"] == first.record["id"]
    assert second.record["pages"] == 3
    assert len(entry.runtime_data.scanner.archive.entries()) == 1
    from custom_components.home_print.convert.render import count_pages

    path = tmp_path / "media" / second.record["path"]
    assert count_pages(path.read_bytes()) == 3


async def test_append_rejects_unknown_and_non_pdf(hass, entry):
    req = ScanRequest("platen", "color", 300, "pdf", append_to="a" * 32)
    with pytest.raises(ScanError) as err:
        await async_start_scan(hass, entry, req, None)
    assert err.value.code == "not_found"
    entry.runtime_data.scanner.client.scan.return_value = [scan_jpeg()]
    jpg = await _run(hass, entry, ScanRequest("platen", "color", 300, "jpeg"))
    req = ScanRequest("platen", "color", 300, "pdf", append_to=jpg.record["id"])
    with pytest.raises(ScanOptionError):
        await async_start_scan(hass, entry, req, None)
    req = ScanRequest("platen", "color", 300, "jpeg", append_to=jpg.record["id"])
    with pytest.raises(ScanOptionError):
        await async_start_scan(hass, entry, req, None)


async def test_second_scan_busy(hass, entry):
    gate = asyncio.Event()

    async def scan(caps, settings, on_page=None):
        await gate.wait()
        return [scan_jpeg()]

    entry.runtime_data.scanner.client.scan = scan
    first = await async_start_scan(hass, entry, REQ, None)
    assert first.state == "scanning"
    assert first.pages == 0
    with pytest.raises(ScannerBusy):
        await async_start_scan(hass, entry, REQ, None)
    gate.set()
    await entry.runtime_data.scanner.task
    assert first.state == "done"
    # A finished scan doesn't block the next one.
    entry.runtime_data.scanner.client.scan = lambda *a, **k: _pages()
    second = await _run(hass, entry)
    assert second.scan_id != first.scan_id


async def _pages():
    return [scan_jpeg()]


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ScannerUnavailable(), "scanner_unavailable"),
        (AdfEmpty(), "adf_empty"),
        (ScannerBusy(), "scanner_busy"),
        (EsclError("invalid_option"), "invalid_option"),
        (EsclError("bad_response"), "scan_failed"),
        (RuntimeError("boom"), "scan_failed"),
    ],
)
async def test_scanner_errors_set_error_state(hass, entry, error, code, caplog):
    entry.runtime_data.scanner.client.scan.side_effect = error
    state = await _run(hass, entry)
    assert (state.state, state.error) == ("error", code)
    assert state.record is None
    assert entry.runtime_data.scanner.archive.entries() == []
    # The scanner is free again.
    entry.runtime_data.scanner.client.scan.side_effect = None
    entry.runtime_data.scanner.client.scan.return_value = [scan_jpeg()]
    assert (await _run(hass, entry)).state == "done"


async def test_bad_page_sets_bad_scan(hass, entry):
    entry.runtime_data.scanner.client.scan.return_value = [b"not an image"]
    state = await _run(hass, entry)
    assert (state.state, state.error) == ("error", "bad_scan")


async def test_invalid_option_rejected(hass, entry):
    for req in (
        ScanRequest("adf", "color", 300, "pdf"),
        ScanRequest("platen", "gray", 300, "pdf"),
        ScanRequest("platen", "color", 600, "pdf"),
        ScanRequest("platen", "color", 300, "tiff"),
    ):
        with pytest.raises(ScanOptionError):
            await async_start_scan(hass, entry, req, None)
    assert entry.runtime_data.scanner.active is None
    entry.runtime_data.scanner.client.scan.assert_not_called()


async def test_no_scanner(hass, tmp_path, mock_client):
    from .common import setup_entry

    entry = await setup_entry(hass)
    with pytest.raises(ScanError) as err:
        await async_start_scan(hass, entry, REQ, None)
    assert err.value.code == "no_scanner"


async def test_event_fired(hass, entry):
    events = async_capture_events(hass, EVENT_SCAN)
    await _run(hass, entry, ScanRequest("platen", "color", 300, "pdf", "doc"))
    entry.runtime_data.scanner.client.scan.side_effect = ScannerUnavailable()
    await _run(hass, entry, ScanRequest("platen", "color", 300, "pdf", "x"))
    await hass.async_block_till_done()
    assert [e.data for e in events] == [
        {
            "entry_id": entry.entry_id,
            "user": "Ada",
            "name": "doc",
            "pages": 1,
            "result": "done",
        },
        {
            "entry_id": entry.entry_id,
            "user": "Ada",
            "name": "x",
            "pages": 0,
            "result": "error",
        },
    ]


async def test_finished_state_kept_then_dropped(hass, entry, monkeypatch):
    state = await _run(hass, entry)
    runtime = entry.runtime_data.scanner
    assert scanning.active_state(runtime) is state
    monkeypatch.setattr(scanning.time, "monotonic", lambda: state.finished_at + 601)
    assert scanning.active_state(runtime) is None
    assert runtime.active is None


async def test_unload_cancels_running_scan(hass, entry):
    started = asyncio.Event()

    async def scan(caps, settings, on_page=None):
        started.set()
        await asyncio.sleep(3600)

    entry.runtime_data.scanner.client.scan = scan
    state = await async_start_scan(hass, entry, REQ, None)
    task = entry.runtime_data.scanner.task
    await started.wait()
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert state.state == "error"
    assert task.cancelled()


async def test_wait_returns_final_state(hass, entry):
    state = await scanning.async_scan_and_wait(hass, entry, REQ, None)
    assert state.state == "done"


def test_validate_request_picks_png_when_no_jpeg():
    caps = ScannerCaps(
        "2.0",
        None,
        None,
        {"platen": SourceCaps(0, 1, 0, 1, ("color",), (300,), ("image/png",))},
    )
    assert validate_request(caps, REQ).mime == "image/png"
    assert validate_request(CAPS, REQ).mime == "image/jpeg"


def test_defaults_prefer_300_platen_color():
    caps = ScannerCaps(
        "2.0",
        None,
        None,
        {
            "adf": SourceCaps(0, 1, 0, 1, ("gray", "bw"), (200, 600), ()),
            "platen": SourceCaps(0, 1, 0, 1, ("gray",), (150, 600, 400), ()),
        },
    )
    assert scanning.scan_defaults(caps) == {
        "source": "platen",
        "color_mode": "gray",
        "resolution": 400,
        "format": "pdf",
    }
    only_adf = ScannerCaps("2.0", None, None, {"adf": caps.sources["adf"]})
    assert scanning.scan_defaults(only_adf)["source"] == "adf"
    assert scanning.scan_defaults(CAPS) == {
        "source": "platen",
        "color_mode": "color",
        "resolution": 300,
        "format": "pdf",
    }
    assert DOMAIN


async def test_unload_during_service_scan_gives_translated_error(hass, entry):
    from homeassistant.exceptions import HomeAssistantError

    started = asyncio.Event()

    async def scan(caps, settings, on_page=None):
        started.set()
        await asyncio.sleep(3600)

    entry.runtime_data.scanner.client.scan = scan
    call = hass.async_create_task(
        hass.services.async_call(
            DOMAIN, "scan", {"config_entry_id": entry.entry_id}, blocking=True
        )
    )
    await started.wait()
    assert await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(HomeAssistantError) as err:
        await call
    assert err.value.translation_key == "scan_error_scan_failed"


async def test_cancelled_service_call_keeps_scan_running(hass, entry):
    gate = asyncio.Event()

    async def scan(caps, settings, on_page=None):
        await gate.wait()
        return [scan_jpeg()]

    runtime = entry.runtime_data.scanner
    runtime.client.scan = scan
    waiter = hass.async_create_task(
        scanning.async_scan_and_wait(hass, entry, REQ, None)
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not runtime.task.done()
    gate.set()
    await runtime.task
    assert runtime.active.state == "done"


async def test_unload_cancels_scan_before_archive_flush(hass, entry):
    order = []
    runtime = entry.runtime_data.scanner

    async def scan(caps, settings, on_page=None):
        try:
            await asyncio.sleep(3600)
        finally:
            order.append("cancelled")

    runtime.client.scan = scan
    orig = runtime.archive.async_flush

    async def flush():
        order.append("flush")
        await orig()

    runtime.archive.async_flush = flush
    await async_start_scan(hass, entry, REQ, None)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert order == ["cancelled", "flush"]
    assert runtime.task.done()


def test_resolutions_above_scan_pixel_cap_are_not_offered():
    # 8.5x11.7 in platen: 1200 dpi is ~143 MP, over SCAN_MAX_PIXELS.
    src = SourceCaps(0, 2550, 0, 3507, ("color",), (300, 600, 1200), ("image/jpeg",))
    caps = ScannerCaps("2.0", None, None, {"platen": src})
    assert scanning.allowed_resolutions(src) == (300, 600)
    assert validate_request(caps, ScanRequest("platen", "color", 600, "pdf"))
    with pytest.raises(ScanOptionError):
        validate_request(caps, ScanRequest("platen", "color", 1200, "pdf"))
    only_big = SourceCaps(0, 2550, 0, 3507, ("color",), (1200, 2400), ())
    assert scanning.allowed_resolutions(only_big) == ()


async def test_append_target_deleted_during_scan_saves_new_record(
    hass, tmp_path, entry
):
    first = await _run(hass, entry, ScanRequest("platen", "color", 300, "pdf", "doc"))
    gate = asyncio.Event()

    async def scan(caps, settings, on_page=None):
        await gate.wait()
        return [scan_jpeg(), scan_jpeg()]

    runtime = entry.runtime_data.scanner
    runtime.client.scan = scan
    req = ScanRequest("platen", "color", 300, "pdf", append_to=first.record["id"])
    state = await async_start_scan(hass, entry, req, "Ada")
    assert await runtime.archive.async_delete(first.record["id"])
    gate.set()
    await runtime.task
    assert state.state == "done"
    assert state.record["id"] != first.record["id"]
    assert state.record["pages"] == 2
    assert state.record["mime"] == "application/pdf"
    assert [r["id"] for r in runtime.archive.entries()] == [state.record["id"]]


async def test_append_target_file_removed_during_scan_saves_new_record(
    hass, tmp_path, entry
):
    first = await _run(hass, entry, ScanRequest("platen", "color", 300, "pdf", "doc"))
    gate = asyncio.Event()

    async def scan(caps, settings, on_page=None):
        await gate.wait()
        return [scan_jpeg()]

    runtime = entry.runtime_data.scanner
    runtime.client.scan = scan
    req = ScanRequest("platen", "color", 300, "pdf", append_to=first.record["id"])
    state = await async_start_scan(hass, entry, req, None)
    (tmp_path / "media" / first.record["path"]).unlink()
    gate.set()
    await runtime.task
    assert state.state == "done"
    assert state.record["id"] != first.record["id"]
    assert state.record["pages"] == 1


async def test_cancel_scan_sets_canceled(hass, entry):
    started = asyncio.Event()

    async def scan(caps, settings, on_page=None):
        started.set()
        await asyncio.sleep(3600)

    runtime = entry.runtime_data.scanner
    runtime.client.scan = scan
    events = async_capture_events(hass, EVENT_SCAN)
    state = await async_start_scan(hass, entry, REQ, None)
    await started.wait()
    result = await scanning.async_cancel_scan(entry, state.scan_id)
    assert result is state
    assert state.state == "error"
    assert state.error == "canceled"
    assert runtime.task.done()
    assert events[-1].data["result"] == "error"
    # Cancelling again (or a finished scan) changes nothing.
    assert await scanning.async_cancel_scan(entry, state.scan_id) is state
    assert await scanning.async_cancel_scan(entry, "0" * 32) is None


def test_unusable_source_hidden_from_defaults_and_rejected():
    huge = SourceCaps(0, 2550, 0, 3507, ("color",), (1200,), ("image/jpeg",))
    ok = SourceCaps(0, 2550, 0, 3507, ("gray",), (300,), ("image/jpeg",))
    caps = ScannerCaps("2.0", None, None, {"platen": huge, "adf": ok})
    assert scanning.usable_sources(caps) == ("adf",)
    defaults = scanning.scan_defaults(caps)
    assert defaults["source"] == "adf"
    assert defaults["resolution"] == 300
    with pytest.raises(ScanOptionError):
        validate_request(caps, ScanRequest("platen", "color", 1200, "pdf"))


async def test_scan_start_and_end_refresh_entities(hass, entry, monkeypatch):
    """The scanner status sensor shows 'scanning' right away, not at next poll."""
    coordinator = entry.runtime_data.coordinator
    calls = []
    original = coordinator.async_update_listeners

    def spy():
        calls.append(entry.runtime_data.scanner.active.state)
        original()

    monkeypatch.setattr(coordinator, "async_update_listeners", spy)
    await _run(hass, entry)
    assert calls[0] == "scanning"
    assert calls[-1] == "done"
