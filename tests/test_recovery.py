"""Tests for Settings recovery-button wiring.

No real workspace, no modal, no BLE: the opener is injected and the
retry callbacks are plain Python.
"""

from __future__ import annotations

from hrm_live.state import AppState
from hrm_live.ui.guidance import OPEN_BLUETOOTH_URI, OPEN_PRIVACY_URI, RecoveryAction
from hrm_live.ui.settings import SettingsWindow


class _FakeButton:
    def __init__(self) -> None:
        self.hidden = True
        self.title = ""
        self.enabled = False
        self.tag_value = 0

    def setHidden_(self, value: bool) -> None:
        self.hidden = value

    def setTitle_(self, value: str) -> None:
        self.title = value

    def setEnabled_(self, value: bool) -> None:
        self.enabled = value

    def setTag_(self, value: int) -> None:
        self.tag_value = value

    def tag(self) -> int:
        return self.tag_value


def test_recovery_button_hidden_without_action() -> None:
    window = SettingsWindow(AppState())
    window._controls["scan_recovery_button"] = _FakeButton()
    window._sync_recovery_button("scan")
    assert window._controls["scan_recovery_button"].hidden is True


def test_scan_permission_button_calls_injected_opener() -> None:
    opened: list[str] = []
    window = SettingsWindow(AppState(), open_system_settings=opened.append)
    window._controls["scan_recovery_button"] = _FakeButton()
    window.state.update_scan(
        status="error",
        error="denied",
        recovery=RecoveryAction.OPEN_PRIVACY.value,
    )
    window._sync_recovery_button("scan")
    button = window._controls["scan_recovery_button"]
    assert button.hidden is False
    assert "Privacy" in button.title
    window.recovery_action_(button)
    assert opened == [OPEN_PRIVACY_URI]


def test_connection_powered_off_button_opens_bluetooth_settings() -> None:
    opened: list[str] = []
    window = SettingsWindow(AppState(), open_system_settings=opened.append)
    window._controls["connection_recovery_button"] = _FakeButton()
    window.state.update_connection(
        status="error",
        error="off",
        recovery=RecoveryAction.OPEN_BLUETOOTH.value,
    )
    window._sync_recovery_button("connection")
    button = window._controls["connection_recovery_button"]
    assert button.hidden is False
    assert "Bluetooth" in button.title
    button.tag_value = 1
    window.recovery_action_(button)
    assert opened == [OPEN_BLUETOOTH_URI]


def test_scan_retry_routes_to_on_scan() -> None:
    scanned: list[str] = []
    window = SettingsWindow(AppState(), on_scan=lambda: scanned.append("scan"))
    window._controls["scan_recovery_button"] = _FakeButton()
    window.state.update_scan(
        status="error",
        error="timeout",
        recovery=RecoveryAction.RETRY.value,
    )
    window._sync_recovery_button("scan")
    window.recovery_action_(window._controls["scan_recovery_button"])
    assert scanned == ["scan"]


def test_connection_retry_routes_to_on_retry() -> None:
    retried: list[str] = []
    window = SettingsWindow(AppState(), on_retry=lambda: retried.append("retry"))
    window._controls["connection_recovery_button"] = _FakeButton()
    window.state.update_connection(
        status="error",
        error="lost",
        recovery=RecoveryAction.RETRY.value,
    )
    window._sync_recovery_button("connection")
    button = window._controls["connection_recovery_button"]
    button.tag_value = 1
    window.recovery_action_(button)
    assert retried == ["retry"]


def test_snapshot_carries_recovery_actions() -> None:
    state = AppState()
    state.update_scan(status="error", error="m", recovery="open_privacy")
    state.update_connection(status="error", error="m", recovery="retry")
    snapshot = state.snapshot_for_ui()
    assert snapshot.scan_recovery == "open_privacy"
    assert snapshot.connection_recovery == "retry"
    # Defaults are "none" and survive normal transitions
    state.update_scan(status="complete", error=None)
    state.update_connection(status="connected", error=None)
    fresh = state.snapshot_for_ui()
    assert fresh.scan_recovery == "open_privacy"
    assert fresh.connection_recovery == "retry"
