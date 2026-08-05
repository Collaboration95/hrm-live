"""Settings window — grouped form with native colour wells and inline validation.

Design (from FEATURE_ROADMAP):
  - Sections: Device, Heart Rate, Zones, Graph, with fixed footer
  - Shared 120–140 pt label column with aligned value controls
  - Scrollable / auto-layout content
  - Native NSColorWell for each zone colour + validated hex field
  - Zone boundaries as percent fields with inline validation
  - Graph interval as constrained segment (5, 10, 30 min)
  - Device card: scan, result picker, connection status, "Use device" confirmation
  - Clear permission/BT-off/reconnect guidance
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

import objc
from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSApp,
    NSBezelStyleRounded,
    NSBezierPath,
    NSBox,
    NSBoxCustom,
    NSBoxSeparator,
    NSButton,
    NSColor,
    NSColorWell,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSNumberFormatter,
    NSObject,
    NSPanel,
    NSPopUpButton,
    NSScrollView,
    NSSegmentedControl,
    NSSegmentSwitchTrackingSelectOne,
    NSTextField,
    NSView,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
    NSWorkspace,
)
from Foundation import NSURL, NSString

import hrm_live.config as cfg_mod
from hrm_live.state import AppState, DiscoveredDevice
from hrm_live.ui.guidance import (
    OPEN_BLUETOOTH_URI,
    OPEN_PRIVACY_URI,
    RecoveryAction,
    classify_error,
)
from hrm_live.ui.tokens import (
    CARD_PADDING,
    DIVIDER,
    INLINE_GAP,
    OUTER_PADDING,
    SURFACE,
    TEXT_SECONDARY,
    TEXT_TERTIARY,
    status_dot_colour,
)
from hrm_live.zones import DEFAULT_COLORS, ZONE_ORDER, validate_zones

log = logging.getLogger(__name__)

PANEL_WIDTH = 440
PANEL_HEIGHT = 680
LABEL_COLUMN_WIDTH = 130
VALUE_COLUMN_X = 150
SECTION_GAP_SETTINGS = 20
PREVIEW_HEIGHT = 66

# Settings is a real utility window opened from a transient popover.  It must
# be activatable after the popover closes; a non-activating panel can be
# ordered in front and still remain invisible when the menu-bar app is not
# active.
SETTINGS_PANEL_STYLE_MASK = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable


class _SettingsDelegate(NSObject):
    """AppKit delegate bridging close/field events back to the controller.

    The settings window is a plain Python controller; AppKit needs an
    Objective-C object as its delegate and as the text-field delegate so it
    can ask ``windowShouldClose:`` and report ``controlTextDidChange:``.
    """

    def initWithOwner_(self, owner: SettingsWindow) -> _SettingsDelegate:
        self = objc.super(_SettingsDelegate, self).init()
        if self is not None:
            self.owner = owner
        return self

    def windowShouldClose_(self, sender: Any) -> bool:
        return self.owner._window_should_close()

    def controlTextDidChange_(self, notification: Any) -> None:
        self.owner._mark_dirty()


class ZonePreviewView(NSView):
    """Compact live preview of the four training zones.

    Draws a horizontal zone ramp whose segment colors, boundary markers,
    and computed BPM cutoffs track the settings form in real time, so
    personalization is visible before it is committed.
    """

    def initWithFrame_(self, frame: tuple) -> ZonePreviewView:
        self = objc.super(ZonePreviewView, self).initWithFrame_(frame)
        if self is not None:
            self._colors: dict[str, str] = dict(DEFAULT_COLORS)
            self._zones: dict[str, float] = {"z1_max": 0.60, "z2_max": 0.75, "z3_max": 0.88}
            self._max_hr: int = 190
        return self

    def refreshWithColors_zones_maxHr_(
        self, colors: dict[str, str], zones: dict[str, float], max_hr: int
    ) -> None:
        """Update the preview from current form values and redraw."""
        self._colors = dict(colors)
        self._zones = dict(zones)
        self._max_hr = int(max_hr)
        self.setNeedsDisplay_(True)

    def isFlipped(self) -> bool:
        return True  # Top-down layout keeps text drawing simple

    def drawRect_(self, rect: tuple) -> None:
        try:
            self._draw_ramp()
        except Exception:
            log.exception("Failed to draw zone preview")

    def _draw_ramp(self) -> None:
        bounds = self.bounds()
        width = bounds.size.width
        ramp_h = 26
        ramp_y = 18

        z1 = self._zones["z1_max"]
        z2 = self._zones["z2_max"]
        z3 = self._zones["z3_max"]

        # ── Zone ramp ────────────────────────────────────────────────
        spans = [
            ("Z1", 0.0, z1, self._colors["Z1"]),
            ("Z2", z1, z2, self._colors["Z2"]),
            ("Z3", z2, z3, self._colors["Z3"]),
            ("Z4", z3, 1.0, self._colors["Z4"]),
        ]
        for label, lo, hi, hex_color in spans:
            x0 = lo * width
            seg_w = (hi - lo) * width
            if seg_w <= 0:
                continue
            _ns_color(hex_color, 0.9).setFill()
            NSBezierPath.fillRect_(((x0, ramp_y), (seg_w, ramp_h)))
            _preview_draw_text(
                label,
                (x0 + seg_w / 2, ramp_y + ramp_h / 2),
                font_size=11,
                color=_preview_contrast_color(hex_color),
                align="center",
            )

        # ── Boundary markers + percent captions ──────────────────────
        for frac in (z1, z2, z3):
            x = frac * width
            if 0 < x < width:
                tick = NSBezierPath.bezierPath()
                tick.moveToPoint_((x, ramp_y))
                tick.lineToPoint_((x, ramp_y + ramp_h))
                tick.setLineWidth_(1.0)
                _ns_color(DIVIDER).setStroke()
                tick.stroke()
                _preview_draw_text(
                    f"{frac * 100:.0f}%",
                    (x, 2),
                    font_size=10,
                    color=_ns_color(TEXT_SECONDARY),
                    align="center",
                )

        # ── Computed BPM cutoffs ─────────────────────────────────────
        z1_bpm = round(self._max_hr * z1)
        z2_bpm = round(self._max_hr * z2)
        z3_bpm = round(self._max_hr * z3)
        cutoff_text = (
            f"Z1 <{z1_bpm} · Z2 {z1_bpm}–{z2_bpm} · Z3 {z2_bpm}–{z3_bpm} · Z4 ≥{z3_bpm} bpm"
        )
        _preview_draw_text(
            cutoff_text,
            (0, ramp_y + ramp_h + 6),
            font_size=10,
            color=_ns_color(TEXT_SECONDARY),
            align="left",
        )


class DotIndicatorView(NSView):
    """Small filled-circle status dot used in the Device card header."""

    def initWithFrame_(self, frame: tuple) -> DotIndicatorView:
        self = objc.super(DotIndicatorView, self).initWithFrame_(frame)
        if self is not None:
            self._color = NSColor.clearColor()
        return self

    def setColor_(self, color: NSColor) -> None:
        self._color = color
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect: tuple) -> None:
        try:
            self._color.setFill()
            NSBezierPath.bezierPathWithOvalInRect_(self.bounds()).fill()
        except Exception:
            log.exception("Failed to draw status dot")


class SettingsWindow:
    """Settings panel controller with grouped form and live validation."""

    def __init__(
        self,
        state: AppState,
        on_scan: Any | None = None,
        on_cancel_scan: Any | None = None,
        on_config_saved: Any | None = None,
        *,
        open_system_settings: Any | None = None,
        on_retry: Any | None = None,
    ) -> None:
        self.state = state
        self.on_scan = on_scan
        self.on_cancel_scan = on_cancel_scan
        self.on_config_saved = on_config_saved
        self.on_retry = on_retry
        self._open_system_settings_cb = open_system_settings or _default_system_settings_opener
        self._panel: NSPanel | None = None
        self._scroll_view: NSScrollView | None = None
        self._content_view: NSView | None = None
        self._controls: dict[str, Any] = {}
        self._validation_labels: dict[str, NSTextField] = {}
        self._selected_scan_address = ""
        self._scan_result_addresses: list[str] = []
        self._last_state_signature: tuple[Any, ...] | None = None
        self._color_wells: dict[str, NSColorWell] = {}
        self._color_hex_fields: dict[str, NSTextField] = {}
        self._preview_view: ZonePreviewView | None = None
        self._device_card: Any | None = None
        self._dirty = False
        self._delegate: _SettingsDelegate | None = None

    @property
    def is_visible(self) -> bool:
        return self._panel is not None and self._panel.isVisible()

    def show(self) -> None:
        """Open the settings window."""
        if self._panel and self._panel.isVisible():
            NSApp.activateIgnoringOtherApps_(True)
            self._panel.makeKeyAndOrderFront_(None)
            self._panel.orderFrontRegardless()
            return

        self._build_panel()
        self.refresh_from_state(force=True)
        assert self._panel is not None
        NSApp.activateIgnoringOtherApps_(True)
        self._panel.makeKeyAndOrderFront_(None)
        self._panel.orderFrontRegardless()
        log.debug("Settings window presented: visible=%s", self._panel.isVisible())

    def close(self) -> None:
        """Close the settings window."""
        if self._panel:
            self._panel.close()
            self._panel = None

    def refresh_from_state(self, force: bool = False) -> None:
        """Refresh the visible panel from shared state."""
        if not self.is_visible:
            return

        snapshot = self.state.snapshot_for_ui()
        signature = (
            snapshot.scan_generation,
            snapshot.scan_status,
            snapshot.scan_error,
            snapshot.connection_status,
            snapshot.connection_error,
        )
        if not force and signature == self._last_state_signature:
            return
        self._last_state_signature = signature

        if force:
            self._sync_config_fields()
        self._sync_scan_section()
        self._sync_connection_status()

    # ── Panel construction ────────────────────────────────────────────

    def _build_panel(self) -> None:
        if NSApp() is None:
            raise RuntimeError("Settings window requires a running NSApplication")

        self._dirty = False
        self._delegate = _SettingsDelegate.alloc().initWithOwner_(self)

        # Main window
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            ((0, 0), (PANEL_WIDTH, PANEL_HEIGHT)),
            SETTINGS_PANEL_STYLE_MASK,
            2,
            False,
        )
        panel.setTitle_("HRM Settings")
        panel.setFloatingPanel_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setBecomesKeyOnlyIfNeeded_(False)
        panel.setReleasedWhenClosed_(False)
        panel.setFrameAutosaveName_("HRMSettingsPanel")
        panel.setDelegate_(self._delegate)
        panel.center()

        # Scroll view for content
        scroll = NSScrollView.alloc().initWithFrame_(((0, 60), (PANEL_WIDTH, PANEL_HEIGHT - 60)))
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        scroll.setBorderType_(0)  # NSNoBorder
        panel.contentView().addSubview_(scroll)
        self._scroll_view = scroll

        # Content view inside scroll
        content_h = 960  # Tall enough to allow scrolling
        content = NSView.alloc().initWithFrame_(((0, 0), (PANEL_WIDTH - 20, content_h)))
        scroll.setDocumentView_(content)
        self._content_view = content

        cfg = self.state.snapshot_for_ui().config or cfg_mod.DEFAULT_CONFIG
        y: float = content_h - OUTER_PADDING

        # ══════════════════════════════════════════════════════════════
        # SECTION: Device
        # ══════════════════════════════════════════════════════════════
        y = self._add_section_header(content, y, "Device")
        y = self._add_device_card(content, y, cfg)

        # ══════════════════════════════════════════════════════════════
        # SECTION: Heart Rate
        # ══════════════════════════════════════════════════════════════
        y = self._add_section_header(content, y, "Heart Rate")
        y = self._add_field_row(
            content,
            y,
            "Max HR (bpm):",
            str(cfg.get("max_hr", 190)),
            "max_hr",
            formatter=_int_formatter(),
        )

        # ══════════════════════════════════════════════════════════════
        # SECTION: Zones
        # ══════════════════════════════════════════════════════════════
        y = self._add_section_header(content, y, "Zones")
        y = self._add_zones_section(content, y, cfg)
        y = self._add_colors_section(content, y, cfg)

        # ══════════════════════════════════════════════════════════════
        # SECTION: Preview (live zone ramp)
        # ══════════════════════════════════════════════════════════════
        y = self._add_section_header(content, y, "Preview")
        y -= INLINE_GAP
        preview = ZonePreviewView.alloc().initWithFrame_(
            ((OUTER_PADDING, y - PREVIEW_HEIGHT), (PANEL_WIDTH - 2 * OUTER_PADDING, PREVIEW_HEIGHT))
        )
        content.addSubview_(preview)
        self._preview_view = preview
        self._update_preview()
        y -= PREVIEW_HEIGHT + INLINE_GAP

        # ══════════════════════════════════════════════════════════════
        # SECTION: Graph
        # ══════════════════════════════════════════════════════════════
        y = self._add_section_header(content, y, "Graph")

        graph_label = _make_label("Time window:", (OUTER_PADDING, y - 20, 120, 20))
        content.addSubview_(graph_label)

        graph_seg = NSSegmentedControl.alloc().initWithFrame_(((VALUE_COLUMN_X, y - 24), (180, 24)))
        graph_seg.setSegmentCount_(3)
        graph_seg.setLabel_forSegment_("5 min", 0)
        graph_seg.setLabel_forSegment_("10 min", 1)
        graph_seg.setLabel_forSegment_("30 min", 2)
        graph_seg.setTrackingMode_(NSSegmentSwitchTrackingSelectOne)
        graph_seg.setTarget_(self)
        graph_seg.setAction_("graph_window_changed:")
        current_minutes = cfg.get("graph_window_minutes", 10)
        graph_seg.setSelectedSegment_(
            0 if current_minutes <= 5 else (1 if current_minutes <= 10 else 2)
        )
        content.addSubview_(graph_seg)
        self._controls["graph_window"] = graph_seg

        y -= 60

        # ══════════════════════════════════════════════════════════════
        # FOOTER: Save / Reset
        # ══════════════════════════════════════════════════════════════
        y = self._add_footer(content, y)

        # Set content height
        # Document height spans from the bottom-most control to the top of
        # the first section (content_h), so taller sections never clip or
        # collapse the scroll view.
        content.setFrameSize_((PANEL_WIDTH - 20, max(content_h, content_h - y)))
        self._panel = panel
        log.debug("Settings panel built: frame=%s", panel.frame())

    def _add_section_header(self, parent: NSView, y: float, title: str) -> float:
        """Add a section header label and separator line."""
        y -= 8
        lbl = _make_label(
            title,
            (OUTER_PADDING, y - 18, 200, 18),
            font_size=14,
            weight=NSFont.boldSystemFontOfSize_(14),
        )
        parent.addSubview_(lbl)
        y -= 24

        sep = NSBox.alloc().initWithFrame_(((OUTER_PADDING, y - 1), (PANEL_WIDTH - 60, 1)))
        sep.setBoxType_(NSBoxSeparator)
        parent.addSubview_(sep)
        y -= 16
        return y

    def _add_field_row(
        self,
        parent: NSView,
        y: float,
        label: str,
        value: str,
        key: str,
        *,
        formatter: Any = None,
    ) -> float:
        """Add a label + text field row and store the control."""
        lbl = _make_label(label, (OUTER_PADDING, y - 20, LABEL_COLUMN_WIDTH, 20))
        parent.addSubview_(lbl)

        field = NSTextField.alloc().initWithFrame_(((VALUE_COLUMN_X, y - 22), (180, 22)))
        field.setStringValue_(value)
        if formatter:
            field.setFormatter_(formatter)
        if self._delegate is not None:
            field.setDelegate_(self._delegate)
        parent.addSubview_(field)
        self._controls[key] = field

        return y - 30

    def _add_device_card(self, parent: NSView, y: float, cfg: dict) -> float:
        """Build the one compact Device setup card and return the next y.

        Rows (8 pt grid): status header with dot, scan button + status,
        Discovered picker + Use Device, read-only Address, editable Name,
        plus contextual recovery buttons that appear only on failure.
        The address field is informational: it is written only by
        "Use Device" (or config load), never hand-edited.
        """
        card_x = OUTER_PADDING
        card_w = PANEL_WIDTH - 2 * OUTER_PADDING - 10
        inner_x = card_x + CARD_PADDING
        inner_w = card_w - 2 * CARD_PADDING
        label_w = 120
        value_x = inner_x + label_w

        # Card height (8 pt multiples): 12 + rows + gaps + 12
        header_h = 20
        recovery_h = 24
        field_h = 22
        row_gap = INLINE_GAP
        card_h = (
            CARD_PADDING
            + header_h
            + recovery_h
            + row_gap
            + field_h
            + field_h
            + row_gap
            + 28  # scan button
            + 16  # scan status line
            + recovery_h
            + row_gap
            + 26  # picker row
            + CARD_PADDING
        )

        card = NSBox.alloc().initWithFrame_(((card_x, y - card_h), (card_w, card_h)))
        card.setBoxType_(NSBoxCustom)
        card.setBorderType_(0)
        card.setFillColor_(_ns_color(SURFACE))
        card.setBorderColor_(_ns_color(DIVIDER))
        card.setBorderWidth_(1.0)
        card.setCornerRadius_(8.0)
        parent.addSubview_(card)
        self._device_card = card

        cy = y - CARD_PADDING

        # ── Header: status dot + connection status ────────────────────
        dot = DotIndicatorView.alloc().initWithFrame_(((inner_x, cy - 10), (10, 10)))
        dot.setColor_(_ns_color(status_dot_colour(self.state.snapshot_for_ui().connection_status)))
        parent.addSubview_(dot)
        self._controls["connection_status_dot"] = dot

        status_label = _make_label(
            self._connection_status_text(),
            (inner_x + 18, cy - 18, inner_w - 18, 18),
            font_size=11,
            color=_ns_color(TEXT_SECONDARY),
        )
        parent.addSubview_(status_label)
        self._controls["connection_status"] = status_label
        cy -= header_h

        # ── Connection recovery button (hidden unless failure) ────────
        conn_recovery = self._make_recovery_button(
            parent, (inner_x, cy - recovery_h, 190, recovery_h), tag=1
        )
        self._controls["connection_recovery_button"] = conn_recovery
        cy -= recovery_h + row_gap

        # ── Read-only Address row ─────────────────────────────────────
        addr_lbl = _make_label("Address:", (inner_x, cy - 20, label_w, 20), font_size=11)
        parent.addSubview_(addr_lbl)
        addr_field = NSTextField.alloc().initWithFrame_(((value_x, cy - field_h), (180, field_h)))
        addr_field.setStringValue_(cfg.get("device_address", ""))
        addr_field.setEditable_(False)
        addr_field.setSelectable_(True)
        parent.addSubview_(addr_field)
        self._controls["device_address"] = addr_field
        cy -= field_h

        # ── Editable Name row ─────────────────────────────────────────
        name_lbl = _make_label("Name:", (inner_x, cy - 20, label_w, 20), font_size=11)
        parent.addSubview_(name_lbl)
        name_field = NSTextField.alloc().initWithFrame_(((value_x, cy - field_h), (180, field_h)))
        name_field.setStringValue_(cfg.get("device_name", ""))
        if self._delegate is not None:
            name_field.setDelegate_(self._delegate)
        parent.addSubview_(name_field)
        self._controls["device_name"] = name_field
        cy -= field_h + row_gap

        # ── Scan button + status ──────────────────────────────────────
        scan_btn = NSButton.alloc().initWithFrame_(((inner_x, cy - 28), (160, 28)))
        scan_btn.setBezelStyle_(NSBezelStyleRounded)
        scan_btn.setTarget_(self)
        scan_btn.setAction_("scan_action:")
        parent.addSubview_(scan_btn)
        self._controls["scan_button"] = scan_btn
        cy -= 34

        scan_status = _make_label(
            "Click Scan to find nearby HRMs",
            (inner_x, cy - 16, inner_w, 16),
            font_size=11,
            color=_ns_color(TEXT_SECONDARY),
        )
        parent.addSubview_(scan_status)
        self._controls["scan_status"] = scan_status
        cy -= 22

        # ── Scan recovery button (hidden unless failure) ──────────────
        scan_recovery = self._make_recovery_button(
            parent, (inner_x, cy - recovery_h, 190, recovery_h), tag=0
        )
        self._controls["scan_recovery_button"] = scan_recovery
        cy -= recovery_h + row_gap

        # ── Discovered picker + Use Device ────────────────────────────
        picker_label = _make_label("Discovered:", (inner_x, cy - 20, label_w, 20), font_size=11)
        parent.addSubview_(picker_label)

        popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            _rect((value_x, cy - 26, 150, 26)), False
        )
        popup.setTarget_(self)
        popup.setAction_("scan_result_selected:")
        parent.addSubview_(popup)
        self._controls["scan_results"] = popup

        use_btn = NSButton.alloc().initWithFrame_(_rect((value_x + 158, cy - 26, 90, 26)))
        use_btn.setBezelStyle_(NSBezelStyleRounded)
        use_btn.setTitle_("Use Device")
        use_btn.setTarget_(self)
        use_btn.setAction_("use_selected:")
        parent.addSubview_(use_btn)
        self._controls["use_selected"] = use_btn
        cy -= 26

        return y - card_h - INLINE_GAP

    def _make_recovery_button(self, parent: NSView, frame: tuple, *, tag: int) -> NSButton:
        """Create a hidden recovery button; the sync pass reveals it on failure."""
        button = NSButton.alloc().initWithFrame_(_rect(frame))
        button.setBezelStyle_(NSBezelStyleRounded)
        button.setTarget_(self)
        button.setAction_("recovery_action:")
        button.setTag_(tag)
        button.setHidden_(True)
        parent.addSubview_(button)
        return button

    def _add_zones_section(self, parent: NSView, y: float, cfg: dict) -> float:
        """Add zone boundary percent fields with inline validation labels."""
        zones = cfg.get("zones", {})
        boundaries = [
            ("Z1/Z2 boundary:", "z1_max", zones.get("z1_max", 0.60)),
            ("Z2/Z3 boundary:", "z2_max", zones.get("z2_max", 0.75)),
            ("Z3/Z4 boundary:", "z3_max", zones.get("z3_max", 0.88)),
        ]

        # Column header
        perc_label = _make_label(
            "% of Max HR",
            (VALUE_COLUMN_X, y - 16, 120, 16),
            font_size=10,
            color=_ns_color(TEXT_SECONDARY),
        )
        parent.addSubview_(perc_label)
        y -= 22

        for label_text, key, default_val in boundaries:
            lbl = _make_label(label_text, (OUTER_PADDING + 10, y - 18, 130, 18), font_size=11)
            parent.addSubview_(lbl)

            # Percent field
            field = NSTextField.alloc().initWithFrame_(((VALUE_COLUMN_X, y - 20), (60, 20)))
            field.setStringValue_(f"{default_val * 100:.0f}")
            field.setFont_(NSFont.systemFontOfSize_(11))
            field.setTarget_(self)
            field.setAction_("zone_field_changed:")
            if self._delegate is not None:
                field.setDelegate_(self._delegate)
            parent.addSubview_(field)
            self._controls[f"zone_{key}"] = field

            # Validation label (hidden until invalid)
            val_lbl = _make_label(
                "",
                (VALUE_COLUMN_X + 68, y - 20, 180, 20),
                font_size=10,
                color=NSColor.systemRedColor(),
            )
            val_lbl.setHidden_(True)
            parent.addSubview_(val_lbl)
            self._validation_labels[f"zone_{key}"] = val_lbl

            y -= 26

        # Visual ramp hint
        ramp_lbl = _make_label(
            "Values must increase: Z1 < Z2 < Z3 < Z4",
            (OUTER_PADDING + 10, y - 16, 280, 16),
            font_size=10,
            color=_ns_color(TEXT_SECONDARY),
        )
        parent.addSubview_(ramp_lbl)
        y -= 24

        return y

    def _add_colors_section(self, parent: NSView, y: float, cfg: dict) -> float:
        """Add NSColorWell + hex field for each zone colour."""
        colors = cfg.get("zone_colors", {})

        for zone in ZONE_ORDER:
            hex_color = colors.get(zone, DEFAULT_COLORS[zone])
            zcol = _ns_color(hex_color)

            # Zone label
            lbl = _make_label(
                f"  {zone}:",
                (OUTER_PADDING + 10, y - 22, 50, 22),
                font_size=11,
                color=_ns_color(hex_color),
            )
            parent.addSubview_(lbl)

            # NSColorWell (native colour picker)
            well = NSColorWell.alloc().initWithFrame_(((VALUE_COLUMN_X, y - 22), (44, 22)))
            well.setColor_(zcol)
            well.setTarget_(self)
            well.setAction_("color_well_changed:")
            well.setBordered_(True)
            parent.addSubview_(well)
            self._controls[f"color_well_{zone}"] = well
            self._color_wells[zone] = well

            # Hex text field
            hex_field = NSTextField.alloc().initWithFrame_(
                ((VALUE_COLUMN_X + 52, y - 22), (80, 22))
            )
            hex_field.setStringValue_(hex_color)
            hex_field.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(11, 0))
            hex_field.setTarget_(self)
            hex_field.setAction_("hex_color_changed:")
            if self._delegate is not None:
                hex_field.setDelegate_(self._delegate)
            parent.addSubview_(hex_field)
            self._controls[f"color_{zone}"] = hex_field
            self._color_hex_fields[zone] = hex_field

            # Swatch preview (small coloured dot)
            swatch = _make_label(
                "●",
                (VALUE_COLUMN_X + 140, y - 22, 20, 22),
                font_size=14,
                color=_ns_color(hex_color),
            )
            parent.addSubview_(swatch)
            self._controls[f"swatch_{zone}"] = swatch

            y -= 28

        return y

    def _add_footer(self, parent: NSView, y: float) -> float:
        """Add the footer with Save, Reset, and Cancel."""
        y -= 12
        # Separator
        sep = NSBox.alloc().initWithFrame_(((OUTER_PADDING, y - 1), (PANEL_WIDTH - 60, 1)))
        sep.setBoxType_(NSBoxSeparator)
        parent.addSubview_(sep)
        y -= 24

        save_btn = NSButton.alloc().initWithFrame_(((VALUE_COLUMN_X, y - 28), (100, 28)))
        save_btn.setBezelStyle_(NSBezelStyleRounded)
        save_btn.setTitle_("Save Changes")
        save_btn.setKeyEquivalent_("\r")  # Enter key
        save_btn.setTarget_(self)
        save_btn.setAction_("save_settings:")
        parent.addSubview_(save_btn)

        reset_btn = NSButton.alloc().initWithFrame_(((VALUE_COLUMN_X + 110, y - 28), (140, 28)))
        reset_btn.setBezelStyle_(NSBezelStyleRounded)
        reset_btn.setTitle_("Reset to Defaults")
        reset_btn.setTarget_(self)
        reset_btn.setAction_("reset_defaults:")
        parent.addSubview_(reset_btn)

        cancel_btn = NSButton.alloc().initWithFrame_(((VALUE_COLUMN_X + 260, y - 28), (80, 28)))
        cancel_btn.setBezelStyle_(NSBezelStyleRounded)
        cancel_btn.setTitle_("Cancel")
        cancel_btn.setTarget_(self)
        cancel_btn.setAction_("close_settings:")
        parent.addSubview_(cancel_btn)

        y -= 40
        return y

    # ── Actions ─────────────────────────────────────────────────────────

    def _mark_dirty(self) -> None:
        """Record that the form differs from the last saved configuration."""
        self._dirty = True

    def _update_preview(self) -> None:
        """Refresh the live zone ramp from the current form values."""
        if self._preview_view is None:
            return
        try:
            z1 = float(self._controls["zone_z1_max"].stringValue()) / 100.0
            z2 = float(self._controls["zone_z2_max"].stringValue()) / 100.0
            z3 = float(self._controls["zone_z3_max"].stringValue()) / 100.0
            max_hr = int(self._controls["max_hr"].stringValue())
        except ValueError, AttributeError, KeyError, TypeError:
            return  # Keep the last valid preview while the field is being edited

        colors: dict[str, str] = {}
        for zone in ZONE_ORDER:
            raw = self._controls[f"color_{zone}"].stringValue().strip()
            colors[zone] = raw if _is_valid_hex(raw) else DEFAULT_COLORS[zone]
        self._preview_view.refreshWithColors_zones_maxHr_(
            colors, {"z1_max": z1, "z2_max": z2, "z3_max": z3}, max_hr
        )

    def _window_should_close(self) -> bool:
        """Return whether the window may close, prompting on unsaved edits."""
        if not self._dirty:
            return True
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Discard unsaved changes?")
        alert.setInformativeText_("Your edits to HRM settings have not been saved.")
        alert.addButtonWithTitle_("Discard")
        alert.addButtonWithTitle_("Cancel")
        return alert.runModal() == NSAlertFirstButtonReturn

    def scan_action_(self, sender: Any) -> None:
        try:
            if self.state.snapshot_for_ui().scan_status == "scanning":
                if self.on_cancel_scan is not None:
                    self.on_cancel_scan()
            else:
                if self.on_scan is not None:
                    self.on_scan()
            self.refresh_from_state()
        except Exception as exc:
            log.exception("Scan action failed")
            self._show_error(classify_error(exc, context="scan").display_text)

    def scan_result_selected_(self, sender: Any) -> None:
        try:
            result = self._selected_scan_result()
            self._selected_scan_address = result.address if result else ""
        except Exception:
            log.exception("Failed to update scan selection")

    def use_selected_(self, sender: Any) -> None:
        try:
            result = self._selected_scan_result()
            if result is None:
                return
            self._selected_scan_address = result.address
            self._set_text("device_address", result.address)
            self._set_text("device_name", result.name)
            self._mark_dirty()
        except Exception:
            log.exception("Failed to apply selected scan result")
            self._show_error("Failed to use the selected device. Try scanning again.")

    def color_well_changed_(self, sender: NSColorWell) -> None:
        """Sync hex field when colour well changes."""
        self._mark_dirty()
        color = sender.color()
        hex_str = self._ns_color_to_hex(color)
        # Find which zone this well belongs to
        for zone, well in self._color_wells.items():
            if well is sender:
                self._set_text(f"color_{zone}", hex_str)
                swatch = self._controls.get(f"swatch_{zone}")
                if swatch:
                    swatch.setTextColor_(color)
                break
        self._update_preview()

    def hex_color_changed_(self, sender: NSTextField) -> None:
        """Sync colour well when hex field changes (on Enter)."""
        self._mark_dirty()
        hex_str = sender.stringValue().strip()
        if _is_valid_hex(hex_str):
            color = _ns_color(hex_str)
            # Find which zone this hex field belongs to
            for zone, field in self._color_hex_fields.items():
                if field is sender:
                    well = self._color_wells.get(zone)
                    if well:
                        well.setColor_(color)
                    swatch = self._controls.get(f"swatch_{zone}")
                    if swatch:
                        swatch.setTextColor_(color)
                    break
        self._update_preview()

    def zone_field_changed_(self, sender: NSTextField) -> None:
        """Inline validation of zone boundary fields."""
        self._mark_dirty()
        try:
            # Collect current values
            z1_str = self._controls["zone_z1_max"].stringValue()
            z2_str = self._controls["zone_z2_max"].stringValue()
            z3_str = self._controls["zone_z3_max"].stringValue()

            z1 = float(z1_str) / 100.0
            z2 = float(z2_str) / 100.0
            z3 = float(z3_str) / 100.0

            validate_zones({"z1_max": z1, "z2_max": z2, "z3_max": z3})

            # Clear all validation errors
            for key in ["zone_z1_max", "zone_z2_max", "zone_z3_max"]:
                self._validation_labels[key].setHidden_(True)
                self._validation_labels[key].setStringValue_("")
            self._update_preview()

        except ValueError, TypeError:
            # Show error on the changed field
            error_msg = "Must increase: Z1 < Z2 < Z3"
            for key in ["zone_z1_max", "zone_z2_max", "zone_z3_max"]:
                self._validation_labels[key].setStringValue_(error_msg)
                self._validation_labels[key].setHidden_(False)

    def graph_window_changed_(self, sender: NSSegmentedControl) -> None:
        """Handle graph window segment change (value saved with Save)."""
        self._mark_dirty()

    def save_settings_(self, sender: Any) -> None:
        try:
            old_config = deepcopy(self.state.snapshot_for_ui().config or cfg_mod.DEFAULT_CONFIG)
            new_config = self._collect_values()
            cfg_mod.save_config(new_config)
            self.state.set_config(cfg_mod.load_config())
            saved_config = self.state.snapshot_for_ui().config or cfg_mod.DEFAULT_CONFIG
            if self.on_config_saved is not None:
                self.on_config_saved(old_config, deepcopy(saved_config))
            self._dirty = False
            self.refresh_from_state(force=True)
            log.info("Settings saved")
        except (ValueError, OSError) as exc:
            log.error("Failed to save settings: %s", exc)
            self._show_error(str(exc))
        except Exception as exc:
            log.exception("Settings save callback failed")
            self._show_error(f"Settings callback failed: {exc}")

    def reset_defaults_(self, sender: Any) -> None:
        """Reset the form to defaults after asking for confirmation."""
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Reset all settings?")
        alert.setInformativeText_(
            "This replaces the current form values with the defaults. "
            "Changes are applied when you click Save."
        )
        alert.addButtonWithTitle_("Reset")
        alert.addButtonWithTitle_("Cancel")
        if alert.runModal() != NSAlertFirstButtonReturn:
            return

        self._apply_defaults_to_form()
        self._mark_dirty()

    def _apply_defaults_to_form(self) -> None:
        defaults = cfg_mod.DEFAULT_CONFIG
        self._selected_scan_address = ""
        self._set_text("device_address", defaults["device_address"])
        self._set_text("device_name", defaults["device_name"])
        self._set_text("max_hr", str(defaults["max_hr"]))
        self._set_text("zone_z1_max", f"{defaults['zones']['z1_max'] * 100:.0f}")
        self._set_text("zone_z2_max", f"{defaults['zones']['z2_max'] * 100:.0f}")
        self._set_text("zone_z3_max", f"{defaults['zones']['z3_max'] * 100:.0f}")

        for zone in ZONE_ORDER:
            hex_c = defaults["zone_colors"][zone]
            self._set_text(f"color_{zone}", hex_c)
            well = self._color_wells.get(zone)
            if well:
                well.setColor_(_ns_color(hex_c))
            swatch = self._controls.get(f"swatch_{zone}")
            if swatch:
                swatch.setTextColor_(_ns_color(hex_c))

        # Graph window
        seg = self._controls.get("graph_window")
        if seg:
            default_minutes = defaults.get("graph_window_minutes", 10)
            seg.setSelectedSegment_(
                0 if default_minutes <= 5 else (1 if default_minutes <= 10 else 2)
            )

        # Clear validation errors
        for key in self._validation_labels:
            self._validation_labels[key].setHidden_(True)
            self._validation_labels[key].setStringValue_("")

        self._update_preview()

    def close_settings_(self, sender: Any) -> None:
        """Cancel and close, prompting when the form has unsaved edits."""
        if not self._window_should_close():
            return
        self.close()

    # ── State sync ─────────────────────────────────────────────────────

    def _sync_config_fields(self) -> None:
        cfg = self.state.snapshot_for_ui().config or cfg_mod.DEFAULT_CONFIG
        self._dirty = False
        self._set_text("device_address", cfg.get("device_address", ""))
        self._set_text("device_name", cfg.get("device_name", ""))
        self._set_text("max_hr", str(cfg.get("max_hr", 190)))
        zones = cfg.get("zones", {})
        self._set_text("zone_z1_max", f"{zones.get('z1_max', 0.60) * 100:.0f}")
        self._set_text("zone_z2_max", f"{zones.get('z2_max', 0.75) * 100:.0f}")
        self._set_text("zone_z3_max", f"{zones.get('z3_max', 0.88) * 100:.0f}")

        colors = cfg.get("zone_colors", {})
        for zone in ZONE_ORDER:
            hex_c = colors.get(zone, DEFAULT_COLORS[zone])
            self._set_text(f"color_{zone}", hex_c)
            well = self._color_wells.get(zone)
            if well:
                well.setColor_(_ns_color(hex_c))
            swatch = self._controls.get(f"swatch_{zone}")
            if swatch:
                swatch.setTextColor_(_ns_color(hex_c))

        seg = self._controls.get("graph_window")
        if seg:
            minutes = cfg.get("graph_window_minutes", 10)
            seg.setSelectedSegment_(0 if minutes <= 5 else (1 if minutes <= 10 else 2))

        self._update_preview()

    def _sync_scan_section(self) -> None:
        self._set_text("scan_button", self._scan_button_title())
        self._set_text("scan_status", self._scan_status_text())
        self._refresh_scan_popup()
        self._sync_recovery_button("scan")

    def _sync_connection_status(self) -> None:
        self._set_text("connection_status", self._connection_status_text())
        dot = self._controls.get("connection_status_dot")
        if dot is not None and hasattr(dot, "setColor_"):
            try:
                dot.setColor_(
                    _ns_color(status_dot_colour(self.state.snapshot_for_ui().connection_status))
                )
            except Exception:
                log.debug("Failed to update connection status dot", exc_info=True)
        self._sync_recovery_button("connection")

    _RECOVERY_BUTTON_TITLES = {
        RecoveryAction.OPEN_PRIVACY.value: "Open Privacy & Security",
        RecoveryAction.OPEN_BLUETOOTH.value: "Open Bluetooth Settings",
        RecoveryAction.RETRY.value: "Retry",
    }

    def _sync_recovery_button(self, context: str) -> None:
        """Show a single contextual recovery button, or hide it when none applies."""
        key = "scan_recovery_button" if context == "scan" else "connection_recovery_button"
        button = self._controls.get(key)
        if button is None:
            return
        snapshot = self.state.snapshot_for_ui()
        action = snapshot.scan_recovery if context == "scan" else snapshot.connection_recovery
        title = self._RECOVERY_BUTTON_TITLES.get(action)
        if title is None:
            button.setHidden_(True)
            return
        button.setHidden_(False)
        button.setTitle_(title)
        button.setEnabled_(True)

    def recovery_action_(self, sender: Any) -> None:
        """Handle a contextual recovery button: open a pane or retry."""
        try:
            tag = int(sender.tag())
        except Exception:
            return
        snapshot = self.state.snapshot_for_ui()
        action = snapshot.scan_recovery if tag == 0 else snapshot.connection_recovery
        if action == RecoveryAction.OPEN_PRIVACY.value:
            self._open_system_settings(OPEN_PRIVACY_URI)
        elif action == RecoveryAction.OPEN_BLUETOOTH.value:
            self._open_system_settings(OPEN_BLUETOOTH_URI)
        elif action == RecoveryAction.RETRY.value:
            if tag == 0:
                if self.on_scan is not None:
                    self.on_scan()
            elif self.on_retry is not None:
                self.on_retry()

    def _open_system_settings(self, uri: str) -> None:
        try:
            self._open_system_settings_cb(uri)
        except Exception:
            log.debug("Failed to open System Settings at %s", uri, exc_info=True)

    def _refresh_scan_popup(self) -> None:
        popup = self._controls.get("scan_results")
        if popup is None:
            return

        results = list(self.state.snapshot_for_ui().scan_results)
        popup.removeAllItems()
        self._scan_result_addresses = []

        if not results:
            popup.addItemWithTitle_("No devices found")
            popup.setEnabled_(False)
            self._controls["use_selected"].setEnabled_(False)
            self._selected_scan_address = ""
            return

        popup.setEnabled_(True)
        for result in results:
            popup.addItemWithTitle_(_scan_result_label(result))
            index = popup.numberOfItems() - 1
            item = popup.itemAtIndex_(index)
            item.setRepresentedObject_(result.address)
            self._scan_result_addresses.append(result.address)

        selected_index = self._index_for_selected_address(results)
        popup.selectItemAtIndex_(selected_index)
        self._selected_scan_address = results[selected_index].address if results else ""
        self._controls["use_selected"].setEnabled_(True)

    def _index_for_selected_address(self, results: list[DiscoveredDevice]) -> int:
        if self._selected_scan_address:
            for idx, result in enumerate(results):
                if result.address == self._selected_scan_address:
                    return idx
        return 0

    def _selected_scan_result(self) -> DiscoveredDevice | None:
        popup = self._controls.get("scan_results")
        if popup is None or not self._scan_result_addresses:
            return None
        index = popup.indexOfSelectedItem()
        if index < 0:
            return None
        results = list(self.state.snapshot_for_ui().scan_results)
        if index >= len(results):
            return None
        return results[index]

    def _scan_button_title(self) -> str:
        status = self.state.snapshot_for_ui().scan_status
        if status == "scanning":
            return "Cancel Scan"
        if status in {"complete", "cancelled", "error"}:
            return "Scan Again"
        return "Scan for HRMs"

    def _scan_status_text(self) -> str:
        snapshot = self.state.snapshot_for_ui()
        status = snapshot.scan_status
        count = len(snapshot.scan_results)
        if status == "scanning":
            return f"Scanning... {count} found"
        if status == "complete":
            if count == 0:
                return "No devices found. Wake the strap, wear it, and scan again."
            return f"{count} devices found"
        if status == "cancelled":
            if count == 0:
                return "Scan cancelled."
            return f"Scan cancelled. {count} devices found so far."
        if status == "error":
            return snapshot.scan_error or "Scan failed. Try again."
        return "Click Scan for HRMs to find nearby heart-rate monitors."

    def _connection_status_text(self) -> str:
        snapshot = self.state.snapshot_for_ui()
        status = snapshot.connection_status
        device_name = self._current_connection_name()
        if status == "connected":
            return f"Connected to {device_name}"
        if status == "connecting":
            return f"Connecting to {device_name}..."
        if status == "reconnecting":
            if snapshot.connection_error:
                return f"Reconnecting... {snapshot.connection_error}"
            return f"Reconnecting to {device_name}..."
        if status == "error":
            return snapshot.connection_error or "Connection failed."
        return "Not connected"

    def _current_connection_name(self) -> str:
        cfg = self.state.snapshot_for_ui().config or {}
        address = cfg.get("device_address", "")
        name = cfg.get("device_name", "")
        if name:
            return name
        if address:
            scan_name = self._scan_name_for_address(address)
            return scan_name or address
        return "—"

    def _scan_name_for_address(self, address: str) -> str:
        for result in self.state.snapshot_for_ui().scan_results:
            if result.address == address:
                return result.name
        return ""

    def _collect_values(self) -> dict[str, Any]:
        c = self._controls
        base = deepcopy(self.state.snapshot_for_ui().config or cfg_mod.DEFAULT_CONFIG)

        device_address = c["device_address"].stringValue().strip()
        device_name = c["device_name"].stringValue().strip()
        if not device_name and device_address:
            device_name = self._scan_name_for_address(device_address)

        try:
            max_hr = int(c["max_hr"].stringValue())
        except (ValueError, AttributeError, KeyError) as exc:
            raise ValueError("Max HR must be a valid integer") from exc

        try:
            z1_pct = float(c["zone_z1_max"].stringValue()) / 100.0
            z2_pct = float(c["zone_z2_max"].stringValue()) / 100.0
            z3_pct = float(c["zone_z3_max"].stringValue()) / 100.0
        except (ValueError, AttributeError, KeyError) as exc:
            raise ValueError("Zone boundaries must be valid numbers") from exc

        validate_zones({"z1_max": z1_pct, "z2_max": z2_pct, "z3_max": z3_pct})

        zone_colors: dict[str, str] = {}
        for zone in ZONE_ORDER:
            key = f"color_{zone}"
            value = c[key].stringValue().strip()
            if not _is_valid_hex(value):
                raise ValueError(f"Color for {zone} must be a hex string like #RRGGBB")
            zone_colors[zone] = value

        # Get graph window from segmented control
        seg = c.get("graph_window")
        minutes_map = {0: 5, 1: 10, 2: 30}
        graph_window = minutes_map.get(seg.selectedSegment(), 10) if seg else 10

        base["device_address"] = device_address
        base["device_name"] = device_name
        base["max_hr"] = max_hr
        base["zones"] = {
            "z1_max": z1_pct,
            "z2_max": z2_pct,
            "z3_max": z3_pct,
        }
        base["zone_colors"] = zone_colors
        base["graph_window_minutes"] = graph_window
        return base

    def _ns_color_to_hex(self, color: NSColor) -> str:
        """Convert an NSColor to #RRGGBB hex string."""
        try:
            rgb = color.colorUsingColorSpaceName_("NSCalibratedRGBColorSpace")
            if rgb is None:
                rgb = color
            r = int(rgb.redComponent() * 255)
            g = int(rgb.greenComponent() * 255)
            b = int(rgb.blueComponent() * 255)
            return f"#{r:02X}{g:02X}{b:02X}"
        except Exception:
            return TEXT_TERTIARY

    def _set_text(self, key: str, value: str) -> None:
        control = self._controls.get(key)
        if control is None:
            return
        try:
            if hasattr(control, "setTitle_"):
                control.setTitle_(value)
            else:
                control.setStringValue_(value)
        except Exception:
            log.debug("Failed to update control %s", key, exc_info=True)

    def _show_error(self, message: str) -> None:
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Settings Error")
        alert.setInformativeText_(message)
        alert.addButtonWithTitle_("OK")
        alert.runModal()


