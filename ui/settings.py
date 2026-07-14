"""Settings window for editing configuration and scanning for HRMs."""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from AppKit import (
    NSAlert,
    NSApp,
    NSBezelStyleRounded,
    NSBox,
    NSBoxSeparator,
    NSButton,
    NSColor,
    NSComboBox,
    NSFont,
    NSNumberFormatter,
    NSPanel,
    NSPopUpButton,
    NSTextField,
    NSView,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskNonactivatingPanel,
    NSWindowStyleMaskTitled,
)

import config as cfg_mod
from state import AppState, DiscoveredDevice
from zones import DEFAULT_COLORS, ZONE_ORDER, validate_zones

log = logging.getLogger(__name__)

PANEL_WIDTH = 420
PANEL_HEIGHT = 720


class SettingsWindow:
    """Settings panel controller."""

    def __init__(
        self,
        state: AppState,
        on_scan: Any | None = None,
        on_cancel_scan: Any | None = None,
        on_config_saved: Any | None = None,
    ) -> None:
        self.state = state
        self.on_scan = on_scan
        self.on_cancel_scan = on_cancel_scan
        self.on_config_saved = on_config_saved
        self._panel: NSPanel | None = None
        self._controls: dict[str, Any] = {}
        self._selected_scan_address = ""
        self._scan_result_addresses: list[str] = []
        self._last_state_signature: tuple[Any, ...] | None = None

    @property
    def is_visible(self) -> bool:
        return self._panel is not None and self._panel.isVisible()

    def show(self) -> None:
        """Open the settings window."""
        if self._panel and self._panel.isVisible():
            self._panel.orderFront_(None)
            return

        self._build_panel()
        self.refresh_from_state(force=True)
        self._panel.makeKeyAndOrderFront_(None)

    def close(self) -> None:
        """Close the settings window."""
        if self._panel:
            self._panel.close()
            self._panel = None

    def refresh_from_state(self, force: bool = False) -> None:
        """Refresh the visible panel from shared state."""

        if not self.is_visible:
            return

        signature = (
            self.state.scan_generation,
            self.state.scan_status,
            self.state.scan_error,
            self.state.connection_status,
            self.state.connection_error,
        )
        if not force and signature == self._last_state_signature:
            return
        self._last_state_signature = signature

        if force:
            self._sync_config_fields()
        self._sync_scan_section()
        self._sync_connection_status()

    def _build_panel(self) -> None:
        if NSApp() is None:
            raise RuntimeError("Settings window requires a running NSApplication")

        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            ((0, 0), (PANEL_WIDTH, PANEL_HEIGHT)),
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskNonactivatingPanel,
            2,
            False,
        )
        panel.setTitle_("HRM Settings")
        panel.setFloatingPanel_(True)
        panel.setFrameAutosaveName_("HRMSettingsPanel")
        panel.center()

        content = panel.contentView()
        cfg = self.state.config or cfg_mod.DEFAULT_CONFIG

        y = PANEL_HEIGHT - 40

        # Device identity section.
        content.addSubview_(_make_label("Device Address:", (20, y, 120, 22)))
        addr_field = NSTextField.alloc().initWithFrame_(_rect((150, y, 240, 22)))
        addr_field.setStringValue_(cfg.get("device_address", ""))
        content.addSubview_(addr_field)
        self._controls["device_address"] = addr_field

        y -= 30
        content.addSubview_(_make_label("Friendly Name:", (20, y, 120, 22)))
        name_field = _make_value_field((150, y, 240, 22))
        name_field.setStringValue_(cfg.get("device_name", ""))
        content.addSubview_(name_field)
        self._controls["device_name"] = name_field

        y -= 36
        scan_btn = NSButton.alloc().initWithFrame_(_rect((20, y, 150, 28)))
        scan_btn.setTitle_("Scan for HRMs")
        scan_btn.setBezelStyle_(NSBezelStyleRounded)
        scan_btn.setTarget_(self)
        scan_btn.setAction_("scan_action:")
        content.addSubview_(scan_btn)
        self._controls["scan_button"] = scan_btn

        y -= 34
        scan_status = _make_status_field((20, y, 380, 36))
        content.addSubview_(scan_status)
        self._controls["scan_status"] = scan_status

        y -= 42
        content.addSubview_(_make_label("Discovered devices:", (20, y, 140, 20)))
        popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            _rect((20, y - 30, 260, 26)),
            False,
        )
        popup.setTarget_(self)
        popup.setAction_("scan_result_selected:")
        content.addSubview_(popup)
        self._controls["scan_results"] = popup

        use_selected_btn = NSButton.alloc().initWithFrame_(_rect((290, y - 30, 110, 26)))
        use_selected_btn.setTitle_("Use Selected")
        use_selected_btn.setBezelStyle_(NSBezelStyleRounded)
        use_selected_btn.setTarget_(self)
        use_selected_btn.setAction_("use_selected:")
        content.addSubview_(use_selected_btn)
        self._controls["use_selected"] = use_selected_btn

        y -= 72
        connection_status = _make_status_field((20, y, 380, 36))
        content.addSubview_(connection_status)
        self._controls["connection_status"] = connection_status

        y -= 44

        content.addSubview_(_make_separator((20, y), (380, 1)))
        y -= 24

        # Existing heart-rate settings.
        content.addSubview_(_make_label("Max HR:", (20, y, 120, 22)))
        max_hr_field = NSTextField.alloc().initWithFrame_(_rect((150, y, 60, 22)))
        max_hr_field.setStringValue_(str(cfg.get("max_hr", 190)))
        max_hr_field.setFormatter_(_int_formatter())
        content.addSubview_(max_hr_field)
        self._controls["max_hr"] = max_hr_field

        y -= 30
        content.addSubview_(_make_label("Zone boundaries (%):", (20, y, 200, 22)))
        y -= 28

        zones = cfg.get("zones", {})
        boundaries = [
            ("Z1/Z2 (z1_max)", "z1_max", zones.get("z1_max", 0.60)),
            ("Z2/Z3 (z2_max)", "z2_max", zones.get("z2_max", 0.75)),
            ("Z3/Z4 (z3_max)", "z3_max", zones.get("z3_max", 0.88)),
        ]
        for label_text, key, value in boundaries:
            content.addSubview_(_make_label(label_text, (40, y, 120, 20), font_size=11))
            field = NSTextField.alloc().initWithFrame_(_rect((170, y, 60, 20)))
            field.setStringValue_(f"{value * 100:.0f}")
            field.setFont_(NSFont.systemFontOfSize_(11))
            content.addSubview_(field)
            self._controls[f"zone_{key}"] = field
            y -= 24

        y -= 10
        content.addSubview_(_make_label("Zone colors:", (20, y, 200, 22)))
        y -= 28

        colors = cfg.get("zone_colors", {})
        for zone in ZONE_ORDER:
            content.addSubview_(_make_label(f"  {zone}", (40, y, 50, 20), font_size=11))
            field = NSTextField.alloc().initWithFrame_(_rect((100, y, 100, 20)))
            field.setStringValue_(colors.get(zone, DEFAULT_COLORS[zone]))
            field.setFont_(NSFont.systemFontOfSize_(11))
            content.addSubview_(field)
            self._controls[f"color_{zone}"] = field
            y -= 24

        y -= 10
        content.addSubview_(_make_label("Graph window:", (20, y, 120, 22)))
        graph_combo = NSComboBox.alloc().initWithFrame_(_rect((150, y, 80, 22)))
        graph_combo.addItemsWithObjectValues_(["5", "10", "30"])
        graph_combo.setStringValue_(str(cfg.get("graph_window_minutes", 10)))
        content.addSubview_(graph_combo)
        self._controls["graph_window"] = graph_combo

        y -= 52
        save_btn = NSButton.alloc().initWithFrame_(_rect((20, y, 100, 28)))
        save_btn.setTitle_("Save")
        save_btn.setBezelStyle_(NSBezelStyleRounded)
        save_btn.setTarget_(self)
        save_btn.setAction_("save_settings:")
        content.addSubview_(save_btn)

        reset_btn = NSButton.alloc().initWithFrame_(_rect((130, y, 140, 28)))
        reset_btn.setTitle_("Reset to Defaults")
        reset_btn.setBezelStyle_(NSBezelStyleRounded)
        reset_btn.setTarget_(self)
        reset_btn.setAction_("reset_defaults:")
        content.addSubview_(reset_btn)

        self._panel = panel

    def scan_action_(self, sender: Any) -> None:
        try:
            if self.state.scan_status == "scanning":
                if self.on_cancel_scan is not None:
                    self.on_cancel_scan()
            else:
                if self.on_scan is not None:
                    self.on_scan()
            self.refresh_from_state()
        except Exception as exc:
            log.exception("Scan action failed")
            self._show_error("Scan failed: %s" % exc)

    def scan_result_selected_(self, sender: Any) -> None:
        try:
            result = self._selected_scan_result()
            if result is None:
                self._selected_scan_address = ""
                return
            self._selected_scan_address = result.address
        except Exception:
            log.exception("Failed to update scan selection")

    def use_selected_(self, sender: Any) -> None:
        try:
            result = self._selected_scan_result()
            if result is None:
                return
            self._selected_scan_address = result.address
            self._controls["device_address"].setStringValue_(result.address)
            self._controls["device_name"].setStringValue_(result.name)
            self._set_status_text(
                f"Selected {_display_name(result)} — click Save to connect."
            )
        except Exception as exc:
            log.exception("Failed to apply selected scan result")
            self._show_error(f"Failed to use the selected device: {exc}")

    def save_settings_(self, sender: Any) -> None:
        try:
            old_config = deepcopy(self.state.config or cfg_mod.DEFAULT_CONFIG)
            new_config = self._collect_values()
            cfg_mod.save_config(new_config)
            self.state.config = cfg_mod.load_config()
            if self.on_config_saved is not None:
                self.on_config_saved(old_config, deepcopy(self.state.config))
            self.refresh_from_state(force=True)
            log.info("Settings saved")
        except (ValueError, OSError) as exc:
            log.error("Failed to save settings: %s", exc)
            self._show_error(str(exc))
        except Exception as exc:
            log.exception("Settings save callback failed")
            self._show_error(f"Settings callback failed: {exc}")

    def reset_defaults_(self, sender: Any) -> None:
        defaults = cfg_mod.DEFAULT_CONFIG
        self._selected_scan_address = ""
        self._set_text("device_address", defaults["device_address"])
        self._set_text("device_name", defaults["device_name"])
        self._set_text("max_hr", str(defaults["max_hr"]))
        self._set_text("zone_z1_max", f"{defaults['zones']['z1_max'] * 100:.0f}")
        self._set_text("zone_z2_max", f"{defaults['zones']['z2_max'] * 100:.0f}")
        self._set_text("zone_z3_max", f"{defaults['zones']['z3_max'] * 100:.0f}")
        for zone in ZONE_ORDER:
            self._set_text(f"color_{zone}", defaults["zone_colors"][zone])
        self._set_text("graph_window", str(defaults["graph_window_minutes"]))
        self._set_status_text("Defaults loaded. Click Save to apply.")

    def _sync_config_fields(self) -> None:
        cfg = self.state.config or cfg_mod.DEFAULT_CONFIG
        self._set_text("device_address", cfg.get("device_address", ""))
        self._set_text("device_name", cfg.get("device_name", ""))
        self._set_text("max_hr", str(cfg.get("max_hr", 190)))
        zones = cfg.get("zones", {})
        self._set_text("zone_z1_max", f"{zones.get('z1_max', 0.60) * 100:.0f}")
        self._set_text("zone_z2_max", f"{zones.get('z2_max', 0.75) * 100:.0f}")
        self._set_text("zone_z3_max", f"{zones.get('z3_max', 0.88) * 100:.0f}")
        colors = cfg.get("zone_colors", {})
        for zone in ZONE_ORDER:
            self._set_text(f"color_{zone}", colors.get(zone, DEFAULT_COLORS[zone]))
        self._set_text("graph_window", str(cfg.get("graph_window_minutes", 10)))

    def _sync_scan_section(self) -> None:
        self._set_text("scan_button", self._scan_button_title())
        self._set_text("scan_status", self._scan_status_text())
        self._refresh_scan_popup()

    def _sync_connection_status(self) -> None:
        self._set_text("connection_status", self._connection_status_text())

    def _refresh_scan_popup(self) -> None:
        popup = self._controls.get("scan_results")
        if popup is None:
            return

        results = list(self.state.scan_results)
        popup.removeAllItems()
        self._scan_result_addresses = []

        if not results:
            popup.addItemWithTitle_("No devices found")
            popup.setEnabled_(False)
            self._set_text("use_selected", "Use Selected")
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
        self._selected_scan_address = results[selected_index].address
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
        results = list(self.state.scan_results)
        if index >= len(results):
            return None
        return results[index]

    def _scan_button_title(self) -> str:
        if self.state.scan_status == "scanning":
            return "Cancel Scan"
        if self.state.scan_status in {"complete", "cancelled", "error"}:
            return "Scan Again"
        return "Scan for HRMs"

    def _scan_status_text(self) -> str:
        status = self.state.scan_status
        count = len(self.state.scan_results)
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
            return self.state.scan_error or "Scan failed. Try again."
        return "Click Scan for HRMs to find nearby heart-rate monitors."

    def _connection_status_text(self) -> str:
        status = self.state.connection_status
        device_name = self._current_connection_name()
        if status == "connected":
            return f"Connected to {device_name}"
        if status == "connecting":
            return f"Connecting to {device_name}..."
        if status == "reconnecting":
            if self.state.connection_error:
                return f"Reconnecting to {device_name}... {self.state.connection_error}"
            return f"Reconnecting to {device_name}..."
        if status == "error":
            return self.state.connection_error or "Connection failed."
        return "Not connected"

    def _current_connection_name(self) -> str:
        cfg = self.state.config or {}
        device_address = cfg.get("device_address", "")
        device_name = cfg.get("device_name", "")
        if device_name:
            return device_name
        if device_address:
            scan_name = self._scan_name_for_address(device_address)
            if scan_name:
                return scan_name
            return device_address
        return "the selected device"

    def _scan_name_for_address(self, address: str) -> str:
        for result in self.state.scan_results:
            if result.address == address:
                return result.name
        return ""

    def _collect_values(self) -> dict[str, Any]:
        c = self._controls
        base = deepcopy(self.state.config or cfg_mod.DEFAULT_CONFIG)

        device_address = c["device_address"].stringValue().strip()
        device_name = c["device_name"].stringValue().strip()
        if not device_name and device_address:
            device_name = self._scan_name_for_address(device_address)

        try:
            max_hr = int(c["max_hr"].stringValue())
        except (ValueError, AttributeError, KeyError):
            raise ValueError("Max HR must be a valid integer")

        try:
            z1_pct = float(c["zone_z1_max"].stringValue()) / 100.0
            z2_pct = float(c["zone_z2_max"].stringValue()) / 100.0
            z3_pct = float(c["zone_z3_max"].stringValue()) / 100.0
        except (ValueError, AttributeError, KeyError):
            raise ValueError("Zone boundaries must be valid numbers")

        validate_zones({"z1_max": z1_pct, "z2_max": z2_pct, "z3_max": z3_pct})

        zone_colors: dict[str, str] = {}
        for zone in ZONE_ORDER:
            key = f"color_{zone}"
            value = c[key].stringValue().strip()
            if not _is_valid_hex(value):
                raise ValueError(f"Color for {zone} must be a hex string like #RRGGBB")
            zone_colors[zone] = value

        try:
            graph_window = int(c["graph_window"].stringValue())
        except (ValueError, AttributeError, KeyError):
            raise ValueError("Graph window must be a valid integer")

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

    def _set_status_text(self, message: str) -> None:
        self._set_text("scan_status", message)

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


