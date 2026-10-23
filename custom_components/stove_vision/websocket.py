"""Admin-only visual calibration against a frozen camera frame."""

from __future__ import annotations

import asyncio
import base64
from io import BytesIO
from uuid import uuid4

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .calibration import find_drift, refine_digit_positions, shift_options
from .const import DEFAULT_GLASS_BOX, DEFAULT_ZONE_POSITIONS, DEFAULT_ZONE_RINGS, DOMAIN
from .coordinator import async_fetch_frame, parse_ints, parse_position, parse_rings
from .decoder import Zone, is_infrared, load_frame, read_frame


def _positions(config: dict) -> dict:
    return {
        **{f"zone_{k}": config.get(f"zone_{k}", v) for k, v in DEFAULT_ZONE_POSITIONS.items()},
        **{f"rings_{k}": config.get(f"rings_{k}", v) for k, v in DEFAULT_ZONE_RINGS.items()},
        "glass_box": config.get("glass_box", DEFAULT_GLASS_BOX),
        "timer_x": config.get("timer_x", 975),
        "timer_y": config.get("timer_y", 547),
    }


def _validate(positions: dict, size: tuple[int, int]) -> None:
    width, height = size
    for key, value in positions.items():
        if key.startswith("zone_"):
            x, y = parse_position(value)
            if not (9 <= x < width - 9 and 11 <= y < height - 11):
                raise ValueError("Digit window must fit inside the frame")
        elif key.startswith("rings_"):
            for ring in parse_rings(value):
                if not (
                    ring.rx > 0
                    and ring.ry > 0
                    and 0 <= ring.cx - ring.rx < ring.cx + ring.rx < width
                    and 0 <= ring.cy - ring.ry < ring.cy + ring.ry < height
                ):
                    raise ValueError("Ring center and radii must fit the frame")
        elif key == "glass_box":
            x0, y0, x1, y1 = parse_ints(value, 4)
            if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
                raise ValueError("Glass reference must be a nonempty rectangle inside the frame")
    if not (7 <= positions["timer_x"] < width - 19 and 10 <= positions["timer_y"] < height - 10):
        raise ValueError("Both timer digits must fit inside the frame")


def _snapshot(frame: bytes, rotation: int) -> tuple:
    image = load_frame(frame, rotation)
    output = BytesIO()
    image.save(output, format="PNG")
    return image, base64.b64encode(output.getvalue()).decode("ascii")


def async_register(hass: HomeAssistant) -> None:
    """Register calibration commands; snapshots live only until entry unload."""
    snapshots: dict[str, dict] = {}

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "stove_vision/calibration",
            vol.Optional("entry_id"): str,
            vol.Optional("action", default="frame"): vol.In(
                ["list", "frame", "auto", "preview", "save"]
            ),
            vol.Optional("frame_id"): str,
            vol.Optional("positions"): dict,
        }
    )
    @websocket_api.require_admin
    @websocket_api.async_response
    async def handle(hass, connection, msg) -> None:
        try:
            entries = hass.config_entries.async_loaded_entries(DOMAIN)
            if msg["action"] == "list":
                connection.send_result(
                    msg["id"], [{"entry_id": e.entry_id, "title": e.title} for e in entries]
                )
                return
            entry = next((e for e in entries if e.entry_id == msg.get("entry_id")), None)
            if entry is None:
                raise ValueError("Choose a loaded Stove Vision integration")
            coordinator = entry.runtime_data
            if msg["action"] == "frame":
                async with asyncio.timeout(30):
                    frame = await async_fetch_frame(hass, coordinator.config)
                image, encoded = await hass.async_add_executor_job(
                    _snapshot, frame, coordinator.rotation
                )
                if is_infrared(image):
                    raise ValueError("Use a colour camera frame for calibration")
                if entry.entry_id not in snapshots:
                    entry.async_on_unload(lambda: snapshots.pop(entry.entry_id, None))
                snapshot = snapshots[entry.entry_id] = {
                    "image": image,
                    "frame_id": uuid4().hex,
                    "options": dict(entry.options),
                    "data": dict(entry.data),
                }
                connection.send_result(
                    msg["id"],
                    {
                        "image": encoded,
                        "width": image.width,
                        "height": image.height,
                        "positions": _positions(coordinator.config),
                        "frame_id": snapshot["frame_id"],
                    },
                )
                return
            snapshot = snapshots.get(entry.entry_id)
            if snapshot is None or snapshot["frame_id"] != msg.get("frame_id"):
                raise ValueError("Refresh the calibration frame first")
            if dict(entry.options) != snapshot["options"] or dict(entry.data) != snapshot["data"]:
                raise ValueError("Configuration changed; refresh the frame before saving")
            image = snapshot["image"]
            positions = _positions(coordinator.config)
            proposed = msg.get("positions", {})
            if set(proposed) - set(positions):
                raise ValueError("Only calibration positions may be changed")
            positions.update(proposed)
            if msg["action"] == "auto":
                lx = coordinator.config.get("landmark_x", 935)
                ly = coordinator.config.get("landmark_y", 633)
                drift = await hass.async_add_executor_job(find_drift, image, lx, ly)
                if drift is None:
                    raise ValueError("Landmark not found; place the windows manually")
                positions = _positions(
                    shift_options(_positions(coordinator.config), drift[0], drift[1])
                )
                positions = await hass.async_add_executor_job(
                    refine_digit_positions, image, positions
                )
                snapshot["landmark"] = (lx + drift[0], ly + drift[1])
            _validate(positions, image.size)
            zones = [
                Zone(key, *parse_position(positions[f"zone_{key}"]))
                for key in DEFAULT_ZONE_POSITIONS
            ]
            readings = await hass.async_add_executor_job(read_frame, image, zones)
            if msg["action"] == "save":
                options = {
                    **entry.options,
                    **positions,
                    "calibration_width": image.width,
                    "calibration_height": image.height,
                }
                if "landmark" in snapshot:
                    options["landmark_x"], options["landmark_y"] = snapshot["landmark"]
                hass.config_entries.async_update_entry(entry, options=options)
            connection.send_result(
                msg["id"],
                {
                    "positions": positions,
                    "readings": {k: r.state for k, r in readings.items()},
                    "saved": msg["action"] == "save",
                },
            )
        except (ValueError, TypeError, KeyError, HomeAssistantError, OSError, TimeoutError):
            connection.send_error(
                msg["id"],
                "calibration_failed",
                "Calibration failed: check the frame, positions and integration availability",
            )

    websocket_api.async_register_command(hass, handle)
