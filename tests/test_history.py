"""Tests for the persisted print history."""

from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE

from custom_components.home_print.history import MAX_ENTRIES, PrintHistory

from .common import make_entry, setup_entry


def _add(history, name="a.pdf", job_id=1, state="sent"):
    return history.add(
        file_name=name,
        user="Ada",
        job_id=job_id,
        state=state,
        pages=2,
        converted_to=None,
        error=None,
    )


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
        "converted_to", "error",
    }  # fmt: skip
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
    assert history.delete(gone["id"]) is True
    assert history.delete(gone["id"]) is False
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
    history.delete(gone["id"])
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
        "id": "a" * 32, "time": "2026-01-01T00:00:00+00:00", "file_name": "x.pdf",
        "user": None, "job_id": 3, "state": "sent", "pages": None,
        "converted_to": None, "error": None,
    }  # fmt: skip
    hass_storage[_key(entry)] = {
        "version": 1, "minor_version": 1, "key": _key(entry),
        "data": {"entries": [record]},
    }  # fmt: skip
    await setup_entry(hass, entry)
    assert entry.runtime_data.history.entries() == [record]


async def test_removing_entry_deletes_store(hass, mock_client, hass_storage):
    entry = await setup_entry(hass)
    _add(entry.runtime_data.history)
    await _flush_save(hass)
    assert _key(entry) in hass_storage

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert _key(entry) not in hass_storage
