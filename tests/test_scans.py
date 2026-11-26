"""Tests for the scan archive."""

import shutil
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE
from homeassistant.util import dt as dt_util

from custom_components.home_print.const import CONF_SCAN_DAYS, CONF_SCAN_MAX_MB
from custom_components.home_print.scans import (
    ScanArchive,
    clean_scan_name,
    default_scan_name,
    media_root,
)

from .common import make_entry

PDF = b"%PDF-1.4 fake"


def _setup(hass, tmp_path, **options):
    hass.config.media_dirs = {"local": str(tmp_path / "media")}
    return ScanArchive(hass, make_entry(**options))


async def _add(archive, name="doc", data=PDF, mime="application/pdf"):
    return await archive.async_add(
        name=name,
        data=data,
        mime=mime,
        pages=1,
        user="Ada",
        source="platen",
        color_mode="color",
        resolution=300,
    )


def _scans_dir(tmp_path) -> Path:
    return tmp_path / "media" / "home_print" / "scans"


async def test_add_writes_under_media_month_folder(hass, tmp_path):
    archive = _setup(hass, tmp_path)
    record = await _add(archive, "report")
    month = dt_util.as_local(dt_util.utcnow()).strftime("%Y-%m")
    assert record["path"] == f"home_print/scans/{month}/report.pdf"
    assert (tmp_path / "media" / record["path"]).read_bytes() == PDF
    assert set(record) == {
        "id", "time", "name", "user", "pages", "size", "mime", "path",
        "source", "color_mode", "resolution",
    }  # fmt: skip
    assert record["size"] == len(PDF)
    assert archive.entries()[0]["id"] == record["id"]
    jpg = await _add(archive, "photo", b"\xff\xd8x", "image/jpeg")
    assert jpg["path"].endswith("/photo.jpg")


async def test_add_without_name_uses_default(hass, tmp_path):
    archive = _setup(hass, tmp_path)
    record = await _add(archive, None)
    assert record["name"].startswith("scan_")


async def test_name_collision_appends_counter(hass, tmp_path):
    archive = _setup(hass, tmp_path)
    first = await _add(archive, "same")
    second = await _add(archive, "same")
    third = await _add(archive, "same")
    assert first["name"] == "same"
    assert second["name"] == "same (2)"
    assert third["name"] == "same (3)"
    assert second["path"].endswith("same (2).pdf")


async def test_clean_name_strips_path_and_limits_80(hass, tmp_path):
    name = clean_scan_name("../../etc/x", "fb")
    assert "/" not in name
    assert name == "_.._etc_x"
    assert clean_scan_name('a\\b:c*d?e"f<g>h|i\x00j', "fb") == "a_b_c_d_e_f_g_h_i_j"
    assert clean_scan_name("  ..name.. ", "fb") == "name"
    assert clean_scan_name("   ", "fb") == "fb"
    assert clean_scan_name(None, "fb") == "fb"
    assert clean_scan_name("...", "fb") == "fb"
    assert len(clean_scan_name("ş" * 200, "fb")) == 80

    archive = _setup(hass, tmp_path)
    record = await _add(archive, "../../etc/x")
    path = await archive.async_file_path(record["id"])
    assert path is not None
    assert _scans_dir(tmp_path) in path.resolve().parents
    assert "/" not in record["name"]
    record = await _add(archive, "/etc/passwd")
    path = await archive.async_file_path(record["id"])
    assert _scans_dir(tmp_path) in path.resolve().parents


async def test_default_name_tr_and_en(hass):
    when = datetime(2026, 11, 16, 16, 52, tzinfo=dt_util.get_default_time_zone())
    hass.config.language = "tr"
    assert default_scan_name(hass, when) == "tarama_2026-11-16_1652"
    hass.config.language = "tr-TR"
    assert default_scan_name(hass, when).startswith("tarama_")
    hass.config.language = "en"
    assert default_scan_name(hass, when) == "scan_2026-11-16_1652"


def test_media_root_falls_back_to_config_media(hass, tmp_path):
    hass.config.media_dirs = {}
    assert media_root(hass) == Path(hass.config.path("media"))
    hass.config.media_dirs = {"local": str(tmp_path / "m")}
    assert media_root(hass) == tmp_path / "m"


async def test_rename_moves_file(hass, tmp_path):
    archive = _setup(hass, tmp_path)
    record = await _add(archive, "old")
    other = await _add(archive, "taken")
    old_path = tmp_path / "media" / record["path"]
    renamed = await archive.async_rename(record["id"], "new")
    assert renamed["name"] == "new"
    assert not old_path.exists()
    assert (old_path.parent / "new.pdf").read_bytes() == PDF
    assert await archive.async_file_path(record["id"]) == old_path.parent / "new.pdf"
    clash = await archive.async_rename(record["id"], "taken")
    assert clash["name"] == "taken (2)"
    assert (old_path.parent / "taken (2).pdf").exists()
    assert (old_path.parent / "taken.pdf").exists()
    assert await archive.async_file_path(other["id"]) is not None
    assert await archive.async_rename("0" * 32, "x") is None


