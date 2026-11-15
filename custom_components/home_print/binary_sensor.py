"""Binary sensors for Home Print."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HomePrintConfigEntry
from .coordinator import HomePrintCoordinator
from .entity import HomePrintEntity

PARALLEL_UPDATES = 0

PROBLEM_PREFIXES = (
    "media-empty",
    "media-jam",
    "door-open",
    "cover-open",
    "marker-supply-empty",
    "toner-empty",
)
SEVERITY_SUFFIXES = ("-error", "-warning", "-report")


def is_problem(reason: str) -> bool:
    """Whether a printer-state-reason signals something needing attention."""
    if reason == "none" or reason.endswith("-report"):
        return False
    for suffix in SEVERITY_SUFFIXES:
        if reason.endswith(suffix):
            reason = reason[: -len(suffix)]
            break
    return reason.startswith(PROBLEM_PREFIXES)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomePrintConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ProblemBinarySensor(entry.runtime_data.coordinator)])


class ProblemBinarySensor(HomePrintEntity, BinarySensorEntity):
    """On when the printer needs attention (paper, jam, door, ink)."""

    _attr_translation_key = "problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: HomePrintCoordinator) -> None:
        super().__init__(coordinator, "problem")

    @property
    def is_on(self) -> bool:
        return any(is_problem(r) for r in self.coordinator.data.state_reasons)
