"""HR graph rendering — AppKit (CoreGraphics) to PNG bytes.

Generates a rolling line graph of heart rate over the configured time
window, with colored zone bands. Rendering is offscreen (no windows), so
the chart needs no bundled charting library (matplotlib was removed in
favor of this module; the packaged app is far smaller as a result).

Usage:

    png_bytes = render_graph(ring_buffer, max_hr=190, ...)
    if png_bytes:
        # display as NSImage in the popover
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from datetime import datetime

from AppKit import (
    NSAffineTransform,
    NSBezierPath,
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSGraphicsContext,
    NSRoundLineCapStyle,
)
from Foundation import NSString

from hrm_live.ui.tokens import CANVAS, DIVIDER, TEXT_SECONDARY, ZONE_COLORS_DEFAULT
from hrm_live.zones import get_zone

log = logging.getLogger(__name__)

# ── Canvas geometry (matches the old 450x220 @ 1x figure) ────────────────

CHART_WIDTH = 450
CHART_HEIGHT = 220
MARGIN_LEFT = 46
MARGIN_RIGHT = 14
MARGIN_TOP = 14
MARGIN_BOTTOM = 28

# Default zone colors for graph bands
_ZONE_BAND_COLORS = dict(ZONE_COLORS_DEFAULT)
_DEFAULT_ZONES = {"z1_max": 0.60, "z2_max": 0.75, "z3_max": 0.88}
_LEGACY_ZONE_COLORS = {
    "Z1": "#888888",
    "Z2": "#4CAF50",
    "Z3": "#FF9800",
    "Z4": "#F44336",
}
_CHART_ZONE_COLORS_DEFAULT = {
    # These saturated chart accents follow the visual language of the
    # reference tracker while keeping the dashboard's semantic tokens intact.
    "Z1": "#2BC7B7",
    "Z2": "#F2D33B",
    "Z3": "#FF8A3D",
    "Z4": "#ED3C70",
}


def _windowed_readings(
    ring_buffer: Sequence[tuple[datetime, int]], window_minutes: int
) -> list[tuple[datetime, int]]:
    """Return readings in the selected rolling window, newest timestamp last."""
    if not ring_buffer:
        return []

    now = ring_buffer[-1][0]
    cutoff = now.timestamp() - window_minutes * 60
    return [(timestamp, bpm) for timestamp, bpm in ring_buffer if timestamp.timestamp() >= cutoff]


def summarize_heart_rate(
    ring_buffer: Sequence[tuple[datetime, int]], window_minutes: int = 10
) -> tuple[float, int, int] | None:
    """Return average, minimum, and maximum BPM for the selected window."""
    readings = _windowed_readings(ring_buffer, window_minutes)
    if not readings:
        return None

    bpms = [bpm for _, bpm in readings]
    return (sum(bpms) / len(bpms), min(bpms), max(bpms))


def _resolve_chart_colors(zone_colors: dict[str, str] | None) -> dict[str, str]:
    """Use vivid chart defaults while preserving explicit user colors."""
    if not zone_colors or zone_colors in (_ZONE_BAND_COLORS, _LEGACY_ZONE_COLORS):
        return dict(_CHART_ZONE_COLORS_DEFAULT)
    return {**_CHART_ZONE_COLORS_DEFAULT, **zone_colors}


def _chart_color_for_bpm(
    bpm: float,
    max_hr: int,
    zones: dict[str, float],
    zone_colors: dict[str, str],
) -> str:
    """Resolve the saturated line color for one BPM value."""
    zone = get_zone(int(round(bpm)), max_hr, zones)
    return zone_colors.get(zone, _CHART_ZONE_COLORS_DEFAULT["Z1"])


def _segment_colors(
    bpms: Sequence[int],
    max_hr: int,
    zones: dict[str, float],
    zone_colors: dict[str, str],
) -> list[str]:
    """Return one zone color per drawn line segment.

    A single point renders as a dot in its own zone color; every other
    segment takes the color of its midpoint so effort changes are visible
    immediately instead of hiding in one blue stroke.
    """
    if len(bpms) == 1:
        return [_chart_color_for_bpm(bpms[0], max_hr, zones, zone_colors)]
    return [
        _chart_color_for_bpm((bpms[index] + bpms[index + 1]) / 2, max_hr, zones, zone_colors)
        for index in range(len(bpms) - 1)
    ]


def _format_elapsed_tick(elapsed_seconds: float, span_seconds: float) -> str:
    """Format a relative chart tick without repeating wall-clock minutes."""
    elapsed = max(0, int(round(elapsed_seconds)))
    if span_seconds < 60:
        return f"{elapsed}s"
    minutes, seconds = divmod(elapsed, 60)
    return f"{minutes}:{seconds:02d}"


def _nice_step(raw: float) -> float:
    """Choose the smallest ``1/2/5 x 10^k`` step that covers *raw*."""
    if raw <= 0:
        return 1.0
    magnitude = 10 ** math.floor(math.log10(raw))
    for multiplier in (1, 2, 5, 10):
        step = multiplier * magnitude
        if step >= raw:
            return step
    return 10 * magnitude


def _elapsed_tick_offsets(span_seconds: float) -> list[float]:
    """Choose clean elapsed-time tick positions and always include the end."""
    if span_seconds <= 0:
        return [0.0]

    step = _nice_step(span_seconds / 4.0)
    offsets = [float(index * step) for index in range(int(span_seconds // step) + 1)]
    if not offsets:
        offsets = [0.0]
    if offsets[-1] < span_seconds:
        offsets.append(span_seconds)
    return offsets


def _nice_ticks(lower: float, upper: float, nbins: int) -> list[float]:
    """Return integer-friendly tick positions covering [lower, upper]."""
    if upper <= lower:
        return [lower]
    step = _nice_step((upper - lower) / nbins)
    ticks: list[float] = []
    value = math.ceil(lower / step) * step
    while value <= upper + 1e-9:
        ticks.append(value)
        value += step
    return ticks or [lower]


def _chart_y_limits(bpms: Sequence[int]) -> tuple[float, float]:
    """Return readable BPM bounds centered on the visible readings."""
    data_min = min(bpms)
    data_max = max(bpms)
    data_span = data_max - data_min
    padding = max(8.0, data_span * 0.2)
    lower = max(0.0, data_min - padding)
    upper = data_max + padding

    # A nearly flat trace still needs enough vertical breathing room to read
    # as a chart rather than a line pinned to one pixel row.
    if upper - lower < 20:
        midpoint = (data_min + data_max) / 2
        lower = max(0.0, midpoint - 10)
        upper = midpoint + 10

    # Keep the bounds on familiar five-BPM increments so the tick labels are
    # easy to scan in the narrow popover.
    lower = math.floor(lower / 5) * 5
    upper = math.ceil(upper / 5) * 5
    return lower, upper


# ── AppKit drawing helpers ───────────────────────────────────────────────


def _ns_color(hex_str: str, alpha: float = 1.0) -> NSColor:
    """Convert a ``#RRGGBB`` hex string to an NSColor (optionally alpha)."""
    try:
        h = hex_str.lstrip("#")
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
        return NSColor.colorWithRed_green_blue_alpha_(r, g, b, alpha)
    except Exception:
        return NSColor.labelColor()


