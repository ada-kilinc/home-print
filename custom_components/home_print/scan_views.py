"""Download and page previews of archived scans.

Both views require authentication; the card loads them with paths signed by
``auth/sign_path``. Everyone signed in may look (as with print history).
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from aiohttp import web
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .convert.scan_doc import SCAN_MAX_PIXELS
from .preview import render_bounded
from .scans import RECORD_ID_RE, media_root

_PAGE_RE = re.compile(r"^[1-9][0-9]{0,3}$")
_NON_ASCII_RE = re.compile(r"[^\x20-\x7e]")
PREVIEW_CACHE_CONTROL = "private, max-age=300"
DOWNLOAD_CACHE_CONTROL = "private, no-store"


def _lookup(
    hass: HomeAssistant, entry_id: str, record_id: str
) -> tuple[Path, dict] | None:
    """The scan's file and record, or None for anything unknown or missing."""
    if not RECORD_ID_RE.fullmatch(record_id):
        return None
    entry = hass.config_entries.async_get_entry(entry_id)
    if (
        entry is None
        or entry.domain != DOMAIN
        or entry.state is not ConfigEntryState.LOADED
        or entry.runtime_data.scanner is None
    ):
        return None
    archive = entry.runtime_data.scanner.archive
    path = archive.file_path(record_id)
    record = archive.record(record_id)
    if path is None or record is None:
        return None
    return path, record


def content_disposition(filename: str) -> str:
    """Attachment header with an ASCII fallback and an RFC 5987 name."""
    ascii_name = _NON_ASCII_RE.sub("_", filename).replace('"', "_").replace("\\", "_")
    return (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )


class ScanFileView(HomeAssistantView):
    """Download one scan."""

    url = "/api/home_print/scans/{entry_id}/{record_id}/file"
    name = "api:home_print:scan_file"
    requires_auth = True

    async def get(
        self, request: web.Request, entry_id: str, record_id: str
    ) -> web.StreamResponse:
        """Return the file; 404 for anything unknown."""
        found = _lookup(request.app[KEY_HASS], entry_id, record_id)
        if found is None:
            raise web.HTTPNotFound
        path, record = found
        return web.FileResponse(
            path,
            headers={
                "Content-Type": record["mime"],
                "Content-Disposition": content_disposition(
                    f"{record['name']}{path.suffix}"
                ),
                "Cache-Control": DOWNLOAD_CACHE_CONTROL,
            },
        )


class ScanPreviewView(HomeAssistantView):
    """Render one page of a scan as JPEG."""

    url = "/api/home_print/scans/{entry_id}/{record_id}/page/{page}"
    name = "api:home_print:scan_page"
    requires_auth = True

    async def get(
        self, request: web.Request, entry_id: str, record_id: str, page: str
    ) -> web.Response:
        """Return the page as a JPEG; 404 for anything unknown."""
        hass = request.app[KEY_HASS]
        if not _PAGE_RE.fullmatch(page):
            raise web.HTTPNotFound
        found = _lookup(hass, entry_id, record_id)
        if found is None:
            raise web.HTTPNotFound
        path, _ = found
        folder = media_root(hass) / "home_print" / "scans"
        body = await hass.async_add_executor_job(
            render_bounded, folder, path, int(page), SCAN_MAX_PIXELS
        )
        if body is None:
            raise web.HTTPNotFound
        return web.Response(
            body=body,
            content_type="image/jpeg",
            headers={"Cache-Control": PREVIEW_CACHE_CONTROL},
        )
