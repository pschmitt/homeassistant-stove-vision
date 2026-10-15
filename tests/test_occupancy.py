"""Occupancy tests on real frames (crops of a Miele stove, 1080p camera)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from PIL import Image
import pytest

_MODULE = (
    Path(__file__).parents[1] / "custom_components" / "stove_vision" / "occupancy.py"
)
_spec = importlib.util.spec_from_file_location("stove_vision_occupancy", _MODULE)
occupancy = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = occupancy
_spec.loader.exec_module(occupancy)

FIXTURES = Path(__file__).parent / "fixtures"
Ring, ZoneArea = occupancy.Ring, occupancy.ZoneArea

# Rings in the 580x500 crops (frame offset 690,160)
AREAS = [
    ZoneArea("rear_left", (Ring(105, 120, 71, 70),)),
    ZoneArea("rear_right", (Ring(421, 151, 105, 103), Ring(421, 149, 61, 59))),
    ZoneArea("front_left", (Ring(119, 359, 91, 92), Ring(119, 358, 51, 52))),
    ZoneArea("front_right", (Ring(458, 376, 73, 74),)),
]
GLASS = (240, 235, 290, 280)


def _read(name: str) -> dict[str, occupancy.OccupancyReading]:
    img = Image.open(FIXTURES / name).convert("RGB")
    return occupancy.read_occupancy(img, AREAS, GLASS)


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("stove_empty.png", [False, False, False, False]),
        ("stove_empty_glare.png", [False, False, False, False]),
        ("stove_pot_rear_right.png", [False, True, False, False]),
    ],
)
def test_occupancy(fixture: str, expected: list[bool]) -> None:
    readings = _read(fixture)
    assert [readings[a.key].occupied for a in AREAS] == expected


def test_dark_kitchen_is_unsure() -> None:
    """Lights off: some rings vanish. Without good light that's no evidence."""
    readings = _read("stove_dark_pot_rear_right.png")
    assert readings["front_right"].occupied is None
    assert readings["rear_right"].occupied is not False
    assert readings["rear_left"].occupied is False


def test_pot_is_bright() -> None:
    assert _read("stove_pot_rear_right.png")["rear_right"].bright


def test_shadow_is_not_occupied() -> None:
    """A person at the stove shadows the front ring: unsure, not occupied."""
    reading = _read("stove_shadow_front_right.png")["front_right"]
    assert reading.occupied is not True


def _r(occupied: bool | None, bright: bool = False) -> occupancy.OccupancyReading:
    return occupancy.OccupancyReading(occupied, 0.0, 0.0, bright)


def _settle(tracker: occupancy.OccupancyTracker, reading) -> None:
    for _ in range(tracker.slow):
        tracker.update(reading)


def test_tracker_first_readings_are_debounced() -> None:
    tracker = occupancy.OccupancyTracker(fast=2, slow=6)
    assert tracker.update(_r(False)) is None
    assert tracker.update(_r(False)) is False


def test_tracker_start_with_hidden_ring_needs_slow() -> None:
    tracker = occupancy.OccupancyTracker(fast=2, slow=6)
    states = [tracker.update(_r(True)) for _ in range(6)]
    assert states == [None] * 5 + [True]


def test_tracker_bright_switches_fast() -> None:
    tracker = occupancy.OccupancyTracker(fast=2, slow=6)
    _settle(tracker, _r(False))
    assert tracker.update(_r(True, bright=True)) is False
    assert tracker.update(_r(True, bright=True)) is True


def test_tracker_hidden_ring_switches_slow() -> None:
    tracker = occupancy.OccupancyTracker(fast=2, slow=6)
    _settle(tracker, _r(False))
    states = [tracker.update(_r(True)) for _ in range(6)]
    assert states == [False] * 5 + [True]


def test_tracker_covered_ring_switches_fast() -> None:
    tracker = occupancy.OccupancyTracker(fast=2, slow=6)
    _settle(tracker, _r(False))
    covered = occupancy.OccupancyReading(True, 0.0, 20.0, False, True)
    assert tracker.update(covered) is False
    assert tracker.update(covered) is True


def test_dark_pan_ring_entirely_hidden_is_certain() -> None:
    """A dark pan (barely brighter than glass) hiding the whole inner ring."""
    reading = _read("stove_dark_pan_rear_right.png")["rear_right"]
    assert reading.occupied is True
    assert not reading.bright
    assert reading.certain


def test_tracker_unsure_keeps_state() -> None:
    tracker = occupancy.OccupancyTracker()
    _settle(tracker, _r(True, bright=True))
    assert tracker.update(_r(None)) is True
    assert tracker.update(_r(None)) is True


def test_annotate_stove_returns_jpeg() -> None:
    img = Image.open(FIXTURES / "stove_empty.png").convert("RGB")
    data = occupancy.annotate_stove(img, AREAS, GLASS, {a.key: False for a in AREAS})
    assert data[:2] == b"\xff\xd8"
