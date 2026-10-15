"""The Stove Vision integration.

Reads the zone displays of a stove (power level, residual heat) from a camera
pointed at it.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import StoveVisionCoordinator

type StoveVisionConfigEntry = ConfigEntry[StoveVisionCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: StoveVisionConfigEntry) -> bool:
    """Set up Stove Vision from a config entry."""
    coordinator = StoveVisionCoordinator(hass, entry)
    entry.runtime_data = coordinator

    # Never block startup on the camera: forward the platforms first and grab
    # the first frame in the background. Entities stay unavailable until then.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(
        hass, coordinator.async_refresh(), f"{DOMAIN}_first_refresh"
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_update))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: StoveVisionConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_on_update(
    hass: HomeAssistant, entry: StoveVisionConfigEntry
) -> None:
    """Reload when the options change."""
    await hass.config_entries.async_reload(entry.entry_id)
