"""Annotated crop of the control panel, to calibrate the zone positions."""

from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HobVisionConfigEntry
from .coordinator import HobVisionCoordinator
from .entity import HobVisionEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HobVisionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the panel image."""
    async_add_entities([PanelImage(entry.runtime_data)])


class PanelImage(HobVisionEntity, ImageEntity):
    """The panel as last seen, with the zone windows and what was read."""

    _attr_content_type = "image/jpeg"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "panel"

    def __init__(self, coordinator: HobVisionCoordinator) -> None:
        """Set up the image entity."""
        HobVisionEntity.__init__(self, coordinator, "panel")
        ImageEntity.__init__(self, coordinator.hass)
        self._attr_image_last_updated = coordinator.panel_image_time

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_image_last_updated = self.coordinator.panel_image_time
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        """Latest annotated panel crop."""
        return self.coordinator.panel_image