async def test_replace_file_updates_pages_and_size(hass, tmp_path):
    archive = _setup(hass, tmp_path)
    record = await _add(archive, "doc")
    updated = await archive.async_replace_file(record["id"], PDF * 3, 2)
    assert updated["pages"] == 2
    assert updated["size"] == len(PDF) * 3
    assert (tmp_path / "media" / record["path"]).read_bytes() == PDF * 3
    assert not list(_scans_dir(tmp_path).rglob("*.tmp"))
    assert await archive.async_replace_file("0" * 32, b"x", 1) is None


async def test_delete_removes_file(hass, tmp_path):
    archive = _setup(hass, tmp_path)
    record = await _add(archive)
    path = tmp_path / "media" / record["path"]
    assert path.exists()
    assert await archive.async_delete(record["id"]) is True
    assert not path.exists()
    assert archive.entries() == []
    assert await archive.async_delete(record["id"]) is False


async def test_cleanup_drops_expired_unless_zero_days(hass, tmp_path):
    archive = _setup(hass, tmp_path, **{CONF_SCAN_DAYS: 30})
    record = await _add(archive)
    path = tmp_path / "media" / record["path"]
    later = dt_util.utcnow() + timedelta(days=31)
    await archive.async_cleanup(later)
    assert archive.entries() == []
    assert not path.exists()

    archive = _setup(hass, tmp_path, **{CONF_SCAN_DAYS: 0})
    record = await _add(archive, "keep")
    path = tmp_path / "media" / record["path"]
    await archive.async_cleanup(dt_util.utcnow() + timedelta(days=5000))
    assert len(archive.entries()) == 1
    assert path.exists()


async def test_cleanup_drops_record_when_file_missing(hass, tmp_path):
    archive = _setup(hass, tmp_path)
    gone = await _add(archive, "gone")
    kept = await _add(archive, "kept")
    (tmp_path / "media" / gone["path"]).unlink()
    assert await archive.async_file_path(gone["id"]) is None
    await archive.async_cleanup()
    assert [e["id"] for e in archive.entries()] == [kept["id"]]


async def test_cleanup_size_cap_removes_oldest(hass, tmp_path):
    archive = _setup(hass, tmp_path, **{CONF_SCAN_MAX_MB: 1})
    mb = 1024 * 1024
    old = await _add(archive, "old", b"a" * (600 * 1024))
    mid = await _add(archive, "mid", b"b" * (600 * 1024))
    new = await _add(archive, "new", b"c" * (300 * 1024))
    assert old["size"] + mid["size"] + new["size"] > mb  # 1.5 MB, cap 1 MB
    await hass.async_block_till_done()
    await archive.async_cleanup()
    ids = [e["id"] for e in archive.entries()]
    assert ids == [new["id"], mid["id"]]
    assert not (tmp_path / "media" / old["path"]).exists()
    assert (tmp_path / "media" / mid["path"]).exists()

    unlimited = _setup(hass, tmp_path, **{CONF_SCAN_MAX_MB: 0})
    await _add(unlimited, "big", b"z" * (2 * mb))
    await unlimited.async_cleanup()
    assert len(unlimited.entries()) == 1


async def test_file_path_rejects_bad_id_and_outside_root(hass, tmp_path):
    archive = _setup(hass, tmp_path)
    record = await _add(archive)
    assert await archive.async_file_path(record["id"]) is not None
    assert await archive.async_file_path("../../etc/passwd") is None
    assert await archive.async_file_path("g" * 32) is None
    assert await archive.async_file_path("0" * 32) is None
    # A tampered record pointing outside the scans folder is refused.
    outside = tmp_path / "media" / "other.pdf"
    outside.write_bytes(PDF)
    archive._entries[0]["path"] = "other.pdf"
    assert await archive.async_file_path(record["id"]) is None
    archive._entries[0]["path"] = "home_print/scans/../../../outside.pdf"
    assert await archive.async_file_path(record["id"]) is None


async def test_records_survive_reload(hass, tmp_path):
    archive = _setup(hass, tmp_path)
    record = await _add(archive, "persist")
    await archive.async_flush()
    again = ScanArchive(hass, archive._entry)
    await again.async_load()
    assert again.entries() == archive.entries()
    assert await again.async_file_path(record["id"]) is not None


async def test_delayed_save_writes_store(hass, tmp_path, hass_storage):
    archive = _setup(hass, tmp_path)
    await _add(archive)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
    await hass.async_block_till_done()
    key = f"home_print.scans.{archive._entry.entry_id}"
    assert len(hass_storage[key]["data"]["entries"]) == 1


