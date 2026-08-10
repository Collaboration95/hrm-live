"""Headless unit tests for UI decision/formatting logic.

AppKit view construction is safe without a window server; only *showing*
windows, panels, or popovers needs a GUI session.  These tests therefore
build the popover/settings hierarchies in memory and exercise the pure
presentation logic (status text, formatting, validation, layout decisions)
without launching a real app or touching Bluetooth/disk.
"""

from __future__ import annotations

import logging
from datetime import datetime

import pytest
from AppKit import NSApplication, NSColor

from hrm_live.app import _setup_logging, _shutdown_app
from hrm_live.state import AppState, DiscoveredDevice, SessionSample, UISnapshot
from hrm_live.ui.menubar import HRMBarApp
from hrm_live.ui.popover import (
    HRMPopover,
    _connection_target_name,
    _export_failure_message,
    _export_feedback,
    _rect,
)
from hrm_live.ui.popover import (
    _ns_color as popover_ns_color,
)
from hrm_live.ui.settings import (
    SettingsWindow,
    _is_valid_hex,
    _scan_result_label,
)
from hrm_live.ui.settings import (
    _ns_color as settings_ns_color,
)


def _snap(**overrides: object) -> UISnapshot:
    """Build a UISnapshot with sensible defaults for one-off assertions."""
    defaults: dict[str, object] = {
        "latest_bpm": None,
        "connected": False,
        "connection_status": "disconnected",
        "connection_error": None,
        "scan_status": "idle",
        "scan_results": (),
        "scan_error": None,
        "scan_generation": 0,
        "ring_buffer": (),
        "ring_revision": 0,
        "session_active": False,
        "session_start": None,
        "session_data": (),
        "session_max": 0,
        "session_min": 0,
        "session_sum": 0,
        "session_count": 0,
        "zone_times": {"Z1": 0.0, "Z2": 0.0, "Z3": 0.0, "Z4": 0.0},
        "last_csv_path": None,
        "last_csv_error": None,
        "pending_export": (),
        "recent_sessions": (),
        "config": None,
    }
    defaults.update(overrides)
    return UISnapshot(**defaults)  # type: ignore[arg-type]


def _device(
    address: str = "AA:BB:CC", name: str = "Polar H10", rssi: int | None = -50
) -> DiscoveredDevice:
    return DiscoveredDevice(address=address, name=name, rssi=rssi, heart_rate_capable=True)


# ── Popover: export feedback helpers ──────────────────────────────────────


class TestExportFailureMessage:
    def test_value_error_keeps_message(self) -> None:
        assert _export_failure_message(ValueError("Bad destination"), "csv") == "Bad destination"

    def test_os_error_gets_retry_hint(self) -> None:
        msg = _export_failure_message(OSError("denied"), "csv")
        assert "Could not write the CSV" in msg
        assert "try again" in msg

    def test_generic_exception(self) -> None:
        msg = _export_failure_message(RuntimeError("boom"), "json")
        assert "Could not save the session as JSON" in msg


class TestExportFeedback:
    def test_error_state_shows_message(self) -> None:
        snap = _snap(last_csv_error="disk full")
        assert _export_feedback(snap) == (False, "Save failed: disk full", True)

    def test_error_state_with_pending_export_keeps_retry(self) -> None:
        pending = (SessionSample(datetime.now(), 120, "Z2"),)
        snap = _snap(last_csv_error="disk full", pending_export=pending)
        assert _export_feedback(snap) == (True, "Save failed: disk full", True)

    def test_success_shows_saved_path(self) -> None:
        snap = _snap(last_csv_path="/tmp/session.csv")
        assert _export_feedback(snap) == (False, "Saved: /tmp/session.csv", False)

    def test_neutral_state(self) -> None:
        assert _export_feedback(_snap()) == (False, None, False)

    def test_neutral_state_with_pending_export(self) -> None:
        pending = (SessionSample(datetime.now(), 120, "Z2"),)
        assert _export_feedback(_snap(pending_export=pending)) == (True, None, False)


# ── Popover: status text helpers ──────────────────────────────────────────


