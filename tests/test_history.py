"""Tests for the persisted print history."""

import asyncio
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.home_print import history as history_module
from custom_components.home_print.const import CONF_HISTORY_DAYS
from custom_components.home_print.history import MAX_ENTRIES, PrintHistory

from .common import PNG, make_entry, setup_entry
from .convert.samples import blank_pdf


def _add(history, name="a.pdf", job_id=1, state="sent", data=None, mime=None):
    return history.add(
        file_name=name,
        user="Ada",
        job_id=job_id,
        state=state,
        pages=2,
        converted_to=None,
        error=None,
        data=data,
        mime=mime,
    )


def _add_pdf(history, name="a.pdf", data=None):
    return _add(history, name, data=data or blank_pdf(1), mime="application/pdf")


def _dir(hass, entry) -> Path:
    return Path(hass.config.path("home_print", entry.entry_id))


def _key(entry):
    return f"home_print.history.{entry.entry_id}"


async def _flush_save(hass):
    # Store schedules its delayed write with loop.call_at, which the time
    # helpers can't advance; the final-write event flushes the same pending data.
    hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
    await hass.async_block_till_done()


async def test_add_orders_newest_first(hass):
    history = PrintHistory(hass, make_entry())
    first = _add(history, "one.pdf", 1)
    _add(history, "two.pdf", 2)
    assert [e["file_name"] for e in history.entries()] == ["two.pdf", "one.pdf"]
    assert set(first) == {
        "id", "time", "file_name", "user", "job_id", "state", "pages",
        "converted_to", "error", "file", "size", "mime",
    }  # fmt: skip
    assert first["file"] is False
    assert len(first["id"]) == 32


async def test_entries_returns_copy(hass):
    history = PrintHistory(hass, make_entry())
    _add(history)
    history.entries()[0]["state"] = "hacked"
    assert history.entries()[0]["state"] == "sent"


async def test_limit_drops_oldest(hass):
    history = PrintHistory(hass, make_entry())
    for i in range(MAX_ENTRIES + 5):
        _add(history, f"f{i}.pdf", i)
    entries = history.entries()
    assert len(entries) == MAX_ENTRIES
    assert entries[0]["file_name"] == f"f{MAX_ENTRIES + 4}.pdf"
    assert entries[-1]["file_name"] == "f5.pdf"


async def test_delete(hass):
    history = PrintHistory(hass, make_entry())
    keep = _add(history, "keep.pdf", 1)
    gone = _add(history, "gone.pdf", 2)
    assert await history.async_delete(gone["id"]) is True
    assert await history.async_delete(gone["id"]) is False
    assert [e["id"] for e in history.entries()] == [keep["id"]]


async def test_update_state(hass):
    history = PrintHistory(hass, make_entry())
    _add(history, job_id=7)
    assert history.update_state(7, "completed") is True
    assert history.entries()[0]["state"] == "completed"
    assert history.update_state(99, "completed") is False


async def test_persists_and_reloads(hass, hass_storage):
    entry = make_entry()
    history = PrintHistory(hass, entry)
    await history.async_load()
    kept = _add(history, "kept.pdf", 1)
    gone = _add(history, "gone.pdf", 2)
    await history.async_delete(gone["id"])
    await _flush_save(hass)

    saved = hass_storage[_key(entry)]
    assert saved["version"] == 1
    assert [e["id"] for e in saved["data"]["entries"]] == [kept["id"]]

    reloaded = PrintHistory(hass, entry)
    await reloaded.async_load()
    assert [e["id"] for e in reloaded.entries()] == [kept["id"]]


async def test_load_without_file_is_empty(hass, hass_storage):
    history = PrintHistory(hass, make_entry())
    await history.async_load()
    assert history.entries() == []


async def test_entry_setup_loads_saved_history(hass, mock_client, hass_storage):
    entry = make_entry()
    record = {
        "id": "a" * 32, "time": dt_util.utcnow().isoformat(), "file_name": "x.pdf",
        "user": None, "job_id": 3, "state": "sent", "pages": None,
        "converted_to": None, "error": None,
    }  # fmt: skip
    hass_storage[_key(entry)] = {
        "version": 1, "minor_version": 1, "key": _key(entry),
        "data": {"entries": [record]},
    }  # fmt: skip
    await setup_entry(hass, entry)
    # Records saved before files were kept have no file fields.
    assert entry.runtime_data.history.entries() == [
        {**record, "file": False, "size": None, "mime": None}
    ]


