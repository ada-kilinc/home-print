"""The ``home_print.print_file`` service."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
)
from homeassistant.helpers import config_validation as cv

from .const import CONF_ADMIN_ONLY, DOMAIN
from .escl.errors import EsclError
from .printing import (
    COLOR_MODES,
    SIDES,
    FileTooLarge,
    async_print,
    async_report_result,
    build_options,
    clean_file_name,
    ensure_printer,
    max_file_bytes,
    max_file_mb,
)
from .scanning import (
    COLOR_MODES as SCAN_COLOR_MODES,
)
from .scanning import (
    FORMATS,
    SOURCES,
    ScanError,
    ScanRequest,
    async_scan_and_wait,
    scan_defaults,
)
from .scans import media_root

SERVICE_PRINT_FILE = "print_file"
SERVICE_SCAN = "scan"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_PATH = "path"
ATTR_COPIES = "copies"
ATTR_SIDES = "sides"
ATTR_COLOR_MODE = "color_mode"
ATTR_PAGE_RANGES = "page_ranges"
ATTR_SOURCE = "source"
ATTR_RESOLUTION = "resolution"
ATTR_FORMAT = "format"
ATTR_FILE_NAME = "file_name"
ATTR_FOLDER = "folder"

PRINT_FILE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_PATH): cv.string,
        vol.Optional(ATTR_COPIES): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(ATTR_SIDES): vol.In(SIDES),
        vol.Optional(ATTR_COLOR_MODE): vol.In(COLOR_MODES),
        vol.Optional(ATTR_PAGE_RANGES): cv.string,
    }
)


SCAN_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_SOURCE): vol.In(SOURCES),
        vol.Optional(ATTR_COLOR_MODE): vol.In(SCAN_COLOR_MODES),
        vol.Optional(ATTR_RESOLUTION): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(ATTR_FORMAT): vol.In(FORMATS),
        vol.Optional(ATTR_FILE_NAME): cv.string,
        vol.Optional(ATTR_FOLDER): cv.string,
    }
)


class _PathNotAllowed(Exception):
    pass


class _TooLarge(Exception):
    pass


def _read_allowed_file(hass: HomeAssistant, path: str, limit: int) -> bytes:
    """Resolve, authorize and read a file. Runs in the executor."""
    try:
        resolved = Path(path).resolve()
    except (OSError, RuntimeError):
        raise _PathNotAllowed from None
    # Authorize the resolved path (so a symlink cannot point outside the
    # allowlist) before looking at whether it exists, so callers cannot probe
    # for files outside the allowlist.
    if not hass.config.is_allowed_path(str(resolved)):
        raise _PathNotAllowed
    if not resolved.is_file():
        raise FileNotFoundError(path)
    with resolved.open("rb") as file:
        if os.fstat(file.fileno()).st_size > limit:
            raise _TooLarge
        data = file.read(limit + 1)
    if len(data) > limit:  # grew after the size check
        raise _TooLarge
    return data


def _copy_unique(source: Path, folder: str, name: str) -> str:
    """Copy ``source`` into an allowed folder under a free name. Executor job."""
    target_dir = Path(folder).resolve()
    if not target_dir.is_dir():
        raise NotADirectoryError(folder)
    stem, ext = Path(name).stem, Path(name).suffix
    candidate, counter = target_dir / name, 1
    while candidate.exists():
        counter += 1
        candidate = target_dir / f"{stem} ({counter}){ext}"
    with candidate.open("xb") as out, source.open("rb") as src:
        shutil.copyfileobj(src, out)
    return str(candidate)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's services (once, from ``async_setup``)."""

    async def async_print_file(call: ServiceCall) -> ServiceResponse:
        entry = hass.config_entries.async_get_entry(call.data[ATTR_CONFIG_ENTRY_ID])
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_not_found"
            )
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_not_loaded"
            )

        user = None
        if call.context.user_id:
            user = await hass.auth.async_get_user(call.context.user_id)
            if user is None:
                raise Unauthorized(context=call.context)
            if entry.options.get(CONF_ADMIN_ONLY) and not user.is_admin:
                raise Unauthorized(context=call.context)
        ensure_printer(entry)

        options = build_options(
            entry,
            copies=call.data.get(ATTR_COPIES),
            sides=call.data.get(ATTR_SIDES),
            color_mode=call.data.get(ATTR_COLOR_MODE),
            page_ranges=call.data.get(ATTR_PAGE_RANGES),
        )

        path: str = call.data[ATTR_PATH]
        file_name = clean_file_name(path)
        try:
            data = await hass.async_add_executor_job(
                _read_allowed_file, hass, path, max_file_bytes(entry)
            )
        except _PathNotAllowed:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="path_not_allowed",
                translation_placeholders={"path": path},
            ) from None
        except _TooLarge:
            err = FileTooLarge(max=max_file_mb(entry))
            async_report_result(hass, entry, file_name=file_name, user=user, error=err)
            raise err from None
        except OSError:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="file_not_found",
                translation_placeholders={"path": path},
            ) from None

        result = await async_print(
            hass, entry, data, file_name=file_name, options=options, user=user
        )
        return {"job_id": result.job_id}

    async def async_scan(call: ServiceCall) -> ServiceResponse:
        entry = hass.config_entries.async_get_entry(call.data[ATTR_CONFIG_ENTRY_ID])
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_not_found"
            )
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_not_loaded"
            )
        scanner = entry.runtime_data.scanner
        if scanner is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_scanner"
            )

        user = None
        if call.context.user_id:
            user = await hass.auth.async_get_user(call.context.user_id)
            if user is None:
                raise Unauthorized(context=call.context)
            if entry.options.get(CONF_ADMIN_ONLY) and not user.is_admin:
                raise Unauthorized(context=call.context)

        folder: str | None = call.data.get(ATTR_FOLDER)
        if folder:
            try:
                resolved = Path(folder).resolve()
            except (OSError, RuntimeError):
                resolved = None
            if resolved is None or not hass.config.is_allowed_path(str(resolved)):
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="path_not_allowed",
                    translation_placeholders={"path": folder},
                )
            if not await hass.async_add_executor_job(resolved.is_dir):
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="folder_not_found",
                    translation_placeholders={"path": folder},
                )
            folder = str(resolved)

        defaults = scan_defaults(scanner.caps)
        request = ScanRequest(
            source=call.data.get(ATTR_SOURCE, defaults["source"]),
            color_mode=call.data.get(ATTR_COLOR_MODE, defaults["color_mode"]),
            resolution=call.data.get(ATTR_RESOLUTION, defaults["resolution"]),
            format=call.data.get(ATTR_FORMAT, defaults["format"]),
            name=call.data.get(ATTR_FILE_NAME) or None,
        )
        try:
            state = await async_scan_and_wait(
                hass, entry, request, user.name if user else None
            )
        except (ScanError, EsclError) as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=f"scan_error_{err.code}",
            ) from err
        if state.state != "done" or state.record is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=f"scan_error_{state.error or 'scan_failed'}",
            )
        record = state.record
        archived = scanner.archive.file_path(record["id"])
        if archived is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="scan_error_scan_failed"
            )
        copy: str | None = None
        if folder:
            try:
                copy = await hass.async_add_executor_job(
                    _copy_unique,
                    archived,
                    folder,
                    f"{record['name']}{archived.suffix}",
                )
            except OSError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="scan_error_copy_failed",
                    translation_placeholders={"path": folder},
                ) from err
        return {
            "path": str(media_root(hass) / record["path"]),
            "copy": copy,
            "name": record["name"],
            "pages": record["pages"],
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_SCAN,
        async_scan,
        schema=SCAN_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PRINT_FILE,
        async_print_file,
        schema=PRINT_FILE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
