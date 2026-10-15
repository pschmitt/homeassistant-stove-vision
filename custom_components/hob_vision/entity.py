"""Base entity for Hob Vision."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HobVisionCoordinator


class HobVisionEntity(CoordinatorEntity[HobVisionCoordinator]):
    """An entity of the hob device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HobVisionCoordinator, key: str) -> None:
        """Set up the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            model="Display reader (camera)",
        )
