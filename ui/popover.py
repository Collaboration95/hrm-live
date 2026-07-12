"""Popover dashboard — gauge, graph, session stats, and controls.

Built using AppKit (PyObjC) views inside an NSPopover.
Reads from ``AppState`` and delegates session actions to ``session.py``.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

import objc
from AppKit import (
    NSImage,
    NSImageView,
    NSView,
    NSTextField,
    NSFont,
    NSColor,
    NSPopover,
    NSPopoverBehaviorTransient,
    NSViewController,
    NSButton,
    NSBezelStyleRounded,
    NSBezierPath,
    NSGraphicsContext,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
)
from Foundation import NSString

from state import AppState
from zones import get_zone, zone_color, zone_label, ZONE_ORDER
from ui.graph import render_graph
import session as sess_mod

log = logging.getLogger(__name__)

POPOVER_WIDTH = 280
GAUGE_SIZE = 110
GAUGE_LINE_WIDTH = 14


class HRMPopover:
    """Popover controller — manages the NSPopover lifecycle."""

    def __init__(self, state: AppState) -> None:
        self.state = state
        self._popover: NSPopover | None = None
        self._latest_graph_bytes: bytes | None = None
        self.on_settings: Any = None  # callback for settings button

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
        """Create and show the popover."""
        if self._popover is None:
            self._popover = NSPopover.alloc().init()
            self._popover.setBehavior_(NSPopoverBehaviorTransient)

        vc = NSViewController.alloc().init()
        vc.setView_(self._build_view())
        self._popover.setContentViewController_(vc)
        self._popover.setContentSize_((POPOVER_WIDTH, 500))

        # Determine the positioning view
        positioning_view = sender
        if hasattr(sender, "ns_status_item") and sender.ns_status_item:
            button = sender.ns_status_item.button()
            if button:
                positioning_view = button

        self._popover.showRelativeToRect_ofView_preferredEdge_(
            ((0, 0), (0, 0)),
            positioning_view,
            0,  # NSRectEdgeMinY
        )

    def refresh(self) -> None:
        """Rebuild the view (called after state changes)."""
        if self._popover and self._popover.isShown():
            vc = NSViewController.alloc().init()
            vc.setView_(self._build_view())
            self._popover.setContentViewController_(vc)

    def _build_view(self) -> NSView:
        """Build the full popover content as an NSView."""
        s = self.state

        # Root view with dark background
        root = NSView.alloc().initWithFrame_(((0, 0), (POPOVER_WIDTH, 500)))
        root.setWantsLayer_(True)
        root.layer().setBackgroundColor_(
            NSColor.colorWithCalibratedWhite_alpha_(0.12, 1.0).CGColor()
        )

        y_offset = 470

        # ── Resolve config once ────────────────────────────────────
        cfg = s.config or {}
        max_hr = cfg.get("max_hr", 190)
        zones_cfg = cfg.get("zones", {})
        colors_cfg = cfg.get("zone_colors", {})

        zone_bounds = {
            "z1_max": zones_cfg.get("z1_max", 0.60),
            "z2_max": zones_cfg.get("z2_max", 0.75),
            "z3_max": zones_cfg.get("z3_max", 0.88),
        }

        bpm = s.latest_bpm if s.connected and s.latest_bpm is not None else None
        if bpm is not None:
            current_zone = get_zone(bpm, max_hr, zone_bounds)
        else:
            current_zone = "Z1"

        z_col = _ns_color(zone_color(current_zone, colors_cfg))

        # ── Hero BPM ──────────────────────────────────────────────
        bpm_str = f"{bpm}" if bpm is not None else "---"
        lbl = _make_label(bpm_str, NSFont.boldSystemFontOfSize_(36),
                          z_col, (20, y_offset - 10, 180, 44))
        root.addSubview_(lbl)

        # Zone label
        label = zone_label(current_zone)
        zone_str = f"{current_zone} — {label}"
        lbl2 = _make_label(zone_str, NSFont.systemFontOfSize_(14),
                           z_col, (20, y_offset - 48, 200, 24))
        root.addSubview_(lbl2)

        # ── Donut gauge ───────────────────────────────────────────
        gauge_frame = ((POPOVER_WIDTH - GAUGE_SIZE - 10, y_offset - GAUGE_SIZE - 10),
                       (GAUGE_SIZE, GAUGE_SIZE))
        gauge_view = DonutGaugeView.alloc().initWithFrame_(gauge_frame)
        gauge_view.setBpm_zone_zoneBounds_maxHr_colorsCfg_(
            bpm, current_zone, zone_bounds, max_hr, colors_cfg
        )
        root.addSubview_(gauge_view)

        y_offset -= GAUGE_SIZE + 30

        # ── Graph ──────────────────────────────────────────────────
        if s.ring_buffer:
            png_bytes = render_graph(
                s.ring_buffer,
                max_hr=max_hr,
                window_minutes=cfg.get("graph_window_minutes", 10),
                zones=zones_cfg,
                zone_colors=colors_cfg,
            )
            if png_bytes:
                image = NSImage.alloc().initWithData_(png_bytes)
                if image:
                    img_view = NSImageView.alloc().initWithFrame_(
                        ((10, y_offset - 170), (POPOVER_WIDTH - 20, 170))
                    )
                    img_view.setImage_(image)
                    img_view.setImageScaling_(1)  # NSImageScaleAxesIndependently
                    root.addSubview_(img_view)
                    self._latest_graph_bytes = png_bytes
                    y_offset -= 180
        else:
            # Empty graph placeholder
            placeholder = _make_label(
                "No HR data yet — waiting for connection...",
                NSFont.systemFontOfSize_(11),
                NSColor.grayColor(),
                (20, y_offset - 20, POPOVER_WIDTH - 40, 40),
            )
            root.addSubview_(placeholder)
            y_offset -= 40

        y_offset -= 10

        # ── Session stats ──────────────────────────────────────────
        if s.session_active or s.session_count > 0:
            # Elapsed time
            if s.session_active and s.session_start:
                elapsed = datetime.now(timezone.utc) - s.session_start
                elapsed_str = _format_td(elapsed)
            elif s.session_start and s.session_data:
                elapsed = s.session_data[-1][0] - s.session_data[0][0]
                elapsed_str = _format_td(elapsed)
            else:
                elapsed_str = "00:00:00"

            avg = s.session_sum / s.session_count if s.session_count > 0 else 0
            mx = s.session_max if s.session_count > 0 else 0
            mn = s.session_min if s.session_count > 0 else 0
            stats_str = f"Session: {elapsed_str}   Avg: {avg:.0f}   Max: {mx}   Min: {mn}"

            lbl3 = _make_label(stats_str, NSFont.systemFontOfSize_(11),
                               NSColor.whiteColor(), (10, y_offset - 20, POPOVER_WIDTH - 20, 20))
            root.addSubview_(lbl3)
            y_offset -= 30

            # Zone time bars
            for zone in ZONE_ORDER:
                seconds = s.zone_times.get(zone, 0)
                bar_str = f"{zone}  {_format_td_short(seconds)}"
                lbl4 = _make_label(bar_str, NSFont.systemFontOfSize_(10),
                                   NSColor.lightGrayColor(), (15, y_offset - 18, 100, 18))
                root.addSubview_(lbl4)

                # Simple bar
                total = sum(s.zone_times.values()) or 1
                frac = seconds / total
                bar = NSView.alloc().initWithFrame_(
                    ((115, y_offset - 16), (int(frac * 140), 14))
                )
                bar.setWantsLayer_(True)
                bar.layer().setBackgroundColor_(
                    _ns_color(zone_color(zone, colors_cfg)).CGColor()
                )
                bar.layer().setCornerRadius_(3)
                root.addSubview_(bar)

                y_offset -= 22

        y_offset -= 10

        # ── Controls ───────────────────────────────────────────────
        # Session toggle
        if s.session_active:
            btn_title = "■ Stop Session"
        else:
            btn_title = "▶ Start Session"

        btn = NSButton.alloc().initWithFrame_(((10, y_offset - 36), (130, 32)))
        btn.setTitle_(btn_title)
        btn.setBezelStyle_(NSBezelStyleRounded)
        btn.setTarget_(self)
        btn.setAction_(
            "start_session:" if not s.session_active else "stop_session:"
        )
        root.addSubview_(btn)

        # Settings button
        settings_btn = NSButton.alloc().initWithFrame_(((150, y_offset - 36), (100, 32)))
        settings_btn.setTitle_("⚙ Settings")
        settings_btn.setBezelStyle_(NSBezelStyleRounded)
        settings_btn.setTarget_(self)
        settings_btn.setAction_("open_settings:")
        root.addSubview_(settings_btn)

        return root

    # ── Actions ───────────────────────────────────────────────────────

    def start_session_(self, sender: Any) -> None:
        """Start a new session."""
        sess_mod.start_session(self.state)
        self.refresh()

    def stop_session_(self, sender: Any) -> None:
        """Stop the active session and export CSV."""
        cfg = self.state.config or {}
        max_hr = cfg.get("max_hr", 190)
        zones_cfg = cfg.get("zones", {})
        sess_mod.stop_session(self.state, max_hr=max_hr, zones=zones_cfg)
        self.refresh()

    def open_settings_(self, sender: Any) -> None:
        """Open the settings window."""
        if self.on_settings:
            self.on_settings()


# ── Donut Gauge View ────────────────────────────────────────────────────

# The PyObjC selector name must match the number of colons in the selector.
# setBpm:zone:zoneBounds:maxHr:colorsCfg: — 5 colons → 5 arguments (plus self)
# The trailing _ in the Python name maps to the colon in the selector.


class DonutGaugeView(NSView):
    """An NSView subclass that draws a donut/arc gauge showing HR zone.

    Uses NSBezierPath for reliable arc drawing in PyObjC.
    """

    def initWithFrame_(self, frame: tuple) -> "DonutGaugeView":
        self = objc.super(DonutGaugeView, self).initWithFrame_(frame)
        if self:
            self._bpm = None
            self._zone = "Z1"
            self._zone_bounds = {}
            self._max_hr = 190
            self._colors_cfg = {}
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
        """Draw the donut gauge."""
        ctx = NSGraphicsContext.currentContext()
        ctx.saveGraphicsState()

        bounds = self.bounds()
        cx = bounds.size.width / 2
        cy = bounds.size.height / 2
        radius = min(cx, cy) - GAUGE_LINE_WIDTH / 2 - 4

        # ---- Background ring ----
        bg_path = NSBezierPath.bezierPath()
        bg_path.appendBezierPathWithArcWithCenter_startAngle_endAngle_clockwise_(
            (cx, cy), radius, 0, 360, False
        )
        bg_path.setLineWidth_(GAUGE_LINE_WIDTH)
        NSColor.darkGrayColor().setStroke()
        bg_path.stroke()

        # ---- Active arc ----
        if self._bpm is not None:
            fraction = min(self._bpm / self._max_hr, 1.0)
            end_angle = fraction * 360.0  # degrees

            color = _ns_color(zone_color(self._zone, self._colors_cfg))
            color.setStroke()

            arc_path = NSBezierPath.bezierPath()
            arc_path.appendBezierPathWithArcWithCenter_startAngle_endAngle_clockwise_(
                (cx, cy), radius, -90, -90 + end_angle, False
            )
            arc_path.setLineWidth_(GAUGE_LINE_WIDTH)
            arc_path.setLineCapStyle_(2)  # NSSquareLineCapStyle
            arc_path.stroke()

            # ---- Zone boundary tick marks ----
            for zone_key in ["z1_max", "z2_max", "z3_max"]:
                frac = self._zone_bounds.get(zone_key, 0.0)
                if frac > 0 and frac < 1.0:
                    angle_deg = frac * 360.0 - 90
                    tick_inner_r = radius - GAUGE_LINE_WIDTH / 2 - 2
                    tick_outer_r = radius + GAUGE_LINE_WIDTH / 2 + 2
                    rad = math.radians(angle_deg)
                    tick_path = NSBezierPath.bezierPath()
                    tick_path.moveToPoint_(
                        (cx + tick_inner_r * math.cos(rad),
                         cy + tick_inner_r * math.sin(rad))
                    )
                    tick_path.lineToPoint_(
                        (cx + tick_outer_r * math.cos(rad),
                         cy + tick_outer_r * math.sin(rad))
                    )
                    tick_path.setLineWidth_(1.5)
                    NSColor.grayColor().setStroke()
                    tick_path.stroke()

        # ---- Center text ----
        bpm_str = f"{self._bpm}" if self._bpm is not None else "---"
        font = NSFont.boldSystemFontOfSize_(18)
        color = _ns_color(zone_color(self._zone, self._colors_cfg))
        attrs = {
            NSFontAttributeName: font,
            NSForegroundColorAttributeName: color,
        }
        ns_str = NSString.alloc().initWithString_(bpm_str)
        size = ns_str.sizeWithAttributes_(attrs)
        x = cx - size.width / 2
        y = cy - size.height / 2
        ns_str.drawAtPoint_withAttributes_((x, y), attrs)

        ctx.restoreGraphicsState()


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_label(text: str, font: NSFont, color: NSColor,
                frame: tuple[float, float, float, float]) -> NSTextField:
    """Convenience: create a non-editable, non-bezelled text field."""
    f = NSTextField.alloc().initWithFrame_(frame)
    f.setStringValue_(text)
    f.setFont_(font)
    f.setTextColor_(color)
    f.setDrawsBackground_(False)
    f.setBezeled_(False)
    f.setEditable_(False)
    f.setSelectable_(False)
    f.setBordered_(False)
    return f


def _ns_color(hex_str: str) -> NSColor:
    """Convert hex string #RRGGBB to NSColor."""
    try:
        h = hex_str.lstrip("#")
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
        return NSColor.colorWithRed_green_blue_alpha_(r, g, b, 1.0)
    except Exception:
        return NSColor.whiteColor()


def _format_td(td: Any) -> str:
    """Format timedelta to HH:MM:SS."""
    total = int(td.total_seconds())
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _format_td_short(seconds: int) -> str:
    """Format seconds to MM:SS or HH:MM:SS if long."""
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
