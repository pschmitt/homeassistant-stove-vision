"""Decoder tests on real frames (panel crops of a Miele hob, 1080p camera)."""

from __future__ import annotations

import importlib.util
import sys
from io import BytesIO
from pathlib import Path

import pytest

_DECODER = Path(__file__).parents[1] / "custom_components" / "hob_vision" / "decoder.py"
_spec = importlib.util.spec_from_file_location("hob_vision_decoder", _DECODER)
decoder = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = decoder
_spec.loader.exec_module(decoder)

FIXTURES = Path(__file__).parent / "fixtures"

# Digit centres in the 200x120 crops (frame offset 880,530)
ZONES = [
    decoder.Zone("rear_left", 77, 45),
    decoder.Zone("rear_right", 125, 45),
    decoder.Zone("front_left", 59, 70),
    decoder.Zone("front_right", 142, 70),
]


def _read(name: str) -> dict[str, decoder.ZoneReading]:
    img = decoder.load_frame((FIXTURES / name).read_bytes())
    return decoder.read_frame(img, ZONES)


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("off.png", ["off", "off", "off", "off"]),
        ("levels_1_2_3_4.png", ["1", "2", "3", "4"]),
        ("levels_1_1_1_1.png", ["1", "1", "1", "1"]),
    ],
)
def test_levels(fixture: str, expected: list[str]) -> None:
    readings = _read(fixture)
    assert [readings[z.key].state for z in ZONES] == expected


def test_residual_heat() -> None:
    readings = _read("residual_heat_2_2_3_3.png")
    assert [readings[z.key].state for z in ZONES] == ["residual_heat"] * 4
    assert [readings[z.key].heat_bars for z in ZONES] == [2, 2, 3, 3]


def test_residual_heat_dim() -> None:
    """Paler display (kitchen lights on), single bars."""
    readings = _read("residual_heat_dim_2_1_1_1.png")
    assert [readings[z.key].state for z in ZONES] == ["residual_heat"] * 4
    assert [readings[z.key].heat_bars for z in ZONES] == [2, 1, 1, 1]


def test_rotation_roundtrip() -> None:
    img = decoder.load_frame((FIXTURES / "levels_1_2_3_4.png").read_bytes())
    flipped = img.rotate(180)
    # load_frame rotates clockwise; 180 either way gets us back
    buf = BytesIO()
    flipped.save(buf, format="PNG")
    restored = decoder.load_frame(buf.getvalue(), rotation=180)
    readings = decoder.read_frame(restored, ZONES)
    assert [readings[z.key].state for z in ZONES] == ["1", "2", "3", "4"]


def _r(state: str) -> decoder.ZoneReading:
    return decoder.ZoneReading(state)


def test_smooth_drops_flicker() -> None:
    assert decoder.smooth([_r("3"), _r("off"), _r("3")]).state == "3"


def test_smooth_follows_change() -> None:
    assert decoder.smooth([_r("3"), _r("4"), _r("4")]).state == "4"


def test_smooth_ignores_no_info() -> None:
    history = [_r("2"), _r("obstructed"), _r("unknown")]
    assert decoder.smooth(history).state == "2"
    assert decoder.smooth([_r("obstructed")] * 3).state == "obstructed"


def test_smooth_tie_goes_to_latest() -> None:
    assert decoder.smooth([_r("2"), _r("3")]).state == "3"


def test_annotate_returns_jpeg() -> None:
    img = decoder.load_frame((FIXTURES / "levels_1_2_3_4.png").read_bytes())
    data = decoder.annotate(img, ZONES, decoder.read_frame(img, ZONES), margin=10)
    assert data[:2] == b"\xff\xd8"