def _tick_attributes() -> dict:
    return {
        NSFontAttributeName: NSFont.systemFontOfSize_(9),
        NSForegroundColorAttributeName: _ns_color(TEXT_SECONDARY),
    }


def _draw_text(
    text: str,
    point: tuple[float, float],
    attributes: dict,
    *,
    align: str = "left",
    valign: str = "center",
) -> None:
    """Draw a string so *point* anchors it horizontally/vertically."""
    ns = NSString.alloc().initWithString_(text)
    size = ns.sizeWithAttributes_(attributes)
    x, y = point
    if align == "center":
        x -= size.width / 2
    elif align == "right":
        x -= size.width
    if valign == "center":
        y -= size.height / 2
    ns.drawAtPoint_withAttributes_((x, y), attributes)


def _draw_chart(
    timestamps: Sequence[datetime],
    bpms: Sequence[int],
    max_hr: int,
    zones: dict[str, float],
    zone_colors: dict[str, str],
    width: int,
    height: int,
) -> None:
    """Draw the chart into the current graphics context."""
    left = MARGIN_LEFT
    right = width - MARGIN_RIGHT
    bottom = MARGIN_BOTTOM
    top = height - MARGIN_TOP
    plot_w = right - left
    plot_h = top - bottom

    t0 = timestamps[0].timestamp()
    t1 = timestamps[-1].timestamp()
    if t1 == t0:
        # Single data point — add 30s padding on each side.
        t0 -= 30.0
        t1 += 30.0
    span_seconds = max(0.0, t1 - t0)

    lower, upper = _chart_y_limits(bpms)

    def x_px(timestamp: datetime) -> float:
        return left + (timestamp.timestamp() - t0) / span_seconds * plot_w

    def y_px(value: float) -> float:
        return bottom + (value - lower) / (upper - lower) * plot_h

    z1_bpm = max_hr * zones["z1_max"]
    z2_bpm = max_hr * zones["z2_max"]
    z3_bpm = max_hr * zones["z3_max"]

    # ── Zone bands (fill between) ─────────────────────────────────────
    def band(zone: str, band_lower: float, band_upper: float) -> None:
        low = max(band_lower, lower)
        high = min(band_upper, upper)
        if high <= low:
            return
        _ns_color(zone_colors[zone], 0.14).setFill()
        NSBezierPath.fillRect_(((left, y_px(low)), (plot_w, y_px(high) - y_px(low))))

    band("Z1", 0.0, z1_bpm)
    band("Z2", z1_bpm, z2_bpm)
    band("Z3", z2_bpm, z3_bpm)
    band("Z4", z3_bpm, max_hr * 1.15)

    # ── Horizontal grid lines ─────────────────────────────────────────
    for tick in _nice_ticks(lower, upper, 5):
        y = y_px(tick)
        path = NSBezierPath.bezierPath()
        path.moveToPoint_((left, y))
        path.lineToPoint_((right, y))
        path.setLineWidth_(0.7)
        path.setLineDash_count_phase_([3.0, 3.0], 2, 0.0)
        _ns_color(DIVIDER, 0.65).setStroke()
        path.stroke()

    # ── Zone boundary lines (dashed) ──────────────────────────────────
    for bpm_val in (z1_bpm, z2_bpm, z3_bpm):
        if lower < bpm_val < upper:
            y = y_px(bpm_val)
            path = NSBezierPath.bezierPath()
            path.moveToPoint_((left, y))
            path.lineToPoint_((right, y))
            path.setLineWidth_(0.5)
            path.setLineDash_count_phase_([4.0, 3.0], 2, 0.0)
            _ns_color(DIVIDER, 0.5).setStroke()
            path.stroke()

    # ── HR trace (one segment per zone color) ─────────────────────────
    colors = _segment_colors(bpms, max_hr, zones, zone_colors)
    if len(bpms) == 1:
        cx = x_px(timestamps[0])
        cy = y_px(bpms[0])
        dot = NSBezierPath.bezierPathWithOvalInRect_(((cx - 3, cy - 3), (6, 6)))
        _ns_color(colors[0]).setFill()
        dot.fill()
    else:
        for index in range(len(bpms) - 1):
            path = NSBezierPath.bezierPath()
            path.moveToPoint_((x_px(timestamps[index]), y_px(bpms[index])))
            path.lineToPoint_((x_px(timestamps[index + 1]), y_px(bpms[index + 1])))
            path.setLineWidth_(2.6)
            path.setLineCapStyle_(NSRoundLineCapStyle)
            _ns_color(colors[index]).setStroke()
            path.stroke()

    # ── Axes spines (bottom + left) ───────────────────────────────────
    spine = NSBezierPath.bezierPath()
    spine.moveToPoint_((left, bottom))
    spine.lineToPoint_((right, bottom))
    spine.moveToPoint_((left, bottom))
    spine.lineToPoint_((left, top))
    spine.setLineWidth_(0.8)
    _ns_color(DIVIDER).setStroke()
    spine.stroke()

    # ── X tick labels (relative elapsed time) ─────────────────────────
    tick_attributes = _tick_attributes()
    for offset in _elapsed_tick_offsets(span_seconds):
        x = left + (offset / span_seconds) * plot_w
        _draw_text(
            _format_elapsed_tick(offset, span_seconds),
            (x, bottom - 12),
            tick_attributes,
            align="center",
        )

    # ── Y tick labels ─────────────────────────────────────────────────
    for tick in _nice_ticks(lower, upper, 5):
        _draw_text(
            f"{tick:.0f}",
            (left - 6, y_px(tick)),
            tick_attributes,
            align="right",
        )

    # ── Y axis title (rotated) ────────────────────────────────────────
    transform = NSAffineTransform.transform()
    transform.translateXBy_yBy_(12, bottom + plot_h / 2)
    transform.rotateByDegrees_(-90)
    transform.concat()
    _draw_text("BPM", (0, 0), tick_attributes, align="center", valign="center")