def _make_label(
    text: str,
    frame: tuple[float, float, float, float],
    *,
    font_size: int = 12,
) -> NSTextField:
    field = NSTextField.alloc().initWithFrame_(_rect(frame))
    field.setStringValue_(text)
    field.setFont_(NSFont.systemFontOfSize_(font_size))
    field.setTextColor_(NSColor.labelColor())
    field.setDrawsBackground_(False)
    field.setBezeled_(False)
    field.setEditable_(False)
    field.setSelectable_(False)
    field.setBordered_(False)
    return field


def _make_value_field(frame: tuple[float, float, float, float]) -> NSTextField:
    field = NSTextField.alloc().initWithFrame_(_rect(frame))
    field.setFont_(NSFont.systemFontOfSize_(12))
    field.setTextColor_(NSColor.labelColor())
    field.setDrawsBackground_(False)
    field.setBezeled_(False)
    field.setEditable_(False)
    field.setSelectable_(False)
    field.setBordered_(False)
    return field


def _make_status_field(frame: tuple[float, float, float, float]) -> NSTextField:
    field = NSTextField.alloc().initWithFrame_(_rect(frame))
    field.setFont_(NSFont.systemFontOfSize_(11))
    field.setTextColor_(NSColor.secondaryLabelColor())
    field.setDrawsBackground_(False)
    field.setBezeled_(False)
    field.setEditable_(False)
    field.setSelectable_(False)
    field.setBordered_(False)
    return field


def _make_separator(origin: tuple[float, float], size: tuple[float, float]) -> NSView:
    separator = NSBox.alloc().initWithFrame_((origin, size))
    separator.setBoxType_(NSBoxSeparator)
    return separator


def _rect(frame: tuple) -> tuple:
    if len(frame) == 2:
        return frame
    x, y, width, height = frame
    return ((x, y), (width, height))


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


def _display_name(device: DiscoveredDevice) -> str:
    return device.name or (
        "Unnamed HR device" if device.heart_rate_capable else "Unnamed BLE device"
    )


def _scan_result_label(device: DiscoveredDevice) -> str:
    prefix = "♥ " if device.heart_rate_capable else ""
    rssi = f" ({device.rssi} dBm)" if device.rssi is not None else ""
    return f"{prefix}{_display_name(device)}{rssi}"
