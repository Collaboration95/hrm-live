"""Settings window — NSPanel for editing app configuration.

Opened from the popover. Reads/writes config via ``config.py``.
"""

from __future__ import annotations

import logging
from typing import Any

from AppKit import (
    NSApp,
    NSPanel,
    NSView,
    NSTextField,
    NSSecureTextField,
    NSButton,
    NSBezelStyle,
    NSWindowController,
    NSWindowStyleMaskTitled,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskNonactivatingPanel,
    NSTabView,
    NSTabViewItem,
    NSLayoutAttributeTop,
    NSLayoutAttributeBottom,
    NSLayoutAttributeLeading,
    NSLayoutAttributeTrailing,
    NSLayoutConstraint,
    NSLayoutRelationEqual,
    NSFont,
    NSColor,
    NSComboBox,
    NSFormCell,
    NSAlert,
)
from PyObjCTools import AppHelper

from state import AppState
import config as cfg_mod
from zones import validate_zones, DEFAULT_COLORS, ZONE_ORDER

log = logging.getLogger(__name__)


class SettingsWindow:
    """Settings panel controller."""

    def __init__(self, state: AppState) -> None:
        self.state = state
        self._panel: NSPanel | None = None
        self._controls: dict[str, Any] = {}

    def show(self) -> None:
        """Open the settings window."""
        if self._panel and self._panel.isVisible():
            self._panel.orderFront_(None)
            return

        self._build_panel()
        self._panel.makeKeyAndOrderFront_(None)

    def close(self) -> None:
        """Close the settings window."""
        if self._panel:
            self._panel.close()
            self._panel = None

    def _build_panel(self) -> None:
        """Build the settings panel."""
        if NSApp() is None:
            raise RuntimeError("Settings window requires a running NSApplication")

        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            ((0, 0), (400, 420)),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskNonactivatingPanel,
            2,  # NSBackingStoreBuffered
            False,
        )
        panel.setTitle_("HRM Settings")
        panel.setFloatingPanel_(True)
        panel.setFrameAutosaveName_("HRMSettingsPanel")
        panel.center()

        content = panel.contentView()
        cfg = self.state.config or cfg_mod.DEFAULT_CONFIG

        # ── Device Address ───────────────────────────────────────────
        y = 380
        lbl = _make_label("Device Address:", (20, y, 120, 22))
        content.addSubview_(lbl)

        addr_field = NSTextField.alloc().initWithFrame_(_rect((150, y, 220, 22)))
        addr_field.setStringValue_(cfg.get("device_address", ""))
        content.addSubview_(addr_field)
        self._controls["device_address"] = addr_field

        y -= 30

        # Scan button (disabled — v2)
        scan_btn = NSButton.alloc().initWithFrame_(_rect((150, y, 120, 24)))
        scan_btn.setTitle_("Scan (v2)")
        scan_btn.setBezelStyle_(NSBezelStyle.NSBezelStyleRounded)
        scan_btn.setEnabled_(False)
        content.addSubview_(scan_btn)

        y -= 40

        # ── Separator ────────────────────────────────────────────────
        sep = _make_separator((20, y), (360, 1))
        content.addSubview_(sep)
        y -= 20

        # ── Max HR ───────────────────────────────────────────────────
        lbl = _make_label("Max HR:", (20, y, 120, 22))
        content.addSubview_(lbl)

        max_hr_field = NSTextField.alloc().initWithFrame_(_rect((150, y, 60, 22)))
        max_hr_field.setStringValue_(str(cfg.get("max_hr", 190)))
        max_hr_field.setFormatter_(_int_formatter())
        content.addSubview_(max_hr_field)
        self._controls["max_hr"] = max_hr_field

        y -= 30

        # ── Zone boundaries ──────────────────────────────────────────
        lbl = _make_label("Zone boundaries (%):", (20, y, 200, 22))
        content.addSubview_(lbl)
        y -= 28

        zones = cfg.get("zones", {})
        boundaries = [
            ("Z1/Z2 (z1_max)", "z1_max", zones.get("z1_max", 0.60)),
            ("Z2/Z3 (z2_max)", "z2_max", zones.get("z2_max", 0.75)),
            ("Z3/Z4 (z3_max)", "z3_max", zones.get("z3_max", 0.88)),
        ]
        for label_text, key, val in boundaries:
            lbl = _make_label(label_text, (40, y, 120, 20))
            lbl.setFont_(NSFont.systemFontOfSize_(11))
            content.addSubview_(lbl)

            field = NSTextField.alloc().initWithFrame_(_rect((170, y, 60, 20)))
            # Display as percentage * 100
            field.setStringValue_(f"{val * 100:.0f}")
            field.setFont_(NSFont.systemFontOfSize_(11))
            content.addSubview_(field)
            self._controls[f"zone_{key}"] = field
            y -= 24

        y -= 10

        # ── Zone colors ──────────────────────────────────────────────
        lbl = _make_label("Zone colors:", (20, y, 200, 22))
        content.addSubview_(lbl)
        y -= 28

        colors = cfg.get("zone_colors", {})
        for zone in ZONE_ORDER:
            lbl = _make_label(f"  {zone}", (40, y, 50, 20))
            lbl.setFont_(NSFont.systemFontOfSize_(11))
            content.addSubview_(lbl)

            field = NSTextField.alloc().initWithFrame_(_rect((100, y, 80, 20)))
            field.setStringValue_(colors.get(zone, DEFAULT_COLORS[zone]))
            field.setFont_(NSFont.systemFontOfSize_(11))
            content.addSubview_(field)
            self._controls[f"color_{zone}"] = field
            y -= 24

        y -= 10

        # ── Graph window ─────────────────────────────────────────────
        lbl = _make_label("Graph window:", (20, y, 120, 22))
        content.addSubview_(lbl)

        combo = NSComboBox.alloc().initWithFrame_(_rect((150, y, 80, 22)))
        combo.addItemsWithObjectValues_(["5", "10", "30"])
        combo.setStringValue_(str(cfg.get("graph_window_minutes", 10)))
        content.addSubview_(combo)
        self._controls["graph_window"] = combo

        y -= 50

        # ── Buttons ──────────────────────────────────────────────────
        save_btn = NSButton.alloc().initWithFrame_(_rect((20, y, 100, 28)))
        save_btn.setTitle_("Save")
        save_btn.setBezelStyle_(NSBezelStyle.NSBezelStyleRounded)
        save_btn.setTarget_(self)
        save_btn.setAction_("save_settings:")
        content.addSubview_(save_btn)

        reset_btn = NSButton.alloc().initWithFrame_(_rect((130, y, 140, 28)))
        reset_btn.setTitle_("Reset to Defaults")
        reset_btn.setBezelStyle_(NSBezelStyle.NSBezelStyleRounded)
        reset_btn.setTarget_(self)
        reset_btn.setAction_("reset_defaults:")
        content.addSubview_(reset_btn)

        self._panel = panel

    # ── Actions ──────────────────────────────────────────────────────

    def save_settings_(self, sender: Any) -> None:
        """Validate and save the settings."""
        try:
            new_config = self._collect_values()
            cfg_mod.save_config(new_config)
            # Update live state
            self.state.config = cfg_mod.load_config()
            log.info("Settings saved")
        except ValueError as exc:
            self._show_error(str(exc))

    def reset_defaults_(self, sender: Any) -> None:
        """Reset all controls to default values."""
        defaults = cfg_mod.DEFAULT_CONFIG
        self._controls.get("device_address", None)  # skip, leave as-is
        if "max_hr" in self._controls:
            self._controls["max_hr"].setStringValue_(str(defaults["max_hr"]))
        if "zone_z1_max" in self._controls:
            self._controls["zone_z1_max"].setStringValue_(
                f"{defaults['zones']['z1_max'] * 100:.0f}"
            )
            self._controls["zone_z2_max"].setStringValue_(
                f"{defaults['zones']['z2_max'] * 100:.0f}"
            )
            self._controls["zone_z3_max"].setStringValue_(
                f"{defaults['zones']['z3_max'] * 100:.0f}"
            )
        for zone in ZONE_ORDER:
            key = f"color_{zone}"
            if key in self._controls:
                self._controls[key].setStringValue_(defaults["zone_colors"][zone])
        if "graph_window" in self._controls:
            self._controls["graph_window"].setStringValue_(
                str(defaults["graph_window_minutes"])
            )

    # ── Internals ────────────────────────────────────────────────────

    def _collect_values(self) -> dict[str, Any]:
        """Read all control values and build a config dict."""
        c = self._controls

        device_address = c.get("device_address", "").stringValue() if "device_address" in c else ""

        try:
            max_hr = int(c.get("max_hr").stringValue())
        except (ValueError, AttributeError):
            raise ValueError("Max HR must be a valid integer")

        try:
            z1_pct = float(c.get("zone_z1_max").stringValue()) / 100.0
            z2_pct = float(c.get("zone_z2_max").stringValue()) / 100.0
            z3_pct = float(c.get("zone_z3_max").stringValue()) / 100.0
        except (ValueError, AttributeError):
            raise ValueError("Zone boundaries must be valid numbers")

        validate_zones({"z1_max": z1_pct, "z2_max": z2_pct, "z3_max": z3_pct})

        zone_colors = {}
        for zone in ZONE_ORDER:
            key = f"color_{zone}"
            val = c.get(key).stringValue() if key in c else DEFAULT_COLORS[zone]
            if not _is_valid_hex(val):
                raise ValueError(f"Color for {zone} must be a hex string like #RRGGBB")
            zone_colors[zone] = val

        try:
            gw = int(c.get("graph_window").stringValue())
        except (ValueError, AttributeError):
            raise ValueError("Graph window must be a valid integer")

        return {
            "device_address": device_address,
            "max_hr": max_hr,
            "zones": {"z1_max": z1_pct, "z2_max": z2_pct, "z3_max": z3_pct},
            "zone_colors": zone_colors,
            "graph_window_minutes": gw,
        }

    def _show_error(self, message: str) -> None:
        """Show an error alert."""
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Settings Error")
        alert.setInformativeText_(message)
        alert.addButtonWithTitle_("OK")
        alert.runModal()


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_label(text: str, frame: tuple[float, float, float, float]) -> NSTextField:
    """Create a non-editable label."""
    f = NSTextField.alloc().initWithFrame_(_rect(frame))
    f.setStringValue_(text)
    f.setFont_(NSFont.systemFontOfSize_(12))
    f.setTextColor_(NSColor.whiteColor())
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


def _make_separator(origin: tuple[float, float], size: tuple[float, float]) -> NSView:
    """Create a horizontal line separator."""
    view = NSView.alloc().initWithFrame_((origin, size))
    view.setWantsLayer_(True)
    view.layer().setBackgroundColor_(
        NSColor.darkGrayColor().CGColor()
    )
    return view


def _int_formatter() -> Any:
    """Return an NSNumberFormatter for integer input."""
    from Foundation import NSNumberFormatter, NSNumberFormatterDecimalStyle
    fmt = NSNumberFormatter.alloc().init()
    fmt.setNumberStyle_(NSNumberFormatterDecimalStyle)
    fmt.setAllowsFloats_(False)
    return fmt


def _is_valid_hex(s: str) -> bool:
    """Check if *s* is a valid hex color like #RRGGBB."""
    if not isinstance(s, str) or not s.startswith("#") or len(s) != 7:
        return False
    try:
        int(s[1:], 16)
        return True
    except ValueError:
        return False