async def test_removing_entry_deletes_store(hass, mock_client, hass_storage):
    entry = await setup_entry(hass)
    _add(entry.runtime_data.history)
    await _flush_save(hass)
    assert _key(entry) in hass_storage

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert _key(entry) not in hass_storage


async def test_max_entries_is_200():
    assert MAX_ENTRIES == 200


async def test_add_writes_original_file(hass):
    entry = make_entry()
    history = PrintHistory(hass, entry)
    data = blank_pdf(2)
    record = _add_pdf(history, data=data)
    assert record["size"] == len(data)
    assert record["mime"] == "application/pdf"
    await hass.async_block_till_done()

    [stored] = history.entries()
    assert stored["file"] is True
    path = history.file_path(record["id"])
    assert path == _dir(hass, entry) / f"{record['id']}.pdf"
    assert path.read_bytes() == data


async def test_image_file_extension(hass):
    history = PrintHistory(hass, make_entry())
    record = _add(history, "p.png", data=PNG, mime="image/png")
    await hass.async_block_till_done()
    assert history.file_path(record["id"]).name == f"{record['id']}.png"


async def test_zero_days_writes_no_file(hass):
    entry = make_entry(**{CONF_HISTORY_DAYS: 0})
    history = PrintHistory(hass, entry)
    record = _add_pdf(history)
    await hass.async_block_till_done()
    assert history.entries()[0]["file"] is False
    assert history.file_path(record["id"]) is None
    folder = _dir(hass, entry)
    assert not folder.exists() or not any(folder.iterdir())


async def test_no_data_writes_no_file(hass):
    history = PrintHistory(hass, make_entry())
    record = _add(history)
    await hass.async_block_till_done()
    assert history.entries()[0]["file"] is False
    assert history.file_path(record["id"]) is None


async def test_file_path_rejects_bad_ids(hass):
    history = PrintHistory(hass, make_entry())
    _add_pdf(history)
    await hass.async_block_till_done()
    for bad in ("../" + "a" * 29, "A" * 32, "a" * 31, "", "x" * 32):
        assert history.file_path(bad) is None


async def test_cleanup_removes_expired_record_and_file(hass, freezer):
    entry = make_entry()
    history = PrintHistory(hass, entry)
    old = _add_pdf(history, "old.pdf")
    await hass.async_block_till_done()
    old_path = history.file_path(old["id"])
    assert old_path.exists()

    freezer.tick(timedelta(days=8))
    new = _add_pdf(history, "new.pdf")
    await hass.async_block_till_done()
    await history.async_cleanup()

    assert [e["id"] for e in history.entries()] == [new["id"]]
    assert not old_path.exists()
    assert history.file_path(new["id"]).exists()


async def test_cleanup_keeps_records_within_days(hass, freezer):
    history = PrintHistory(hass, make_entry(**{CONF_HISTORY_DAYS: 30}))
    record = _add_pdf(history)
    await hass.async_block_till_done()
    freezer.tick(timedelta(days=8))
    await history.async_cleanup()
    assert history.entries()[0]["file"] is True
    assert history.file_path(record["id"]).exists()


async def test_zero_days_records_expire_after_seven_days(hass, freezer):
    history = PrintHistory(hass, make_entry(**{CONF_HISTORY_DAYS: 0}))
    _add(history)
    freezer.tick(timedelta(days=6))
    await history.async_cleanup()
    assert len(history.entries()) == 1
    freezer.tick(timedelta(days=2))
    await history.async_cleanup()
    assert history.entries() == []


async def test_days_lowered_to_zero_deletes_kept_files(hass):
    entry = make_entry()
    entry.add_to_hass(hass)
    history = PrintHistory(hass, entry)
    record = _add_pdf(history)
    await hass.async_block_till_done()
    path = history.file_path(record["id"])

    hass.config_entries.async_update_entry(entry, options={CONF_HISTORY_DAYS: 0})
    await history.async_cleanup()
    assert not path.exists()
    assert history.entries()[0]["file"] is False
    assert len(history.entries()) == 1


async def test_size_cap_deletes_oldest_file(hass):
    history = PrintHistory(hass, make_entry())
    data = blank_pdf(1)
    with patch.object(history_module, "MAX_STORAGE_BYTES", len(data) * 2 + 10):
        first = _add_pdf(history, "1.pdf", data)
        await hass.async_block_till_done()
        first_path = history.file_path(first["id"])
        _add_pdf(history, "2.pdf", data)
        await hass.async_block_till_done()
        assert first_path.exists()
        _add_pdf(history, "3.pdf", data)
        await hass.async_block_till_done()

    entries = history.entries()
    assert [e["file_name"] for e in entries] == ["3.pdf", "2.pdf", "1.pdf"]
    assert [e["file"] for e in entries] == [True, True, False]
    assert not first_path.exists()
    assert history.file_path(first["id"]) is None


