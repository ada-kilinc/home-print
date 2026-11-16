"""Persisted print history: one small record per job, never file contents."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

MAX_ENTRIES = 50
STORAGE_VERSION = 1
SAVE_DELAY = 1  # seconds; batches writes and keeps disk I/O off the loop


class PrintHistory:
    """The last ``MAX_ENTRIES`` print jobs of one config entry, newest first."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.history.{entry.entry_id}"
        )
        self._entries: list[dict[str, Any]] = []

    async def async_load(self) -> None:
        """Load the saved history from disk."""
        data = await self._store.async_load()
        entries = data.get("entries") if isinstance(data, dict) else None
        self._entries = list(entries)[:MAX_ENTRIES] if entries else []

    def entries(self) -> list[dict[str, Any]]:
        """Return a copy of the records, newest first."""
        return copy.deepcopy(self._entries)

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
    ) -> dict[str, Any]:
        """Record a job at the top, dropping the oldest past the limit."""
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
        }
        self._entries.insert(0, entry)
        del self._entries[MAX_ENTRIES:]
        self._schedule_save()
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

    def delete(self, entry_id: str) -> bool:
        """Remove one record; False if there is none with this id."""
        for index, entry in enumerate(self._entries):
            if entry["id"] == entry_id:
                del self._entries[index]
                self._schedule_save()
                return True
        return False

    async def async_flush(self) -> None:
        """Write pending changes now (used when the entry unloads)."""
        await self._store.async_save(self._data())

    async def async_remove(self) -> None:
        """Delete the history file."""
        await self._store.async_remove()

    def _schedule_save(self) -> None:
        self._store.async_delay_save(self._data, SAVE_DELAY)

    def _data(self) -> dict[str, Any]:
        return {"entries": copy.deepcopy(self._entries)}
