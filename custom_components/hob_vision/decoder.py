"""Read the seven-segment zone displays of a hob from a camera frame.

Pure Pillow, no Home Assistant imports, so it can be tested on saved frames.

The displays are tiny in a camera frame (a digit is about 7x12 pixels at
1080p) and the LEDs clip the sensor: segment cores come out white, only their
edges keep the LED colour (a magenta tint on a red display). So:

- a zone is lit when its window contains enough tinted pixels (white glare
  from cabinet lights has no tint, food and pot handles have no blue),
- segments are sampled on red+blue brightness, relative to the brightest
  segment, after undoing the italic slant of the digits,
- residual heat shows as 1-3 stacked horizontal bars (Miele) and is detected
  before the digit decoder.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageDraw

# Segment order: a (top), b (upper right), c (lower right), d (bottom),
# e (lower left), f (upper left), g (middle)
SEGMENTS: dict[tuple[int, ...], str] = {
    (1, 1, 1, 1, 1, 1, 0): "0",
    (0, 1, 1, 0, 0, 0, 0): "1",
    (1, 1, 0, 1, 1, 0, 1): "2",
    (1, 1, 1, 1, 0, 0, 1): "3",
    (0, 1, 1, 0, 0, 1, 1): "4",
    (1, 0, 1, 1, 0, 1, 1): "5",
    (1, 0, 1, 1, 1, 1, 1): "6",
    (1, 1, 1, 0, 0, 0, 0): "7",
    (1, 1, 1, 0, 0, 1, 0): "7",
    (1, 1, 1, 1, 1, 1, 1): "8",
    (1, 1, 1, 1, 0, 1, 1): "9",
    (0, 1, 1, 0, 1, 1, 1): "H",
    (1, 1, 0, 0, 1, 1, 1): "P",
}
ONE = (0, 1, 1, 0, 0, 0, 0)

# Where each segment sits in the (de-slanted) digit box: x0, x1, y0, y1 as
# fractions of the box
SEGMENT_REGIONS = (
    (0.25, 0.75, 0.00, 0.18),  # a
    (0.62, 1.00, 0.12, 0.42),  # b
    (0.62, 1.00, 0.58, 0.88),  # c
    (0.25, 0.75, 0.82, 1.00),  # d
    (0.00, 0.38, 0.58, 0.88),  # e
    (0.00, 0.38, 0.12, 0.42),  # f
    (0.25, 0.75, 0.41, 0.59),  # g
)

STATE_OFF = "off"
STATE_UNKNOWN = "unknown"
STATE_OBSTRUCTED = "obstructed"
STATE_RESIDUAL_HEAT = "residual_heat"
# Readings that carry no information about the zone; ignored when smoothing
NO_INFO = {STATE_UNKNOWN, STATE_OBSTRUCTED}


@dataclass(frozen=True, slots=True)
class Zone:
    """A zone display: its key plus the centre of its digit in the frame."""

    key: str
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class DecoderSettings:
    """Tuning knobs. The defaults fit a 1080p frame of a Miele panel."""

    half_w: int = 9
    half_h: int = 11
    min_lit: int = 4
    slant: float = 0.25
    threshold: float = 0.5
    min_score: float = 0.7
    min_margin: float = 0.04


@dataclass(frozen=True, slots=True)
class ZoneReading:
    """What was read from one zone display in one frame."""

    state: str
    segments: tuple[int, ...] | None = None
    lit_pixels: int = 0
    bright_pixels: int = 0
    heat_bars: int | None = None


def is_tinted(r: int, g: int, b: int) -> bool:
    """Edge of a lit segment: bright with a magenta tint.

    White glare has r ~= g ~= b; orange pot handles and food have low blue.
    """
    return r > 130 and b > 110 and r - g > 25 and b - g > 20


def is_bright(r: int, g: int, b: int) -> bool:
    """Any bright pixel (segment core, glare, a pot, a hand)."""
    return r + g + b > 450


def _residual_heat_bars(
    tinted: list[list[bool]], glow: list[list[bool]], w: int, h: int
) -> int | None:
    """Number of stacked horizontal bars, or None if this is not that pattern."""
    groups: list[tuple[int, int]] = []
    for y in range(h):
        if sum(tinted[y]) >= 2:
            if groups and groups[-1][1] >= y - 1:
                groups[-1] = (groups[-1][0], y)
            else:
                groups.append((y, y))
    if not 1 <= len(groups) <= 3 or any(b - a > 3 for a, b in groups):
        return None
    if any(groups[i + 1][0] - groups[i][1] < 2 for i in range(len(groups) - 1)):
        return None
    # The gaps between the bars must be completely dark. A digit like 3 also
    # has three bars, but joined by (thin, faint) vertical strokes.
    span = [
        x
        for x in range(w)
        if any(tinted[y][x] for a, b in groups for y in range(a, b + 1))
    ]
    for i in range(len(groups) - 1):
        for y in range(groups[i][1] + 1, groups[i + 1][0]):
            for x in range(max(0, min(span) - 1), min(w, max(span) + 2)):
                if tinted[y][x] or glow[y][x]:
                    return None
    return len(groups)


def read_zone(
    img: Image.Image, zone: Zone, settings: DecoderSettings | None = None
) -> ZoneReading:
    """Read a single zone display around its configured centre."""
    s = settings or DecoderSettings()
    crop = img.crop(
        (
            zone.x - s.half_w,
            zone.y - s.half_h,
            zone.x + s.half_w + 1,
            zone.y + s.half_h + 1,
        )
    )
    w, h = crop.size
    px = crop.load()
    tinted = [[False] * w for _ in range(h)]
    glow = [[False] * w for _ in range(h)]
    lit = bright = 0
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y][:3]
            if is_tinted(r, g, b):
                tinted[y][x] = True
                lit += 1
            elif is_bright(r, g, b):
                glow[y][x] = True
                bright += 1

    if lit < s.min_lit:
        # Dark display. If the window is mostly bright, something (a pot, a
        # hand, glare) is covering it and we can't tell.
        state = STATE_OBSTRUCTED if bright > w * h * 0.4 else STATE_OFF
        return ZoneReading(state, lit_pixels=lit, bright_pixels=bright)

    bars = _residual_heat_bars(tinted, glow, w, h)
    if bars is not None:
        return ZoneReading(
            STATE_RESIDUAL_HEAT, lit_pixels=lit, bright_pixels=bright, heat_bars=bars
        )

    ys = [y for y in range(h) if any(tinted[y])]
    y0, y1 = min(ys), max(ys)
    bh = y1 - y0 + 1

    # Column extent once the slant is undone (rows above the bottom of the
    # digit shifted left), ignoring columns with a single stray pixel
    col_hits: Counter[int] = Counter()
    raw_hits: Counter[int] = Counter()
    for y in range(h):
        for x in range(w):
            if tinted[y][x]:
                col_hits[round(x - (y1 - y) * s.slant)] += 1
                raw_hits[x] += 1
    cols = [c for c, n in col_hits.items() if n >= 2] or list(col_hits)
    raw_cols = [c for c, n in raw_hits.items() if n >= 2] or list(raw_hits)
    x0, x1 = min(cols), max(cols)
    bw = x1 - x0 + 1

    # A 1 is a single narrow stroke, sometimes drawn upright, so also check
    # the width without de-slanting
    if bh >= 6 and min(bw, max(raw_cols) - min(raw_cols) + 1) <= bh * 0.45:
        return ZoneReading(SEGMENTS[ONE], ONE, lit, bright)

    # Segment cores clip to white, the gaps between segments only get some
    # bloom and the glass stays dark: sample red+blue brightness.
    val = [[(px[x, y][0] + px[x, y][2]) / 2 for x in range(w)] for y in range(h)]

    def sample(x: float, y: int) -> float:
        xs = x + (y1 - y) * s.slant
        xi = int(xs)
        if xi < 0 or xi + 1 >= w:
            return 0.0
        fx = xs - xi
        return val[y][xi] * (1 - fx) + val[y][xi + 1] * fx

    means = []
    for fx0, fx1, fy0, fy1 in SEGMENT_REGIONS:
        total = n = 0.0
        for y in range(y0 + round(fy0 * (bh - 1)), y0 + round(fy1 * (bh - 1)) + 1):
            for i in range(5):
                total += sample(x0 + (fx0 + (fx1 - fx0) * i / 4) * (bw - 1), y)
                n += 1
        means.append(total / n if n else 0.0)

    hi, lo = max(means), min(means)
    if hi - lo < 25:
        # All segments equally bright: an 8, or nothing readable
        segs = tuple(1 if hi > 120 else 0 for _ in means)
        return ZoneReading(SEGMENTS.get(segs, STATE_UNKNOWN), segs, lit, bright)

    norm = [(m - lo) / (hi - lo) for m in means]
    segs = tuple(1 if n >= s.threshold else 0 for n in norm)
    if segs in SEGMENTS:
        return ZoneReading(SEGMENTS[segs], segs, lit, bright)

    # No exact match: pick the glyph that best explains the brightness of each
    # segment, if it clearly beats the runner-up
    scores: dict[str, float] = {}
    for pattern, glyph in SEGMENTS.items():
        score = sum(n if on else 1 - n for n, on in zip(norm, pattern, strict=True)) / 7
        scores[glyph] = max(scores.get(glyph, 0.0), score)
    (best, best_score), (_, second) = sorted(
        scores.items(), key=lambda kv: kv[1], reverse=True
    )[:2]
    if best_score >= s.min_score and best_score - second >= s.min_margin:
        return ZoneReading(best, segs, lit, bright)
    return ZoneReading(STATE_UNKNOWN, segs, lit, bright)


def load_frame(data: bytes, rotation: int = 0) -> Image.Image:
    """Decode a JPEG/PNG frame, rotated clockwise by `rotation` degrees."""
    img = Image.open(BytesIO(data)).convert("RGB")
    if rotation:
        img = img.rotate(-rotation, expand=True)
    return img


def read_frame(
    img: Image.Image, zones: Iterable[Zone], settings: DecoderSettings | None = None
) -> dict[str, ZoneReading]:
    """Read all zones from a frame."""
    return {zone.key: read_zone(img, zone, settings) for zone in zones}


def smooth(history: Sequence[ZoneReading]) -> ZoneReading:
    """Majority vote over the last few readings of a zone.

    The displays are multiplexed, so a single frame sometimes catches a digit
    dark; a pot or a hand hides it for a while. Readings without information
    don't vote, ties go to the most recent reading.
    """
    informative = [r for r in history if r.state not in NO_INFO]
    if not informative:
        return history[-1]
    counts = Counter(r.state for r in informative)
    top = max(counts.values())
    for reading in reversed(informative):
        if counts[reading.state] == top:
            return reading
    return informative[-1]  # unreachable


def annotate(
    img: Image.Image,
    zones: Sequence[Zone],
    readings: dict[str, ZoneReading],
    settings: DecoderSettings | None = None,
    margin: int = 40,
    scale: int = 3,
) -> bytes:
    """JPEG of the panel around the zones, with their windows and readings.

    Used to calibrate the zone positions.
    """
    s = settings or DecoderSettings()
    left = max(0, min(z.x for z in zones) - s.half_w - margin)
    top = max(0, min(z.y for z in zones) - s.half_h - margin)
    right = min(img.width, max(z.x for z in zones) + s.half_w + margin)
    bottom = min(img.height, max(z.y for z in zones) + s.half_h + margin)
    panel = img.crop((left, top, right, bottom))
    panel = panel.resize(
        (panel.width * scale, panel.height * scale), Image.Resampling.NEAREST
    )
    draw = ImageDraw.Draw(panel)
    for zone in zones:
        x0 = (zone.x - s.half_w - left) * scale
        y0 = (zone.y - s.half_h - top) * scale
        x1 = (zone.x + s.half_w + 1 - left) * scale
        y1 = (zone.y + s.half_h + 1 - top) * scale
        draw.rectangle((x0, y0, x1, y1), outline=(0, 200, 255), width=2)
        reading = readings.get(zone.key)
        label = reading.state if reading else "?"
        if reading and reading.heat_bars:
            label = f"heat {reading.heat_bars}"
        draw.text((x0, y1 + 3), f"{zone.key}: {label}", fill=(0, 200, 255))
    out = BytesIO()
    panel.save(out, format="JPEG", quality=85)
    return out.getvalue()
