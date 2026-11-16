"""Archive of finished scans, kept as files in the Home Assistant media folder.

Each record is small JSON in a HA ``Store``; the scan itself is a PDF or JPEG
under ``<media>/home_print/scans/YYYY-MM/``, where the user can also reach it
from the Media browser. ``path`` in a record is relative to the media root.
Like ``PrintHistory``, all disk work runs in the executor and is serialised by
one lock; writes are atomic (temporary file, then ``replace``).

Removing the config entry deletes the records but never the files: they are
the user's documents (see ``async_remove``).
"""

from __future__ import annotations

import asyncio
import copy
import logging
import re
from collections.abc import Coroutine
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_SCAN_DAYS,
    CONF_SCAN_MAX_MB,
    DEFAULT_SCAN_DAYS,
    DEFAULT_SCAN_MAX_MB,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

MAX_ENTRIES = 500
MAX_NAME_LENGTH = 80
# Most file systems allow 255 bytes per name; emoji names stay well below it.
MAX_NAME_BYTES = 200
STORAGE_VERSION = 1
SAVE_DELAY = 1  # seconds; batches writes and keeps disk I/O off the loop

RECORD_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_EXTENSIONS = {"application/pdf": ".pdf", "image/jpeg": ".jpg"}
_BAD_CHARS_RE = re.compile(r'[/\\:*?"<>|\x00-\x1f\x7f]')
_EXT_RE = re.compile(r"\.(pdf|jpe?g)$", re.IGNORECASE)
_REQUIRED_KEYS = frozenset({"id", "time", "name", "path", "mime", "pages", "size"})
_SUBPATH = Path("home_print") / "scans"


def media_root(hass: HomeAssistant) -> Path:
    """The ``local`` media folder, or ``<config>/media`` when none is set."""
    local = hass.config.media_dirs.get("local")
    return Path(local) if local else Path(hass.config.path("media"))


def default_scan_name(hass: HomeAssistant, when: datetime) -> str:
    """``tarama_YYYY-MM-DD_HHMM`` for Turkish, else ``scan_...`` (local time)."""
    prefix = "tarama" if (hass.config.language or "").startswith("tr") else "scan"
    return f"{prefix}_{dt_util.as_local(when).strftime('%Y-%m-%d_%H%M')}"


def clean_scan_name(name: str | None, fallback: str) -> str:
    """Make a user-given name safe as a file name (without extension)."""
    cleaned = _BAD_CHARS_RE.sub("_", name or "").rstrip(" .")
    cleaned = _EXT_RE.sub("", cleaned).strip(" .")
    cleaned = cleaned[:MAX_NAME_LENGTH]
    while len(cleaned.encode()) > MAX_NAME_BYTES:
        cleaned = cleaned[:-1]
    cleaned = cleaned.strip(" .")
    return cleaned or fallback


def _unique_name(folder: Path, name: str, ext: str, own: Path | None = None) -> str:
    """``name``, or ``name (2)``, ``name (3)``... if that file already exists."""
    candidate, counter = name, 1
    while (path := folder / f"{candidate}{ext}").exists() and path != own:
        counter += 1
        candidate = f"{name} ({counter})"
    return candidate


def _write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _write_new(folder: Path, name: str, ext: str, data: bytes) -> str:
    """Write ``data`` under a free name in ``folder``; return the name used."""
    folder.mkdir(parents=True, exist_ok=True)
    unique = _unique_name(folder, name, ext)
    _write_file(folder / f"{unique}{ext}", data)
    return unique


def _rename_file(path: Path, name: str) -> str:
    """Rename a file within its folder to a free name; return the name used."""
    ext = path.suffix
    unique = _unique_name(path.parent, name, ext, own=path)
    if (target := path.with_name(f"{unique}{ext}")) != path:
        path.replace(target)
    return unique


def _remove_file(path: Path, scans_dir: Path) -> None:
    """Delete a scan and its month folder if that is now empty."""
    path.unlink(missing_ok=True)
    folder = path.parent
    if folder != scans_dir:
        try:
            folder.rmdir()  # only succeeds when empty
        except OSError:
            pass


