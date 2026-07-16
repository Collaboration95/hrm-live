"""Popover dashboard — gauge, graph, session stats, and controls.

Built using AppKit (PyObjC) views inside an NSPopover.
Reads from ``AppState`` and delegates session actions to ``session.py``.

Design (from FEATURE_ROADMAP):
  - Header: connection dot, device name/status, gear button
  - Hero card: large BPM, zone dial (no centre number), zone name/label
  - Trend card: range selector, 16:9 graph, legend
  - Session card: elapsed, avg, max, zone-time bars
  - Action area: primary Start/Stop, secondary Save, Quit in utility area

Uses persistent view objects and updates values rather than rebuilding
the entire view hierarchy every timer tick.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

import objc
from AppKit import (
    NSAttributedString,
    NSBezelStyleRounded,
    NSBezierPath,
    NSButton,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSGraphicsContext,
    NSImage,
    NSImageView,
    NSModalResponseOK,
    NSPopover,
    NSPopoverBehaviorTransient,
    NSSavePanel,
    NSSegmentedControl,
    NSSegmentSwitchTrackingSelectOne,
    NSTextField,
    NSView,
    NSViewController,
    NSWorkspace,
)
from Foundation import NSURL, NSString

import hrm_live.config as cfg_mod
import hrm_live.session as sess_mod
from hrm_live.state import AppState, ExportSnapshot, UISnapshot
from hrm_live.ui.graph import render_graph
from hrm_live.ui.tokens import (
    CANVAS,
    CARD_PADDING,
    DIVIDER,
    GAUGE_LINE_WIDTH,
    GAUGE_SIZE,
    GRAPH_HEIGHT,
    HERO_BPM,
    INLINE_GAP,
    LABEL,
    OUTER_PADDING,
    SECTION_GAP,
    SECTION_GAP_LARGE,
    SECTION_VALUE,
    STATUS_CONNECTED,
    STATUS_DISCONNECTED,
    STATUS_ERROR,
    STATUS_RECONNECTING,
    SURFACE,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    TEXT_TERTIARY,
    zone_accent,
)
from hrm_live.zones import ZONE_ORDER, get_zone, zone_label

log = logging.getLogger(__name__)

POPOVER_WIDTH = 344
GAUGE_LABEL_FONT_SIZE = 12
HERO_FONT_SIZE = 48
RECENT_SESSION_ROWS = 4


class HRMPopover:
    """Popover controller — manages the NSPopover lifecycle with persistent views."""

    def __init__(
        self,
        state: AppState,
        *,
        save_panel_factory: Any | None = None,
        on_quit: Any | None = None,
    ) -> None:
        self.state = state
        self._popover: NSPopover | None = None
        self._latest_graph_bytes: bytes | None = None
        self._latest_graph_key: tuple[Any, ...] | None = None
        self._save_panel_factory = save_panel_factory or macos_save_panel
        self._on_quit = on_quit
        self.on_settings: Any = None  # callback for settings button

        # Persistent view references for value updates (no full rebuild)
        self._root_view: NSView | None = None
        self._controls: dict[str, Any] = {}
        self._hero_label: NSTextField | None = None
        self._zone_label: NSTextField | None = None
        self._gauge_view: DonutGaugeView | None = None
        self._graph_image_view: NSImageView | None = None
        self._graph_placeholder: NSTextField | None = None
        self._trend_selector: NSSegmentedControl | None = None
        self._session_stats_label: NSTextField | None = None
        self._zone_bar_container: NSView | None = None
        self._session_button: NSButton | None = None
        self._save_button: NSButton | None = None
        self._json_save_button: NSButton | None = None
        self._export_feedback: NSTextField | None = None
        self._export_controls_container: NSView | None = None
        self._recent_sessions_container: NSView | None = None
        self._header_device_label: NSTextField | None = None
        self._header_dot_view: NSView | None = None
        self._action_area_y: float = 0
        self._built = False

    @property
    def is_shown(self) -> bool:
        return self._popover is not None and self._popover.isShown()

    def toggle(self, sender: Any) -> None:
        """Toggle the popover from a menu bar click."""
        if self.is_shown:
            if self._popover:
                self._popover.performClose_(sender)
        else:
            self._show(sender)

    def _show(self, sender: Any) -> None:
        """Create and show the popover with persistent view hierarchy."""
        if self._popover is None:
            self._popover = NSPopover.alloc().init()
            self._popover.setBehavior_(NSPopoverBehaviorTransient)

        if not self._built:
            vc = NSViewController.alloc().init()
            self._root_view = self._build_view()
            vc.setView_(self._root_view)
            self._popover.setContentViewController_(vc)
            self._popover.setContentSize_((POPOVER_WIDTH, self._calculate_height()))
            self._built = True

        self.refresh()
        self._popover.showRelativeToRect_ofView_preferredEdge_(
            sender.bounds(),
            sender,
            0,  # NSRectEdgeMinY
        )

    def refresh(self) -> None:
        """Update persistent view values without rebuilding the hierarchy."""
        if not self._popover or not self._popover.isShown():
            return
        if not self._built or self._root_view is None:
            return

        s = self.state.snapshot_for_ui()
        cfg = s.config or {}
        colors_cfg = cfg.get("zone_colors", {})
        max_hr = cfg.get("max_hr", 190)
        zones_cfg = cfg.get("zones", {})
        zone_bounds = {
            "z1_max": zones_cfg.get("z1_max", 0.60),
            "z2_max": zones_cfg.get("z2_max", 0.75),
            "z3_max": zones_cfg.get("z3_max", 0.88),
        }
        bpm = s.latest_bpm if s.connected and s.latest_bpm is not None else None
        current_zone = get_zone(bpm, max_hr, zone_bounds) if bpm is not None else "Z1"

        # ── Header: connection dot + device name ────────────────────
        self._update_header(s, current_zone, colors_cfg)

        # ── Hero BPM ────────────────────────────────────────────────
        if self._hero_label:
            bpm_str = f"{bpm}" if bpm is not None else "---"
            col = _ns_color(
                zone_accent(current_zone, colors_cfg) if bpm is not None else TEXT_TERTIARY
            )
            self._hero_label.setStringValue_(bpm_str)
            self._hero_label.setTextColor_(col)

        # ── Zone label ──────────────────────────────────────────────
        if self._zone_label:
            if bpm is not None:
                zl = zone_label(current_zone)
                self._zone_label.setStringValue_(f"{current_zone} — {zl}")
            else:
                self._zone_label.setStringValue_("No signal")

        # ── Gauge ───────────────────────────────────────────────────
        if self._gauge_view:
            self._gauge_view.setBpm_zone_zoneBounds_maxHr_colorsCfg_(
                bpm, current_zone, zone_bounds, max_hr, colors_cfg
            )

        # ── Trend card: graph ───────────────────────────────────────
        self._update_graph(s, max_hr, zones_cfg, colors_cfg)
        if self._trend_selector:
            self._trend_selector.setSelectedSegment_(self._trend_segment_for_minutes(s.config))

        # ── Session card ────────────────────────────────────────────
        self._update_session(s, colors_cfg)

        # ── Action area ─────────────────────────────────────────────
        self._update_actions(s)

        # ── Recent sessions ────────────────────────────────────────
        self._update_recent_sessions(s)

    def _calculate_height(self) -> float:
        """Estimate the total popover height based on content sections."""
        # Header: ~24pt
        h = OUTER_PADDING + 24 + INLINE_GAP
        # Hero card: gauge (110) + label space
        h += HERO_BPM + 8 + GAUGE_SIZE + SECTION_GAP
        # Trend card: graph + selector
        h += GRAPH_HEIGHT + 30 + SECTION_GAP
        # Session card: stats + zone bars
        h += 60 + 100 + SECTION_GAP
        # Action area + recent sessions archive
        h += 80 + 128 + SECTION_GAP
        return max(h, 520)

    def _build_view(self) -> NSView:
        """Build the persistent view hierarchy (called once)."""
        s = self.state.snapshot_for_ui()
        cfg = s.config or {}
        colors_cfg = cfg.get("zone_colors", {})
        max_hr = cfg.get("max_hr", 190)
        zones_cfg = cfg.get("zones", {})
        zone_bounds = {
            "z1_max": zones_cfg.get("z1_max", 0.60),
            "z2_max": zones_cfg.get("z2_max", 0.75),
            "z3_max": zones_cfg.get("z3_max", 0.88),
        }
        bpm = s.latest_bpm if s.connected and s.latest_bpm is not None else None
        current_zone = get_zone(bpm, max_hr, zone_bounds) if bpm is not None else "Z1"

        height = self._calculate_height()
        root = ColoredRectView.alloc().initWithFrame_(((0, 0), (POPOVER_WIDTH, height)))
        root.setColor_(_ns_color(CANVAS))
        self._root_view = root

        y = height - OUTER_PADDING

        # ═══════════════════════════════════════════════════════════════
        # HEADER
        # ═══════════════════════════════════════════════════════════════
        y = self._build_header(root, y, s, current_zone, colors_cfg)
        y -= SECTION_GAP

        # ═══════════════════════════════════════════════════════════════
        # HERO CARD
        # ═══════════════════════════════════════════════════════════════
        y = self._build_hero_card(root, y, s, current_zone, colors_cfg, zone_bounds, max_hr)
        y -= SECTION_GAP_LARGE

        # ═══════════════════════════════════════════════════════════════
        # TREND CARD
        # ═══════════════════════════════════════════════════════════════
        y = self._build_trend_card(root, y, s, max_hr, zones_cfg, colors_cfg)
        y -= SECTION_GAP_LARGE

        # ═══════════════════════════════════════════════════════════════
        # SESSION CARD
        # ═══════════════════════════════════════════════════════════════
        y = self._build_session_card(root, y, s, colors_cfg)
        y -= SECTION_GAP

        # ═══════════════════════════════════════════════════════════════
        # ACTION AREA
        # ═══════════════════════════════════════════════════════════════
        y = self._build_action_area(root, y, s)
        y -= SECTION_GAP

        # ═══════════════════════════════════════════════════════════════
        # RECENT SESSIONS
        # ═══════════════════════════════════════════════════════════════
        y = self._build_recent_sessions_card(root, y, s)
        _ = y  # bottom padding handled by height

        return root

    # ── Header ──────────────────────────────────────────────────────────

    def _build_header(
        self,
        root: NSView,
        y: float,
        s: UISnapshot,
        zone: str,
        colors_cfg: dict,
    ) -> float:
        """Build the header row: status dot, device label, gear button."""
        x = OUTER_PADDING

        # Status dot (small coloured circle view)
        dot_size = 10
        dot_frame = ((x, y - dot_size), (dot_size, dot_size))
        dot = ColoredRectView.alloc().initWithFrame_(dot_frame)
        dot.setCornerRadius_(dot_size / 2)
        dot.setColor_(_ns_color(self._dot_colour(s.connection_status)))
        root.addSubview_(dot)
        self._header_dot_view = dot

        # Device name / status text
        device_text = self._device_status_text(s)
        dev_label = _make_label(
            device_text,
            NSFont.systemFontOfSize_(LABEL),
            _ns_color(TEXT_SECONDARY),
            (x + dot_size + INLINE_GAP, y - 18, 240, 18),
        )
        root.addSubview_(dev_label)
        self._header_device_label = dev_label

        # Gear / settings button
        gear_btn = NSButton.alloc().initWithFrame_(
            ((POPOVER_WIDTH - OUTER_PADDING - 32, y - 28), (28, 28))
        )
        gear_btn.setBezelStyle_(NSBezelStyleRounded)
        gear_btn.setTitle_("⚙")
        gear_btn.setTarget_(self)
        gear_btn.setAction_("open_settings:")
        _set_dark_button_title(gear_btn, "Settings")
        root.addSubview_(gear_btn)

        return y - 36

    def _update_header(self, s: UISnapshot, zone: str, colors_cfg: dict) -> None:
        if self._header_dot_view:
            self._header_dot_view.setColor_(_ns_color(self._dot_colour(s.connection_status)))
            self._header_dot_view.setNeedsDisplay_(True)
        if self._header_device_label:
            self._header_device_label.setStringValue_(self._device_status_text(s))

    def _dot_colour(self, status: str) -> str:
        return {
            "connected": STATUS_CONNECTED,
            "connecting": STATUS_RECONNECTING,
            "reconnecting": STATUS_RECONNECTING,
            "disconnected": STATUS_DISCONNECTED,
            "error": STATUS_ERROR,
        }.get(status, STATUS_DISCONNECTED)

    def _device_status_text(self, s: UISnapshot) -> str:
        cfg = s.config or {}
        name = cfg.get("device_name", "") or cfg.get("device_address", "") or "No device"
        if s.connection_status == "connected":
            return f"Connected — {name}" if name != "No device" else "Connected"
        elif s.connection_status in {"connecting", "reconnecting"}:
            return f"{s.connection_status.title()}..."
        elif s.connection_status == "error":
            return s.connection_error or "Connection error"
        return f"Disconnected — {name}" if name != "No device" else "Disconnected"

    # ── Hero Card ───────────────────────────────────────────────────────

    def _build_hero_card(
        self,
        root: NSView,
        y: float,
        s: UISnapshot,
        zone: str,
        colors_cfg: dict,
        zone_bounds: dict,
        max_hr: int,
    ) -> float:
        """Build the hero card: large BPM + gaug + zone label."""
        x = OUTER_PADDING
        card_w = POPOVER_WIDTH - 2 * OUTER_PADDING
        card_h = HERO_BPM + 8 + GAUGE_SIZE + CARD_PADDING * 2

        # Card background
        card = ColoredRectView.alloc().initWithFrame_(((x, y - card_h), (card_w, card_h)))
        card.setColor_(_ns_color(SURFACE))
        card.setCornerRadius_(8)
        root.addSubview_(card)

        cy = y - CARD_PADDING

        # Hero BPM
        bpm_val = s.latest_bpm if s.connected and s.latest_bpm is not None else None
        bpm_str = f"{bpm_val}" if bpm_val is not None else "---"
        accent = zone_accent(zone, colors_cfg) if bpm_val is not None else TEXT_TERTIARY
        hero = _make_label(
            bpm_str,
            NSFont.monospacedDigitSystemFontOfSize_weight_(HERO_BPM, 0),
            _ns_color(accent),
            (x + CARD_PADDING, cy - HERO_BPM, 180, HERO_BPM),
        )
        root.addSubview_(hero)
        self._hero_label = hero

        # BPM unit label next to hero
        unit = _make_label(
            "BPM",
            NSFont.systemFontOfSize_(LABEL),
            _ns_color(TEXT_TERTIARY),
            (x + CARD_PADDING + 140, cy - HERO_BPM + 8, 50, 20),
        )
        root.addSubview_(unit)

        # Zone name
        if bpm_val is not None:
            zl = zone_label(zone)
            zone_str = f"{zone} — {zl}"
        else:
            zone_str = "Waiting for signal..."
        zlbl = _make_label(
            zone_str,
            NSFont.systemFontOfSize_(LABEL),
            _ns_color(accent if bpm_val is not None else TEXT_TERTIARY),
            (x + CARD_PADDING, cy - HERO_BPM - 20, 200, 20),
        )
        root.addSubview_(zlbl)
        self._zone_label = zlbl

        # Donut gauge (right side, no centre number)
        gauge_x = POPOVER_WIDTH - OUTER_PADDING - CARD_PADDING - GAUGE_SIZE
        gauge_y = cy - GAUGE_SIZE - CARD_PADDING
        gauge_frame = ((gauge_x, gauge_y), (GAUGE_SIZE, GAUGE_SIZE))
        gauge_view = DonutGaugeView.alloc().initWithFrame_(gauge_frame)
        gauge_view.setBpm_zone_zoneBounds_maxHr_colorsCfg_(
            bpm_val, zone, zone_bounds, max_hr, colors_cfg
        )
        root.addSubview_(gauge_view)
        self._gauge_view = gauge_view

        return y - card_h - INLINE_GAP

    # ── Trend Card ──────────────────────────────────────────────────────

    def _build_trend_card(
        self,
        root: NSView,
        y: float,
        s: UISnapshot,
        max_hr: int,
        zones_cfg: dict,
        colors_cfg: dict,
    ) -> float:
        """Build the trend card: range selector + graph."""
        x = OUTER_PADDING
        card_w = POPOVER_WIDTH - 2 * OUTER_PADDING
        header_h = 24
        selector_h = 22
        gap = INLINE_GAP
        card_h = header_h + gap + selector_h + gap + GRAPH_HEIGHT + CARD_PADDING * 2

        card = ColoredRectView.alloc().initWithFrame_(((x, y - card_h), (card_w, card_h)))
        card.setColor_(_ns_color(SURFACE))
        card.setCornerRadius_(8)
        root.addSubview_(card)

        cy = y - CARD_PADDING

        # Section header
        trend_header = _make_label(
            "Heart Rate",
            NSFont.systemFontOfSize_(LABEL),
            _ns_color(TEXT_PRIMARY),
            (x + CARD_PADDING, cy - header_h, 120, header_h),
        )
        root.addSubview_(trend_header)

        cy -= header_h + gap

        # Range selector (5 / 10 / 30 min)
        selector = NSSegmentedControl.alloc().initWithFrame_(
            ((x + CARD_PADDING, cy - selector_h), (200, selector_h))
        )
        selector.setSegmentCount_(3)
        selector.setLabel_forSegment_("5 min", 0)
        selector.setLabel_forSegment_("10 min", 1)
        selector.setLabel_forSegment_("30 min", 2)
        selector.setTrackingMode_(NSSegmentSwitchTrackingSelectOne)
        selector.setTarget_(self)
        selector.setAction_("trend_range_changed:")
        selector.setSelectedSegment_(self._trend_segment_for_minutes(s.config))
        root.addSubview_(selector)
        self._trend_selector = selector

        graph_y = cy - selector_h - gap - GRAPH_HEIGHT

        # Graph image view
        img_view = NSImageView.alloc().initWithFrame_(
            ((x + CARD_PADDING, graph_y), (card_w - 2 * CARD_PADDING, GRAPH_HEIGHT))
        )
        img_view.setImageScaling_(1)  # NSImageScaleAxesIndependently
        root.addSubview_(img_view)
        self._graph_image_view = img_view

        # Placeholder for empty state (hidden when graph is shown)
        placeholder = _make_label(
            _empty_graph_placeholder(s),
            NSFont.systemFontOfSize_(11),
            _ns_color(TEXT_TERTIARY),
            ((x + CARD_PADDING, graph_y + GRAPH_HEIGHT / 2 - 20), (card_w - 2 * CARD_PADDING, 40)),
        )
        placeholder.setHidden_(True)
        root.addSubview_(placeholder)
        self._graph_placeholder = placeholder

        # Load initial graph
        self._update_graph(s, max_hr, zones_cfg, colors_cfg)

        return y - card_h - INLINE_GAP

    def _trend_segment_for_minutes(self, config: dict | None) -> int:
        minutes = (config or {}).get("graph_window_minutes", 10)
        if minutes <= 5:
            return 0
        elif minutes <= 10:
            return 1
        else:
            return 2

    def trend_range_changed_(self, sender: Any) -> None:
        """Handle graph time range selection."""
        segments = {0: 5, 1: 10, 2: 30}
        minutes = segments.get(sender.selectedSegment(), 10)
        cfg = deepcopy(self.state.snapshot_for_ui().config or cfg_mod.DEFAULT_CONFIG)
        if cfg.get("graph_window_minutes") != minutes:
            cfg["graph_window_minutes"] = minutes
            self.state.set_config(cfg)
            try:
                cfg_mod.save_config(cfg)
            except Exception:
                log.exception("Failed to persist graph window change")
            self._latest_graph_key = None  # Force graph redraw
            self.refresh()

    def _update_graph(
        self,
        s: UISnapshot,
        max_hr: int,
        zones_cfg: dict,
        colors_cfg: dict,
    ) -> None:
        if not self._graph_image_view or not self._graph_placeholder:
            return

        window_minutes = (s.config or {}).get("graph_window_minutes", 10)

        if s.ring_buffer:
            key = (
                s.ring_revision,
                max_hr,
                window_minutes,
                tuple(sorted(zones_cfg.items())),
                tuple(sorted(colors_cfg.items())),
            )
            if key != self._latest_graph_key:
                png_bytes = render_graph(
                    s.ring_buffer,
                    max_hr=max_hr,
                    window_minutes=window_minutes,
                    zones=zones_cfg,
                    zone_colors=colors_cfg,
                )
                self._latest_graph_key = key
                self._latest_graph_bytes = png_bytes
            else:
                png_bytes = self._latest_graph_bytes

            if png_bytes:
                image = NSImage.alloc().initWithData_(png_bytes)
                if image:
                    self._graph_image_view.setImage_(image)
                    self._graph_image_view.setHidden_(False)
                    self._graph_placeholder.setHidden_(True)
                    return

        # No data or no image — show placeholder
        self._graph_image_view.setHidden_(True)
        self._graph_placeholder.setStringValue_(_empty_graph_placeholder(s))
        self._graph_placeholder.setHidden_(False)

    # ── Session Card ────────────────────────────────────────────────────

    def _build_session_card(
        self,
        root: NSView,
        y: float,
        s: UISnapshot,
        colors_cfg: dict,
    ) -> float:
        """Build the session card: stats + zone-time bars."""
        x = OUTER_PADDING
        card_w = POPOVER_WIDTH - 2 * OUTER_PADDING
        header_h = 24
        stats_h = 20
        bar_area_h = 80
        card_h = header_h + INLINE_GAP + stats_h + INLINE_GAP + bar_area_h + CARD_PADDING * 2

        card = ColoredRectView.alloc().initWithFrame_(((x, y - card_h), (card_w, card_h)))
        card.setColor_(_ns_color(SURFACE))
        card.setCornerRadius_(8)
        root.addSubview_(card)

        cy = y - CARD_PADDING

        # Section header
        sess_header = _make_label(
            "Session",
            NSFont.systemFontOfSize_(LABEL),
            _ns_color(TEXT_PRIMARY),
            (x + CARD_PADDING, cy - header_h, 120, header_h),
        )
        root.addSubview_(sess_header)

        cy -= header_h + INLINE_GAP

        # Stats line: elapsed | avg | max
        stats_font = NSFont.monospacedDigitSystemFontOfSize_weight_(SECTION_VALUE, 0)
        stats_str = self._session_stats_string(s)
        stats_lbl = _make_label(
            stats_str,
            stats_font,
            _ns_color(TEXT_PRIMARY),
            (x + CARD_PADDING, cy - stats_h, card_w - 2 * CARD_PADDING, stats_h),
        )
        root.addSubview_(stats_lbl)
        self._session_stats_label = stats_lbl
        cy -= stats_h + INLINE_GAP

        # Zone time bars
        zone_bar_y = cy - bar_area_h
        zone_container = NSView.alloc().initWithFrame_(
            ((x + CARD_PADDING, zone_bar_y), (card_w - 2 * CARD_PADDING, bar_area_h))
        )
        root.addSubview_(zone_container)
        self._zone_bar_container = zone_container
        self._rebuild_zone_bars(s, colors_cfg)

        return y - card_h - INLINE_GAP

    def _update_session(self, s: UISnapshot, colors_cfg: dict) -> None:
        """Update session stats and zone bars without rebuilding."""
        if self._session_stats_label:
            self._session_stats_label.setStringValue_(self._session_stats_string(s))
        self._rebuild_zone_bars(s, colors_cfg)

    def _session_stats_string(self, s: UISnapshot) -> str:
        if not s.session_active and s.session_count == 0:
            return "No session data"
        elapsed = _format_td_short(sum(s.zone_times.values()))
        avg = s.session_sum / s.session_count if s.session_count > 0 else 0
        mx = s.session_max if s.session_count > 0 else 0
        mn = s.session_min if s.session_count > 0 and s.session_min < 999 else 0
        return f"{elapsed}  |  Avg {avg:.0f}  |  Max {mx}  |  Min {mn}"

    def _rebuild_zone_bars(self, s: UISnapshot, colors_cfg: dict) -> None:
        container = self._zone_bar_container
        if container is None:
            return

        for child in list(container.subviews()):
            child.removeFromSuperview()

        bar_area_w = container.frame().size.width
        total = sum(s.zone_times.values()) or 1
        row_height = 18
        for idx, zone in enumerate(ZONE_ORDER):
            row_y = idx * row_height
            seconds = s.zone_times.get(zone, 0)
            bar_str = f"{zone}  {_format_td_short(seconds)}"
            lbl = _make_label(
                bar_str,
                NSFont.systemFontOfSize_(10),
                _ns_color(TEXT_SECONDARY),
                (0, row_y, 80, 16),
            )
            container.addSubview_(lbl)

            frac = seconds / total
            bar_w = max(int(frac * (bar_area_w - 90)), 4)
            bar = ColoredRectView.alloc().initWithFrame_(((85, row_y + 2), (bar_w, 12)))
            bar.setColor_(_ns_color(zone_accent(zone, colors_cfg)))
            bar.setCornerRadius_(2)
            container.addSubview_(bar)

    # ── Action Area ─────────────────────────────────────────────────────

    def _build_action_area(
        self,
        root: NSView,
        y: float,
        s: UISnapshot,
    ) -> float:
        """Build the action area: primary session button + secondary row."""
        x = OUTER_PADDING
        card_w = POPOVER_WIDTH - 2 * OUTER_PADDING

        # Separator line
        sep = ColoredRectView.alloc().initWithFrame_(((x, y - 1), (card_w, 1)))
        sep.setColor_(_ns_color(DIVIDER))
        root.addSubview_(sep)
        y -= 12

        # Primary session button (full width)
        btn_title = "■ Stop & Save" if s.session_active else "▶ Start Session"
        primary_btn = NSButton.alloc().initWithFrame_(((x, y - 36), (card_w, 36)))
        primary_btn.setBezelStyle_(NSBezelStyleRounded)
        primary_btn.setTarget_(self)
        primary_btn.setAction_("start_session:" if not s.session_active else "stop_session:")
        _set_dark_button_title(primary_btn, btn_title)
        root.addSubview_(primary_btn)
        self._session_button = primary_btn
        y -= 42

        export_container_h = 56
        export_container = NSView.alloc().initWithFrame_(
            ((x, y - export_container_h), (card_w, export_container_h))
        )
        root.addSubview_(export_container)
        self._export_controls_container = export_container
        self._rebuild_export_controls(s)

        return y - export_container_h - 8

    def _update_actions(self, s: UISnapshot) -> None:
        """Update action button titles and visibility."""
        if self._session_button:
            title = "■ Stop & Save" if s.session_active else "▶ Start Session"
            self._session_button.setTitle_(title)
            action = "stop_session:" if s.session_active else "start_session:"
            self._session_button.setAction_(action)
        self._rebuild_export_controls(s)

    def _rebuild_export_controls(self, s: UISnapshot) -> None:
        container = self._export_controls_container
        if container is None:
            return

        for child in list(container.subviews()):
            child.removeFromSuperview()

        show_retry, export_message, export_is_error = _export_feedback(s)
        if show_retry:
            save_btn = NSButton.alloc().initWithFrame_(((0, 24), (140, 30)))
            save_btn.setBezelStyle_(NSBezelStyleRounded)
            save_btn.setTarget_(self)
            save_btn.setAction_("save_last_session:")
            _set_dark_button_title(save_btn, "💾 Save CSV")
            container.addSubview_(save_btn)
            self._save_button = save_btn

            json_btn = NSButton.alloc().initWithFrame_(((148, 24), (140, 30)))
            json_btn.setBezelStyle_(NSBezelStyleRounded)
            json_btn.setTarget_(self)
            json_btn.setAction_("save_last_session_json:")
            _set_dark_button_title(json_btn, "📊 Save JSON")
            container.addSubview_(json_btn)
            self._json_save_button = json_btn
            self._controls["json_save_button"] = json_btn
        else:
            self._save_button = None
            self._json_save_button = None
            self._controls.pop("json_save_button", None)

        if export_message:
            msg_col = NSColor.systemRedColor() if export_is_error else _ns_color(TEXT_SECONDARY)
            fb = _make_label(
                export_message,
                NSFont.systemFontOfSize_(10),
                msg_col,
                (0, 0, container.frame().size.width, 18),
            )
            container.addSubview_(fb)
            self._export_feedback = fb
        else:
            self._export_feedback = None

    def _build_recent_sessions_card(
        self,
        root: NSView,
        y: float,
        s: UISnapshot,
    ) -> float:
        """Build the recent-session archive card."""
        x = OUTER_PADDING
        card_w = POPOVER_WIDTH - 2 * OUTER_PADDING
        header_h = 24
        row_h = 22
        visible_rows = min(len(s.recent_sessions), RECENT_SESSION_ROWS) or 1
        note_h = 16 if s.recent_sessions else 0
        card_h = header_h + INLINE_GAP + visible_rows * row_h + note_h + CARD_PADDING * 2

        card = ColoredRectView.alloc().initWithFrame_(((x, y - card_h), (card_w, card_h)))
        card.setColor_(_ns_color(SURFACE))
        card.setCornerRadius_(8)
        root.addSubview_(card)

        cy = y - CARD_PADDING
        header = _make_label(
            "Recent sessions",
            NSFont.systemFontOfSize_(LABEL),
            _ns_color(TEXT_PRIMARY),
            (x + CARD_PADDING, cy - header_h, 140, header_h),
        )
        root.addSubview_(header)
        cy -= header_h + INLINE_GAP

        recent = list(reversed(s.recent_sessions[-RECENT_SESSION_ROWS:]))
        container = NSView.alloc().initWithFrame_(
            (
                (x + CARD_PADDING, cy - visible_rows * row_h),
                (card_w - 2 * CARD_PADDING, visible_rows * row_h),
            )
        )
        root.addSubview_(container)
        self._recent_sessions_container = container
        self._rebuild_recent_sessions(container, recent)

        if len(s.recent_sessions) > RECENT_SESSION_ROWS:
            note = _make_label(
                f"Showing latest {RECENT_SESSION_ROWS} of {len(s.recent_sessions)} archived sessions.",
                NSFont.systemFontOfSize_(10),
                _ns_color(TEXT_SECONDARY),
                (x + CARD_PADDING, y - card_h + CARD_PADDING, card_w - 2 * CARD_PADDING, 14),
            )
            root.addSubview_(note)

        return y - card_h - INLINE_GAP

    def _rebuild_recent_sessions(
        self,
        container: NSView,
        sessions: list[Any],
    ) -> None:
        for child in list(container.subviews()):
            child.removeFromSuperview()

        row_h = 22
        if not sessions:
            empty = _make_label(
                "Archived sessions will appear here after you stop and save.",
                NSFont.systemFontOfSize_(10),
                _ns_color(TEXT_SECONDARY),
                (0, 0, container.frame().size.width, row_h),
            )
            container.addSubview_(empty)
            return

        for idx, session in enumerate(sessions):
            row_y = (len(sessions) - idx - 1) * row_h + 2
            label = _make_label(
                session.display_summary(),
                NSFont.systemFontOfSize_(10),
                _ns_color(TEXT_PRIMARY if session.has_export else TEXT_SECONDARY),
                (0, row_y, container.frame().size.width - 120, 18),
            )
            container.addSubview_(label)

            reveal = NSButton.alloc().initWithFrame_(
                ((container.frame().size.width - 112, row_y - 1), (52, 20))
            )
            reveal.setBezelStyle_(NSBezelStyleRounded)
            reveal.setTarget_(self)
            reveal.setAction_("reveal_recent_session:")
            reveal.setTag_(idx)
            reveal.setEnabled_(session.has_export)
            _set_dark_button_title(reveal, "Reveal")
            container.addSubview_(reveal)

            delete_btn = NSButton.alloc().initWithFrame_(
                ((container.frame().size.width - 56, row_y - 1), (52, 20))
            )
            delete_btn.setBezelStyle_(NSBezelStyleRounded)
            delete_btn.setTarget_(self)
            delete_btn.setAction_("delete_recent_session:")
            delete_btn.setTag_(idx)
            _set_dark_button_title(delete_btn, "Delete")
            container.addSubview_(delete_btn)

    def _update_recent_sessions(self, s: UISnapshot) -> None:
        container = self._recent_sessions_container
        if container is None:
            return
        recent = list(reversed(s.recent_sessions[-RECENT_SESSION_ROWS:]))
        self._rebuild_recent_sessions(container, recent)

    def reveal_recent_session_(self, sender: Any) -> None:
        """Reveal the selected archived session export in Finder."""

        try:
            index = int(sender.tag())
        except Exception:
            return
        recent = list(reversed(self.state.snapshot_for_ui().recent_sessions[-RECENT_SESSION_ROWS:]))
        if index < 0 or index >= len(recent):
            return
        session = recent[index]
        if not session.export_path:
            return
        self._reveal_in_finder(session.export_path)

    def delete_recent_session_(self, sender: Any) -> None:
        """Delete the selected archived session from local history."""

        try:
            index = int(sender.tag())
        except Exception:
            return
        recent = list(reversed(self.state.snapshot_for_ui().recent_sessions[-RECENT_SESSION_ROWS:]))
        if index < 0 or index >= len(recent):
            return
        session = recent[index]
        if self.state.delete_recent_session(session.session_id):
            self.refresh()

    # ── Actions ─────────────────────────────────────────────────────────

    def start_session_(self, sender: Any) -> None:
        """Start a new session."""
        try:
            sess_mod.start_session(self.state)
            self.refresh()
        except Exception:
            log.exception("Failed to start session")

    def stop_session_(self, sender: Any) -> None:
        """Stop the active session and export CSV."""
        try:
            snapshot = sess_mod.finalize_session(self.state)
            if snapshot is not None and not snapshot.is_empty:
                self._save_snapshot(snapshot)
            self.refresh()
        except Exception:
            log.exception("Failed to stop session")

    def open_settings_(self, sender: Any) -> None:
        """Open the settings window."""
        try:
            if self.on_settings:
                self.on_settings()
        except Exception:
            log.exception("Failed to open settings")

    def save_last_session_(self, sender: Any) -> None:
        """Retry saving a finalized session as CSV."""
        snapshot = sess_mod.retryable_export(self.state)
        if snapshot is not None:
            self._save_snapshot(snapshot, fmt="csv")
        self.refresh()

    def save_last_session_json_(self, sender: Any) -> None:
        """Retry saving a finalized session as JSON."""
        snapshot = sess_mod.retryable_export(self.state)
        if snapshot is not None:
            self._save_snapshot(snapshot, fmt="json")
        self.refresh()

    def _save_snapshot(self, snapshot: ExportSnapshot, fmt: str = "csv") -> None:
        """Open a destination picker and save without leaking callback errors.

        Args:
            snapshot: The completed session data to export.
            fmt: ``"csv"`` for CSV export, ``"json"`` for JSON export.
        """
        suggested = (
            sess_mod.suggested_json_filename()
            if fmt == "json"
            else sess_mod.suggested_csv_filename()
        )
        try:
            try:
                destination = self._save_panel_factory(suggested, fmt)
            except TypeError:
                destination = self._save_panel_factory(suggested)
        except Exception:
            log.exception("Failed to open session save panel")
            self.state.mark_export_failure("Could not open the save dialog. Try again.")
            return
        if destination is None:
            return
        try:
            if fmt == "json":
                path = sess_mod.export_session_json(snapshot, destination)
            else:
                path = sess_mod.export_session_csv(snapshot, destination)
        except ValueError as exc:
            log.info("Session export destination was rejected: %s", exc)
            self.state.mark_export_failure(str(exc))
        except OSError:
            log.exception("Failed to write session %s", fmt.upper())
            self.state.mark_export_failure(
                f"Could not write the {fmt.upper()}. Check the destination and try again."
            )
        except Exception:
            log.exception("Failed to export session %s", fmt.upper())
            self.state.mark_export_failure(
                f"Could not save the session as {fmt.upper()}. Try again."
            )
        else:
            self.state.mark_export_success(str(path), fmt)
            self._reveal_in_finder(str(path))

    def _reveal_in_finder(self, path: str) -> None:
        """Reveal the saved export in Finder."""
        try:
            url = NSURL.fileURLWithPath_(path)
            NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_([url])
        except Exception:
            log.debug("Failed to reveal file in Finder", exc_info=True)


# ── Donut Gauge View ────────────────────────────────────────────────────


class DonutGaugeView(NSView):
    """An NSView subclass that draws a donut/arc gauge showing HR zone.

    No centre BPM number — the hero label is the sole numeric reading.
    Shows zone ticks and coloured arc only.
    """

    def initWithFrame_(self, frame: tuple) -> DonutGaugeView:
        self = objc.super(DonutGaugeView, self).initWithFrame_(frame)
        if self:
            self._bpm: int | None = None
            self._zone: str = "Z1"
            self._zone_bounds: dict[str, float] = {}
            self._max_hr: int = 190
            self._colors_cfg: dict[str, str] = {}
        return self

    def setBpm_zone_zoneBounds_maxHr_colorsCfg_(
        self,
        bpm: int | None,
        zone: str,
        zone_bounds: dict,
        max_hr: int,
        colors_cfg: dict,
    ) -> None:
        self._bpm = bpm
        self._zone = zone
        self._zone_bounds = zone_bounds
        self._max_hr = max_hr
        self._colors_cfg = colors_cfg
        self.setNeedsDisplay_(True)

    def isFlipped(self) -> bool:
        return False  # Default AppKit coordinate system

    def drawRect_(self, rect: tuple) -> None:
        ctx = NSGraphicsContext.currentContext()
        if ctx is None:
            return

        ctx.saveGraphicsState()
        try:
            self._draw_gauge()
        except Exception:
            log.exception("Failed to draw heart-rate gauge")
        finally:
            ctx.restoreGraphicsState()

    def _draw_gauge(self) -> None:
        """Render the gauge: background ring, active arc, zone ticks.

        No centre BPM number — that belongs in the hero label.
        """
        import math as m

        bounds = self.bounds()
        cx = bounds.size.width / 2
        cy = bounds.size.height / 2
        radius = min(cx, cy) - GAUGE_LINE_WIDTH / 2 - 4

        # Background ring
        bg_path = NSBezierPath.bezierPath()
        bg_path.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
            (cx, cy), radius, 0, 360, False
        )
        bg_path.setLineWidth_(GAUGE_LINE_WIDTH - 2)
        _ns_color("#333333").setStroke()
        bg_path.stroke()

        # Active arc
        if self._bpm is not None:
            fraction = min(self._bpm / self._max_hr, 1.0)
            end_angle = fraction * 360.0

            color = _ns_color(zone_accent(self._zone, self._colors_cfg))
            color.setStroke()

            arc_path = NSBezierPath.bezierPath()
            arc_path.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
                (cx, cy), radius, -90, -90 + end_angle, False
            )
            arc_path.setLineWidth_(GAUGE_LINE_WIDTH)
            arc_path.setLineCapStyle_(2)
            arc_path.stroke()

            # Zone boundary tick marks
            for zone_key in ["z1_max", "z2_max", "z3_max"]:
                frac = self._zone_bounds.get(zone_key, 0.0)
                if frac > 0 and frac < 1.0:
                    angle_deg = frac * 360.0 - 90
                    tick_inner_r = radius - GAUGE_LINE_WIDTH / 2 - 2
                    tick_outer_r = radius + GAUGE_LINE_WIDTH / 2 + 2
                    rad = m.radians(angle_deg)
                    tick_path = NSBezierPath.bezierPath()
                    tick_path.moveToPoint_(
                        (cx + tick_inner_r * m.cos(rad), cy + tick_inner_r * m.sin(rad))
                    )
                    tick_path.lineToPoint_(
                        (cx + tick_outer_r * m.cos(rad), cy + tick_outer_r * m.sin(rad))
                    )
                    tick_path.setLineWidth_(1.5)
                    _ns_color("#666666").setStroke()
                    tick_path.stroke()

            # Zone label at bottom of gauge
            label = zone_label(self._zone)
            font = NSFont.systemFontOfSize_(GAUGE_LABEL_FONT_SIZE)
            col = _ns_color(zone_accent(self._zone, self._colors_cfg))
            attrs = {
                NSFontAttributeName: font,
                NSForegroundColorAttributeName: col,
            }
            ns_str = NSString.alloc().initWithString_(label)
            size = ns_str.sizeWithAttributes_(attrs)
            x = cx - size.width / 2
            y = cy - size.height / 2 - radius + GAUGE_LINE_WIDTH + 8
            ns_str.drawAtPoint_withAttributes_((x, y), attrs)

        # No centre BPM number — hero label is the sole numeric reading.


class ColoredRectView(NSView):
    """Simple colored view with optional rounded corners."""

    def initWithFrame_(self, frame: tuple) -> ColoredRectView:
        self = objc.super(ColoredRectView, self).initWithFrame_(frame)
        if self:
            self._color = NSColor.clearColor()
            self._corner_radius: float = 0
        return self

    def setColor_(self, color: NSColor) -> None:
        self._color = color
        self.setNeedsDisplay_(True)

    def setCornerRadius_(self, radius: float) -> None:
        self._corner_radius = radius
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect: tuple) -> None:
        try:
            self._color.setFill()
            if self._corner_radius > 0:
                path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    self.bounds(), self._corner_radius, self._corner_radius
                )
                path.fill()
            else:
                NSBezierPath.fillRect_(self.bounds())
        except Exception:
            log.exception("Failed to draw colored view")


# ── Helpers ──────────────────────────────────────────────────────────────


def macos_save_panel(default_name: str, fmt: str = "csv") -> str | None:
    """Return a user-selected export path, or ``None`` when cancelled."""
    panel = NSSavePanel.savePanel()
    panel.setNameFieldStringValue_(default_name)
    panel.setCanCreateDirectories_(True)
    panel.setAllowedFileTypes_([fmt.lower()])
    panel.setExtensionHidden_(False)
    if panel.runModal() != NSModalResponseOK:
        return None
    url = panel.URL()
    return None if url is None else str(url.path())


def _export_feedback(snapshot: UISnapshot) -> tuple[bool, str | None, bool]:
    """Return retry visibility, message, and error styling for export state."""
    has_pending_export = bool(snapshot.pending_export)
    if snapshot.last_csv_error:
        return has_pending_export, f"Save failed: {snapshot.last_csv_error}", True
    if snapshot.last_csv_path:
        return False, f"Saved: {snapshot.last_csv_path}", False
    return has_pending_export, None, False


def _make_label(text: str, font: NSFont, color: NSColor, frame: tuple) -> NSTextField:
    """Convenience: create a non-editable, non-bezelled text field."""
    f = NSTextField.alloc().initWithFrame_(_rect(frame))
    f.setStringValue_(text)
    f.setFont_(font)
    f.setTextColor_(color)
    f.setDrawsBackground_(False)
    f.setBezeled_(False)
    f.setEditable_(False)
    f.setSelectable_(False)
    f.setBordered_(False)
    return f


def _rect(frame: tuple) -> tuple:
    """Accept flat or AppKit-style rect tuples and return AppKit form."""
    if len(frame) == 2:
        return frame
    if len(frame) == 4:
        x, y, width, height = frame
        return ((x, y), (width, height))
    return frame


def _ns_color(hex_str: str) -> NSColor:
    """Convert hex string #RRGGBB to NSColor."""
    try:
        h = hex_str.lstrip("#")
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
        return NSColor.colorWithRed_green_blue_alpha_(r, g, b, 1.0)
    except Exception:
        return NSColor.labelColor()


