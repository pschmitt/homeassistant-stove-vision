"""Polls camera frames and reads the hob displays."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from aiohttp import ClientError, ClientTimeout

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CAMERA_ENTITY,
    CONF_ROTATION,
    CONF_SCAN_INTERVAL,
    CONF_SMOOTHING,
    CONF_SNAPSHOT_URL,
    CONF_ZONE_PREFIX,
    DEFAULT_ROTATION,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SMOOTHING,
    DEFAULT_ZONE_POSITIONS,
    DOMAIN,
    FETCH_TIMEOUT,
    MAX_CONSECUTIVE_FAILURES,
    STATE_BOOST,
    ZONES,
)
from .decoder import (
    DecoderSettings,
    Zone,
    ZoneReading,
    annotate,
    load_frame,
    read_frame,
    smooth,
)

if TYPE_CHECKING:
    from . import HobVisionConfigEntry

_LOGGER = logging.getLogger(__name__)


def parse_position(value: str) -> tuple[int, int]:
    """Parse an "x,y" zone position."""
    x, y = (int(part.strip()) for part in value.split(","))
    return x, y


def zones_from_options(options: dict[str, Any]) -> list[Zone]:
    """The configured zone positions."""
    zones = []
    for key in ZONES:
        x, y = parse_position(
            options.get(f"{CONF_ZONE_PREFIX}{key}", DEFAULT_ZONE_POSITIONS[key])
        )
        zones.append(Zone(key, x, y))
    return zones


async def async_fetch_frame(hass: HomeAssistant, config: dict[str, Any]) -> bytes:
    """Fetch one frame from the snapshot URL or the camera entity."""
    if camera_entity := config.get(CONF_CAMERA_ENTITY):
        from homeassistant.components.camera import async_get_image  # noqa: PLC0415

        image = await async_get_image(hass, camera_entity, timeout=FETCH_TIMEOUT)
        return image.content
    session = async_get_clientsession(hass)
    async with session.get(
        config[CONF_SNAPSHOT_URL], timeout=ClientTimeout(total=FETCH_TIMEOUT)
    ) as resp:
        resp.raise_for_status()
        return await resp.read()


@dataclass(slots=True)
class ZoneState:
    """Smoothed state of a zone plus the latest raw reading."""

    reading: ZoneReading
    raw: ZoneReading

    @property
    def state(self) -> str:
        """Display state: off, 1-9, boost, residual_heat, unknown, obstructed."""
        return STATE_BOOST if self.reading.state == "P" else self.reading.state

    @property
    def level(self) -> int | None:
        """Power level, if the zone is on."""
        return int(self.state) if self.state.isdigit() and self.state != "0" else None

    @property
    def is_on(self) -> bool:
        """Zone is heating."""
        return self.level is not None or self.state == STATE_BOOST


@dataclass(slots=True)
class HobData:
    """Result of one poll."""

    zones: dict[str, ZoneState]
    frame_time: datetime


class HobVisionCoordinator(DataUpdateCoordinator[HobData]):
    """Grabs a frame every few seconds and reads the zone displays."""

    config_entry: HobVisionConfigEntry

    def __init__(self, hass: HomeAssistant, entry: HobVisionConfigEntry) -> None:
        """Set up the coordinator from the entry's data and options."""
        self.config: dict[str, Any] = {**entry.data, **entry.options}
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=self.config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.zones = zones_from_options(self.config)
        self.rotation = int(self.config.get(CONF_ROTATION, DEFAULT_ROTATION))
        self.settings = DecoderSettings()
        smoothing = int(self.config.get(CONF_SMOOTHING, DEFAULT_SMOOTHING))
        self._history: dict[str, deque[ZoneReading]] = {
            zone.key: deque(maxlen=max(1, smoothing)) for zone in self.zones
        }
        self._failures = 0
        self.panel_image: bytes | None = None
        self.panel_image_time: datetime | None = None

    def _decode(self, frame: bytes) -> tuple[dict[str, ZoneReading], bytes]:
        """Decode a frame (runs in the executor: Pillow is CPU work)."""
        img = load_frame(frame, self.rotation)
        readings = read_frame(img, self.zones, self.settings)
        return readings, annotate(img, self.zones, readings, self.settings)

    async def _async_update_data(self) -> HobData:
        try:
            async with asyncio.timeout(FETCH_TIMEOUT + 10):
                frame = await async_fetch_frame(self.hass, self.config)
                readings, panel = await self.hass.async_add_executor_job(
                    self._decode, frame
                )
        except (
            ClientError,
            HomeAssistantError,
            OSError,
            ValueError,
            TimeoutError,
        ) as err:
            # OSError covers Pillow's UnidentifiedImageError (truncated or
            # empty frames)
            self._failures += 1
            if self.data is not None and self._failures < MAX_CONSECUTIVE_FAILURES:
                _LOGGER.debug("Skipping bad frame (%s): %s", self._failures, err)
                return self.data
            raise UpdateFailed(f"Could not read a frame: {err}") from err
        self._failures = 0

        now = dt_util.utcnow()
        self.panel_image, self.panel_image_time = panel, now
        zones = {}
        for key, reading in readings.items():
            history = self._history[key]
            history.append(reading)
            zones[key] = ZoneState(smooth(history), reading)
        return HobData(zones, now)
