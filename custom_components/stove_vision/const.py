"""Constants for Stove Vision."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "stove_vision"
PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.IMAGE, Platform.SENSOR]

CONF_SNAPSHOT_URL = "snapshot_url"
CONF_CAMERA_ENTITY = "camera_entity"
CONF_CAMERA_STREAM = "camera_stream"
CONF_ROTATION = "rotation"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_SMOOTHING = "smoothing"

# Zone keys, in the order they appear on the panel
ZONES = ("rear_left", "rear_right", "front_left", "front_right")
CONF_ZONE_PREFIX = "zone_"
CONF_RINGS_PREFIX = "rings_"
CONF_GLASS_BOX = "glass_box"

DEFAULT_NAME = "Stove"
DEFAULT_SNAPSHOT_URL = (
    "http://ccab4aaf-frigate:1984/api/frame.jpeg?src=magicam_main_rtsp"
)
DEFAULT_ROTATION = 0
# Read a frame from the camera entity's stream (full resolution) rather than
# its snapshot, which many cameras (e.g. behind a Reolink Home Hub) scale down
DEFAULT_CAMERA_STREAM = True
DEFAULT_SCAN_INTERVAL = 10
DEFAULT_SMOOTHING = 3
# Digit centres in a 1080p frame of the Miele panel this was calibrated on
DEFAULT_ZONE_POSITIONS = {
    "rear_left": "957,575",
    "rear_right": "1005,575",
    "front_left": "939,600",
    "front_right": "1022,600",
}
# Printed rings per zone (cx,cy,rx,ry; dual zones have two, separated by ";")
# and a patch of bare glass between the zones, same frame
DEFAULT_ZONE_RINGS = {
    "rear_left": "795,280,71,70",
    "rear_right": "1111,311,105,103;1111,309,61,59",
    "front_left": "809,519,91,92;809,518,51,52",
    "front_right": "1148,536,73,74",
}
DEFAULT_GLASS_BOX = "930,395,980,440"

# A frame grab (go2rtc waits for a keyframe) or decode can fail now and then;
# keep the last state for a few polls before going unavailable.
MAX_CONSECUTIVE_FAILURES = 3
FETCH_TIMEOUT = 20

LEVELS = tuple(str(level) for level in range(1, 10))
