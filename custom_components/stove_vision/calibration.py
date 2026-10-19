"""Auto-calibration for camera drift using panel landmark cross-correlation."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from PIL import Image

CONF_ZONE_PREFIX = "zone_"
CONF_RINGS_PREFIX = "rings_"
CONF_GLASS_BOX = "glass_box"
CONF_LANDMARK_X = "landmark_x"
CONF_LANDMARK_Y = "landmark_y"

DEFAULT_LANDMARK_X = 935
DEFAULT_LANDMARK_Y = 633
DEFAULT_GLASS_BOX = "930,395,980,440"

ZONES = ("rear_left", "rear_right", "front_left", "front_right")

DEFAULT_ZONE_POSITIONS = {
    "rear_left": "962,584",
    "rear_right": "1010,583",
    "front_left": "944,606",
    "front_right": "1030,608",
}

DEFAULT_ZONE_RINGS = {
    "rear_left": "798,290,74,69",
    "rear_right": "1115,328,109,102;1115,328,64,60",
    "front_left": "809,538,92,94;809,538,52,53",
    "front_right": "1149,553,75,75",
}

LANDMARK_PATH = Path(__file__).parent / "panel_landmark.png"


def find_drift(
    img: Image.Image,
    base_x: int = DEFAULT_LANDMARK_X,
    base_y: int = DEFAULT_LANDMARK_Y,
    search_r: int = 30,
) -> tuple[int, int, float] | None:
    """Find (dx, dy, ncc) of the panel landmark relative to (base_x, base_y)."""
    if not LANDMARK_PATH.is_file():
        return None

    template = Image.open(LANDMARK_PATH).convert("L")
    tw, th = template.size

    w, h = img.size
    crop_x0 = max(0, base_x - search_r)
    crop_y0 = max(0, base_y - search_r)
    crop_x1 = min(w, base_x + tw + search_r)
    crop_y1 = min(h, base_y + th + search_r)

    if crop_x1 <= crop_x0 + tw or crop_y1 <= crop_y0 + th:
        return None

    sub_img = img.crop((crop_x0, crop_y0, crop_x1, crop_y1)).convert("L")
    sub_px = sub_img.load()

    t_px = template.load()
    t_vals = [t_px[x, y] for y in range(th) for x in range(tw)]
    t_mean = sum(t_vals) / len(t_vals)
    t_diff = [v - t_mean for v in t_vals]
    t_denom = sum(d * d for d in t_diff) ** 0.5
    if t_denom == 0:
        return None

    best_ncc = -1.0
    best_dx = 0
    best_dy = 0

    max_x = sub_img.width - tw
    max_y = sub_img.height - th

    for dy in range(max_y + 1):
        for dx in range(max_x + 1):
            vals = [sub_px[dx + x, dy + y] for y in range(th) for x in range(tw)]
            mean = sum(vals) / len(vals)
            v_diff = [v - mean for v in vals]
            denom = (sum(d * d for d in v_diff) ** 0.5) * t_denom
            if denom == 0:
                continue
            ncc = sum(a * b for a, b in zip(v_diff, t_diff)) / denom
            if ncc > best_ncc:
                best_ncc = ncc
                best_dx = (crop_x0 + dx) - base_x
                best_dy = (crop_y0 + dy) - base_y

    if best_ncc < 0.5:
        return None

    return best_dx, best_dy, best_ncc


def shift_options(options: dict[str, Any], dx: int, dy: int) -> dict[str, Any]:
    """Shift all zone coordinates, rings, and bare glass box by (dx, dy)."""
    new_opts = dict(options)

    for key in ZONES:
        zk = f"{CONF_ZONE_PREFIX}{key}"
        pos_val = str(new_opts.get(zk, DEFAULT_ZONE_POSITIONS[key]))
        x, y = (int(p.strip()) for p in pos_val.split(","))
        new_opts[zk] = f"{x + dx},{y + dy}"

        rk = f"{CONF_RINGS_PREFIX}{key}"
        rings_val = str(new_opts.get(rk, DEFAULT_ZONE_RINGS[key]))
        shifted_rings = []
        for part in rings_val.split(";"):
            if not part.strip():
                continue
            cx, cy, rx, ry = (int(p.strip()) for p in part.split(","))
            shifted_rings.append(f"{cx + dx},{cy + dy},{rx},{ry}")
        new_opts[rk] = ";".join(shifted_rings)

    gb_val = str(new_opts.get(CONF_GLASS_BOX, DEFAULT_GLASS_BOX))
    x0, y0, x1, y1 = (int(p.strip()) for p in gb_val.split(","))
    new_opts[CONF_GLASS_BOX] = f"{x0 + dx},{y0 + dy},{x1 + dx},{y1 + dy}"

    lx = int(new_opts.get(CONF_LANDMARK_X, DEFAULT_LANDMARK_X))
    ly = int(new_opts.get(CONF_LANDMARK_Y, DEFAULT_LANDMARK_Y))
    new_opts[CONF_LANDMARK_X] = lx + dx
    new_opts[CONF_LANDMARK_Y] = ly + dy

    return new_opts