def render_graph(
    ring_buffer: Sequence,
    max_hr: int = 190,
    window_minutes: int = 10,
    zones: dict[str, float] | None = None,
    zone_colors: dict[str, str] | None = None,
) -> bytes | None:
    """Render HR graph to PNG bytes.

    Parameters
    ----------
    ring_buffer:
        Deque of ``(timestamp, bpm)`` tuples, newest last.
    max_hr:
        Maximum heart rate for zone boundary calculation.
    window_minutes:
        Time window to display (configurable).
    zones:
        Dict with ``z1_max``, ``z2_max``, ``z3_max`` keys (fractions of max_hr).
    zone_colors:
        Dict mapping zone names to hex colors for the bands.

    Returns
    -------
    PNG bytes, or ``None`` if there is no data to render.
    """
    if not ring_buffer or len(ring_buffer) < 1:
        return None

    # Accept partial dictionaries as well as None. UI state can be observed
    # while configuration is being replaced, so rendering must not assume all
    # nested keys are present.
    zones = {**_DEFAULT_ZONES, **(zones or {})}
    zone_colors = _resolve_chart_colors(zone_colors)

    filtered = _windowed_readings(ring_buffer, window_minutes)
    if not filtered:
        return None

    timestamps = [t for t, _ in filtered]
    bpms = [b for _, b in filtered]

    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None,
        CHART_WIDTH,
        CHART_HEIGHT,
        8,
        4,
        True,
        False,
        "NSCalibratedRGBColorSpace",
        0,
        0,
    )
    if rep is None:
        log.error("Failed to create offscreen bitmap for HR graph")
        return None

    context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    if context is None:
        log.error("Failed to create graphics context for HR graph")
        return None

    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(context)
    try:
        try:
            _ns_color(CANVAS).setFill()
            NSBezierPath.fillRect_(((0, 0), (CHART_WIDTH, CHART_HEIGHT)))
            _draw_chart(timestamps, bpms, max_hr, zones, zone_colors, CHART_WIDTH, CHART_HEIGHT)
            context.flushGraphics()
        except Exception:
            log.exception("Failed to draw heart-rate graph")
            return None
    finally:
        NSGraphicsContext.restoreGraphicsState()

    data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
    if data is None:
        log.error("Failed to encode HR graph as PNG")
        return None
    return bytes(data)
