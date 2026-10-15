"""Annotated crops of the panel and the hob, to calibrate the positions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.image import ImageEntity, ImageEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HobVisionConfigEntry
from .coordinator import HobVisionCoordinator
from .entity import HobVisionEntity


@dataclass(frozen=True, kw_only=True)
class HobImageDescription(ImageEntityDescription):
    """Which annotated crop."""

    image_fn: Callable[[HobVisionCoordinator], bytes | None]


DESCRIPTIONS = (
    # Control panel: digit windows and readings
    HobImageDescription(
        key="panel",
        translation_key="panel",
        entity_category=EntityCategory.DIAGNOSTIC,
        image_fn=lambda coordinator: coordinator.panel_image,
    ),
    # Whole hob: zone rings, glass reference and occupancy
    HobImageDescription(
        key="zones",
        translation_key="zones",
        entity_category=EntityCategory.DIAGNOSTIC,
        image_fn=lambda coordinator: coordinator.hob_image,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HobVisionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the annotated images."""
    async_add_entities(
        HobImage(entry.runtime_data, description) for description in DESCRIPTIONS
    )


class HobImage(HobVisionEntity, ImageEntity):
    """The latest annotated crop."""

    _attr_content_type = "image/jpeg"
    entity_description: HobImageDescription

    def __init__(
        self, coordinator: HobVisionCoordinator, description: HobImageDescription
    ) -> None:
        """Set up the image entity."""
        HobVisionEntity.__init__(self, coordinator, description.key)
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
