"""Polls camera frames and reads the stove displays."""

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
    CONF_CAMERA_STREAM,
    CONF_GLASS_BOX,
    CONF_RINGS_PREFIX,
    CONF_ROTATION,
    CONF_SCAN_INTERVAL,
    CONF_SMOOTHING,
    CONF_SNAPSHOT_URL,
    CONF_ZONE_PREFIX,
    DEFAULT_ROTATION,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_CAMERA_STREAM,
    DEFAULT_GLASS_BOX,
    DEFAULT_SMOOTHING,
    DEFAULT_ZONE_POSITIONS,
    DEFAULT_ZONE_RINGS,
    DOMAIN,
    FETCH_TIMEOUT,
    MAX_CONSECUTIVE_FAILURES,
    ZONES,
)
from .decoder import (
    STATE_UNKNOWN,
    DecoderSettings,
    Zone,
    ZoneReading,
    annotate,
    is_infrared,
    load_frame,
    read_frame,
    smooth,
)
from .occupancy import (
    OccupancyReading,
    OccupancyTracker,
    Ring,
    ZoneArea,
    annotate_stove,
    read_occupancy,
)

if TYPE_CHECKING:
    from . import StoveVisionConfigEntry

_LOGGER = logging.getLogger(__name__)


def parse_position(value: str) -> tuple[int, int]:
    """Parse an "x,y" zone position."""
    x, y = (int(part.strip()) for part in value.split(","))
    return x, y


def parse_ints(value: str, count: int) -> tuple[int, ...]:
    """Parse comma separated integers, exactly `count` of them."""
    parts = tuple(int(part.strip()) for part in value.split(","))
    if len(parts) != count:
        raise ValueError(f"expected {count} numbers, got {len(parts)}")
    return parts


def parse_rings(value: str) -> tuple[Ring, ...]:
    """Parse "cx,cy,rx,ry[;cx,cy,rx,ry]"."""
    rings = tuple(
        Ring(*parse_ints(part, 4)) for part in value.split(";") if part.strip()
    )
    if not rings:
        raise ValueError("no ring")
    return rings


def areas_from_options(options: dict[str, Any]) -> list[ZoneArea]:
    """The configured zone rings."""
    return [
        ZoneArea(
            key,
            parse_rings(
                options.get(f"{CONF_RINGS_PREFIX}{key}", DEFAULT_ZONE_RINGS[key])
            ),
        )
        for key in ZONES
    ]


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
    """Fetch one frame from the snapshot URL or the camera entity.

    For a camera entity, prefer one frame of its stream (decoded by HA's
    ffmpeg, full resolution) over its snapshot; fall back to the snapshot
    when the camera has no stream or the grab fails. The stream URL (with
    credentials) stays inside Home Assistant.
    """
    if camera_entity := config.get(CONF_CAMERA_ENTITY):
        from homeassistant.components import camera  # noqa: PLC0415

        if config.get(CONF_CAMERA_STREAM, DEFAULT_CAMERA_STREAM):
            from homeassistant.components.ffmpeg import (  # noqa: PLC0415
                async_get_image as ffmpeg_get_image,
            )

            source = await camera.async_get_stream_source(hass, camera_entity)
            if source:
                frame = await ffmpeg_get_image(hass, source)
                if frame:
                    return frame
                _LOGGER.debug(
                    "No frame from %s's stream, using its snapshot", camera_entity
                )
        image = await camera.async_get_image(hass, camera_entity, timeout=FETCH_TIMEOUT)
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
        """Display state: off, 0-9, residual_heat, unknown, obstructed."""
        return self.reading.state

    @property
    def level(self) -> int | None:
        """Power level, if the zone is on."""
        return int(self.state) if self.state.isdigit() and self.state != "0" else None

    @property
    def is_on(self) -> bool:
        """Zone is heating."""
        return self.level is not None


@dataclass(slots=True)
class ZoneOccupancy:
    """Debounced occupancy of a zone plus the latest frame's evidence."""

    occupied: bool | None
    reading: OccupancyReading


@dataclass(slots=True)
class StoveData:
    """Result of one poll."""

    zones: dict[str, ZoneState]
    occupancy: dict[str, ZoneOccupancy]
    frame_time: datetime
    infrared: bool = False


class StoveVisionCoordinator(DataUpdateCoordinator[StoveData]):
    """Grabs a frame every few seconds and reads the zone displays."""

    config_entry: StoveVisionConfigEntry

    def __init__(self, hass: HomeAssistant, entry: StoveVisionConfigEntry) -> None:
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
        self.areas = areas_from_options(self.config)
        self.glass_box = parse_ints(
            self.config.get(CONF_GLASS_BOX, DEFAULT_GLASS_BOX), 4
        )
        self._trackers = {area.key: OccupancyTracker() for area in self.areas}
        self._failures = 0
        self.panel_image: bytes | None = None
        self.stove_image: bytes | None = None
        self.image_time: datetime | None = None

    def _decode(
        self, frame: bytes
    ) -> tuple[
        dict[str, ZoneReading] | None, dict[str, OccupancyReading] | None, bytes, bytes
    ]:
        """Decode a frame (runs in the executor: Pillow is CPU work).

        Readings are None for an infrared frame.
        """
        img = load_frame(frame, self.rotation)
        if is_infrared(img):
            for tracker in self._trackers.values():
                tracker.reset()
            unknown = {key: None for key in self._trackers}
            return (
                None,
                None,
                annotate(img, self.zones, {}, self.settings),
                annotate_stove(img, self.areas, self.glass_box, unknown),
            )
        readings = read_frame(img, self.zones, self.settings)
        occupancy = read_occupancy(img, self.areas, self.glass_box)
        states = {
            key: self._trackers[key].update(reading)
            for key, reading in occupancy.items()
        }
        return (
            readings,
            occupancy,
            annotate(img, self.zones, readings, self.settings),
            annotate_stove(img, self.areas, self.glass_box, states),
        )

    async def _async_update_data(self) -> StoveData:
        try:
            async with asyncio.timeout(FETCH_TIMEOUT + 10):
                frame = await async_fetch_frame(self.hass, self.config)
                (
                    readings,
                    occupancy,
                    panel,
                    stove,
                ) = await self.hass.async_add_executor_job(self._decode, frame)
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
        self.panel_image, self.stove_image, self.image_time = panel, stove, now
        if readings is None or occupancy is None:
            # Night vision: nothing readable, and nothing to carry over
            for history in self._history.values():
                history.clear()
            unknown = ZoneReading(STATE_UNKNOWN)
            no_evidence = OccupancyReading(None, 0.0, 0.0, False)
            return StoveData(
                {key: ZoneState(unknown, unknown) for key in self._history},
                {key: ZoneOccupancy(None, no_evidence) for key in self._trackers},
                now,
                infrared=True,
            )
        zones = {}
        for key, reading in readings.items():
            history = self._history[key]
            history.append(reading)
            zones[key] = ZoneState(smooth(history), reading)
        occupied = {
            key: ZoneOccupancy(self._trackers[key].state, reading)
            for key, reading in occupancy.items()
        }
        return StoveData(zones, occupied, now)
