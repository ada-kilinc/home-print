"""Persisted print history, with the printed files kept for a few days.

Each record is small JSON in a HA ``Store``. When ``CONF_HISTORY_DAYS`` is
above zero the original file of a successful job is kept next to it, under
``<config>/home_print/<entry_id>/<record id><ext>``. All disk work for those
files runs in the executor; writes, deletions and clean-ups are serialised by
one lock so a clean-up never sees a half-written file.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import re
import shutil
from collections.abc import Coroutine
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS, DOMAIN
from .convert.render import count_pages

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

MAX_ENTRIES = 200
# Kept files of one entry may use at most this much disk; oldest go first.
MAX_STORAGE_BYTES = 500 * 1024 * 1024
# How long records live when no files are kept (CONF_HISTORY_DAYS == 0).
RECORD_DAYS_WITHOUT_FILES = 7
STORAGE_VERSION = 1
SAVE_DELAY = 1  # seconds; batches writes and keeps disk I/O off the loop

RECORD_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}
# Fields added after the first release; older saved records lack them.
_RECORD_DEFAULTS = {"file": False, "size": None, "mime": None}


def files_dir(hass: HomeAssistant, entry_id: str) -> Path:
    """Folder holding the kept files of one config entry."""
    return Path(hass.config.path(DOMAIN, entry_id))


def _file_name(record: dict[str, Any]) -> str | None:
    ext = _EXTENSIONS.get(record.get("mime") or "")
    return f"{record['id']}{ext}" if ext else None


def _write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _sweep(folder: Path, wanted: list[tuple[str, str]], max_bytes: int) -> set[str]:
    """Make the folder match the records; return the ids whose file is kept.

    ``wanted`` lists ``(record id, file name)`` newest first. Files of no
    record are removed, and once the total passes ``max_bytes`` every older
    file is removed too.
    """
    if not folder.is_dir():
        return set()
    names = {name for _, name in wanted}
    files: dict[str, Path] = {}
    for path in folder.iterdir():
        if not path.is_file():
            continue
        if path.name in names:
            files[path.name] = path
        else:
            path.unlink(missing_ok=True)
    kept: set[str] = set()
    total = 0
    over = False
    for record_id, name in wanted:
        if (path := files.get(name)) is None:
            continue
        size = path.stat().st_size
        if over or total + size > max_bytes:
            over = True
            path.unlink(missing_ok=True)
            continue
        total += size
        kept.add(record_id)
    return kept


def _count_file_pages(path: Path) -> int | None:
    try:
        return count_pages(path.read_bytes())
    except Exception:  # noqa: BLE001 - a bad or vanished file has no count
        _LOGGER.debug("Could not count pages of %s", path, exc_info=True)
        return None


class PrintHistory:
    """The last ``MAX_ENTRIES`` print jobs of one config entry, newest first."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.history.{entry.entry_id}"
        )
        self._entries: list[dict[str, Any]] = []
        self._dir = files_dir(hass, entry.entry_id)
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[Any]] = set()

    async def async_load(self) -> None:
        """Load the saved history from disk."""
        data = await self._store.async_load()
        entries = data.get("entries") if isinstance(data, dict) else None
        self._entries = [
            {**_RECORD_DEFAULTS, **entry}
            for entry in (entries or [])[:MAX_ENTRIES]
            if isinstance(entry, dict) and "id" in entry
        ]

    def entries(self) -> list[dict[str, Any]]:
        """Return a copy of the records, newest first."""
        return copy.deepcopy(self._entries)

    async def async_entries(self) -> list[dict[str, Any]]:
        """Like ``entries``, with unknown page counts read from kept files."""
        for record in [r for r in self._entries if r["pages"] is None and r["file"]]:
            if (path := self.file_path(record["id"])) is None:
                continue
            pages = await self._hass.async_add_executor_job(_count_file_pages, path)
            if pages is not None and any(r is record for r in self._entries):
                record["pages"] = pages
                self._schedule_save()
        return self.entries()

    def add(
        self,
        *,
        file_name: str,
        user: str | None,
        job_id: int | None,
        state: str,
        pages: int | None,
        converted_to: str | None,
        error: str | None,
        data: bytes | None = None,
        mime: str | None = None,
    ) -> dict[str, Any]:
        """Record a job at the top, dropping the oldest past the limit.

        With ``data`` and a kept-days setting above zero the file is written
        in the background; ``file`` turns true once it is on disk.
        """
        entry = {
            "id": uuid4().hex,
            "time": dt_util.utcnow().isoformat(),
            "file_name": file_name,
            "user": user,
            "job_id": job_id,
            "state": state,
            "pages": pages,
            "converted_to": converted_to,
            "error": error,
            "file": False,
            "size": len(data) if data is not None else None,
            "mime": mime if data is not None else None,
        }
        self._entries.insert(0, entry)
        del self._entries[MAX_ENTRIES:]
        self._schedule_save()
        name = _file_name(entry)
        if data is not None and name and self._keep_days() > 0:
            self._create_task(self._async_store_file(name, data))
        else:
            # Expired or evicted records may leave files behind.
            self._create_task(self.async_cleanup())
        return dict(entry)

    def update_state(self, job_id: int, state: str) -> bool:
        """Set the state of the record with this job id; False if unknown."""
        for entry in self._entries:
            if entry["job_id"] == job_id:
                if entry["state"] != state:
                    entry["state"] = state
                    self._schedule_save()
                return True
        return False

    async def async_delete(self, record_id: str) -> bool:
        """Remove one record and its file; False if there is none."""
        for index, entry in enumerate(self._entries):
            if entry["id"] == record_id:
                del self._entries[index]
                self._schedule_save()
                if name := _file_name(entry):
                    async with self._lock:
                        await self._hass.async_add_executor_job(
                            (self._dir / name).unlink, True
                        )
                return True
        return False

    def file_path(self, record_id: str) -> Path | None:
        """Path of the kept file of a record, or None if it has none.

        Only well-formed ids of known records with a kept file resolve, and
        the result is always inside this entry's folder.
        """
        if not RECORD_ID_RE.fullmatch(record_id):
            return None
        record = next((r for r in self._entries if r["id"] == record_id), None)
        if record is None or not record["file"]:
            return None
        if (name := _file_name(record)) is None:
            return None
        path = self._dir / name
        return path if path.parent == self._dir else None

    async def async_cleanup(self, now: datetime | None = None) -> None:
        """Drop expired records, then make the kept files match the records."""
        days = self._keep_days()
        cutoff = dt_util.utcnow() - timedelta(
            days=days if days > 0 else RECORD_DAYS_WITHOUT_FILES
        )
        kept = [r for r in self._entries if not self._expired(r, cutoff)]
        if len(kept) != len(self._entries):
            self._entries[:] = kept
            self._schedule_save()

        wanted = (
            [(r["id"], name) for r in self._entries if (name := _file_name(r))]
            if days > 0
            else []
        )
        async with self._lock:
            try:
                present = await self._hass.async_add_executor_job(
                    _sweep, self._dir, wanted, MAX_STORAGE_BYTES
                )
            except OSError:
                _LOGGER.warning("Could not clean up %s", self._dir, exc_info=True)
                return
        changed = False
        for record in self._entries:
            has_file = record["id"] in present
            if record["file"] != has_file:
                record["file"] = has_file
                changed = True
        if changed:
            self._schedule_save()

    async def async_flush(self) -> None:
        """Finish pending file work and write the records now (on unload)."""
        while pending := [task for task in self._tasks if not task.done()]:
            await asyncio.gather(*pending, return_exceptions=True)
        await self._store.async_save(self._data())

    async def async_remove(self) -> None:
        """Delete the history file and every kept file."""
        await self._store.async_remove()
        await self._hass.async_add_executor_job(
            lambda: shutil.rmtree(self._dir, ignore_errors=True)
        )

    async def _async_store_file(self, name: str, data: bytes) -> None:
        async with self._lock:
            try:
                await self._hass.async_add_executor_job(
                    _write_file, self._dir / name, data
                )
            except OSError:
                _LOGGER.warning("Could not keep printed file %s", name, exc_info=True)
        # Marks the file as kept, or removes it if the record is gone already.
        await self.async_cleanup()

    def _keep_days(self) -> int:
        return int(self._entry.options.get(CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS))

    @staticmethod
    def _expired(record: dict[str, Any], cutoff: datetime) -> bool:
        time = dt_util.parse_datetime(str(record.get("time")))
        return time is not None and time < cutoff

    def _create_task(self, coro: Coroutine[Any, Any, None]) -> None:
        task = self._hass.async_create_task(coro, f"{DOMAIN} history files")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _schedule_save(self) -> None:
        self._store.async_delay_save(self._data, SAVE_DELAY)

    def _data(self) -> dict[str, Any]:
        return {"entries": copy.deepcopy(self._entries)}
