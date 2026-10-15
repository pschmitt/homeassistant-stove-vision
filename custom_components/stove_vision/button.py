"""Diagnostic button: read a frame now."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import StoveVisionConfigEntry
from .coordinator import StoveVisionCoordinator
from .entity import StoveVisionEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StoveVisionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the refresh button."""
    async_add_entities([RefreshButton(entry.runtime_data)])


class RefreshButton(StoveVisionEntity, ButtonEntity):
    """Fetch and decode a frame right away instead of at the next poll."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "refresh"

    def __init__(self, coordinator: StoveVisionCoordinator) -> None:
        """Set up the button."""
        super().__init__(coordinator, "refresh")

    @property
    def available(self) -> bool:
        """Always pressable, also when the last poll failed."""
        return True

    async def async_press(self) -> None:
        """Poll now."""
        await self.coordinator.async_refresh()
