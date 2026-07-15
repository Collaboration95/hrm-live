"""Popover dashboard — gauge, graph, session stats, and controls.

Built using AppKit (PyObjC) views inside an NSPopover.
Reads from ``AppState`` and delegates session actions to ``session.py``.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import objc
from AppKit import (
    NSApp,
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
    NSTextField,
    NSView,
    NSViewController,
)
from Foundation import NSString

import hrm_live.session as sess_mod
from hrm_live.state import AppState, ExportSnapshot, UISnapshot
from hrm_live.ui.graph import render_graph
from hrm_live.zones import ZONE_ORDER, get_zone, zone_color, zone_label

log = logging.getLogger(__name__)

POPOVER_WIDTH = 280
POPOVER_HEIGHT = 620
GAUGE_SIZE = 110
GAUGE_LINE_WIDTH = 14


class HRMPopover:
    """Popover controller — manages the NSPopover lifecycle."""

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
        self._popover.setContentSize_((POPOVER_WIDTH, POPOVER_HEIGHT))

        self._popover.showRelativeToRect_ofView_preferredEdge_(
            sender.bounds(),
            sender,
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
        s = self.state.snapshot_for_ui()

        # Root view with dark background
        root = ColoredRectView.alloc().initWithFrame_(((0, 0), (POPOVER_WIDTH, POPOVER_HEIGHT)))
        root.setColor_(_ns_color("#1F1F1F"))

        y_offset = POPOVER_HEIGHT - 30

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
        current_zone = get_zone(bpm, max_hr, zone_bounds) if bpm is not None else "Z1"

        z_col = _ns_color(zone_color(current_zone, colors_cfg))

        # ── Hero BPM ──────────────────────────────────────────────
        bpm_str = f"{bpm}" if bpm is not None else "---"
        lbl = _make_label(
            bpm_str, NSFont.boldSystemFontOfSize_(36), z_col, (20, y_offset - 10, 180, 44)
        )
        root.addSubview_(lbl)

        # Zone label
        label = zone_label(current_zone)
        zone_str = f"{current_zone} — {label}"
        lbl2 = _make_label(
            zone_str, NSFont.systemFontOfSize_(14), z_col, (20, y_offset - 48, 200, 24)
        )
        root.addSubview_(lbl2)

        # ── Donut gauge ───────────────────────────────────────────
        gauge_frame = (
            (POPOVER_WIDTH - GAUGE_SIZE - 10, y_offset - GAUGE_SIZE - 10),
            (GAUGE_SIZE, GAUGE_SIZE),
        )
        gauge_view = DonutGaugeView.alloc().initWithFrame_(gauge_frame)
        gauge_view.setBpm_zone_zoneBounds_maxHr_colorsCfg_(
            bpm, current_zone, zone_bounds, max_hr, colors_cfg
        )
        root.addSubview_(gauge_view)

        y_offset -= GAUGE_SIZE + 30

        # ── Graph ──────────────────────────────────────────────────
        if s.ring_buffer:
            png_bytes = self._graph_bytes(s, max_hr, zones_cfg, colors_cfg)
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
                _empty_graph_placeholder(s),
                NSFont.systemFontOfSize_(11),
                NSColor.grayColor(),
                (20, y_offset - 20, POPOVER_WIDTH - 40, 40),
            )
            root.addSubview_(placeholder)
            y_offset -= 40

        y_offset -= 10

        # ── Session stats ──────────────────────────────────────────
        if s.session_active or s.session_count > 0:
            elapsed_str = _format_td_seconds(sum(s.zone_times.values()))

            avg = s.session_sum / s.session_count if s.session_count > 0 else 0
            mx = s.session_max if s.session_count > 0 else 0
            mn = s.session_min if s.session_count > 0 else 0
            stats_str = f"Session: {elapsed_str}   Avg: {avg:.0f}   Max: {mx}   Min: {mn}"

            lbl3 = _make_label(
                stats_str,
                NSFont.systemFontOfSize_(11),
                NSColor.whiteColor(),
                (10, y_offset - 20, POPOVER_WIDTH - 20, 20),
            )
            root.addSubview_(lbl3)
            y_offset -= 30

            # Zone time bars
            for zone in ZONE_ORDER:
                seconds = s.zone_times.get(zone, 0)
                bar_str = f"{zone}  {_format_td_short(seconds)}"
                lbl4 = _make_label(
                    bar_str,
                    NSFont.systemFontOfSize_(10),
                    NSColor.lightGrayColor(),
                    (15, y_offset - 18, 100, 18),
                )
                root.addSubview_(lbl4)

                # Simple bar
                total = sum(s.zone_times.values()) or 1
                frac = seconds / total
                bar = ColoredRectView.alloc().initWithFrame_(
                    ((115, y_offset - 16), (int(frac * 140), 14))
                )
                bar.setColor_(_ns_color(zone_color(zone, colors_cfg)))
                root.addSubview_(bar)

                y_offset -= 22

        y_offset -= 10

        # ── Controls ───────────────────────────────────────────────
        if NSApp() is None:
            return root

        # Session toggle
        btn_title = "■ Stop Session" if s.session_active else "▶ Start Session"

        btn = NSButton.alloc().initWithFrame_(((10, y_offset - 36), (130, 32)))
        btn.setBezelStyle_(NSBezelStyleRounded)
        btn.setTarget_(self)
        btn.setAction_("start_session:" if not s.session_active else "stop_session:")
        _set_dark_button_title(btn, btn_title)
        root.addSubview_(btn)

        show_retry, export_message, export_is_error = _export_feedback(s)
        if show_retry:
            retry_btn = NSButton.alloc().initWithFrame_(((10, y_offset - 74), (160, 30)))
            retry_btn.setBezelStyle_(NSBezelStyleRounded)
            retry_btn.setTarget_(self)
            retry_btn.setAction_("save_last_session:")
            _set_dark_button_title(retry_btn, "Save Last Session...")
            root.addSubview_(retry_btn)
        if export_message:
            message_y = y_offset - (104 if show_retry else 64)
            message_color = (
                NSColor.systemRedColor() if export_is_error else NSColor.lightGrayColor()
            )
            message = _make_label(
                export_message,
                NSFont.systemFontOfSize_(10),
                message_color,
                (10, message_y, POPOVER_WIDTH - 20, 22),
            )
            root.addSubview_(message)

        # Settings button
        settings_btn = NSButton.alloc().initWithFrame_(((150, y_offset - 36), (100, 32)))
        settings_btn.setBezelStyle_(NSBezelStyleRounded)
        settings_btn.setTarget_(self)
        settings_btn.setAction_("open_settings:")
        _set_dark_button_title(settings_btn, "⚙ Settings")
        root.addSubview_(settings_btn)

        quit_btn = NSButton.alloc().initWithFrame_(((150, y_offset - 74), (100, 30)))
        quit_btn.setBezelStyle_(NSBezelStyleRounded)
        quit_btn.setTarget_(self)
        quit_btn.setAction_("quit:")
        _set_dark_button_title(quit_btn, "Quit")
        root.addSubview_(quit_btn)

        return root

    # ── Actions ───────────────────────────────────────────────────────

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
        """Retry saving a finalized session after cancel or write failure."""

        snapshot = sess_mod.retryable_export(self.state)
        if snapshot is not None:
            self._save_snapshot(snapshot)
        self.refresh()

    def quit_(self, sender: Any) -> None:
        """Footer Quit button callback."""

        if self._on_quit is not None:
            self._on_quit()

    def _save_snapshot(self, snapshot: ExportSnapshot) -> None:
        destination = self._save_panel_factory(sess_mod.suggested_csv_filename())
        if destination is None:
            return
        try:
            path = sess_mod.export_session_csv(snapshot, destination)
        except Exception as exc:
            self.state.mark_export_failure(str(exc))
        else:
            self.state.mark_export_success(str(path))

    def _graph_bytes(
        self,
        snapshot: UISnapshot,
        max_hr: int,
        zones_cfg: dict,
        colors_cfg: dict,
    ) -> bytes | None:
        key = (
            snapshot.ring_revision,
            max_hr,
            snapshot.config.get("graph_window_minutes", 10) if snapshot.config else 10,
            tuple(sorted(zones_cfg.items())),
            tuple(sorted(colors_cfg.items())),
        )
        if key != self._latest_graph_key:
            self._latest_graph_bytes = render_graph(
                snapshot.ring_buffer,
                max_hr=max_hr,
                window_minutes=key[2],
                zones=zones_cfg,
                zone_colors=colors_cfg,
            )
            self._latest_graph_key = key
        return self._latest_graph_bytes


# ── Donut Gauge View ────────────────────────────────────────────────────

# The PyObjC selector name must match the number of colons in the selector.
# setBpm:zone:zoneBounds:maxHr:colorsCfg: — 5 colons → 5 arguments (plus self)
# The trailing _ in the Python name maps to the colon in the selector.


class DonutGaugeView(NSView):
    """An NSView subclass that draws a donut/arc gauge showing HR zone.

    Uses NSBezierPath for reliable arc drawing in PyObjC.
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
        """Draw the donut gauge without leaking exceptions into AppKit."""
        ctx = NSGraphicsContext.currentContext()
        if ctx is None:
            return

        ctx.saveGraphicsState()
        try:
            self._draw_gauge()
        except Exception:
            # Exceptions crossing an Objective-C drawRect: callback cause AppKit
            # to terminate the entire process. Keep the app alive and log the
            # rendering error instead.
            log.exception("Failed to draw heart-rate gauge")
        finally:
            ctx.restoreGraphicsState()

    def _draw_gauge(self) -> None:
        """Render the gauge into the current graphics context."""
        bounds = self.bounds()
        cx = bounds.size.width / 2
        cy = bounds.size.height / 2
        radius = min(cx, cy) - GAUGE_LINE_WIDTH / 2 - 4

        # ---- Background ring ----
        bg_path = NSBezierPath.bezierPath()
        bg_path.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
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
            arc_path.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
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
                        (cx + tick_inner_r * math.cos(rad), cy + tick_inner_r * math.sin(rad))
                    )
                    tick_path.lineToPoint_(
                        (cx + tick_outer_r * math.cos(rad), cy + tick_outer_r * math.sin(rad))
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


class ColoredRectView(NSView):
    """Simple colored view that avoids layer-backed AppKit initialization."""

    def initWithFrame_(self, frame: tuple) -> ColoredRectView:
        self = objc.super(ColoredRectView, self).initWithFrame_(frame)
        if self:
            self._color = NSColor.clearColor()
        return self

    def setColor_(self, color: NSColor) -> None:
        self._color = color
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect: tuple) -> None:
        try:
            self._color.setFill()
            NSBezierPath.fillRect_(self.bounds())
        except Exception:
            log.exception("Failed to draw popover background")


# ── Helpers ──────────────────────────────────────────────────────────────


def macos_save_panel(default_name: str) -> str | None:
    """Return a user-selected CSV path, or ``None`` when the panel is cancelled."""

    panel = NSSavePanel.savePanel()
    panel.setNameFieldStringValue_(default_name)
    panel.setCanCreateDirectories_(True)
    panel.setAllowedFileTypes_(["csv"])
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


def _make_label(
    text: str, font: NSFont, color: NSColor, frame: tuple[float, float, float, float]
) -> NSTextField:
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
    x, y, width, height = frame
    return ((x, y), (width, height))


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


def _set_dark_button_title(button: NSButton, title: str) -> None:
    attrs = {
        NSForegroundColorAttributeName: NSColor.whiteColor(),
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