async def test_delete_removes_file(hass):
    history = PrintHistory(hass, make_entry())
    record = _add_pdf(history)
    await hass.async_block_till_done()
    path = history.file_path(record["id"])
    assert await history.async_delete(record["id"]) is True
    assert not path.exists()


async def test_delete_while_writing_leaves_no_file(hass):
    entry = make_entry()
    history = PrintHistory(hass, entry)
    record = _add_pdf(history)
    assert await history.async_delete(record["id"]) is True
    await hass.async_block_till_done()
    assert not (_dir(hass, entry) / f"{record['id']}.pdf").exists()


async def test_evicted_records_lose_their_files(hass):
    entry = make_entry()
    history = PrintHistory(hass, entry)
    with patch.object(history_module, "MAX_ENTRIES", 2):
        first = _add_pdf(history, "1.pdf")
        await hass.async_block_till_done()
        first_path = history.file_path(first["id"])
        _add_pdf(history, "2.pdf")
        _add_pdf(history, "3.pdf")
        await hass.async_block_till_done()
    assert [e["file_name"] for e in history.entries()] == ["3.pdf", "2.pdf"]
    assert not first_path.exists()
    assert len(list(_dir(hass, entry).iterdir())) == 2


async def test_cleanup_removes_orphan_files(hass):
    entry = make_entry()
    history = PrintHistory(hass, entry)
    record = _add_pdf(history)
    await hass.async_block_till_done()
    orphan = _dir(hass, entry) / f"{'b' * 32}.pdf"
    orphan.write_bytes(b"%PDF-")
    await history.async_cleanup()
    assert not orphan.exists()
    assert history.file_path(record["id"]).exists()


async def test_count_pages_fills_and_caches(hass):
    history = PrintHistory(hass, make_entry())
    record = history.add(
        file_name="a.pdf", user=None, job_id=1, state="sent", pages=None,
        converted_to=None, error=None, data=blank_pdf(3), mime="application/pdf",
    )  # fmt: skip
    await hass.async_block_till_done()
    entries = await history.async_entries()
    assert entries[0]["pages"] == 3
    assert history.entries()[0]["pages"] == 3
    assert record["pages"] is None


async def test_record_and_file_survive_reload(hass, mock_client):
    entry = await setup_entry(hass)
    record = _add_pdf(entry.runtime_data.history)
    # No flush and no block: the unload must wait for the write and save.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    [stored] = entry.runtime_data.history.entries()
    assert stored["id"] == record["id"]
    assert stored["file"] is True
    assert entry.runtime_data.history.file_path(record["id"]).exists()


async def test_setup_runs_periodic_cleanup(hass, mock_client, freezer):
    entry = await setup_entry(hass)
    record = _add_pdf(entry.runtime_data.history)
    await hass.async_block_till_done()
    path = entry.runtime_data.history.file_path(record["id"])
    freezer.tick(timedelta(days=8))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data.history.entries() == []
    assert not path.exists()


async def test_removing_entry_deletes_files(hass, mock_client):
    entry = await setup_entry(hass)
    _add_pdf(entry.runtime_data.history)
    await hass.async_block_till_done()
    folder = _dir(hass, entry)
    assert folder.is_dir()
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert not folder.exists()


async def test_flush_waits_for_a_running_periodic_cleanup(hass, mock_client, freezer):
    entry = await setup_entry(hass)
    history = entry.runtime_data.history
    started = asyncio.Event()
    release = asyncio.Event()
    finished = []

    async def slow_cleanup(now=None):
        started.set()
        await release.wait()
        finished.append(True)

    with patch.object(history, "async_cleanup", slow_cleanup):
        freezer.tick(timedelta(hours=6, seconds=1))
        async_fire_time_changed(hass)
        # Time is frozen here, so wait by yielding rather than sleeping.
        for _ in range(20):
            await asyncio.sleep(0)
        started_ok = started.is_set()
        flush = hass.async_create_task(history.async_flush())
        for _ in range(20):
            await asyncio.sleep(0)
        flushed_early = flush.done()
        release.set()
        await flush
        await hass.async_block_till_done(wait_background_tasks=True)
        assert started_ok
        assert not flushed_early
        assert finished == [True]
