"""Sensors for Home Print: status, ink/toner levels and last job."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HomePrintConfigEntry
from .coordinator import HomePrintCoordinator
from .entity import HomePrintEntity

PARALLEL_UPDATES = 0

STATES = ["idle", "processing", "stopped"]
SCANNER_STATES = ["idle", "scanning", "adf_loaded", "stopped"]


def reasons_of(state_reasons: tuple[str, ...]) -> list[str]:
    """Return the reasons list; the IPP value ``none`` means no reasons."""
    return [r for r in state_reasons if r != "none"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomePrintConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[SensorEntity] = [
        StatusSensor(coordinator),
        LastJobSensor(coordinator),
    ]
    if entry.runtime_data.scanner is not None:
        entities.append(ScannerStatusSensor(coordinator))
    entities.extend(
        MarkerSensor(coordinator, index)
        for index in range(len(coordinator.data.markers))
    )
    async_add_entities(entities)


class StatusSensor(HomePrintEntity, SensorEntity):
    """Printer state (idle / processing / stopped)."""

    _attr_translation_key = "status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATES

    def __init__(self, coordinator: HomePrintCoordinator) -> None:
        super().__init__(coordinator, "status")

    @property
    def native_value(self) -> str | None:
        state = self.coordinator.data.state
        return state if state in STATES else None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        return {"reasons": reasons_of(self.coordinator.data.state_reasons)}


class MarkerSensor(HomePrintEntity, SensorEntity):
    """One ink/toner/waste marker level."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 0
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HomePrintCoordinator, index: int) -> None:
        super().__init__(coordinator, f"marker_{index}")
        self._index = index
        marker = coordinator.data.markers[index]
        self._attr_name = marker.name
        # Ink/toner levels are primary; waste/maintenance boxes are diagnostic.
        if "waste" in marker.kind or "maintenance" in marker.kind:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        return super().available and self._index < len(self.coordinator.data.markers)

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.markers[self._index].level

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        marker = self.coordinator.data.markers[self._index]
        return {"color": marker.color, "kind": marker.kind}


class LastJobSensor(HomePrintEntity, SensorEntity):
    """File name of the last job submitted from Home Assistant."""

    _attr_translation_key = "last_job"

    def __init__(self, coordinator: HomePrintCoordinator) -> None:
        super().__init__(coordinator, "last_job")

    @property
    def native_value(self) -> str | None:
        job = self.coordinator.last_job
        return job.file_name if job else None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        job = self.coordinator.last_job
        if job is None:
            return {}
        return {
            "job_id": job.job_id,
            "state": job.state,
            "user": job.user,
            "time": job.time.isoformat(),
        }


class ScannerStatusSensor(HomePrintEntity, SensorEntity):
    """Scanner state (idle / scanning / paper in the ADF / stopped)."""

    _attr_translation_key = "scanner_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = SCANNER_STATES

    def __init__(self, coordinator: HomePrintCoordinator) -> None:
        super().__init__(coordinator, "scanner_status")

    @property
    def available(self) -> bool:
        scanner = self.coordinator.scanner
        return super().available and scanner is not None and scanner.status is not None

    @property
    def native_value(self) -> str | None:
        scanner = self.coordinator.scanner
        status = scanner.status if scanner else None
        if status is None:
            return None
        if status.state in ("processing", "testing"):
            return "scanning"
        if status.state in ("stopped", "down"):
            return "stopped"
        if status.state == "idle":
            return "adf_loaded" if status.adf_loaded else "idle"
        return None
