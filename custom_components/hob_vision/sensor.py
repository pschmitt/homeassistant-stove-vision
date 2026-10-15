"""Zone display sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HobVisionConfigEntry
from .const import LEVELS, STATE_BOOST, ZONES
from .coordinator import HobVisionCoordinator
from .decoder import STATE_OBSTRUCTED, STATE_OFF, STATE_RESIDUAL_HEAT, STATE_UNKNOWN
from .entity import HobVisionEntity

OPTIONS = [
    STATE_OFF,
    "0",
    *LEVELS,
    STATE_BOOST,
    STATE_RESIDUAL_HEAT,
    STATE_OBSTRUCTED,
    STATE_UNKNOWN,
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HobVisionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add one sensor per zone."""
    async_add_entities(ZoneSensor(entry.runtime_data, key) for key in ZONES)


class ZoneSensor(HobVisionEntity, SensorEntity):
    """What a zone display shows."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = OPTIONS

    def __init__(self, coordinator: HobVisionCoordinator, zone: str) -> None:
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
            "raw_segments": "".join(map(str, zone.raw.segments))
            if zone.raw.segments
            else None,
            "lit_pixels": zone.raw.lit_pixels,
        }
