"""Semantic design tokens for the HRM Live instrument interface.

Provides a single source of truth for colour palettes, typography scale,
spacing grid, and semantic state colours used by the dashboard, menu bar,
and settings panels.

All colour values are defined as hex strings (``#RRGGBB``) for use with
``_ns_color()`` helpers.  AppKit semantic colours (``labelColor``,
``secondaryLabelColor``, ``separatorColor``, etc.) are preferred for
native controls; these tokens apply to custom-drawn dashboard surfaces.
"""

from __future__ import annotations

# ── Dashboard surface palette (vibrant light instrument UI) ──────────────

# These values mirror the attached macOS profiler references: a clean white
# canvas, quiet neutral cards, and saturated system accents that remain clear
# at the narrow menu-bar popover size.
CANVAS = "#FFFFFF"  # Root popover background
SURFACE = "#F5F5F7"  # Card / section backgrounds
SURFACE_ALT = "#E5E5EA"  # Secondary surfaces (graph bg, hover, tracks)
DIVIDER = "#D1D1D6"  # Light separators on light surfaces

# ── Text colours ─────────────────────────────────────────────────────────

TEXT_PRIMARY = "#1D1D1F"  # Hero BPM, primary labels
TEXT_SECONDARY = "#6E6E73"  # Captions, secondary stats
TEXT_TERTIARY = "#8E8E93"  # Placeholder, disabled
TEXT_ACCENT = "#0A84FF"  # Graph line, interactive accent

# ── Semantic state colours ───────────────────────────────────────────────

STATUS_CONNECTED = "#34C759"  # Green — connected dot
STATUS_RECONNECTING = "#FF9F0A"  # Orange — reconnecting dot
STATUS_DISCONNECTED = "#8E8E93"  # Grey — disconnected dot
STATUS_ERROR = "#FF3B30"  # Red — error dot

# ── Typography scale (point sizes) ───────────────────────────────────────

CAPTION = 12  # Small captions, timestamps
LABEL = 14  # Section labels, zone names
SECTION_VALUE = 18  # Statistics values (avg, max, elapsed)
HERO_BPM = 48  # Live heart-rate reading (large)
HERO_BPM_COMPACT = 42  # Fallback if 48 pt doesn't fit

# ── Spatial grid (8 pt base) ─────────────────────────────────────────────

OUTER_PADDING = 16  # Popover outer edge padding
CARD_PADDING = 12  # Inside-card padding
INLINE_GAP = 8  # Gap between sibling controls
SECTION_GAP = 16  # Gap between card sections
SECTION_GAP_LARGE = 24  # Larger section gaps

# ── Component sizing ─────────────────────────────────────────────────────

GAUGE_SIZE = 110  # Donut gauge diameter
GAUGE_LINE_WIDTH = 14  # Donut stroke width
GRAPH_HEIGHT = 170  # Trend card graph height
BUTTON_HEIGHT = 36  # Primary/secondary button height
BUTTON_HEIGHT_SMALL = 30  # Utility button height
HIT_TARGET_MIN = 36  # Minimum interactive hit area

# ── Zone accent colours (defaults, overridden by user config) ────────────

ZONE_COLORS_DEFAULT: dict[str, str] = {
    "Z1": "#8E8E93",
    "Z2": "#34C759",
    "Z3": "#FF9F0A",
    "Z4": "#FF375F",
}

# ── Contrast ratio targets ───────────────────────────────────────────────

CONTRAST_NORMAL_TEXT = 4.5  # 4.5:1 minimum for normal-sized text
CONTRAST_LARGE_TEXT = 3.0  # 3:1 minimum for text >= 18pt or bold >= 14pt


# ── State-driven colour resolution ───────────────────────────────────────


def status_dot_colour(connection_status: str) -> str:
    """Return the hex dot colour for a given connection state."""
    return {
        "connected": STATUS_CONNECTED,
        "connecting": STATUS_RECONNECTING,
        "reconnecting": STATUS_RECONNECTING,
        "disconnected": STATUS_DISCONNECTED,
        "error": STATUS_ERROR,
    }.get(connection_status, STATUS_DISCONNECTED)


def zone_accent(zone: str, colors_cfg: dict[str, str] | None = None) -> str:
    """Return zone accent colour from config, falling back to defaults."""
    if colors_cfg and zone in colors_cfg:
        return colors_cfg[zone]
    return ZONE_COLORS_DEFAULT.get(zone, STATUS_DISCONNECTED)


def menu_title(bpm: int | None, connection_status: str) -> str:
    """Build a plain-text menu bar title without colour embedding."""
    if bpm is not None and connection_status == "connected":
        return f"♥ {bpm} bpm"
    return "♡ ---"


def menu_accessibility_label(
    bpm: int | None,
    zone: str,
    zone_name: str,
    connection_status: str,
) -> str:
    """Build a VoiceOver-accessible label for the menu bar status item."""
    if bpm is not None and connection_status == "connected":
        return f"{bpm} beats per minute, {zone}, {zone_name}, connected"
    return f"Heart rate monitor {connection_status}"
