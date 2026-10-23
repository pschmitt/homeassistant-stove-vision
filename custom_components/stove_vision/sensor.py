"""Zone display sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import StoveVisionConfigEntry
from .const import LEVELS, ZONES
from .coordinator import StoveVisionCoordinator
from .decoder import (
    STATE_MISALIGNED,
    STATE_OBSTRUCTED,
    STATE_OFF,
    STATE_RESIDUAL_HEAT,
    STATE_UNKNOWN,
)
from .entity import StoveVisionEntity

OPTIONS = [
    STATE_OFF,
    "0",
    *LEVELS,
    STATE_RESIDUAL_HEAT,
    STATE_OBSTRUCTED,
    STATE_UNKNOWN,
    STATE_MISALIGNED,
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StoveVisionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add one sensor per zone."""
    async_add_entities(
        [*(ZoneSensor(entry.runtime_data, key) for key in ZONES), TimerSensor(entry.runtime_data)]
    )


class ZoneSensor(StoveVisionEntity, SensorEntity):
    """What a zone display shows."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = OPTIONS

    def __init__(self, coordinator: StoveVisionCoordinator, zone: str) -> None:
        """Set up the sensor."""
        super().__init__(coordinator, zone)
        self._zone = zone
        self._attr_translation_key = zone

    @property
    def native_value(self) -> str | None:
        """Smoothed display state."""
        if self.coordinator.data is None:
            return None
        state = self.coordinator.data.zones[self._zone].state
        return state if state in OPTIONS else STATE_UNKNOWN

    @property
    def icon(self) -> str:
        """Icon by state."""
        if self.coordinator.data is None:
            return "mdi:stove"
        zone = self.coordinator.data.zones[self._zone]
        if zone.is_on:
            return "mdi:fire"
        if zone.state == STATE_RESIDUAL_HEAT:
            return "mdi:heat-wave"
        if zone.state == STATE_OBSTRUCTED:
            return "mdi:eye-off"
        return "mdi:stove"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Level, residual heat bars and the latest unsmoothed reading."""
        if self.coordinator.data is None:
            return None
        zone = self.coordinator.data.zones[self._zone]
        return {
            "level": zone.level,
            "residual_heat_bars": zone.reading.heat_bars,
            "raw_state": zone.raw.state,
            "raw_segments": "".join(map(str, zone.raw.segments)) if zone.raw.segments else None,
            "lit_pixels": zone.raw.lit_pixels,
            "alignment_offset": zone.raw.alignment_offset,
        }


class TimerSensor(StoveVisionEntity, SensorEntity):
    """Minutes actually visible on the independent timer display."""

    _attr_name = "Timer remaining"
    _attr_icon = "mdi:timer-outline"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = "min"

    def __init__(self, coordinator: StoveVisionCoordinator) -> None:
        """Set up the timer sensor."""
        super().__init__(coordinator, "timer_remaining")

    @property
    def native_value(self) -> int | None:
        """Confirmed display minutes; no inferred countdown when unreadable."""
        data = self.coordinator.data
        return data.timer_minutes if data is not None and not data.infrared else None