class TestDotColour:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            ("connected", "STATUS_CONNECTED"),
            ("connecting", "STATUS_RECONNECTING"),
            ("reconnecting", "STATUS_RECONNECTING"),
            ("disconnected", "STATUS_DISCONNECTED"),
            ("error", "STATUS_ERROR"),
            ("unknown", "STATUS_DISCONNECTED"),
        ],
    )
    def test_mapping(self, status: str, expected: str) -> None:
        from hrm_live.ui.tokens import (
            STATUS_CONNECTED,
            STATUS_DISCONNECTED,
            STATUS_ERROR,
            STATUS_RECONNECTING,
        )

        wanted = {
            "STATUS_CONNECTED": STATUS_CONNECTED,
            "STATUS_DISCONNECTED": STATUS_DISCONNECTED,
            "STATUS_ERROR": STATUS_ERROR,
            "STATUS_RECONNECTING": STATUS_RECONNECTING,
        }[expected]
        popover = HRMPopover(AppState())
        assert popover._dot_colour(status) == wanted


class TestDeviceStatusText:
    def test_connected_with_name(self) -> None:
        snap = _snap(connection_status="connected", config={"device_name": "Polar"})
        assert HRMPopover(AppState())._device_status_text(snap) == "Connected — Polar"

    def test_connected_without_device(self) -> None:
        snap = _snap(connection_status="connected")
        assert HRMPopover(AppState())._device_status_text(snap) == "Connected"

    def test_connecting(self) -> None:
        snap = _snap(connection_status="connecting")
        assert HRMPopover(AppState())._device_status_text(snap) == "Connecting..."

    def test_reconnecting(self) -> None:
        snap = _snap(connection_status="reconnecting")
        assert HRMPopover(AppState())._device_status_text(snap) == "Reconnecting..."

    def test_error_with_message(self) -> None:
        snap = _snap(connection_status="error", connection_error="Bluetooth off")
        assert HRMPopover(AppState())._device_status_text(snap) == "Bluetooth off"

    def test_error_without_message(self) -> None:
        snap = _snap(connection_status="error")
        assert HRMPopover(AppState())._device_status_text(snap) == "Connection error"

    def test_disconnected_with_device(self) -> None:
        snap = _snap(connection_status="disconnected", config={"device_name": "Polar"})
        assert HRMPopover(AppState())._device_status_text(snap) == "Disconnected — Polar"

    def test_disconnected_without_device(self) -> None:
        snap = _snap(connection_status="disconnected")
        assert HRMPopover(AppState())._device_status_text(snap) == "Disconnected"


class TestConnectionTargetName:
    def test_device_name_wins(self) -> None:
        snap = _snap(config={"device_name": "Polar", "device_address": "AA:BB"})
        assert _connection_target_name(snap) == "Polar"

    def test_address_fallback(self) -> None:
        snap = _snap(config={"device_address": "AA:BB"})
        assert _connection_target_name(snap) == "AA:BB"

    def test_no_device(self) -> None:
        assert _connection_target_name(_snap()) == "the selected device"


class TestTrendSegment:
    def test_defaults_to_10_min(self) -> None:
        popover = HRMPopover(AppState())
        assert popover._trend_segment_for_minutes(None) == 1

    @pytest.mark.parametrize(
        ("minutes", "expected"),
        [(4, 0), (5, 0), (6, 1), (10, 1), (11, 2), (30, 2), (60, 2)],
    )
    def test_buckets(self, minutes: int, expected: int) -> None:
        popover = HRMPopover(AppState())
        assert popover._trend_segment_for_minutes({"graph_window_minutes": minutes}) == expected


class TestRect:
    def test_two_tuple_passthrough(self) -> None:
        assert _rect((10, 20)) == (10, 20)

    def test_four_tuple_expands(self) -> None:
        assert _rect((1, 2, 3, 4)) == ((1, 2), (3, 4))

    def test_other_passthrough(self) -> None:
        assert _rect("frame") == "frame"


class TestNsColor:
    def test_valid_hex(self) -> None:
        color = popover_ns_color("#FF0000")
        assert isinstance(color, NSColor)
        assert abs(color.redComponent() - 1.0) < 0.001
        assert color.greenComponent() < 0.001

    def test_invalid_hex_falls_back(self) -> None:
        color = popover_ns_color("not-a-color")
        assert isinstance(color, NSColor)


