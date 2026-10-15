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
    """Add the hob binary sensors."""
    async_add_entities(
        HobBinarySensor(entry.runtime_data, description) for description in DESCRIPTIONS
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
