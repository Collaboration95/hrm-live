"""HR graph rendering — matplotlib (Agg backend) to PNG bytes.

Generates a rolling line graph of heart rate over the configured time
window, with colored zone bands.

Usage:

    png_bytes = render_graph(ring_buffer, max_hr=190, ...)
    if png_bytes:
        # display as NSImage in the popover
"""

from __future__ import annotations

import io
import logging
import math
import os
import tempfile
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

_MPLCONFIGDIR = Path(tempfile.gettempdir()) / "hrm-live-matplotlib"
_MPLCONFIGDIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPLCONFIGDIR))

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter, MaxNLocator

from hrm_live.ui.tokens import (
    CANVAS,
    DIVIDER,
    TEXT_SECONDARY,
    ZONE_COLORS_DEFAULT,
)
from hrm_live.zones import get_zone

log = logging.getLogger(__name__)

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


def _format_elapsed_tick(elapsed_seconds: float, span_seconds: float) -> str:
    """Format a relative chart tick without repeating wall-clock minutes."""
    elapsed = max(0, int(round(elapsed_seconds)))
    if span_seconds < 60:
        return f"{elapsed}s"
    minutes, seconds = divmod(elapsed, 60)
    return f"{minutes}:{seconds:02d}"


def _elapsed_tick_offsets(span_seconds: float) -> list[float]:
    """Choose clean elapsed-time tick positions and always include the end."""
    if span_seconds <= 0:
        return [0.0]

    locator = MaxNLocator(nbins=4, integer=True, steps=[1, 2, 5, 10])
    offsets = [
        float(value) for value in locator.tick_values(0, span_seconds) if 0 <= value <= span_seconds
    ]
    if not offsets:
        offsets = [0.0]
    if offsets[-1] < span_seconds:
        offsets.append(span_seconds)
    return offsets


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

    # Filter data within the window.  The same helper powers the summary text
    # so the numbers and plotted points always describe the same readings.
    filtered = _windowed_readings(ring_buffer, window_minutes)

    if not filtered:
        return None

    timestamps = [t for t, _ in filtered]
    bpms = [b for _, b in filtered]

    # Build zone boundaries (BPM values)
    z1_bpm = max_hr * zones["z1_max"]
    z2_bpm = max_hr * zones["z2_max"]
    z3_bpm = max_hr * zones["z3_max"]

    # ── Plot ─────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(4.5, 2.2), dpi=100)
    fig.patch.set_facecolor(CANVAS)
    ax.set_facecolor(CANVAS)

    # Zone bands (fill between)
    ax.axhspan(0, z1_bpm, facecolor=zone_colors["Z1"], alpha=0.14, zorder=0)
    ax.axhspan(
        z1_bpm,
        z2_bpm,
        facecolor=zone_colors["Z2"],
        alpha=0.14,
        zorder=0,
    )
    ax.axhspan(
        z2_bpm,
        z3_bpm,
        facecolor=zone_colors["Z3"],
        alpha=0.14,
        zorder=0,
    )
    ax.axhspan(
        z3_bpm,
        max_hr * 1.15,
        facecolor=zone_colors["Z4"],
        alpha=0.14,
        zorder=0,
    )

    # Zone boundary lines (dashed)
    for bpm_val in (z1_bpm, z2_bpm, z3_bpm):
        color = DIVIDER
        ax.axhline(bpm_val, color=color, linewidth=0.5, linestyle="--", alpha=0.5)

    # HR line: each segment follows the zone of its midpoint, making effort
    # changes visible immediately instead of hiding them in one blue stroke.
    if len(timestamps) == 1:
        ax.plot(
            timestamps,
            bpms,
            color=_chart_color_for_bpm(bpms[0], max_hr, zones, zone_colors),
            marker="o",
            markersize=5,
            linewidth=0,
            zorder=4,
        )
    else:
        for index in range(len(timestamps) - 1):
            midpoint = (bpms[index] + bpms[index + 1]) / 2
            ax.plot(
                timestamps[index : index + 2],
                bpms[index : index + 2],
                color=_chart_color_for_bpm(midpoint, max_hr, zones, zone_colors),
                linewidth=2.6,
                solid_capstyle="round",
                zorder=4,
            )

    # Style.  Use elapsed time from the first visible reading instead of a
    # wall-clock formatter: second-level samples otherwise render as the same
    # repeated ``15:43`` label throughout a short window.
    if timestamps[0] != timestamps[-1]:
        axis_start = timestamps[0]
        axis_end = timestamps[-1]
    else:
        # Single data point — add 30s padding on each side.
        pad = timedelta(seconds=30)
        axis_start = timestamps[0] - pad
        axis_end = timestamps[-1] + pad
    ax.set_xlim(axis_start, axis_end)

    axis_start_num = mdates.date2num(axis_start)
    axis_end_num = mdates.date2num(axis_end)
    span_seconds = max(0.0, (axis_end_num - axis_start_num) * 86400)
    tick_offsets = _elapsed_tick_offsets(span_seconds)
    tick_values = [axis_start_num + offset / 86400 for offset in tick_offsets]
    ax.xaxis.set_major_locator(FixedLocator(tick_values))
    ax.xaxis.set_major_formatter(
        FuncFormatter(
            lambda value, _: _format_elapsed_tick(
                (value - axis_start_num) * 86400,
                span_seconds,
            )
        )
    )

    lower, upper = _chart_y_limits(bpms)
    ax.set_ylim(lower, upper)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
    ax.tick_params(colors=TEXT_SECONDARY, labelsize=9, length=0, pad=4)
    ax.grid(axis="y", color=DIVIDER, linewidth=0.7, alpha=0.65)
    ax.set_axisbelow(True)
    for side, spine in ax.spines.items():
        spine.set_color(DIVIDER)
        spine.set_linewidth(0.8)
        if side in {"top", "right"}:
            spine.set_visible(False)
    ax.set_ylabel("BPM", color=TEXT_SECONDARY, fontsize=9, labelpad=6)

    # Tight layout
    fig.tight_layout(pad=0.5)

    # Render to PNG bytes
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()