def _set_dark_button_title(button: NSButton, title: str) -> None:
    """Style a button with white text on dark background."""
    attrs = {
        NSForegroundColorAttributeName: NSColor.labelColor(),
        NSFontAttributeName: NSFont.systemFontOfSize_(13),
    }
    attributed = NSAttributedString.alloc().initWithString_attributes_(title, attrs)
    button.setTitle_(title)
    button.setAttributedTitle_(attributed)
    button.setAccessibilityLabel_(title)


def _empty_graph_placeholder(state: UISnapshot) -> str:
    if state.scan_status == "scanning":
        return "Scanning for heart-rate monitors..."
    if state.connection_status in {"connecting", "reconnecting"}:
        return f"Connecting to {_connection_target_name(state)}..."
    if state.connection_error:
        return state.connection_error
    return "No HR data yet — waiting for connection..."


def _connection_target_name(state: UISnapshot) -> str:
    config = state.config or {}
    device_name = config.get("device_name", "")
    if device_name:
        return device_name
    device_address = config.get("device_address", "")
    return device_address or "the selected device"


def _format_td_seconds(seconds: float) -> str:
    """Format elapsed seconds to HH:MM:SS."""
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _format_td_short(seconds: float) -> str:
    """Format seconds to MM:SS or HH:MM:SS if long."""
    h, remainder = divmod(int(seconds), 3600)
    m, s = divmod(remainder, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
