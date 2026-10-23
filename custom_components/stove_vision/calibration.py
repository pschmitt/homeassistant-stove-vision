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
CONF_TIMER_X = "timer_x"
CONF_TIMER_Y = "timer_y"

DEFAULT_LANDMARK_X = 935
DEFAULT_LANDMARK_Y = 633
DEFAULT_GLASS_BOX = "939,404,989,449"
DEFAULT_TIMER_X = 975
DEFAULT_TIMER_Y = 547

ZONES = ("rear_left", "rear_right", "front_left", "front_right")

DEFAULT_ZONE_POSITIONS = {
    "rear_left": "962,584",
    "rear_right": "1010,583",
    "front_left": "944,606",
    "front_right": "1030,608",
}

DEFAULT_ZONE_RINGS = {
    "rear_left": "798,288,74,69",
    "rear_right": "1114,322,103,103;1113,322,61,58",
    "front_left": "810,527,93,92;809,526,51,51",
    "front_right": "1148,548,74,75",
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
            ncc = sum(a * b for a, b in zip(v_diff, t_diff, strict=True)) / denom
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

    new_opts[CONF_TIMER_X] = int(new_opts.get(CONF_TIMER_X, DEFAULT_TIMER_X)) + dx
    new_opts[CONF_TIMER_Y] = int(new_opts.get(CONF_TIMER_Y, DEFAULT_TIMER_Y)) + dy

    return new_opts


def refine_digit_positions(
    img: Image.Image, options: dict[str, Any], timer_reader=None
) -> dict[str, Any]:
    """Center lit zone windows on complete digits, independently of camera drift.

    A landmark can align the panel while an individual digit's old position is
    wrong. Only move windows with compact, clearly coloured LED evidence; dark
    displays and ambiguous reflections leave their calibration untouched.
    """
    updated = dict(options)
    px = img.convert("RGB").load()
    for zone in ZONES:
        key = f"{CONF_ZONE_PREFIX}{zone}"
        cx, cy = (int(v) for v in updated.get(key, DEFAULT_ZONE_POSITIONS[zone]).split(","))
        points = []
        for y in range(max(0, cy - 13), min(img.height, cy + 14)):
            for x in range(max(0, cx - 20), min(img.width, cx + 21)):
                r, g, b = px[x, y][:3]
                if r > 130 and b > 110 and r - g > 15 and b - g > 10:
                    points.append((x, y))
        if len(points) < 4:
            continue
        x0, x1 = min(x for x, _ in points), max(x for x, _ in points)
        y0, y1 = min(y for _, y in points), max(y for _, y in points)
        if x1 - x0 > 14 or y1 - y0 > 13:
            continue
        updated[key] = f"{(x0 + x1) // 2},{(y0 + y1) // 2}"
    return refine_timer_position(img, updated, timer_reader)


def timer_position(
    img: Image.Image, options: dict[str, Any], reader=None
) -> tuple[int, int] | None:
    """Locate a complete coloured two-digit timer, independently of zone digits."""
    cx = int(options.get(CONF_TIMER_X, DEFAULT_TIMER_X))
    cy = int(options.get(CONF_TIMER_Y, DEFAULT_TIMER_Y))
    px = img.convert("RGB").load()
    points = []
    for y in range(max(0, cy - 16), min(img.height, cy + 18)):
        for x in range(max(0, cx - 15), min(img.width, cx + 28)):
            r, g, b = px[x, y][:3]
            if r > 130 and b > 110 and r - g > 15 and b - g > 10:
                points.append((x, y))
    if len(points) < 10:
        return None
    x0, x1 = min(x for x, _ in points), max(x for x, _ in points)
    y0, y1 = min(y for _, y in points), max(y for _, y in points)
    if not (17 <= x1 - x0 <= 29 and 7 <= y1 - y0 <= 20):
        return None
    # The sampling anchor is one pixel right of each glyph's geometric
    # center; the second glyph is twelve pixels to its right.
    fit_x, fit_y = (x0 + x1) // 2 - 5, (y0 + y1) // 2
    if reader is None:
        return fit_x, fit_y
    for dy in (0, -1, 1, -2, 2):
        for dx in (0, -1, 1):
            if all(digit is not None for digit in reader(img, fit_x + dx, fit_y + dy)):
                return fit_x + dx, fit_y + dy
    return None


def refine_timer_position(img: Image.Image, options: dict[str, Any], reader=None) -> dict[str, Any]:
    """Recenter the timer when both digits provide enough visible evidence."""
    updated = dict(options)
    if position := timer_position(img, options, reader):
        updated[CONF_TIMER_X], updated[CONF_TIMER_Y] = position
    return updated
