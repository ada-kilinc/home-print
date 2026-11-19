"""Config flow and options flow for Home Print."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SSL, CONF_VERIFY_SSL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .client import CannotConnect, HomePrintClient
from .const import (
    CONF_ADMIN_ONLY,
    CONF_BASE_PATH,
    CONF_DEFAULT_COLOR_MODE,
    CONF_DEFAULT_SIDES,
    CONF_HISTORY_DAYS,
    CONF_KIND,
    CONF_MAX_FILE_MB,
    CONF_SCAN_DAYS,
    CONF_SCAN_INTERVAL,
    CONF_SCAN_MAX_MB,
    CONF_SCANNER_ANNOUNCED,
    CONF_SCANNER_TXT,
    CONF_SCANNER_URL,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_MAX_FILE_MB,
    DEFAULT_PATH,
    DEFAULT_PORT,
    DEFAULT_SCAN_DAYS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCAN_MAX_MB,
    DOMAIN,
    KIND_SCANNER,
    MAX_HISTORY_DAYS,
    MAX_SCAN_DAYS,
    MAX_SCAN_MB,
)
from .escl.client import (
    EsclError,
    ScannerUnavailable,
    find_scanner,
    probe_scanner,
    url_host,
)
from .escl.models import ScannerCaps
from .models import PrinterInfo, normalize_uuid

_LOGGER = logging.getLogger(__name__)

SIDES_OPTIONS = ["one-sided", "two-sided-long-edge", "two-sided-short-edge"]
COLOR_OPTIONS = ["auto", "color", "monochrome"]
COLOR_AUTO = "auto"  # sentinel stored as None ("printer default")

# Zeroconf TXT keys of an eSCL scanner kept for diagnostics. Location-like
# keys ("note") are left out.
SCANNER_TXT_KEYS = (
    "ty",
    "rs",
    "vers",
    "representation",
    "pdl",
    "cs",
    "is",
    "duplex",
    "UUID",
)
# Options a scanner without a printer has.
SCANNER_OPTIONS = (
    CONF_SCAN_INTERVAL,
    CONF_ADMIN_ONLY,
    CONF_SCANNER_URL,
    CONF_SCAN_DAYS,
    CONF_SCAN_MAX_MB,
)


def _unique_id(
    info: PrinterInfo, host: str, port: int, base_path: str, txt_uuid: str = ""
) -> str:
    """Pick a stable id: printer uuid, TXT uuid, serial, then address."""
    return info.uuid or txt_uuid or info.serial or f"{host}:{port}{base_path}"


def _scanner_unique_id(host: str, caps: ScannerCaps, txt_uuid: str = "") -> str:
    """A scanner-only entry's id: TXT uuid, eSCL uuid, then the address."""
    return txt_uuid or normalize_uuid(caps.uuid or "") or f"scanner:{host}"


def _scanner_data(host: str, base_url: str, ssl: bool, txt: dict[str, str]) -> dict:
    return {
        CONF_KIND: KIND_SCANNER,
        CONF_HOST: host,
        CONF_SSL: ssl,
        # Scanners use self-signed certificates (HP); like discovered printers.
        CONF_VERIFY_SSL: False,
        CONF_SCANNER_ANNOUNCED: base_url,
        CONF_SCANNER_TXT: txt,
    }


class HomePrintConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Home Print."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._title = ""

    async def _probe(self, data: dict[str, Any]) -> PrinterInfo:
        session = async_get_clientsession(self.hass, verify_ssl=data[CONF_VERIFY_SSL])
        client = HomePrintClient(
            data[CONF_HOST],
            data[CONF_PORT],
            data[CONF_BASE_PATH],
            data[CONF_SSL],
            data[CONF_VERIFY_SSL],
            session,
        )
        return await client.get_printer()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                CONF_HOST: user_input[CONF_HOST].strip(),
                CONF_PORT: user_input.get(CONF_PORT, DEFAULT_PORT),
                CONF_BASE_PATH: user_input.get(CONF_BASE_PATH, DEFAULT_PATH),
                CONF_SSL: user_input.get(CONF_SSL, False),
                CONF_VERIFY_SSL: user_input.get(CONF_VERIFY_SSL, True),
            }
            try:
                if "://" in data[CONF_HOST]:
                    # A typed eSCL address: a scanner, not a printer.
                    raise CannotConnect("scanner address")
                info = await self._probe(data)
            except CannotConnect:
                # No printer there: maybe a scanner without one.
                if (result := await self._async_user_scanner(data)) is not None:
                    return result
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error while probing printer")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(
                    _unique_id(
                        info, data[CONF_HOST], data[CONF_PORT], data[CONF_BASE_PATH]
                    )
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info.make_model, data=data)

        defaults = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Optional(CONF_BASE_PATH, default=DEFAULT_PATH): str,
                vol.Optional(CONF_SSL, default=False): bool,
                vol.Optional(CONF_VERIFY_SSL, default=True): bool,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def _async_user_scanner(
        self, data: dict[str, Any]
    ) -> ConfigFlowResult | None:
        """Add a scanner-only entry for a typed address; None if none answers."""
        typed = data[CONF_HOST]
        session = async_get_clientsession(self.hass, verify_ssl=False)
        try:
            if "://" in typed:
                url = normalize_scanner_url(typed)
                base, caps = await probe_scanner(session, url, verify_ssl=False)
            else:
                found = await find_scanner(session, typed, ssl=False, verify_ssl=False)
                if found is None:
                    return None
                base, caps = found
        except (ValueError, EsclError, ScannerUnavailable):
            return None
        except Exception:  # noqa: BLE001 - shown as "cannot connect"
            _LOGGER.debug("Probe of scanner %s failed", typed, exc_info=True)
            return None
        host = urlsplit(base).hostname or typed
        await self.async_set_unique_id(_scanner_unique_id(host, caps))
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=caps.make_model or host,
            data=_scanner_data(host, base, base.startswith("https:"), {}),
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        if discovery_info.type.startswith(("_uscan.", "_uscans.")):
            return await self._async_step_scanner_zeroconf(discovery_info)
        host = str(discovery_info.host)
        port = discovery_info.port or DEFAULT_PORT
        props = discovery_info.properties
        rp = (props.get("rp") or "").strip("/")
        base_path = f"/{rp}" if rp else DEFAULT_PATH
        data = {
            CONF_HOST: host,
            CONF_PORT: port,
            CONF_BASE_PATH: base_path,
            CONF_SSL: discovery_info.type.startswith("_ipps."),
            # Deliberately off: printers advertising ipps almost always use
            # self-signed certs; verification is a per-printer setting.
            CONF_VERIFY_SSL: False,
        }
        txt_uuid = normalize_uuid(props.get("UUID") or "")

        # A known TXT uuid lets us dedupe (and follow IP changes) before probing.
        if txt_uuid:
            await self.async_set_unique_id(txt_uuid)
            self._abort_if_unique_id_configured(updates=self._zeroconf_updates(data))

        try:
            info = await self._probe(data)
        except Exception:
            _LOGGER.debug("Probe of discovered printer %s failed", host, exc_info=True)
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(
            _unique_id(info, host, port, base_path, txt_uuid)
        )
        self._abort_if_unique_id_configured(updates=self._zeroconf_updates(data))

        self._data = data
        self._title = info.make_model
        self.context["title_placeholders"] = {"name": info.make_model}
        return await self.async_step_zeroconf_confirm()

    async def _async_step_scanner_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """An eSCL scanner announced itself (_uscan / _uscans).

        - Part of a printer that is already added (same host or UUID): that
          entry uses the announced address from now on (unless one was typed).
        - A printer answers IPP at the same host: offered as that printer,
          with this scanner, so one device gives one entry.
        - Otherwise: offered as a scanner without a printer.
        """
        host = str(discovery_info.host)
        secure = discovery_info.type.startswith("_uscans.")
        props = {k: str(v) for k, v in discovery_info.properties.items()}
        port = discovery_info.port or (443 if secure else 80)
        scheme = "https" if secure else "http"
        default_port = (scheme == "https" and port == 443) or port == 80
        netloc = url_host(host) if default_port else f"{url_host(host)}:{port}"
        rs = (props.get("rs") or "eSCL").strip("/")
        url = f"{scheme}://{netloc}/{rs}" if rs else f"{scheme}://{netloc}"
        txt = {k: props[k] for k in SCANNER_TXT_KEYS if k in props}
        txt_uuid = normalize_uuid(props.get("UUID") or "")

        for entry in self._async_current_entries(include_ignore=False):
            same_uuid = bool(txt_uuid) and entry.unique_id == txt_uuid
            if not same_uuid and entry.data.get(CONF_HOST) != host:
                continue
            updates: dict[str, Any] = {}
            known = str(entry.data.get(CONF_SCANNER_ANNOUNCED) or "")
            # A scanner may announce both _uscan and _uscans; the address only
            # follows announcements of the scheme it already has, so the two
            # don't take turns (and reload the entry each time).
            same_scheme = not known or urlsplit(known).scheme == scheme
            if not entry.options.get(CONF_SCANNER_URL) and same_scheme:
                updates[CONF_SCANNER_ANNOUNCED] = url
            if entry.data.get(CONF_KIND) == KIND_SCANNER and same_scheme:
                updates[CONF_HOST] = host
            if any(entry.data.get(k) != v for k, v in updates.items()):
                # A changed address reloads the entry (update listener).
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, **updates, CONF_SCANNER_TXT: txt}
                )
            return self.async_abort(reason="already_configured")

        printer = {
            CONF_HOST: host,
            CONF_PORT: DEFAULT_PORT,
            CONF_BASE_PATH: DEFAULT_PATH,
            CONF_SSL: False,
            CONF_VERIFY_SSL: False,
        }
        try:
            info = await self._probe(printer)
        except Exception:  # noqa: BLE001 - no printer there is normal
            info = None
        if info is not None:
            await self.async_set_unique_id(
                _unique_id(info, host, DEFAULT_PORT, DEFAULT_PATH, txt_uuid)
            )
            self._abort_if_unique_id_configured()
            self._data = {
                **printer,
                CONF_SCANNER_ANNOUNCED: url,
                CONF_SCANNER_TXT: txt,
            }
            self._title = info.make_model
            self.context["title_placeholders"] = {"name": info.make_model}
            return await self.async_step_zeroconf_confirm()

        session = async_get_clientsession(self.hass, verify_ssl=False)
        try:
            base, caps = await probe_scanner(session, url, verify_ssl=False)
        except Exception:  # noqa: BLE001 - an unreadable scanner isn't offered
            _LOGGER.debug("Probe of discovered scanner %s failed", url, exc_info=True)
            return self.async_abort(reason="cannot_connect")
        await self.async_set_unique_id(_scanner_unique_id(host, caps, txt_uuid))
        self._abort_if_unique_id_configured()
        self._data = _scanner_data(host, base, secure, txt)
        self._title = caps.make_model or props.get("ty") or host
        self.context["title_placeholders"] = {"name": self._title}
        return await self.async_step_zeroconf_confirm_scanner()

    async def async_step_zeroconf_confirm_scanner(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title=self._title, data=self._data)
        return self.async_show_form(
            step_id="zeroconf_confirm_scanner",
            description_placeholders={
                "name": self._title,
                "host": self._data[CONF_HOST],
            },
        )

    def _zeroconf_updates(self, data: dict[str, Any]) -> dict[str, Any]:
        """Entry updates for a re-announcement of an already configured printer.

        A printer may advertise both _ipp (631) and _ipps (443). Port and path
        belong to one transport, so they only follow a discovery of the same
        type as the entry; otherwise only the host is updated.
        """
        updates: dict[str, Any] = {CONF_HOST: data[CONF_HOST]}
        entry = self.hass.config_entries.async_entry_for_domain_unique_id(
            DOMAIN, self.unique_id
        )
        if entry is not None and bool(entry.data.get(CONF_SSL)) == data[CONF_SSL]:
            updates[CONF_PORT] = data[CONF_PORT]
            updates[CONF_BASE_PATH] = data[CONF_BASE_PATH]
        return updates

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title=self._title, data=self._data)
        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={
                "name": self._title,
                "host": self._data[CONF_HOST],
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> HomePrintOptionsFlow:
        return HomePrintOptionsFlow()


def normalize_scanner_url(value: str | None) -> str:
    """Tidy a typed scanner address; empty means "find automatically".

    No scheme means ``http://``, no path means ``/eSCL``. Anything that is
    not an http(s) URL with a host raises ``ValueError``.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"http://{text}"
    parts = urlsplit(text)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(text)
    _ = parts.port  # raises ValueError for a bad port
    path = parts.path.rstrip("/") or "/eSCL"
    return urlunsplit((scheme, parts.netloc, path, parts.query, ""))


class HomePrintOptionsFlow(OptionsFlow):
    """Edit Home Print options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                scanner_url = normalize_scanner_url(user_input.get(CONF_SCANNER_URL))
            except ValueError:
                errors[CONF_SCANNER_URL] = "invalid_scanner_url"
        if user_input is not None and not errors:
            if user_input.get(CONF_DEFAULT_COLOR_MODE) == COLOR_AUTO:
                user_input = {**user_input, CONF_DEFAULT_COLOR_MODE: None}
            numbers = (
                CONF_MAX_FILE_MB,
                CONF_SCAN_INTERVAL,
                CONF_HISTORY_DAYS,
                CONF_SCAN_DAYS,
                CONF_SCAN_MAX_MB,
            )
            user_input = {
                # A scanner-only entry's form has fewer fields; keep the rest.
                **self.config_entry.options,
                **user_input,
                **{k: int(user_input[k]) for k in numbers if k in user_input},
                CONF_SCANNER_URL: scanner_url,
            }
            return self.async_create_entry(data=user_input)

        opts = self.config_entry.options
        color = opts.get(CONF_DEFAULT_COLOR_MODE) or COLOR_AUTO
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DEFAULT_SIDES,
                    default=opts.get(CONF_DEFAULT_SIDES, "one-sided"),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=SIDES_OPTIONS,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="sides",
                    )
                ),
                vol.Required(CONF_DEFAULT_COLOR_MODE, default=color): SelectSelector(
                    SelectSelectorConfig(
                        options=COLOR_OPTIONS,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="color_mode",
                    )
                ),
                vol.Required(
                    CONF_MAX_FILE_MB,
                    default=opts.get(CONF_MAX_FILE_MB, DEFAULT_MAX_FILE_MB),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=200, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=15, max=3600, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_ADMIN_ONLY, default=opts.get(CONF_ADMIN_ONLY, False)
                ): BooleanSelector(),
                vol.Required(
                    CONF_HISTORY_DAYS,
                    default=opts.get(CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=MAX_HISTORY_DAYS, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_SCANNER_URL,
                    default=opts.get(CONF_SCANNER_URL, ""),
                ): str,
                vol.Required(
                    CONF_SCAN_DAYS,
                    default=opts.get(CONF_SCAN_DAYS, DEFAULT_SCAN_DAYS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=MAX_SCAN_DAYS, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_SCAN_MAX_MB,
                    default=opts.get(CONF_SCAN_MAX_MB, DEFAULT_SCAN_MAX_MB),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=MAX_SCAN_MB, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
            }
        )
        if self.config_entry.data.get(CONF_KIND) == KIND_SCANNER:
            # A scanner without a printer: only the scanning settings.
            schema = vol.Schema(
                {
                    key: value
                    for key, value in schema.schema.items()
                    if str(key) in SCANNER_OPTIONS
                }
            )
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