async def test_remove_keeps_media_files(hass, tmp_path):
    archive = _setup(hass, tmp_path)
    record = await _add(archive)
    path = tmp_path / "media" / record["path"]
    await archive.async_flush()
    await archive.async_remove()
    assert path.read_bytes() == PDF
    again = ScanArchive(hass, archive._entry)
    await again.async_load()
    assert again.entries() == []


async def test_size_cap_keeps_newest_even_if_alone_over_cap(hass, tmp_path):
    archive = _setup(hass, tmp_path, **{CONF_SCAN_MAX_MB: 1})
    old = await _add(archive, "old", b"a" * 1000)
    big = await _add(archive, "big", b"b" * (2 * 1024 * 1024))
    await hass.async_block_till_done()
    await archive.async_cleanup()
    assert [e["id"] for e in archive.entries()] == [big["id"]]
    assert await archive.async_file_path(big["id"]) is not None
    assert not (tmp_path / "media" / old["path"]).exists()


async def test_cleanup_keeps_record_on_non_missing_oserror(hass, tmp_path):
    archive = _setup(hass, tmp_path)
    record = await _add(archive)
    await hass.async_block_till_done()
    real_stat = Path.stat

    def flaky(self, *args, **kwargs):
        if self.name == "doc.pdf":
            raise PermissionError("denied")
        return real_stat(self, *args, **kwargs)

    with patch.object(Path, "stat", flaky):
        await archive.async_cleanup()
    assert [e["id"] for e in archive.entries()] == [record["id"]]


async def test_cleanup_skips_pruning_when_scans_root_missing(hass, tmp_path):
    archive = _setup(hass, tmp_path)
    record = await _add(archive)
    await hass.async_block_till_done()
    shutil.rmtree(tmp_path / "media")  # like an unmounted share
    await archive.async_cleanup()
    assert [e["id"] for e in archive.entries()] == [record["id"]]


async def test_load_drops_records_missing_required_keys(hass, tmp_path):
    archive = _setup(hass, tmp_path)
    record = await _add(archive)
    await archive.async_flush()
    store_entries = archive._data()["entries"]
    store_entries.append({"id": "f" * 32, "path": "x.pdf"})
    await archive._store.async_save({"entries": store_entries})
    again = ScanArchive(hass, archive._entry)
    await again.async_load()
    assert [e["id"] for e in again.entries()] == [record["id"]]


def test_clean_name_strips_known_extension():
    assert clean_scan_name("x.pdf", "fb") == "x"
    assert clean_scan_name("Scan.JPEG", "fb") == "Scan"
    assert clean_scan_name("a.jpg", "fb") == "a"
    assert clean_scan_name("v1.2", "fb") == "v1.2"
    assert clean_scan_name(".pdf", "fb") == "fb"


async def test_record_returns_a_copy_or_none(hass, tmp_path):
    archive = _setup(hass, tmp_path)
    record = await _add(archive)
    copy = archive.record(record["id"])
    assert copy == record
    copy["name"] = "changed"
    assert archive.record(record["id"])["name"] == record["name"]
    assert archive.record("0" * 32) is None


async def test_async_file_path_and_existing_entries(hass, tmp_path):
    archive = _setup(hass, tmp_path)
    kept = await _add(archive, name="kept")
    gone = await _add(archive, name="gone")
    # Each add schedules a cleanup; let it finish before the file vanishes,
    # or it may drop the record first (it runs in the executor since 1.0.0).
    await hass.async_block_till_done()
    assert (
        await archive.async_file_path(kept["id"])
        == (tmp_path / "media" / kept["path"]).resolve()
    )
    assert await archive.async_file_path("0" * 32) is None
    assert await archive.async_file_path("../x") is None
    (tmp_path / "media" / gone["path"]).unlink()
    assert await archive.async_file_path(gone["id"]) is None
    entries, missing = await archive.async_existing_entries()
    assert [e["id"] for e in entries] == [kept["id"]]
    assert missing is True


async def test_archive_does_no_disk_io_on_the_event_loop(
    hass, tmp_path, forbid_loop_disk_io
):
    archive = _setup(hass, tmp_path, scan_max_mb=1, scan_days=1)
    await archive.async_load()
    first = await _add(archive, name="first")
    second = await _add(archive, name="second")
    await hass.async_block_till_done()
    with forbid_loop_disk_io():
        assert await archive.async_file_path(first["id"]) is not None
        assert await archive.async_replace_file(first["id"], PDF, 2) is not None
        assert (await archive.async_rename(first["id"], "renamed"))["name"] == "renamed"
        await archive.async_existing_entries()
        assert await archive.async_delete(second["id"])
        await archive.async_cleanup()
        await archive.async_cleanup(now=dt_util.utcnow() + timedelta(days=30))
        await hass.async_block_till_done()
