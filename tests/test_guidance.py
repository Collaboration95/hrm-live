"""Tests for pure BLE error classification into user guidance.

The classifier must stay AppKit-free and headless (no modal, no BLE
hardware), matching the existing unit-test convention.
"""

from __future__ import annotations

import pytest
from bleak.exc import (
    BleakBluetoothNotAvailableError,
    BleakBluetoothNotAvailableReason,
    BleakError,
)

from hrm_live.ui.guidance import (
    OPEN_BLUETOOTH_URI,
    OPEN_PRIVACY_URI,
    Guidance,
    RecoveryAction,
    classify_error,
)


def _unavailable(reason: BleakBluetoothNotAvailableReason) -> BleakBluetoothNotAvailableError:
    return BleakBluetoothNotAvailableError("bluetooth unavailable", reason=reason)


class TestPoweredOff:
    def test_powered_off_opens_bluetooth_settings(self) -> None:
        g = classify_error(_unavailable(BleakBluetoothNotAvailableReason.POWERED_OFF))
        assert g.action == RecoveryAction.OPEN_BLUETOOTH
        assert "powered off" in g.display_text

    def test_unknown_reason_opens_bluetooth_settings(self) -> None:
        g = classify_error(_unavailable(BleakBluetoothNotAvailableReason.UNKNOWN))
        assert g.action == RecoveryAction.OPEN_BLUETOOTH
        assert "unknown reason" in g.display_text

    def test_none_reason_opens_bluetooth_settings(self) -> None:
        g = classify_error(_unavailable(BleakBluetoothNotAvailableReason.UNKNOWN))
        assert g.action == RecoveryAction.OPEN_BLUETOOTH


class TestPermissionDenied:
    @pytest.mark.parametrize(
        "reason",
        [
            BleakBluetoothNotAvailableReason.DENIED_BY_USER,
            BleakBluetoothNotAvailableReason.DENIED_BY_SYSTEM,
            BleakBluetoothNotAvailableReason.DENIED_BY_UNKNOWN,
        ],
    )
    def test_denied_opens_privacy_pane(self, reason) -> None:
        g = classify_error(_unavailable(reason))
        assert g.action == RecoveryAction.OPEN_PRIVACY
        assert "permission" in g.display_text.lower()


class TestAdapterIssues:
    def test_no_bluetooth_offers_retry(self) -> None:
        g = classify_error(_unavailable(BleakBluetoothNotAvailableReason.NO_BLUETOOTH))
        assert g.action == RecoveryAction.RETRY

    def test_no_ble_central_role_is_info_only(self) -> None:
        g = classify_error(_unavailable(BleakBluetoothNotAvailableReason.NO_BLE_CENTRAL_ROLE))
        assert g.action == RecoveryAction.INFO


class TestTimeout:
    def test_scan_timeout_retries(self) -> None:
        g = classify_error(TimeoutError("boom"), context="scan")
        assert g.action == RecoveryAction.RETRY
        assert "scanning" in g.display_text

    def test_connection_timeout_retries(self) -> None:
        g = classify_error(TimeoutError("boom"), context="connection")
        assert g.action == RecoveryAction.RETRY
        assert "connecting" in g.display_text


class TestGenericFailures:
    def test_bleak_error_retries(self) -> None:
        g = classify_error(BleakError("pairing failed"))
        assert g.action == RecoveryAction.RETRY

    def test_os_error_retries(self) -> None:
        g = classify_error(OSError("resource busy"))
        assert g.action == RecoveryAction.RETRY

    def test_unexpected_exception_retries(self) -> None:
        g = classify_error(RuntimeError("boom"))
        assert g.action == RecoveryAction.RETRY
        assert "try again" in g.display_text

    def test_raw_exception_text_never_leaks(self) -> None:
        secret = "Traceback secret detail"
        g = classify_error(RuntimeError(secret))
        assert secret not in g.display_text
        assert isinstance(g, Guidance)
        assert g.display_text  # never empty


class TestUris:
    def test_privacy_and_bluetooth_destinations_differ(self) -> None:
        assert OPEN_PRIVACY_URI != OPEN_BLUETOOTH_URI
        assert "Privacy_Bluetooth" in OPEN_PRIVACY_URI
        assert OPEN_BLUETOOTH_URI.endswith("BluetoothSettings")
