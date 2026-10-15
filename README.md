# Hob Vision

Home Assistant integration that reads the zone displays of a hob (power
level, residual heat) and whether something sits on each zone from a camera
pointed at it. No smart hob, no cloud:
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
| `binary_sensor.<name>_rear_left_occupied` (and the other zones) | Something (a pot, a pan) sits on the zone. Attributes: `ring_visibility`, `brightness`, the raw verdict of the latest frame |
| `image.<name>_zones` | The hob with the zone rings (orange: occupied, blue: free, grey: unsure) and the bare glass reference (yellow) |

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
don't qualify. Under some light the camera shifts its white balance and the
dimmer residual heat bars lose their tint; those are then found by contrast
and shape (short wide strokes, dark gaps). Segments are then sampled on brightness, after undoing the
italic slant of the digits, and matched against the seven-segment patterns.

Single frames are noisy: the displays are multiplexed, so a frame often
catches a lit display dark, while a lit display never appears out of
nothing. So a zone only reads `off` when all of the last few frames agree;
otherwise the most common lit reading wins. Frames where a zone is covered
don't vote. Expect a change to show up within a few polls.

## How it sees pots

Each zone has a printed ring on the glass. On bare glass the ring shows as a
thin line brighter than the glass on either side; a pot or pan on the zone
hides it. And the inside of the zone is compared to a patch of bare glass
between the zones: a metal pot, a pan rim or a hand is much brighter.

The ring only shows by reflecting room light, so a person standing at the
hob can shadow the front rings for a minute. Hence:

- something bright on the zone, or the ring clearly visible again, switches
  the sensor after 2 frames,
- a hidden ring alone (a dark pan) needs 6 frames, and only counts when the
  ring is almost entirely gone (a shadow leaves part of it),
- anything in between keeps the previous state.

A pot smaller than the ring doesn't hide it; it is then only found by being
brighter than the glass. Dual zones have both rings checked.

Set the rings in the options (`cx,cy,rx,ry`, `;` between the two rings of a
dual zone) by looking at the *Zones* image.

## Tests

```sh
python -m pytest tests
```

The fixtures are crops of the control panel and the hob glass only.
