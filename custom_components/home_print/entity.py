"""Base entity for Home Print."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HOST, CONF_PORT, CONF_SSL, DOMAIN
from .coordinator import HomePrintCoordinator


class HomePrintEntity(CoordinatorEntity[HomePrintCoordinator]):
    """Entity attached to the printer device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HomePrintCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        ident = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{ident}_{key}"
        info = coordinator.data
        manufacturer, _, model = info.make_model.partition(" ")
        scheme = "https" if entry.data.get(CONF_SSL) else "http"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, ident)},
            name=info.make_model or entry.title,
            manufacturer=manufacturer or None,
            model=model or info.make_model or None,
            serial_number=info.serial,
            configuration_url=(
                f"{scheme}://{entry.data[CONF_HOST]}:{entry.data[CONF_PORT]}/"
            ),
        )
