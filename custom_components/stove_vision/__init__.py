"""The Stove Vision integration.

Reads the zone displays of a stove (power level, residual heat) from a camera
pointed at it.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS
from .coordinator import StoveVisionCoordinator
from .websocket import async_register

type StoveVisionConfigEntry = ConfigEntry[StoveVisionCoordinator]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CARD_URL = f"/{DOMAIN}/stove-vision-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "stove-vision-card.js"


_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the Lovelace card and register it as a dashboard resource."""
    async_register(hass)
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(CARD_URL, str(CARD_PATH), cache_headers=False),
            StaticPathConfig(
                f"/{DOMAIN}/calibration-card.js",
                str(CARD_PATH.with_name("calibration-card.js")),
                cache_headers=False,
            ),
        ]
    )
    # Content hash in the URL so browsers pick up a changed card
    digest = await hass.async_add_executor_job(
        lambda: hashlib.sha256(
            CARD_PATH.read_bytes() + CARD_PATH.with_name("calibration-card.js").read_bytes()
        ).hexdigest()[:10]
    )
    await _async_register_card(hass, f"{CARD_URL}?v={digest}")
    return True


async def _async_register_card(hass: HomeAssistant, url: str) -> None:
    """Keep exactly one Lovelace resource pointing at the current card.

    A resource loads before dashboards build their cards; a script added with
    add_extra_js_url can arrive too late, and some views then keep showing
    "Custom element doesn't exist". With YAML resources, fall back to that.
    """
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None or lovelace.resource_mode != "storage":
        add_extra_js_url(hass, url)
        return
    resources = lovelace.resources
    await resources.async_get_info()  # loads the collection
    mine = [item for item in resources.async_items() if item["url"].split("?")[0] == CARD_URL]
    for duplicate in mine[1:]:
        await resources.async_delete_item(duplicate["id"])
    if not mine:
        _LOGGER.info("Adding the Stove Vision card as a dashboard resource")
        await resources.async_create_item({"res_type": "module", "url": url})
    elif mine[0]["url"] != url:
        await resources.async_update_item(mine[0]["id"], {"res_type": "module", "url": url})


async def async_setup_entry(hass: HomeAssistant, entry: StoveVisionConfigEntry) -> bool:
    """Set up Stove Vision from a config entry."""
    coordinator = StoveVisionCoordinator(hass, entry)
    entry.runtime_data = coordinator

    # Never block startup on the camera: forward the platforms first and grab
    # the first frame in the background. Entities stay unavailable until then.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(hass, coordinator.async_refresh(), f"{DOMAIN}_first_refresh")
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_update))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: StoveVisionConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_on_update(hass: HomeAssistant, entry: StoveVisionConfigEntry) -> None:
    """Reload when the options change."""
    await hass.config_entries.async_reload(entry.entry_id)
