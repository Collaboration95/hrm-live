"""Smoke tests: verify modules import without side effects.

No BLE, UI, config, or file I/O should happen at import time.
"""

import pytest


def test_import_state() -> None:
    """State module imports cleanly."""
    import state
    # Verify no side effects — instantiate dataclass
    s = state.AppState()
    assert s.latest_bpm is None
    assert s.connected is False
    assert s.connection_status == "disconnected"
    assert s.scan_status == "idle"
    assert len(s.ring_buffer) == 0


def test_import_zones() -> None:
    """Zones module imports cleanly."""
    import zones


def test_import_config() -> None:
    """Config module imports without loading files."""
    import config
    # Ensure no file I/O happens at import; load is explicit
    assert hasattr(config, "load_config")


def test_import_session() -> None:
    """Session module imports cleanly."""
    import session


def test_import_ble_no_bluetooth() -> None:
    """BLE module imports without Bluetooth hardware."""
    import ble
    assert ble.HEART_RATE_UUID == "00002a37-0000-1000-8000-00805f9b34fb"


def test_import_ui_package() -> None:
    """UI package imports cleanly."""
    import ui


def test_import_menubar() -> None:
    """Menubar module may require macOS; skip if not available."""
    try:
        import ui.menubar
    except (ImportError, RuntimeError) as exc:
        pytest.skip(f"ui.menubar import failed (expected on non-macOS): {exc}")


def test_import_popover() -> None:
    """Popover module imports cleanly."""
    import ui.popover


def test_dark_button_title_helper_sets_accessible_white_titles() -> None:
    """Popover helper keeps dark buttons readable."""
    from AppKit import NSForegroundColorAttributeName
    from ui.popover import _set_dark_button_title

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
    from state import AppState
    from ui.popover import HRMPopover

    popover = HRMPopover(AppState())
    view = popover._build_view()

    assert view is not None
    assert len(view.subviews()) > 0


def test_settings_panel_headless_guard() -> None:
    """Settings panel fails safely instead of aborting without NSApplication."""
    from state import AppState
    from ui.settings import SettingsWindow

    with pytest.raises(RuntimeError, match="NSApplication"):
        SettingsWindow(AppState())._build_panel()


def test_settings_scan_callbacks_use_injected_functions() -> None:
    """Settings actions delegate scan work to injected callbacks."""
    from state import AppState, DiscoveredDevice
    from ui.settings import SettingsWindow

    calls: list[str] = []

    class FakeField:
        def __init__(self, value: str = "") -> None:
            self._value = value
            self.title = value
            self.enabled = True

        def setStringValue_(self, value: str) -> None:
            self._value = value

        def setTitle_(self, value: str) -> None:
            self.title = value

        def stringValue(self) -> str:
            return self._value

        def setEnabled_(self, value: bool) -> None:
            self.enabled = value

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
    state.scan_results = (
        DiscoveredDevice("ADDR-1", "Polar H10", -48, True),
    )
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
    import ui.graph


def test_import_settings() -> None:
    """Settings module imports cleanly."""
    import ui.settings


def test_compile_all() -> None:
    """All Python files in the project compile without errors."""
    import py_compile
    import os
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
    assert not errors, f"Compilation errors:\n" + "\n".join(errors)
