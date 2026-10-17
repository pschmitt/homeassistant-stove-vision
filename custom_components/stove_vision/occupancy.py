"""Tell whether something sits on each cooking zone.

Pure Pillow, no Home Assistant imports, so it can be tested on saved frames.

Two cues per zone:

- the printed ring(s) around the zone: visible on bare glass, hidden under a
  pot. The ring only shows by reflecting room light, so a person standing at
  the stove can shadow it for a while; that is why a hidden ring alone is only
  trusted after several frames (see OccupancyTracker).
- the inside of the zone compared to a patch of bare glass: a pot, a pan rim
  or a hand is much brighter than the dark glass.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageDraw


@dataclass(frozen=True, slots=True)
class Ring:
    """A printed ring on the glass: an ellipse in the (rotated) frame."""

    cx: int
    cy: int
    rx: int
    ry: int


@dataclass(frozen=True, slots=True)
class ZoneArea:
    """A cooking zone and its ring(s); dual zones have two."""

    key: str
    rings: tuple[Ring, ...]


@dataclass(frozen=True, slots=True)
class OccupancySettings:
    """Tuning knobs. The defaults fit a 1080p frame of a Miele ceramic stove."""

    samples: int = 120
    # A ring point is visible when it is this much brighter than the glass
    # just inside and outside the line
    line_ratio: float = 1.25
    line_offset: float = 5.0
    line_gap: int = 4
    # Fraction of ring points visible
    hidden_below: float = 0.12
    # A ring this hidden is covered, not shadowed (a person at the stove
    # never took a ring below 0.17): switch as fast as for something bright
    covered_below: float = 0.05
    # No trace of the line at all (see _ring_visibility): covered, whatever
    # the light. Empty rings never went below 0.28 in the recordings, a dark
    # pan's were 0.02-0.16.
    line_gone_below: float = 0.22
    # The line traceable almost all around: free, even in light too flat for
    # the ring to stand out clearly (covered rings stayed below 0.5)
    line_present_above: float = 0.6
    # A hidden ring only counts when some other zone's ring is this visible in
    # the same frame, i.e. the light is good enough to see rings at all
    good_light: float = 0.85
    visible_above: float = 0.5
    # Inside of the zone vs the bare glass reference (0-255 brightness)
    bright_delta: float = 65.0
    interior_scale: float = 0.92
    interior_step: int = 3


@dataclass(frozen=True, slots=True)
class OccupancyReading:
    """One frame's evidence for one zone."""

    occupied: bool | None
    ring_visibility: float
    brightness: float
    bright: bool
    # Clear evidence (bright, or the ring entirely gone): switch fast
    certain: bool = False
    # Lowest share of ring points with any trace of the line
    ring_line: float = 1.0


def _ring_visibility(
    px, size: tuple[int, int], ring: Ring, s: OccupancySettings
) -> tuple[float, float]:
    """Share of ring points where the line is clearly visible, and where it
    is brighter than the glass beside it at all.

    The second stays around chance (~0.3-0.4) even for a ring the room light
    doesn't reach, but drops far below it under a pan: the smooth pan bottom
    shows no line whatsoever.
    """
    w, h = size

    def value(radius_offset: float, cos: float, sin: float) -> float:
        x = min(w - 1, max(0, int(ring.cx + (ring.rx + radius_offset) * cos)))
        y = min(h - 1, max(0, int(ring.cy + (ring.ry + radius_offset) * sin)))
        return px[x, y]

    visible = lit = 0
    for i in range(s.samples):
        angle = 2 * math.pi * i / s.samples
        cos, sin = math.cos(angle), math.sin(angle)
        line = max(value(k, cos, sin) for k in (-1, 0, 1))
        glass = max(value(-s.line_gap, cos, sin), value(s.line_gap, cos, sin))
        visible += line > glass * s.line_ratio + s.line_offset
        lit += line > glass
    return visible / s.samples, lit / s.samples


