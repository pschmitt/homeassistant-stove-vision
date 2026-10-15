"""Whole-hob binary sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HobVisionConfigEntry
from .const import ZONES
from .coordinator import HobVisionCoordinator, ZoneState
from .decoder import STATE_RESIDUAL_HEAT
from .entity import HobVisionEntity


@dataclass(frozen=True, kw_only=True)
class HobBinarySensorDescription(BinarySensorEntityDescription):
    """Which zones count."""

    zone_fn: Callable[[ZoneState], bool]


DESCRIPTIONS = (
    HobBinarySensorDescription(
        key="on",
        translation_key="on",
        device_class=BinarySensorDeviceClass.POWER,
        zone_fn=lambda zone: zone.is_on,
    ),
    HobBinarySensorDescription(
        key="hot",
        translation_key="hot",
        device_class=BinarySensorDeviceClass.HEAT,
        zone_fn=lambda zone: zone.is_on or zone.state == STATE_RESIDUAL_HEAT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HobVisionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the hob binary sensors and one occupancy sensor per zone."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            *(
                HobBinarySensor(coordinator, description)
                for description in DESCRIPTIONS
            ),
            *(ZoneOccupancySensor(coordinator, zone) for zone in ZONES),
        ]
    )


class HobBinarySensor(HobVisionEntity, BinarySensorEntity):
    """True when any zone matches."""

    entity_description: HobBinarySensorDescription

    def __init__(
        self, coordinator: HobVisionCoordinator, description: HobBinarySensorDescription
    ) -> None:
        """Set up the binary sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    def _matching(self) -> list[str]:
        if self.coordinator.data is None:
            return []
        return [
            key
            for key, zone in self.coordinator.data.zones.items()
            if self.entity_description.zone_fn(zone)
        ]

    @property
    def is_on(self) -> bool | None:
        """Any zone matches."""
        if self.coordinator.data is None:
            return None
        return bool(self._matching())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The matching zones."""
        return {"zones": self._matching()}


class ZoneOccupancySensor(HobVisionEntity, BinarySensorEntity):
    """Something (a pot, a pan) sits on the zone."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(self, coordinator: HobVisionCoordinator, zone: str) -> None:
        """Set up the sensor."""
        super().__init__(coordinator, f"{zone}_occupied")
        self._zone = zone
        self._attr_translation_key = f"{zone}_occupied"

    @property
    def available(self) -> bool:
        """Unavailable until there is a verdict."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.data.occupancy[self._zone].occupied is not None
        )

    @property
    def is_on(self) -> bool | None:
        """Debounced occupancy."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.occupancy[self._zone].occupied

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The latest frame's evidence."""
        if self.coordinator.data is None:
            return None
        reading = self.coordinator.data.occupancy[self._zone].reading
        return {
            "ring_visibility": round(reading.ring_visibility, 2),
            "brightness": round(reading.brightness),
            "raw": {True: "occupied", False: "free", None: "unsure"}[reading.occupied],
        }