class TestSessionStatsString:
    def test_no_session_data(self) -> None:
        popover = HRMPopover(AppState())
        assert popover._session_stats_string(_snap()) == "No session data"

    def test_populated_session(self) -> None:
        popover = HRMPopover(AppState())
        snap = _snap(
            session_active=True,
            session_count=10,
            session_sum=1200,
            session_max=140,
            session_min=100,
            zone_times={"Z1": 3600.0, "Z2": 600.0},
        )
        assert popover._session_stats_string(snap) == (
            "Elapsed 01:10:00   Avg 120 bpm\nMax 140 bpm      Min 100 bpm"
        )


class _FakePopover:
    """Stand-in for NSPopover that reports itself as shown."""

    def isShown(self) -> bool:
        return True


class TestPopoverRefreshHeadless:
    def test_refresh_updates_persistent_views(self) -> None:
        state = AppState()
        state.update_connection(latest_bpm=72, connected=True, status="connected")
        state.set_config({"device_name": "Polar H10", "max_hr": 190})
        popover = HRMPopover(state)
        popover._build_view()
        popover._built = True
        popover._popover = _FakePopover()

        popover.refresh()

        assert popover._header_device_label is not None
        assert "Connected" in popover._header_device_label.stringValue()
        assert popover._session_stats_label is not None
        assert popover._session_stats_label.stringValue() == "No session data"
        assert popover._trend_buttons  # structural layout executed

    def test_refresh_disconnected_state(self) -> None:
        state = AppState()
        popover = HRMPopover(state)
        popover._build_view()
        popover._built = True
        popover._popover = _FakePopover()

        popover.refresh()

        assert popover._header_device_label is not None
        assert "Disconnected" in popover._header_device_label.stringValue()


# ── Settings: scan + connection status text ───────────────────────────────


def _settings_window() -> SettingsWindow:
    return SettingsWindow(AppState())


class TestScanButtonTitle:
    def test_scanning(self) -> None:
        w = _settings_window()
        w.state.update_scan(status="scanning")
        assert w._scan_button_title() == "Cancel Scan"

    @pytest.mark.parametrize("status", ["complete", "cancelled", "error"])
    def test_scan_again(self, status: str) -> None:
        w = _settings_window()
        w.state.update_scan(status=status)
        assert w._scan_button_title() == "Scan Again"

    def test_idle(self) -> None:
        assert _settings_window()._scan_button_title() == "Scan for HRMs"


class TestScanStatusText:
    def test_scanning_with_results(self) -> None:
        w = _settings_window()
        w.state.update_scan(status="scanning", results=(_device(), _device("DD:EE", "Garmin")))
        assert w._scan_status_text() == "Scanning... 2 found"

    def test_complete_empty(self) -> None:
        w = _settings_window()
        w.state.update_scan(status="complete")
        assert "No devices found" in w._scan_status_text()

    def test_complete_with_results(self) -> None:
        w = _settings_window()
        w.state.update_scan(status="complete", results=(_device(),))
        assert w._scan_status_text() == "1 devices found"

    def test_cancelled_empty(self) -> None:
        w = _settings_window()
        w.state.update_scan(status="cancelled")
        assert w._scan_status_text() == "Scan cancelled."

    def test_cancelled_with_results(self) -> None:
        w = _settings_window()
        w.state.update_scan(status="cancelled", results=(_device(),))
        assert w._scan_status_text() == "Scan cancelled. 1 devices found so far."

    def test_error(self) -> None:
        w = _settings_window()
        w.state.update_scan(status="error", error="CBCentralManager state invalid")
        assert w._scan_status_text() == "CBCentralManager state invalid"

    def test_idle(self) -> None:
        assert "Click Scan for HRMs" in _settings_window()._scan_status_text()