def _sweep(
    scans_dir: Path, expired: list[Path], wanted: list[tuple[str, Path]], max_bytes: int
) -> set[str]:
    """Delete expired files and enforce the size cap; return ids whose file stays.

    ``wanted`` lists ``(record id, path)`` newest first. Ids whose file is
    missing are left out, and once the total passes ``max_bytes`` (when above
    zero) every older file is deleted and left out too; the newest file always
    stays. A file that cannot be stat-ed for another reason than being absent
    is kept, and when the scans folder itself is absent (an unmounted share)
    nothing is pruned.
    """
    for path in expired:
        _remove_file(path, scans_dir)
    if not scans_dir.is_dir():
        return {record_id for record_id, _ in wanted}
    kept: set[str] = set()
    total = 0
    over = False
    for record_id, path in wanted:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            continue
        except OSError:
            kept.add(record_id)
            continue
        if over or (max_bytes > 0 and kept and total + size > max_bytes):
            over = True
            _remove_file(path, scans_dir)
            continue
        total += size
        kept.add(record_id)
    return kept


class ScanArchive:
    """The last ``MAX_ENTRIES`` scans of one config entry, newest first."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.scans.{entry.entry_id}"
        )
        self._entries: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[Any]] = set()

    async def async_load(self) -> None:
        """Load the saved records from disk."""
        data = await self._store.async_load()
        entries = data.get("entries") if isinstance(data, dict) else None
        self._entries = [
            entry
            for entry in (entries or [])[:MAX_ENTRIES]
            if isinstance(entry, dict) and _REQUIRED_KEYS <= entry.keys()
        ]

    def entries(self) -> list[dict[str, Any]]:
        """Return a copy of the records, newest first."""
        return copy.deepcopy(self._entries)

    def record(self, record_id: str) -> dict[str, Any] | None:
        """A copy of one record, or None."""
        record = self._find(record_id)
        return copy.deepcopy(record) if record is not None else None

    async def async_add(
        self,
        *,
        name: str | None,
        data: bytes,
        mime: str,
        pages: int,
        user: str | None,
        source: str,
        color_mode: str,
        resolution: int,
    ) -> dict[str, Any]:
        """Write a scan into the media folder and record it at the top."""
        ext = _EXTENSIONS[mime]
        now = dt_util.utcnow()
        local = dt_util.as_local(now)
        base = clean_scan_name(name, default_scan_name(self._hass, now))
        rel_folder = _SUBPATH / local.strftime("%Y-%m")
        async with self._lock:
            unique = await self._hass.async_add_executor_job(
                _write_new, self._root() / rel_folder, base, ext, data
            )
            record = {
                "id": uuid4().hex,
                "time": now.isoformat(),
                "name": unique,
                "user": user,
                "pages": pages,
                "size": len(data),
                "mime": mime,
                "path": (rel_folder / f"{unique}{ext}").as_posix(),
                "source": source,
                "color_mode": color_mode,
                "resolution": resolution,
            }
            self._entries.insert(0, record)
            self._schedule_save()
        # Enforces the size cap and the record limit; tracked for async_flush.
        self._create_task(self.async_cleanup())
        return dict(record)

    async def async_replace_file(
        self, record_id: str, data: bytes, pages: int
    ) -> dict[str, Any] | None:
        """Overwrite the scan's file (after adding pages); None if unknown."""
        async with self._lock:
            record = self._find(record_id)
            if record is None or (path := self.file_path(record_id)) is None:
                return None
            await self._hass.async_add_executor_job(_write_file, path, data)
            record["pages"] = pages
            record["size"] = len(data)
            self._schedule_save()
            return dict(record)

    async def async_rename(self, record_id: str, name: str) -> dict[str, Any] | None:
        """Rename a scan and its file in place; None if unknown or file gone."""
        async with self._lock:
            record = self._find(record_id)
            if record is None or (path := self.file_path(record_id)) is None:
                return None
            clean = clean_scan_name(name, record["name"])
            unique = await self._hass.async_add_executor_job(_rename_file, path, clean)
            record["name"] = unique
            record["path"] = (
                Path(record["path"]).parent
                / path.with_name(f"{unique}{path.suffix}").name
            ).as_posix()
            self._schedule_save()
            return dict(record)

    async def async_delete(self, record_id: str) -> bool:
        """Remove one record and its file; False if there is none."""
        async with self._lock:
            record = self._find(record_id)
            if record is None:
                return False
            path = self._resolve(record)
            self._entries[:] = [r for r in self._entries if r is not record]
            self._schedule_save()
            if path is not None:
                await self._hass.async_add_executor_job(
                    _remove_file, path, self._scans_dir()
                )
            return True

    def file_path(self, record_id: str) -> Path | None:
        """Absolute path of a scan, or None.

        Only well-formed ids of known records resolve, the file must exist and
        must lie inside ``<media>/home_print/scans/``.
        """
        if not RECORD_ID_RE.fullmatch(record_id):
            return None
        record = self._find(record_id)
        if record is None:
            return None
        path = self._resolve(record)
        return path if path is not None and path.is_file() else None

    async def async_cleanup(self, now: datetime | None = None) -> None:
        """Drop expired records and ones whose file is gone; enforce the cap."""
        days = int(self._entry.options.get(CONF_SCAN_DAYS, DEFAULT_SCAN_DAYS))
        max_mb = int(self._entry.options.get(CONF_SCAN_MAX_MB, DEFAULT_SCAN_MAX_MB))
        cutoff = (now or dt_util.utcnow()) - timedelta(days=days) if days > 0 else None
        async with self._lock:
            del self._entries[MAX_ENTRIES:]
            expired = [
                r
                for r in self._entries
                if cutoff is not None and self._expired(r, cutoff)
            ]
            expired_ids = {r["id"] for r in expired}
            expired_paths = [p for r in expired if (p := self._resolve(r)) is not None]
            wanted = [
                (r["id"], p)
                for r in self._entries
                if r["id"] not in expired_ids and (p := self._resolve(r)) is not None
            ]
            try:
                kept = await self._hass.async_add_executor_job(
                    _sweep,
                    self._scans_dir(),
                    expired_paths,
                    wanted,
                    max_mb * 1024 * 1024 if max_mb > 0 else 0,
                )
            except OSError:
                _LOGGER.warning("Could not clean up scans", exc_info=True)
                return
            remaining = [r for r in self._entries if r["id"] in kept]
            if len(remaining) != len(self._entries):
                self._entries[:] = remaining
                self._schedule_save()

    @callback
    def async_schedule_cleanup(self, _now: datetime | None = None) -> None:
        """Start a cleanup as a tracked task, so async_flush waits for it."""
        self._create_task(self.async_cleanup())

    async def async_flush(self) -> None:
        """Finish pending file work and write the records now (on unload)."""
        while pending := [task for task in self._tasks if not task.done()]:
            await asyncio.gather(*pending, return_exceptions=True)
        await self._store.async_save(self._data())

    async def async_remove(self) -> None:
        """Delete the records only; scans in the media folder stay."""
        await self._store.async_remove()

    def _root(self) -> Path:
        return media_root(self._hass)

    def _scans_dir(self) -> Path:
        return self._root() / _SUBPATH

    def _find(self, record_id: str) -> dict[str, Any] | None:
        return next((r for r in self._entries if r["id"] == record_id), None)

    def _resolve(self, record: dict[str, Any]) -> Path | None:
        """Absolute path of the record's file if it lies inside the scans folder."""
        try:
            path = (self._root() / str(record["path"])).resolve()
            scans = self._scans_dir().resolve()
        except (OSError, RuntimeError, ValueError):
            return None
        return path if scans in path.parents else None

    @staticmethod
    def _expired(record: dict[str, Any], cutoff: datetime) -> bool:
        time = dt_util.parse_datetime(str(record.get("time")))
        return time is not None and time < cutoff

    def _create_task(self, coro: Coroutine[Any, Any, None]) -> None:
        task = self._hass.async_create_task(coro, f"{DOMAIN} scan files")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _schedule_save(self) -> None:
        self._store.async_delay_save(self._data, SAVE_DELAY)

    def _data(self) -> dict[str, Any]:
        return {"entries": copy.deepcopy(self._entries)}
