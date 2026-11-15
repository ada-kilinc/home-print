"""Config flow and options flow for Home Print."""

from __future__ import annotations

import logging
from typing import Any

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
    CONF_MAX_FILE_MB,
    CONF_SCAN_INTERVAL,
    DEFAULT_MAX_FILE_MB,
    DEFAULT_PATH,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .models import PrinterInfo, normalize_uuid

_LOGGER = logging.getLogger(__name__)

SIDES_OPTIONS = ["one-sided", "two-sided-long-edge", "two-sided-short-edge"]
COLOR_OPTIONS = ["auto", "color", "monochrome"]
COLOR_AUTO = "auto"  # sentinel stored as None ("printer default")


def _unique_id(
    info: PrinterInfo, host: str, port: int, base_path: str, txt_uuid: str = ""
) -> str:
    """Pick a stable id: printer uuid, TXT uuid, serial, then address."""
    return info.uuid or txt_uuid or info.serial or f"{host}:{port}{base_path}"


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
                info = await self._probe(data)
            except CannotConnect:
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

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
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
            self._abort_if_unique_id_configured(
                updates={CONF_HOST: host, CONF_PORT: port}
            )

        try:
            info = await self._probe(data)
        except Exception:
            _LOGGER.debug("Probe of discovered printer %s failed", host, exc_info=True)
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(
            _unique_id(info, host, port, base_path, txt_uuid)
        )
        self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})

        self._data = data
        self._title = info.make_model
        self.context["title_placeholders"] = {"name": info.make_model}
        return await self.async_step_zeroconf_confirm()

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


class HomePrintOptionsFlow(OptionsFlow):
    """Edit Home Print options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            if user_input.get(CONF_DEFAULT_COLOR_MODE) == COLOR_AUTO:
                user_input = {**user_input, CONF_DEFAULT_COLOR_MODE: None}
            user_input = {
                **user_input,
                CONF_MAX_FILE_MB: int(user_input[CONF_MAX_FILE_MB]),
                CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
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
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
