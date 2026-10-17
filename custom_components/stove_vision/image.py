"""Annotated crops of the panel and the stove, to calibrate the positions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.image import ImageEntity, ImageEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import StoveVisionConfigEntry
from .coordinator import StoveVisionCoordinator
from .entity import StoveVisionEntity


@dataclass(frozen=True, kw_only=True)
class StoveImageDescription(ImageEntityDescription):
    """Which annotated crop."""

    image_fn: Callable[[StoveVisionCoordinator], bytes | None]


DESCRIPTIONS = (
    # Control panel: digit windows and readings
    StoveImageDescription(
        key="panel",
        translation_key="panel",
        entity_category=EntityCategory.DIAGNOSTIC,
        image_fn=lambda coordinator: coordinator.panel_image,
    ),
    # Whole stove: zone rings, glass reference and occupancy
    StoveImageDescription(
        key="zones",
        translation_key="zones",
        entity_category=EntityCategory.DIAGNOSTIC,
        image_fn=lambda coordinator: coordinator.stove_image,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StoveVisionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the annotated images."""
    async_add_entities(StoveImage(entry.runtime_data, description) for description in DESCRIPTIONS)


class StoveImage(StoveVisionEntity, ImageEntity):
    """The latest annotated crop."""

    _attr_content_type = "image/jpeg"
    entity_description: StoveImageDescription

    def __init__(
        self, coordinator: StoveVisionCoordinator, description: StoveImageDescription
    ) -> None:
        """Set up the image entity."""
        StoveVisionEntity.__init__(self, coordinator, description.key)
        ImageEntity.__init__(self, coordinator.hass)
        self.entity_description = description
        self._attr_image_last_updated = coordinator.image_time

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_image_last_updated = self.coordinator.image_time
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        """Latest annotated crop."""
        return self.entity_description.image_fn(self.coordinator)