# ── Helpers ──────────────────────────────────────────────────────────────


def _default_system_settings_opener(uri: str) -> None:
    """Open a System Settings destination via the system workspace."""
    NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(uri))


def _make_label(
    text: str,
    frame: tuple,
    *,
    font_size: int = 12,
    color: Any = None,
    weight: Any = None,
) -> NSTextField:
    """Create a non-editable label."""
    if color is None:
        color = NSColor.labelColor()
    field = NSTextField.alloc().initWithFrame_(_rect(frame))
    field.setStringValue_(text)
    if weight is not None:
        field.setFont_(weight)
    else:
        field.setFont_(NSFont.systemFontOfSize_(font_size))
    field.setTextColor_(color)
    field.setDrawsBackground_(False)
    field.setBezeled_(False)
    field.setEditable_(False)
    field.setSelectable_(False)
    field.setBordered_(False)
    return field


def _rect(frame: tuple) -> tuple:
    """Accept flat or AppKit-style rect tuples."""
    if len(frame) == 2:
        return frame
    if len(frame) == 4:
        x, y, width, height = frame
        return ((x, y), (width, height))
    return frame


def _ns_color(hex_str: str, alpha: float = 1.0) -> NSColor:
    """Convert hex string #RRGGBB to NSColor (optionally with alpha)."""
    try:
        h = hex_str.lstrip("#")
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
        return NSColor.colorWithRed_green_blue_alpha_(r, g, b, alpha)
    except Exception:
        return NSColor.labelColor()