def _interior_median(px, size: tuple[int, int], ring: Ring, s: OccupancySettings) -> float:
    w, h = size
    rx, ry = ring.rx * s.interior_scale, ring.ry * s.interior_scale
    values = []
    for y in range(max(0, int(ring.cy - ry)), min(h, int(ring.cy + ry) + 1), s.interior_step):
        for x in range(max(0, int(ring.cx - rx)), min(w, int(ring.cx + rx) + 1), s.interior_step):
            if ((x - ring.cx) / rx) ** 2 + ((y - ring.cy) / ry) ** 2 <= 1:
                values.append(px[x, y])
    values.sort()
    return values[len(values) // 2] if values else 0.0


def _box_median(px, box: tuple[int, int, int, int]) -> float:
    x0, y0, x1, y1 = box
    values = sorted(px[x, y] for y in range(y0, y1) for x in range(x0, x1))
    return values[len(values) // 2] if values else 0.0


def read_occupancy(
    img: Image.Image,
    areas: Iterable[ZoneArea],
    glass_box: tuple[int, int, int, int],
    settings: OccupancySettings | None = None,
) -> dict[str, OccupancyReading]:
    """Evidence per zone from one frame."""
    s = settings or OccupancySettings()
    # Green only: a heating zone glows red/orange (little green) and must not
    # look like a pot; steel, pan rims and the printed rings are neutral.
    gray = img.convert("RGB").getchannel("G")
    px = gray.load()
    glass = _box_median(px, glass_box)
    areas = list(areas)
    ring_stats = {
        area.key: [_ring_visibility(px, gray.size, ring, s) for ring in area.rings]
        for area in areas
    }
    ring_visibility = {key: [v for v, _ in stats] for key, stats in ring_stats.items()}
    readings = {}
    for area in areas:
        visibility = min(ring_visibility[area.key])
        ring_line = min(line for _, line in ring_stats[area.key])
        gone = ring_line < s.line_gone_below
        good_light = any(
            max(values) >= s.good_light
            for key, values in ring_visibility.items()
            if key != area.key
        )
        # The outer ring bounds the zone
        outer = max(area.rings, key=lambda ring: ring.rx * ring.ry)
        brightness = _interior_median(px, gray.size, outer, s) - glass
        bright = brightness > s.bright_delta
        if bright or gone or (good_light and visibility < s.hidden_below):
            occupied: bool | None = True
        elif visibility >= s.visible_above or ring_line >= s.line_present_above:
            occupied = False
        else:
            occupied = None
        certain = bright or (good_light and visibility < s.covered_below)
        readings[area.key] = OccupancyReading(
            occupied, visibility, brightness, bright, certain, ring_line
        )
    return readings


class OccupancyTracker:
    """Debounce a zone's occupancy over frames.

    Clear evidence (something bright on the zone, its ring entirely gone, or
    the ring visible again) switches after a couple of frames; a partly hidden
    ring on its own needs more, as a person at the stove shadows the rings
    for a while.
    """

    def __init__(self, fast: int = 2, slow: int = 6) -> None:
        """Set the number of agreeing frames needed to switch."""
        self.fast = fast
        self.slow = slow
        self.reset()

    def reset(self) -> None:
        """Forget everything (e.g. after frames that couldn't be read)."""
        self.state: bool | None = None
        self.last: OccupancyReading | None = None
        self._pending: bool | None = None
        self._count = 0
        self._unsure_count = 0

    def update(self, reading: OccupancyReading) -> bool | None:
        """Feed one frame's reading, return the debounced state."""
        self.last = reading
        if reading.occupied is None:
            self._pending, self._count = None, 0
            self._unsure_count += 1
            # Reflections can hide an empty ring indefinitely. Do not retain
            # an old occupancy verdict after sustained uncertainty.
            if self._unsure_count >= self.slow:
                self.state = None
            return self.state
        self._unsure_count = 0
        # No shortcut for the first readings after a start: a single frame
        # with a shadowed ring must not latch "occupied"
        if reading.occupied == self.state:
            self._pending, self._count = None, 0
            return self.state
        if reading.occupied != self._pending:
            self._pending, self._count = reading.occupied, 0
        self._count += 1
        certain = reading.certain or reading.bright
        needed = self.slow if reading.occupied and not certain else self.fast
        if self._count >= needed:
            self.state = reading.occupied
            self._pending, self._count = None, 0
        return self.state


def annotate_stove(
    img: Image.Image,
    areas: Sequence[ZoneArea],
    glass_box: tuple[int, int, int, int],
    states: dict[str, bool | None],
    margin: int = 30,
) -> bytes:
    """JPEG of the stove with the rings, the glass reference and the states.

    Used to calibrate the ring positions.
    """
    rings = [ring for area in areas for ring in area.rings]
    left = max(0, min(min(r.cx - r.rx for r in rings), glass_box[0]) - margin)
    top = max(0, min(min(r.cy - r.ry for r in rings), glass_box[1]) - margin)
    right = min(img.width, max(max(r.cx + r.rx for r in rings), glass_box[2]) + margin)
    bottom = min(img.height, max(max(r.cy + r.ry for r in rings), glass_box[3]) + margin)
    stove = img.crop((left, top, right, bottom)).convert("RGB")
    draw = ImageDraw.Draw(stove)
    colours = {True: (255, 80, 0), False: (0, 200, 255), None: (160, 160, 160)}
    for area in areas:
        colour = colours[states.get(area.key)]
        for ring in area.rings:
            draw.ellipse(
                (
                    ring.cx - ring.rx - left,
                    ring.cy - ring.ry - top,
                    ring.cx + ring.rx - left,
                    ring.cy + ring.ry - top,
                ),
                outline=colour,
                width=2,
            )
        outer = max(area.rings, key=lambda ring: ring.rx * ring.ry)
        label = {True: "occupied", False: "free", None: "?"}[states.get(area.key)]
        draw.text(
            (outer.cx - left - 25, outer.cy - top - 6),
            f"{area.key}\n{label}",
            fill=colour,
        )
    x0, y0, x1, y1 = glass_box
    draw.rectangle((x0 - left, y0 - top, x1 - left, y1 - top), outline=(255, 255, 0))
    out = BytesIO()
    stove.save(out, format="JPEG", quality=80)
    return out.getvalue()
