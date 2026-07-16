"""Smoke tests: verify modules import without side effects.

No BLE, UI, config, or file I/O should happen at import time.
"""

import pytest


def test_import_state() -> None:
    """State module imports cleanly."""
    import hrm_live.state as state

    # Verify no side effects — instantiate dataclass
    s = state.AppState()
    assert s.latest_bpm is None
    assert s.connected is False
    assert s.connection_status == "disconnected"
    assert s.scan_status == "idle"
    assert len(s.ring_buffer) == 0


def test_import_zones() -> None:
    """Zones module imports cleanly."""
    import hrm_live.zones as zones

    assert zones.zone_label("Z1") == "Recovery"


def test_import_config() -> None:
    """Config module imports without loading files."""
    import hrm_live.config as config

    # Ensure no file I/O happens at import; load is explicit
    assert hasattr(config, "load_config")


def test_import_session() -> None:
    """Session module imports cleanly."""
    import hrm_live.session as session

    assert session.suggested_csv_filename().endswith(".csv")


def test_import_ble_no_bluetooth() -> None:
    """BLE module imports without Bluetooth hardware."""
    import hrm_live.ble as ble

    assert ble.HEART_RATE_UUID == "00002a37-0000-1000-8000-00805f9b34fb"


def test_import_ui_package() -> None:
    """UI package imports cleanly."""
    import hrm_live.ui as ui

    assert ui.__doc__


def test_import_menubar() -> None:
    """Menubar module may require macOS; skip if not available."""
    try:
        import hrm_live.ui.menubar as menubar
    except (ImportError, RuntimeError) as exc:
        pytest.skip(f"ui.menubar import failed (expected on non-macOS): {exc}")
    assert menubar.DISCONNECTED_TITLE


def test_import_popover() -> None:
    """Popover module imports cleanly."""
    import hrm_live.ui.popover as popover

    assert popover.POPOVER_WIDTH > 0


def test_dark_button_title_helper_sets_accessible_white_titles() -> None:
    """Popover helper keeps dark buttons readable."""
    from AppKit import NSForegroundColorAttributeName

    from hrm_live.ui.popover import _set_dark_button_title

    class FakeButton:
        def __init__(self) -> None:
            self.title_value = ""
            self.accessibility_value = ""
            self.attributed = None

        def setTitle_(self, value: str) -> None:
            self.title_value = value

        def setAttributedTitle_(self, value) -> None:
            self.attributed = value

        def setAccessibilityLabel_(self, value: str) -> None:
            self.accessibility_value = value

    button = FakeButton()
    _set_dark_button_title(button, "⚙ Settings")

    assert button.title_value == "⚙ Settings"
    assert button.accessibility_value == "⚙ Settings"
    attributed = button.attributed
    assert attributed.string() == "⚙ Settings"
    color = attributed.attributesAtIndex_effectiveRange_(0, None)[0].get(
        NSForegroundColorAttributeName
    )
    assert color is not None


def test_popover_view_builds_without_appkit_abort() -> None:
    """Headless popover content avoids controls that require NSApplication."""
    from hrm_live.state import AppState
    from hrm_live.ui.popover import HRMPopover

    popover = HRMPopover(AppState())
    view = popover._build_view()

    assert view is not None
    assert len(view.subviews()) > 0


def test_popover_duration_formats_clamped_zone_seconds() -> None:
    """Dashboard duration uses accumulated zone seconds, not wall time."""
    from hrm_live.ui.popover import _format_td_seconds

    assert _format_td_seconds(8.9) == "00:00:08"
    assert _format_td_seconds(3661) == "01:01:01"


def test_popover_export_feedback_shows_error_with_retry() -> None:
    """A failed export keeps retry available and surfaces a readable error."""
    from datetime import UTC, datetime

    from hrm_live.state import AppState
    from hrm_live.ui.popover import _export_feedback

    state = AppState()
    state.start_session(datetime(2026, 7, 15, tzinfo=UTC))
    state.record_bpm(datetime(2026, 7, 15, 0, 0, 1, tzinfo=UTC), 120)
    assert state.finalize_session() is not None
    state.mark_export_failure("disk full")

    assert _export_feedback(state.snapshot_for_ui()) == (
        True,
        "Save failed: disk full",
        True,
    )


