"""Decoder tests on real frames (panel crops of a Miele stove, 1080p camera)."""

from __future__ import annotations

import importlib.util
import sys
from io import BytesIO
from pathlib import Path

import pytest

_DECODER = Path(__file__).parents[1] / "custom_components" / "stove_vision" / "decoder.py"
_spec = importlib.util.spec_from_file_location("stove_vision_decoder", _DECODER)
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
        # Kitchen light reflecting off the zone key symbol under front right:
        # cut by the window it looks like a residual heat bar
        ("levels_off_5_off_off_key_glare.png", ["off", "5", "off", "off"]),
    ],
)
def test_levels(fixture: str, expected: list[str]) -> None:
    readings = _read(fixture)
    assert [readings[z.key].state for z in ZONES] == expected


def test_residual_heat() -> None:
    readings = _read("residual_heat_2_2_3_3.png")
    assert [readings[z.key].state for z in ZONES] == ["residual_heat"] * 4
    assert [readings[z.key].heat_bars for z in ZONES] == [2, 2, 3, 3]


def test_residual_heat_stray_pixel_in_gap() -> None:
    """One stray lit pixel between two bars doesn't make them a 3."""
    readings = _read("residual_heat_off_3_off_off_stray_pixel.png")
    assert readings["rear_right"].state == "residual_heat"
    assert readings["rear_right"].heat_bars == 3
    assert [readings[z].state for z in ("rear_left", "front_left", "front_right")] == ["off"] * 3


def test_residual_heat_dim() -> None:
    """Paler display (kitchen lights on), single bars."""
    readings = _read("residual_heat_dim_2_1_1_1.png")
    assert [readings[z.key].state for z in ZONES] == ["residual_heat"] * 4
    assert [readings[z.key].heat_bars for z in ZONES] == [2, 1, 1, 1]


def test_residual_heat_untinted() -> None:
    """Blue white balance: the single bar comes out white, found by contrast."""
    readings = _read("residual_heat_untinted_0_1_0_0.png")
    states = [readings[z.key].state for z in ZONES]
    assert states == ["off", "residual_heat", "off", "off"]
    assert readings["rear_right"].heat_bars == 1


def test_rotation_roundtrip() -> None:
    img = decoder.load_frame((FIXTURES / "levels_1_2_3_4.png").read_bytes())
    flipped = img.rotate(180)
    # load_frame rotates clockwise; 180 either way gets us back
    buf = BytesIO()
    flipped.save(buf, format="PNG")
    restored = decoder.load_frame(buf.getvalue(), rotation=180)
    readings = decoder.read_frame(restored, ZONES)
    assert [readings[z.key].state for z in ZONES] == ["1", "2", "3", "4"]


def test_infrared_detection() -> None:
    colour = decoder.load_frame((FIXTURES / "levels_1_2_3_4.png").read_bytes())
    assert not decoder.is_infrared(colour)
    assert decoder.is_infrared(colour.convert("L").convert("RGB"))


def _r(state: str) -> decoder.ZoneReading:
    return decoder.ZoneReading(state)


def test_smooth_drops_flicker() -> None:
    assert decoder.smooth([_r("3"), _r("off"), _r("3")]).state == "3"


def test_smooth_follows_change() -> None:
    assert decoder.smooth([_r("3"), _r("4"), _r("4")]).state == "4"


def test_smooth_off_needs_all_frames() -> None:
    assert decoder.smooth([_r("residual_heat"), _r("off"), _r("off")]).state == ("residual_heat")
    assert decoder.smooth([_r("off"), _r("off"), _r("off")]).state == "off"


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


def test_timer_independent_two_digit_display() -> None:
    from PIL import Image

    image = Image.new("RGB", (1920, 1080), (70, 70, 70))
    points = [(-1, 543), (2, 545), (1, 550), (-1, 552), (-3, 550), (-3, 545), (0, 548)]
    patterns = {glyph: pattern for pattern, glyph in decoder.SEGMENTS.items()}
    for cx, glyph in [(975, "1"), (987, "0")]:
        for (dx, y), on in zip(points, patterns[glyph], strict=True):
            if on:
                image.putpixel((cx + dx, y), (240, 200, 240))
    assert decoder.read_timer(image) == 10
    assert decoder.read_timer(Image.new("RGB", (1920, 1080))) is None


def test_timer_real_display() -> None:
    from PIL import Image

    for fixture, expected in [("timer_05.png", ("0", "5")), ("timer_partial_04.png", (None, "4"))]:
        image = Image.new("RGB", (1920, 1080))
        image.paste(Image.open(FIXTURES / fixture), (960, 535))
        assert decoder.read_timer_digits(image) == expected


def test_rear_right_reflected_key_does_not_change_eight_to_seven() -> None:
    from PIL import Image

    for fixture, expected in [("rear_right_8_key_bloom.png", "8"), ("rear_right_9.png", "9")]:
        image = Image.new("RGB", (1920, 1080))
        image.paste(Image.open(FIXTURES / fixture), (990, 565))
        assert decoder.read_zone(image, decoder.Zone("rear_right", 1005, 581)).state == expected
