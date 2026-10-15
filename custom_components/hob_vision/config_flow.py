"""Config flow for Hob Vision."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_CAMERA_ENTITY,
    CONF_ROTATION,
    CONF_SCAN_INTERVAL,
    CONF_SMOOTHING,
    CONF_SNAPSHOT_URL,
    CONF_ZONE_PREFIX,
    DEFAULT_NAME,
    DEFAULT_ROTATION,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SMOOTHING,
    DEFAULT_SNAPSHOT_URL,
    DEFAULT_ZONE_POSITIONS,
    DOMAIN,
    ZONES,
)
from .coordinator import async_fetch_frame, parse_position
from .decoder import load_frame

_LOGGER = logging.getLogger(__name__)

ROTATIONS = ["0", "90", "180", "270"]


def _source_schema(defaults: dict[str, Any]) -> dict[vol.Marker, Any]:
    return {
        vol.Optional(
            CONF_SNAPSHOT_URL,
            description={"suggested_value": defaults.get(CONF_SNAPSHOT_URL)},
        ): selector.TextSelector(selector.TextSelectorConfig(type="url")),
        vol.Optional(
            CONF_CAMERA_ENTITY,
            description={"suggested_value": defaults.get(CONF_CAMERA_ENTITY)},
        ): selector.EntitySelector(selector.EntitySelectorConfig(domain="camera")),
        vol.Required(
            CONF_ROTATION, default=str(defaults.get(CONF_ROTATION, DEFAULT_ROTATION))
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=ROTATIONS, mode=selector.SelectSelectorMode.DROPDOWN
            )
        ),
    }


def _tuning_schema(defaults: dict[str, Any]) -> dict[vol.Marker, Any]:
    schema: dict[vol.Marker, Any] = {
        vol.Required(
            CONF_SCAN_INTERVAL,
            default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=2,
                max=300,
                step=1,
                unit_of_measurement="s",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Required(
            CONF_SMOOTHING, default=defaults.get(CONF_SMOOTHING, DEFAULT_SMOOTHING)
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1, max=10, step=1, mode=selector.NumberSelectorMode.BOX
            )
        ),
    }
    for zone in ZONES:
        key = f"{CONF_ZONE_PREFIX}{zone}"
        schema[
            vol.Required(key, default=defaults.get(key, DEFAULT_ZONE_POSITIONS[zone]))
        ] = selector.TextSelector()
    return schema


async def _async_validate(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> dict[str, str]:
    """Check the source delivers a decodable frame and positions parse."""
    errors: dict[str, str] = {}
    if not user_input.get(CONF_SNAPSHOT_URL) and not user_input.get(CONF_CAMERA_ENTITY):
        return {"base": "no_source"}
    for zone in ZONES:
        key = f"{CONF_ZONE_PREFIX}{zone}"
        if key in user_input:
            try:
                parse_position(user_input[key])
            except ValueError:
                errors[key] = "invalid_position"
    if errors:
        return errors
    try:
        frame = await async_fetch_frame(hass, user_input)
        await hass.async_add_executor_job(
            load_frame, frame, int(user_input.get(CONF_ROTATION, 0))
        )
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Frame check failed", exc_info=True)
        errors["base"] = "cannot_fetch"
    return errors


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    data = dict(user_input)
    data[CONF_ROTATION] = int(data.get(CONF_ROTATION, DEFAULT_ROTATION))
    for key in (CONF_SCAN_INTERVAL, CONF_SMOOTHING):
        if key in data:
            data[key] = int(data[key])
    # The camera entity wins when both are set; drop the empty one
    for key in (CONF_SNAPSHOT_URL, CONF_CAMERA_ENTITY):
        if not data.get(key):
            data.pop(key, None)
    return data


class HobVisionConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a hob display reader."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name and frame source."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await _async_validate(self.hass, user_input)
            if not errors:
                options = _normalize(user_input)
                title = options.pop(CONF_NAME)
                return self.async_create_entry(title=title, data={}, options=options)
        defaults = user_input or {CONF_SNAPSHOT_URL: DEFAULT_SNAPSHOT_URL}
        schema = {
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): str,
            **_source_schema(defaults),
        }
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema(schema), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        """Options: source, rotation, polling and zone positions."""
        return HobVisionOptionsFlow()


class HobVisionOptionsFlow(OptionsFlow):
    """Change the source and calibrate the zone positions."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Single options step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await _async_validate(self.hass, user_input)
            if not errors:
                return self.async_create_entry(data=_normalize(user_input))
        defaults = user_input or dict(self.config_entry.options)
        schema = {**_source_schema(defaults), **_tuning_schema(defaults)}
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(schema), errors=errors
        )