class TestConnectionStatusText:
    def test_connected(self) -> None:
        w = _settings_window()
        w.state.set_config({"device_name": "Polar H10"})
        w.state.update_connection(status="connected")
        assert w._connection_status_text() == "Connected to Polar H10"

    def test_connecting(self) -> None:
        w = _settings_window()
        w.state.set_config({"device_name": "Polar H10"})
        w.state.update_connection(status="connecting")
        assert w._connection_status_text() == "Connecting to Polar H10..."

    def test_reconnecting_with_error(self) -> None:
        w = _settings_window()
        w.state.update_connection(status="reconnecting", error="link lost")
        assert w._connection_status_text() == "Reconnecting... link lost"

    def test_reconnecting(self) -> None:
        w = _settings_window()
        w.state.set_config({"device_name": "Polar H10"})
        w.state.update_connection(status="reconnecting")
        assert w._connection_status_text() == "Reconnecting to Polar H10..."

    def test_error(self) -> None:
        w = _settings_window()
        w.state.update_connection(status="error", error="Bluetooth off")
        assert w._connection_status_text() == "Bluetooth off"

    def test_disconnected(self) -> None:
        assert _settings_window()._connection_status_text() == "Not connected"


class TestCurrentConnectionName:
    def test_device_name(self) -> None:
        w = _settings_window()
        w.state.set_config({"device_name": "Polar H10", "device_address": "AA:BB"})
        assert w._current_connection_name() == "Polar H10"

    def test_scan_name_for_address(self) -> None:
        w = _settings_window()
        w.state.set_config({"device_address": "AA:BB:CC"})
        w.state.update_scan(status="complete", results=(_device(),))
        assert w._current_connection_name() == "Polar H10"

    def test_address_only(self) -> None:
        w = _settings_window()
        w.state.set_config({"device_address": "AA:BB"})
        assert w._current_connection_name() == "AA:BB"

    def test_nothing(self) -> None:
        assert _settings_window()._current_connection_name() == "—"


# ── Settings: collect/validate + helpers ──────────────────────────────────


class TestCollectValues:
    def test_full_mapping(self) -> None:
        NSApplication.sharedApplication()
        w = _settings_window()
        w._build_panel()
        c = w._controls
        c["device_address"].setStringValue_("aa:bb:cc:dd:ee:ff")
        c["device_name"].setStringValue_("Polar H10")
        c["max_hr"].setStringValue_("185")
        c["zone_z1_max"].setStringValue_("50")
        c["zone_z2_max"].setStringValue_("75")
        c["zone_z3_max"].setStringValue_("90")
        for zone in ("Z1", "Z2", "Z3", "Z4"):
            c[f"color_{zone}"].setStringValue_("#112233")
        c["graph_window"].setSelectedSegment_(2)

        values = w._collect_values()

        assert values["device_address"] == "aa:bb:cc:dd:ee:ff"
        assert values["device_name"] == "Polar H10"
        assert values["max_hr"] == 185
        assert values["zones"] == {"z1_max": 0.5, "z2_max": 0.75, "z3_max": 0.9}
        assert values["zone_colors"] == {
            "Z1": "#112233",
            "Z2": "#112233",
            "Z3": "#112233",
            "Z4": "#112233",
        }
        assert values["graph_window_minutes"] == 30

    def test_device_name_derived_from_scan(self) -> None:
        NSApplication.sharedApplication()
        w = _settings_window()
        w.state.update_scan(status="complete", results=(_device(),))
        w._build_panel()
        c = w._controls
        c["device_address"].setStringValue_("AA:BB:CC")
        c["device_name"].setStringValue_("")

        values = w._collect_values()

        assert values["device_name"] == "Polar H10"

    @pytest.mark.parametrize(
        "field",
        ["max_hr", "zone_z1_max", "zone_z2_max", "zone_z3_max"],
    )
    def test_invalid_numeric_field(self, field: str) -> None:
        NSApplication.sharedApplication()
        w = _settings_window()
        w._build_panel()
        w._controls[field].setStringValue_("not-a-number")

        with pytest.raises(ValueError):
            w._collect_values()

    def test_invalid_hex(self) -> None:
        NSApplication.sharedApplication()
        w = _settings_window()
        w._build_panel()
        w._controls["color_Z1"].setStringValue_("nope")

        with pytest.raises(ValueError, match="hex string"):
            w._collect_values()

    def test_unordered_boundaries_rejected(self) -> None:
        NSApplication.sharedApplication()
        w = _settings_window()
        w._build_panel()
        w._controls["zone_z1_max"].setStringValue_("90")
        w._controls["zone_z2_max"].setStringValue_("50")

        with pytest.raises(ValueError, match="z1_max"):
            w._collect_values()


