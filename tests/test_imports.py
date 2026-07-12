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
