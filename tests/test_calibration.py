"""Tests for camera drift calibration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from PIL import Image
import pytest

_DIR = Path(__file__).parents[1] / "custom_components" / "stove_vision"
sys.path.insert(0, str(_DIR))
_CALIBRATION = _DIR / "calibration.py"
_spec = importlib.util.spec_from_file_location("stove_vision_calibration", _CALIBRATION)
calibration = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = calibration
_spec.loader.exec_module(calibration)


def test_shift_options() -> None:
    options = {
        "zone_rear_left": "957,581",
        "zone_rear_right": "1005,581",
        "zone_front_left": "939,600",
        "zone_front_right": "1022,600",
        "rings_rear_left": "795,280,71,70",
        "rings_rear_right": "1111,311,105,103;1111,309,61,59",
        "rings_front_left": "809,519,91,92;809,518,51,52",
        "rings_front_right": "1148,536,73,74",
        "glass_box": "930,395,980,440",
        "landmark_x": 935,
        "landmark_y": 633,
    }

    shifted = calibration.shift_options(options, 10, -5)

    assert shifted["zone_rear_left"] == "967,576"
    assert shifted["zone_rear_right"] == "1015,576"
    assert shifted["zone_front_left"] == "949,595"
    assert shifted["zone_front_right"] == "1032,595"
    assert shifted["rings_rear_left"] == "805,275,71,70"
    assert shifted["rings_rear_right"] == "1121,306,105,103;1121,304,61,59"
    assert shifted["rings_front_left"] == "819,514,91,92;819,513,51,52"
    assert shifted["rings_front_right"] == "1158,531,73,74"
    assert shifted["glass_box"] == "940,390,990,435"
    assert shifted["landmark_x"] == 945
    assert shifted["landmark_y"] == 628


def test_find_drift_synthetic() -> None:
    # Create synthetic image with the landmark placed at (935, 633)
    template = Image.open(calibration.LANDMARK_PATH)
    tw, th = template.size

    img = Image.new("RGB", (1920, 1080), (30, 30, 30))
    img.paste(template, (935, 633))

    drift = calibration.find_drift(img, base_x=935, base_y=633)
    assert drift is not None
    dx, dy, ncc = drift
    assert (dx, dy) == (0, 0)
    assert ncc > 0.99


def test_find_drift_shifted() -> None:
    template = Image.open(calibration.LANDMARK_PATH)
    img = Image.new("RGB", (1920, 1080), (30, 30, 30))
    # Shifted by +6 in x, -4 in y
    img.paste(template, (935 + 6, 633 - 4))

    drift = calibration.find_drift(img, base_x=935, base_y=633)
    assert drift is not None
    dx, dy, ncc = drift
    assert (dx, dy) == (6, -4)
    assert ncc > 0.99


def test_find_drift_unreadable() -> None:
    # Blank image has no landmark
    img = Image.new("RGB", (1920, 1080), (30, 30, 30))
    assert calibration.find_drift(img, base_x=935, base_y=633) is None
