"""Whole-stove binary sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import StoveVisionConfigEntry
from .const import ZONES
from .coordinator import StoveVisionCoordinator, ZoneState
from .decoder import STATE_RESIDUAL_HEAT
from .entity import StoveVisionEntity


@dataclass(frozen=True, kw_only=True)
class StoveBinarySensorDescription(BinarySensorEntityDescription):
    """Which zones count."""

    zone_fn: Callable[[ZoneState], bool]


DESCRIPTIONS = (
    StoveBinarySensorDescription(
        key="on",
        translation_key="on",
        device_class=BinarySensorDeviceClass.POWER,
        zone_fn=lambda zone: zone.is_on,
    ),
    StoveBinarySensorDescription(
        key="hot",
        translation_key="hot",
        device_class=BinarySensorDeviceClass.HEAT,
        zone_fn=lambda zone: zone.is_on or zone.state == STATE_RESIDUAL_HEAT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StoveVisionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the stove binary sensors and one occupancy sensor per zone."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            *(
                StoveBinarySensor(coordinator, description)
                for description in DESCRIPTIONS
            ),
            *(ZoneOccupancySensor(coordinator, zone) for zone in ZONES),
            DangerSensor(coordinator),
            InfraredSensor(coordinator),
        ]
    )


class StoveBinarySensor(StoveVisionEntity, BinarySensorEntity):
    """True when any zone matches."""

    entity_description: StoveBinarySensorDescription

    def __init__(
        self,
        coordinator: StoveVisionCoordinator,
        description: StoveBinarySensorDescription,
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
        if self.coordinator.data is None or self.coordinator.data.infrared:
            return None
        return bool(self._matching())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The matching zones."""
        return {"zones": self._matching()}


class ZoneOccupancySensor(StoveVisionEntity, BinarySensorEntity):
    """Something (a pot, a pan) sits on the zone."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(self, coordinator: StoveVisionCoordinator, zone: str) -> None:
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


class InfraredSensor(StoveVisionEntity, BinarySensorEntity):
    """The camera is in night vision: nothing on the stove can be read."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "infrared"

    def __init__(self, coordinator: StoveVisionCoordinator) -> None:
        """Set up the sensor."""
        super().__init__(coordinator, "infrared")

    @property
    def is_on(self) -> bool | None:
        """Latest frame was an infrared one."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.infrared


class DangerSensor(StoveVisionEntity, BinarySensorEntity):
    """A zone is heating with nothing on it.

    Residual heat doesn't count (that's safe). "Nothing on it" includes
    zones whose occupancy can't be told (dark, just started): the safe side.
    Alert on this staying on for a while, not on the first frame.
    """

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_translation_key = "danger"

    def __init__(self, coordinator: StoveVisionCoordinator) -> None:
        """Set up the sensor."""
        super().__init__(coordinator, "danger")

    def _zones(self) -> dict[str, str]:
        data = self.coordinator.data
        if data is None or data.infrared:
            return {}
        result = {}
        for key, zone in data.zones.items():
            if not zone.is_on:
                continue
            occupied = data.occupancy[key].occupied
            if occupied is not True:
                result[key] = "free" if occupied is False else "unsure"
        return result

    @property
    def is_on(self) -> bool | None:
        """Any heating zone without a pot."""
        if self.coordinator.data is None or self.coordinator.data.infrared:
            return None
        return bool(self._zones())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The zones and why: free, or occupancy unsure."""
        zones = self._zones()
        data = self.coordinator.data
        return {
            "zones": list(zones),
            "reasons": zones,
            "levels": {key: data.zones[key].level for key in zones} if data else {},
        }