class TestNsColorToHex:
    def test_calibrated_color_round_trip(self) -> None:
        w = _settings_window()
        color = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.5, 0.25, 1.0)
        assert w._ns_color_to_hex(color) == "#FF7F3F"

    def test_returns_hex_format(self) -> None:
        import re

        w = _settings_window()
        color = NSColor.colorWithRed_green_blue_alpha_(1.0, 0.5, 0.25, 1.0)
        assert re.fullmatch(r"#[0-9A-F]{6}", w._ns_color_to_hex(color))


class TestSettingsNsColor:
    def test_valid_hex(self) -> None:
        assert isinstance(settings_ns_color("#34C759"), NSColor)

    def test_invalid_hex_falls_back(self) -> None:
        assert isinstance(settings_ns_color("bad"), NSColor)


class TestScanResultLabel:
    def test_hr_capable_with_rssi(self) -> None:
        assert _scan_result_label(_device()) == "♥ Polar H10 (-50 dBm)"

    def test_hr_capable_without_rssi(self) -> None:
        assert _scan_result_label(_device(rssi=None)) == "♥ Polar H10"

    def test_non_hr_device(self) -> None:
        device = DiscoveredDevice("AA:BB", "Keyboard", -60, heart_rate_capable=False)
        assert _scan_result_label(device) == "Keyboard (-60 dBm)"

    def test_unnamed_hr_device(self) -> None:
        device = DiscoveredDevice("AA:BB", "", None, heart_rate_capable=True)
        assert _scan_result_label(device) == "♥ Unnamed HR device"

    def test_unnamed_ble_device(self) -> None:
        device = DiscoveredDevice("AA:BB", "", None, heart_rate_capable=False)
        assert _scan_result_label(device) == "Unnamed BLE device"


class TestIsValidHex:
    def test_lowercase_valid(self) -> None:
        assert _is_valid_hex("#aAbBcC") is True

    def test_rejects_short_and_long(self) -> None:
        assert _is_valid_hex("#FFF") is False
        assert _is_valid_hex("#FFFFFFFF") is False

    def test_rejects_bad_characters(self) -> None:
        assert _is_valid_hex("#GGGGGG") is False


# ── Menu bar: zone decision logic ─────────────────────────────────────────


class TestCurrentZone:
    def test_no_bpm_is_z1(self) -> None:
        app = HRMBarApp(AppState())
        assert app._current_zone(None, None) == "Z1"

    def test_default_bounds(self) -> None:
        app = HRMBarApp(AppState())
        assert app._current_zone(72, None) == "Z1"
        assert app._current_zone(190, None) == "Z4"

    def test_custom_bounds(self) -> None:
        app = HRMBarApp(AppState())
        cfg = {"max_hr": 200, "zones": {"z1_max": 0.5, "z2_max": 0.7, "z3_max": 0.9}}
        assert app._current_zone(100, cfg) == "Z2"
        assert app._current_zone(145, cfg) == "Z3"
        assert app._current_zone(190, cfg) == "Z4"


# ── Composition root ──────────────────────────────────────────────────────


def test_shutdown_app_noop_without_instance() -> None:
    assert _shutdown_app() is None


def test_setup_logging_levels(monkeypatch: pytest.MonkeyPatch) -> None:
    root = logging.getLogger()
    try:
        monkeypatch.delenv("HRM_LIVE_LOG_LEVEL", raising=False)
        root.handlers.clear()
        _setup_logging()
        assert root.level == logging.INFO

        monkeypatch.setenv("HRM_LIVE_LOG_LEVEL", "DEBUG")
        root.handlers.clear()
        _setup_logging()
        assert root.level == logging.DEBUG

        monkeypatch.setenv("HRM_LIVE_LOG_LEVEL", "NOT-A-LEVEL")
        root.handlers.clear()
        _setup_logging()
        assert root.level == logging.INFO
    finally:
        root.handlers.clear()
