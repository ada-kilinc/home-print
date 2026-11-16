"""Page previews of kept files.

``GET /api/home_print/history/{entry_id}/{record_id}/page/{page}`` returns
one page (1-based) as a JPEG. The card loads it into ``<img>`` through a
path signed with ``auth/sign_path``, which HA accepts for any view with
``requires_auth``.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from aiohttp import web
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .convert.errors import InvalidDocument, TooManyPages
from .convert.render import preview_jpeg
from .history import RECORD_ID_RE, files_dir

_PAGE_RE = re.compile(r"^[1-9][0-9]{0,3}$")
CACHE_CONTROL = "private, max-age=300"
# Rendering a page takes a worker thread and some memory; a fast scroll
# through a long PDF must not take every executor thread at once.
MAX_RENDERS = 2
_RENDER_LIMIT = f"{DOMAIN}_preview_renders"


def _render_limit(hass: HomeAssistant) -> asyncio.Semaphore:
    """The per-instance semaphore that caps concurrent renders."""
    if (limit := hass.data.get(_RENDER_LIMIT)) is None:
        limit = hass.data[_RENDER_LIMIT] = asyncio.Semaphore(MAX_RENDERS)
    return limit


def _render(folder: Path, path: Path, page: int) -> bytes | None:
    """The page as JPEG, or None if the file or the page is not there."""
    try:
        if not path.resolve().is_relative_to(folder.resolve()):
            return None
        data = path.read_bytes()
    except OSError:
        return None
    try:
        return preview_jpeg(data, page)
    except (InvalidDocument, TooManyPages):
        return None


class HomePrintPreviewView(HomeAssistantView):
    """Render one page of a kept file."""

    url = "/api/home_print/history/{entry_id}/{record_id}/page/{page}"
    name = "api:home_print:history_page"
    requires_auth = True

    async def get(
        self, request: web.Request, entry_id: str, record_id: str, page: str
    ) -> web.Response:
        """Return the page as a JPEG; 404 for anything unknown."""
        hass = request.app[KEY_HASS]
        if not RECORD_ID_RE.fullmatch(record_id) or not _PAGE_RE.fullmatch(page):
            raise web.HTTPNotFound
        entry = hass.config_entries.async_get_entry(entry_id)
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.state is not ConfigEntryState.LOADED
        ):
            raise web.HTTPNotFound
        path = entry.runtime_data.history.file_path(record_id)
        folder = files_dir(hass, entry.entry_id)
        if path is None or path.parent != folder:
            raise web.HTTPNotFound
        async with _render_limit(hass):
            body = await hass.async_add_executor_job(_render, folder, path, int(page))
        if body is None:
            raise web.HTTPNotFound
        return web.Response(
            body=body,
            content_type="image/jpeg",
            headers={"Cache-Control": CACHE_CONTROL},
        )
