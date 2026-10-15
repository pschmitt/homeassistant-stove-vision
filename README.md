# Hob Vision

Home Assistant integration that reads the zone displays of a hob (power
level, residual heat) from a camera pointed at it. No smart hob, no cloud:
it polls a frame every few seconds and decodes the seven-segment digits.

Calibrated on a Miele ceramic hob with red displays seen from above by a
1080p camera, but nothing in it is Miele-specific except the residual heat
pattern (stacked horizontal bars).

## Entities

| Entity | |
|---|---|
| `sensor.<name>_rear_left` (and `rear_right`, `front_left`, `front_right`) | `off`, `1`-`9`, `boost`, `residual_heat`, `obstructed`, `unknown`. Attributes: `level`, `residual_heat_bars`, the raw (unsmoothed) reading |
| `binary_sensor.<name>_on` | Any zone is heating. Attribute `zones` |
| `binary_sensor.<name>_hot` | Any zone is heating or shows residual heat |
| `image.<name>_panel` | The panel as last seen, with the zone windows and readings drawn in (diagnostic, for calibration) |

## Setup

1. Point a camera at the hob so the control panel is readable. Use the full
   resolution stream: a digit is only about 7x12 pixels at 1080p. Camera
   entities usually only hand out a reduced snapshot; a go2rtc
   `api/frame.jpeg?src=<stream>` URL gives a full frame.
2. Add the integration with that URL (or a camera entity) and the rotation
   that makes the panel upright.
3. Turn all zones on at different levels, open the *Panel* image and adjust
   the zone positions in the options until each box sits on its digit.

## How it reads the display

The LEDs clip the camera sensor: segment cores come out white, only their
edges keep the display colour. A zone counts as lit when its window has
enough tinted pixels; white glare from cabinet lights and orange pot handles
don't qualify. Segments are then sampled on brightness, after undoing the
italic slant of the digits, and matched against the seven-segment patterns.

Single frames are noisy (the displays are multiplexed, hands and pots get in
the way), so each zone reports a majority vote over the last few frames.
Frames where a zone is covered don't vote.

## Tests

```sh
python -m pytest tests
```

The fixtures are crops of the control panel only.