def test_save_panel_failure_keeps_export_retryable() -> None:
    """A native save-panel failure cannot escape the AppKit action callback."""
    from datetime import UTC, datetime

    from hrm_live.state import AppState
    from hrm_live.ui.popover import HRMPopover, _export_feedback

    state = AppState()
    state.start_session(datetime(2026, 7, 15, tzinfo=UTC))
    state.record_bpm(datetime(2026, 7, 15, 0, 0, 1, tzinfo=UTC), 120)
    snapshot = state.finalize_session()
    assert snapshot is not None

    def unavailable_panel(_default_name: str) -> str | None:
        raise RuntimeError("NSApplication unavailable")

    HRMPopover(state, save_panel_factory=unavailable_panel)._save_snapshot(snapshot)

    assert state.pending_export_snapshot() is snapshot
    assert _export_feedback(state.snapshot_for_ui()) == (
        True,
        "Save failed: Could not open the save dialog. Try again.",
        True,
    )


def test_export_os_error_hides_selected_path_from_feedback(tmp_path) -> None:
    """Raw filesystem errors stay in logs rather than the user-visible dashboard."""
    from datetime import UTC, datetime
    from unittest.mock import patch

    from hrm_live.state import AppState
    from hrm_live.ui.popover import HRMPopover, _export_feedback

    state = AppState()
    state.start_session(datetime(2026, 7, 15, tzinfo=UTC))
    state.record_bpm(datetime(2026, 7, 15, 0, 0, 1, tzinfo=UTC), 120)
    snapshot = state.finalize_session()
    assert snapshot is not None

    selected_path = tmp_path / "private-workout.csv"
    popover = HRMPopover(state, save_panel_factory=lambda _default_name: str(selected_path))
    with patch(
        "hrm_live.ui.popover.sess_mod.export_session_csv",
        side_effect=OSError(f"Permission denied: {selected_path}"),
    ):
        popover._save_snapshot(snapshot)

    show_retry, message, is_error = _export_feedback(state.snapshot_for_ui())
    assert (show_retry, message, is_error) == (
        True,
        "Save failed: Could not write the CSV. Check the destination and try again.",
        True,
    )
    assert str(selected_path) not in message


def test_status_item_is_configured_only_after_rumps_creates_it() -> None:
    """Dashboard-first wiring clears rumps' menu after status-bar setup."""
    from hrm_live.ui.menubar import HRMBarApp, _StatusButtonTarget

    class FakeButton:
        def __init__(self) -> None:
            self.target = None
            self.action = None

        def setTarget_(self, target) -> None:
            self.target = target

        def setAction_(self, action: str) -> None:
            self.action = action

    class FakeStatusItem:
        def __init__(self) -> None:
            self.button_value = FakeButton()
            self.menu = object()

        def button(self) -> FakeButton:
            return self.button_value

        def setMenu_(self, menu) -> None:
            self.menu = menu

    app = object.__new__(HRMBarApp)
    app._status_item_configured = False
    app._status_button_target = None
    status_item = FakeStatusItem()
    app._nsapp = type("FakeNSApp", (), {"nsstatusitem": status_item})()

    assert app._configure_status_item() is True
    assert status_item.menu is None
    assert isinstance(status_item.button_value.target, _StatusButtonTarget)
    assert status_item.button_value.action == "statusButtonClicked:"
    assert app._configure_status_item() is True


def test_status_button_target_forwards_to_dashboard() -> None:
    """The retained NSObject bridge forwards AppKit's click selector."""
    from hrm_live.ui.menubar import _StatusButtonTarget

    calls: list[object] = []
    app = type("FakeApp", (), {"_open_popover": lambda _self, sender: calls.append(sender)})()
    target = _StatusButtonTarget.alloc().initWithApp_(app)
    sender = object()

    target.statusButtonClicked_(sender)

    assert calls == [sender]


def test_settings_panel_headless_guard() -> None:
    """Settings panel fails safely instead of aborting without NSApplication."""
    from hrm_live.state import AppState
    from hrm_live.ui.settings import SettingsWindow

    with pytest.raises(RuntimeError, match="NSApplication"):
        SettingsWindow(AppState())._build_panel()


