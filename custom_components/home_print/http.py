"""Authenticated upload endpoint: ``POST /api/home_print/upload/{entry_id}``."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from aiohttp import BodyPartReader, web
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.generated.languages import LANGUAGES
from homeassistant.helpers.translation import async_get_translations

from .const import CONF_ADMIN_ONLY, DOMAIN
from .printing import (
    FileTooLarge,
    InvalidPrintOption,
    PrintError,
    async_print,
    async_report_result,
    build_options,
    clean_file_name,
    max_file_bytes,
    max_file_mb,
)

_LOGGER = logging.getLogger(__name__)

CHUNK_SIZE = 64 * 1024
# Room for boundaries, part headers and the small option fields, so a file of
# exactly the limit is not rejected by the Content-Length pre-check.
MULTIPART_OVERHEAD = 64 * 1024
MAX_FIELD_BYTES = 256
OPTION_FIELDS = ("copies", "sides", "color_mode", "page_ranges")


class _RequestError(Exception):
    """Reject the request with a translated error body."""

    def __init__(
        self, status: int, key: str, placeholders: dict[str, str] | None = None
    ) -> None:
        super().__init__(key)
        self.status = status
        self.key = key
        self.placeholders = placeholders or {}


def _language(request: web.Request, hass: HomeAssistant) -> str:
    """Pick the first Accept-Language entry Home Assistant has a language for."""
    supported = {lang.lower(): lang for lang in LANGUAGES}
    for item in request.headers.get("Accept-Language", "").split(","):
        tag = item.split(";")[0].strip().lower()
        for candidate in (tag, tag.split("-")[0]):
            if candidate in supported:
                return supported[candidate]
    return hass.config.language


async def _message(
    hass: HomeAssistant, language: str, key: str, placeholders: dict[str, str]
) -> str:
    """Return the translated message for an exception key."""
    translations = await async_get_translations(hass, language, "exceptions", {DOMAIN})
    template = translations.get(f"component.{DOMAIN}.exceptions.{key}.message")
    if not template:
        return key
    try:
        return template.format(**placeholders)
    except (KeyError, IndexError, ValueError):
        return template


async def _read_field(part: BodyPartReader) -> str:
    raw = bytearray()
    while chunk := await part.read_chunk(MAX_FIELD_BYTES):
        raw.extend(chunk)
        if len(raw) > MAX_FIELD_BYTES:
            raise _RequestError(
                HTTPStatus.BAD_REQUEST, "invalid_option", {"option": part.name or ""}
            )
    try:
        return raw.decode().strip()
    except UnicodeDecodeError:
        raise _RequestError(
            HTTPStatus.BAD_REQUEST, "invalid_option", {"option": part.name or ""}
        ) from None


async def _read_file(part: BodyPartReader, limit: int, mb: int) -> bytes:
    """Read a file part in chunks, stopping as soon as ``limit`` is crossed."""
    data = bytearray()
    while chunk := await part.read_chunk(CHUNK_SIZE):
        data.extend(chunk)
        if len(data) > limit:
            raise FileTooLarge(max=mb)
    return bytes(data)


class HomePrintUploadView(HomeAssistantView):
    """Receive a file from the dashboard and print it."""

    url = "/api/home_print/upload/{entry_id}"
    name = "api:home_print:upload"
    requires_auth = True

    async def post(self, request: web.Request, entry_id: str) -> web.Response:
        """Handle an upload."""
        hass = request.app[KEY_HASS]
        language = _language(request, hass)
        try:
            return await self._handle(hass, request, entry_id)
        except _RequestError as err:
            return await self._error(
                hass, language, err.status, err.key, err.placeholders
            )
        except PrintError as err:
            return await self._error(
                hass,
                language,
                err.http_status,
                err.key,
                err.translation_placeholders or {},
            )

    async def _error(
        self,
        hass: HomeAssistant,
        language: str,
        status: int,
        key: str,
        placeholders: dict[str, str],
    ) -> web.Response:
        message = await _message(hass, language, key, placeholders)
        return self.json({"error": key, "message": message}, status_code=status)

    async def _handle(
        self, hass: HomeAssistant, request: web.Request, entry_id: str
    ) -> web.Response:
        entry = hass.config_entries.async_get_entry(entry_id)
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.state is not ConfigEntryState.LOADED
        ):
            raise _RequestError(HTTPStatus.NOT_FOUND, "entry_not_found")

        user = request["hass_user"]
        if entry.options.get(CONF_ADMIN_ONLY) and not user.is_admin:
            raise _RequestError(HTTPStatus.FORBIDDEN, "admin_required")

        limit = max_file_bytes(entry)
        mb = max_file_mb(entry)
        if (
            request.content_length is not None
            and request.content_length > limit + MULTIPART_OVERHEAD
        ):
            # Reject before reading any of the body.
            raise FileTooLarge(max=mb)
        if request.content_type != "multipart/form-data":
            raise _RequestError(HTTPStatus.BAD_REQUEST, "invalid_request")

        data: bytes | None = None
        file_name = "document"
        fields: dict[str, str] = {}
        try:
            reader = await request.multipart()
            while (part := await reader.next()) is not None:
                if not isinstance(part, BodyPartReader):
                    raise _RequestError(HTTPStatus.BAD_REQUEST, "invalid_request")
                if part.name == "file":
                    if data is not None:
                        raise _RequestError(HTTPStatus.BAD_REQUEST, "invalid_request")
                    file_name = clean_file_name(part.filename or "document")
                    try:
                        data = await _read_file(part, limit, mb)
                    except FileTooLarge as err:
                        async_report_result(
                            hass, entry, file_name=file_name, user=user, error=err
                        )
                        raise
                elif part.name in OPTION_FIELDS and part.name not in fields:
                    fields[part.name] = await _read_field(part)
                else:
                    raise _RequestError(
                        HTTPStatus.BAD_REQUEST,
                        "invalid_option",
                        {"option": part.name or ""},
                    )
        except ValueError as err:
            _LOGGER.debug("Malformed upload: %s", err)
            raise _RequestError(HTTPStatus.BAD_REQUEST, "invalid_request") from None

        if data is None:
            raise _RequestError(HTTPStatus.BAD_REQUEST, "missing_file")

        options = build_options(entry, **_parse_fields(fields))
        result = await async_print(
            hass, entry, data, file_name=file_name, options=options, user=user
        )
        return self.json({"job_id": result.job_id})


def _parse_fields(fields: dict[str, str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {
        key: value or None
        for key, value in fields.items()
        if key in ("sides", "color_mode", "page_ranges")
    }
    if copies := fields.get("copies"):
        try:
            parsed["copies"] = int(copies)
        except ValueError:
            raise InvalidPrintOption(option="copies") from None
    return parsed
