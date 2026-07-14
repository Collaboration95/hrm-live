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
import os
import tempfile
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_MPLCONFIGDIR = Path(tempfile.gettempdir()) / "hrm-live-matplotlib"
_MPLCONFIGDIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPLCONFIGDIR))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import FancyBboxPatch

from zones import ZONE_ORDER

log = logging.getLogger(__name__)

# Default zone colors for graph bands
_ZONE_BAND_COLORS = {
    "Z1": "#e0e0e0",
    "Z2": "#a5d6a7",
    "Z3": "#ffcc80",
    "Z4": "#ef9a9a",
}
_DEFAULT_ZONES = {"z1_max": 0.60, "z2_max": 0.75, "z3_max": 0.88}


def render_graph(
    ring_buffer: deque,
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
    zone_colors = {**_ZONE_BAND_COLORS, **(zone_colors or {})}

    now = ring_buffer[-1][0]

    # Filter data within the window
    cutoff = now.timestamp() - window_minutes * 60
    filtered = [(ts, bpm) for ts, bpm in ring_buffer if ts.timestamp() >= cutoff]

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
    fig.patch.set_facecolor("#1e1e1e")
    ax.set_facecolor("#1e1e1e")

    # Zone bands (fill between)
    ax.axhspan(0, z1_bpm, facecolor=zone_colors.get("Z1", _ZONE_BAND_COLORS["Z1"]),
               alpha=0.25, zorder=0)
    ax.axhspan(z1_bpm, z2_bpm, facecolor=zone_colors.get("Z2", _ZONE_BAND_COLORS["Z2"]),
               alpha=0.25, zorder=0)
    ax.axhspan(z2_bpm, z3_bpm, facecolor=zone_colors.get("Z3", _ZONE_BAND_COLORS["Z3"]),
               alpha=0.25, zorder=0)
    ax.axhspan(z3_bpm, max_hr * 1.15, facecolor=zone_colors.get("Z4", _ZONE_BAND_COLORS["Z4"]),
               alpha=0.25, zorder=0)

    # Zone boundary lines (dashed)
    for bpm_val, color in [(z1_bpm, "#888888"), (z2_bpm, "#888888"), (z3_bpm, "#888888")]:
        ax.axhline(bpm_val, color=color, linewidth=0.5, linestyle="--", alpha=0.5)

    # HR line
    ax.plot(timestamps, bpms, color="#4fc3f7", linewidth=1.5, zorder=3)

    # Style
    if timestamps[0] != timestamps[-1]:
        ax.set_xlim(timestamps[0], timestamps[-1])
    else:
        # Single data point — add 30s padding on each side
        pad = timedelta(seconds=30)
        ax.set_xlim(timestamps[0] - pad, timestamps[-1] + pad)
    ax.set_ylim(0, max_hr * 1.15)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.tick_params(colors="#aaaaaa", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#444444")
    ax.set_ylabel("BPM", color="#aaaaaa", fontsize=8)

    # Tight layout
    fig.tight_layout(pad=0.5)

    # Render to PNG bytes
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()