def test_settings_scan_callbacks_use_injected_functions() -> None:
    """Settings actions delegate scan work to injected callbacks."""
    from hrm_live.state import AppState, DiscoveredDevice
    from hrm_live.ui.settings import SettingsWindow

    calls: list[str] = []

    class FakeField:
        def __init__(self, value: str = "") -> None:
            self._value = value
            self.title = value
            self.enabled = True
            self._selected_segment = 1

        def setStringValue_(self, value: str) -> None:
            self._value = value

        def setTitle_(self, value: str) -> None:
            self.title = value
            self._value = value

        def stringValue(self) -> str:
            return self._value

        def setEnabled_(self, value: bool) -> None:
            self.enabled = value

        def setSelectedSegment_(self, index: int) -> None:
            self._selected_segment = index

        def selectedSegment(self) -> int:
            return self._selected_segment

    class FakePopupItem:
        def __init__(self, title: str) -> None:
            self.title = title
            self.represented = None

        def setRepresentedObject_(self, value) -> None:
            self.represented = value

    class FakePopup:
        def __init__(self) -> None:
            self.items: list[FakePopupItem] = []
            self.selected = -1
            self.enabled = True

        def removeAllItems(self) -> None:
            self.items.clear()

        def addItemWithTitle_(self, title: str) -> None:
            self.items.append(FakePopupItem(title))

        def numberOfItems(self) -> int:
            return len(self.items)

        def itemAtIndex_(self, index: int) -> FakePopupItem:
            return self.items[index]

        def setEnabled_(self, value: bool) -> None:
            self.enabled = value

        def selectItemAtIndex_(self, index: int) -> None:
            self.selected = index

        def indexOfSelectedItem(self) -> int:
            return self.selected

    state = AppState()
    state.scan_status = "scanning"
    state.scan_results = (DiscoveredDevice("ADDR-1", "Polar H10", -48, True),)
    window = SettingsWindow(
        state,
        on_scan=lambda: calls.append("scan"),
        on_cancel_scan=lambda: calls.append("cancel"),
    )
    window._controls = {
        "scan_button": FakeField(),
        "scan_status": FakeField(),
        "scan_results": FakePopup(),
        "use_selected": FakeField(),
        "device_address": FakeField(),
        "device_name": FakeField(),
        "max_hr": FakeField("190"),
        "zone_z1_max": FakeField("60"),
        "zone_z2_max": FakeField("75"),
        "zone_z3_max": FakeField("88"),
        "graph_window": FakeField("10"),
        "color_Z1": FakeField("#888888"),
        "color_Z2": FakeField("#4CAF50"),
        "color_Z3": FakeField("#FF9800"),
        "color_Z4": FakeField("#F44336"),
    }
    window._panel = type("Panel", (), {"isVisible": lambda self: True})()

    window.scan_action_(None)
    assert calls == ["cancel"]

    state.scan_status = "idle"
    window.scan_action_(None)
    assert calls == ["cancel", "scan"]

    state.scan_status = "complete"
    window.refresh_from_state(force=True)
    popup = window._controls["scan_results"]
    assert popup.enabled is True
    assert popup.selected == 0
    assert popup.items[0].title.startswith("♥ Polar H10")

    window.use_selected_(None)
    assert window._controls["device_address"].stringValue() == "ADDR-1"
    assert window._controls["device_name"].stringValue() == "Polar H10"


def test_import_graph() -> None:
    """Graph module imports cleanly (requires matplotlib)."""
    import hrm_live.ui.graph as graph

    assert graph.render_graph


def test_import_settings() -> None:
    """Settings module imports cleanly."""
    import hrm_live.ui.settings as settings

    assert settings.PANEL_WIDTH > 0


def test_compile_all() -> None:
    """All Python files in the project compile without errors."""
    import os
    import py_compile

    errors = []
    for root, dirs, files in os.walk("."):
        # Skip hidden dirs and venvs
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                try:
                    py_compile.compile(path, doraise=True)
                except py_compile.PyCompileError as exc:
                    errors.append(str(exc))
    assert not errors, "Compilation errors:\n" + "\n".join(errors)
