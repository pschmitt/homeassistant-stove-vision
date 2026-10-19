"""Diagnostic button: read a frame now."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import StoveVisionConfigEntry
from .calibration import find_drift, shift_options
from .const import CONF_LANDMARK_X, CONF_LANDMARK_Y, DEFAULT_LANDMARK_X, DEFAULT_LANDMARK_Y
from .coordinator import StoveVisionCoordinator, async_fetch_frame
from .decoder import load_frame
from .entity import StoveVisionEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StoveVisionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the refresh and calibrate buttons."""
    async_add_entities([
        RefreshButton(entry.runtime_data),
        CalibrateButton(entry.runtime_data),
    ])


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


class CalibrateButton(StoveVisionEntity, ButtonEntity):
    """Calibrate zone and ring positions by matching the control panel landmark."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "calibrate"
    _attr_name = "Calibrate"
    _attr_icon = "mdi:crosshairs-gps"

    def __init__(self, coordinator: StoveVisionCoordinator) -> None:
        """Set up the button."""
        super().__init__(coordinator, "calibrate")

    @property
    def available(self) -> bool:
        """Always pressable, also when the last poll failed."""
        return True

    async def async_press(self) -> None:
        """Locate landmark, calculate camera drift, and update options."""
        frame = await async_fetch_frame(self.hass, self.coordinator.config)
        img = load_frame(frame, self.coordinator.rotation)

        lx = int(self.coordinator.config.get(CONF_LANDMARK_X, DEFAULT_LANDMARK_X))
        ly = int(self.coordinator.config.get(CONF_LANDMARK_Y, DEFAULT_LANDMARK_Y))

        drift = await self.hass.async_add_executor_job(find_drift, img, lx, ly)
        if drift is None:
            raise HomeAssistantError(
                "Could not locate panel landmark. Ensure the stove control panel is clean and visible."
            )

        dx, dy, ncc = drift
        _LOGGER.info(
            "Stove Vision calibration: dx=%d, dy=%d (confidence=%.2f)",
            dx,
            dy,
            ncc,
        )
        if dx == 0 and dy == 0:
            return

        new_options = shift_options(self.coordinator.config_entry.options, dx, dy)
        self.hass.config_entries.async_update_entry(
            self.coordinator.config_entry,
            options=new_options,
        )

