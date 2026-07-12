"""Heart-rate zone calculation and helpers.

Zone model (4-zone, configurable % of max HR):

  - Z1 (Recovery):      below z1_max
  - Z2 (Aerobic):       z1_max .. z2_max
  - Z3 (Threshold):     z2_max .. z3_max
  - Z4 (VO2 Max):       at or above z3_max

Boundary semantics:

    pct < z1_max          → Z1
    z1_max <= pct < z2_max → Z2
    z2_max <= pct < z3_max → Z3
    pct >= z3_max         → Z4
"""

from __future__ import annotations

from typing import Any

# ── Zone constants ───────────────────────────────────────────────────────

ZONE_LABELS: dict[str, str] = {
    "Z1": "Recovery",
    "Z2": "Aerobic",
    "Z3": "Threshold",
    "Z4": "VO2 Max",
}

DEFAULT_COLORS: dict[str, str] = {
    "Z1": "#888888",
    "Z2": "#4CAF50",
    "Z3": "#FF9800",
    "Z4": "#F44336",
}

ZONE_ORDER = ["Z1", "Z2", "Z3", "Z4"]


# ── Public API ───────────────────────────────────────────────────────────

def get_zone(bpm: int, max_hr: int, zones: dict[str, float]) -> str:
    """Return the zone string (``Z1``–``Z4``) for *bpm*.

    ``zones`` should contain ``z1_max``, ``z2_max``, ``z3_max``
    keys (values between 0 and 1).

    If *bpm* or *max_hr* are non-positive, returns ``"Z1"``
    (no crash).
    """
    if max_hr <= 0 or bpm <= 0:
        return "Z1"

    pct = bpm / max_hr
    z1 = zones.get("z1_max", 0.60)
    z2 = zones.get("z2_max", 0.75)
    z3 = zones.get("z3_max", 0.88)

    if pct < z1:
        return "Z1"
    elif pct < z2:
        return "Z2"
    elif pct < z3:
        return "Z3"
    else:
        return "Z4"


def zone_color(zone: str, colors: dict[str, str] | None = None) -> str:
    """Return the hex color string for *zone*.

    Falls back to ``DEFAULT_COLORS``.
    """
    if colors is None:
        colors = DEFAULT_COLORS
    return colors.get(zone, DEFAULT_COLORS.get(zone, "#888888"))


def zone_label(zone: str) -> str:
    """Return a human-readable label for *zone*."""
    return ZONE_LABELS.get(zone, zone)


def validate_zones(zones: dict[str, float]) -> None:
    """Raise ``ValueError`` if zone boundaries are invalid.

    Checks: values are numbers, increasing, and in (0, 1).
    """
    try:
        z1 = float(zones.get("z1_max", 0.60))
        z2 = float(zones.get("z2_max", 0.75))
        z3 = float(zones.get("z3_max", 0.88))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("zone boundaries must be numbers")

    if not (0 < z1 < z2 < z3 < 1):
        raise ValueError(
            f"zone boundaries must satisfy 0 < z1_max < z2_max < z3_max < 1, "
            f"got z1_max={z1}, z2_max={z2}, z3_max={z3}"
        )