def _int_formatter() -> Any:
    try:
        return NSNumberFormatter.alloc().init()
    except Exception:
        return None


def _is_valid_hex(value: str) -> bool:
    if not isinstance(value, str) or not value.startswith("#") or len(value) != 7:
        return False
    try:
        int(value[1:], 16)
        return True
    except ValueError:
        return False


def _preview_text_attributes(font_size: float, color: Any) -> dict:
    """Attributes for zone-preview labels."""
    return {
        NSFontAttributeName: NSFont.systemFontOfSize_(font_size),
        NSForegroundColorAttributeName: color,
    }


def _preview_contrast_color(hex_fill: str) -> Any:
    """Return white or near-black text for a given fill color."""
    try:
        h = hex_fill.lstrip("#")
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
        return NSColor.whiteColor() if luminance < 0.55 else NSColor.blackColor()
    except Exception:
        return NSColor.labelColor()


def _preview_draw_text(
    text: str,
    point: tuple[float, float],
    *,
    font_size: float = 10,
    color: Any = None,
    align: str = "left",
) -> None:
    """Draw a string into the zone preview view, anchored at *point*."""
    if color is None:
        color = NSColor.labelColor()
    attrs = _preview_text_attributes(font_size, color)
    ns = NSString.alloc().initWithString_(text)
    size = ns.sizeWithAttributes_(attrs)
    x, y = point
    if align == "center":
        x -= size.width / 2
    ns.drawAtPoint_withAttributes_((x, y), attrs)


def _scan_result_label(device: DiscoveredDevice) -> str:
    prefix = "♥ " if device.heart_rate_capable else ""
    rssi = f" ({device.rssi} dBm)" if device.rssi is not None else ""
    name = device.name or (
        "Unnamed HR device" if device.heart_rate_capable else "Unnamed BLE device"
    )
    return f"{prefix}{name}{rssi}"
