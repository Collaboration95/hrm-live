"""Error classification into user-facing guidance.

Pure logic only — no AppKit imports — so it is fully unit-testable on a
headless runner (matching the existing test convention).

The BLE background loop catches a few exception classes; this module maps
each one to a friendly display string *and* a ``RecoveryAction`` that the UI
uses to show a single contextual button (open a settings pane, retry, or
nothing). Raw exception text never reaches the user; it is logged separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from bleak.exc import (
    BleakBluetoothNotAvailableError,
    BleakBluetoothNotAvailableReason,
    BleakError,
)

# macOS System Settings destination URIs (verified).
#  * Privacy & Security -> Bluetooth fixes the *permission* denial.
#  * Bluetooth toggle pane fixes the *powered-off* case.
OPEN_PRIVACY_URI = "x-apple.systempreferences:com.apple.preference.security?Privacy_Bluetooth"
OPEN_BLUETOOTH_URI = "x-apple.systempreferences:com.apple.BluetoothSettings"


class RecoveryAction(StrEnum):
    """Machine-readable recovery affordance for a guidance message."""

    OPEN_PRIVACY = "open_privacy"
    OPEN_BLUETOOTH = "open_bluetooth"
    RETRY = "retry"
    INFO = "info"  # informational only — show no button
    NONE = "none"


@dataclass(frozen=True)
class Guidance:
    """A classified, user-safe message plus a recovery action."""

    display_text: str
    action: RecoveryAction


_SCAN_VERB = "scanning"
_CONNECTION_VERB = "connecting"


def _guidance_for_reason(reason: BleakBluetoothNotAvailableReason | None, _verb: str) -> Guidance:
    """Map a ``BleakBluetoothNotAvailableReason`` to guidance."""

    if reason is None:
        return Guidance(
            "Bluetooth is unavailable. Check that it is on and try again.",
            RecoveryAction.OPEN_BLUETOOTH,
        )
    if reason == BleakBluetoothNotAvailableReason.POWERED_OFF:
        return Guidance(
            "Bluetooth is powered off. Turn it on to use HRM Live.",
            RecoveryAction.OPEN_BLUETOOTH,
        )
    if reason in {
        BleakBluetoothNotAvailableReason.DENIED_BY_USER,
        BleakBluetoothNotAvailableReason.DENIED_BY_SYSTEM,
        BleakBluetoothNotAvailableReason.DENIED_BY_UNKNOWN,
    }:
        return Guidance(
            "Bluetooth permission is denied. Allow HRM Live in System Settings "
            "\u2192 Privacy & Security \u2192 Bluetooth.",
            RecoveryAction.OPEN_PRIVACY,
        )
    if reason == BleakBluetoothNotAvailableReason.NO_BLUETOOTH:
        return Guidance(
            "No Bluetooth adapter detected on this Mac.",
            RecoveryAction.RETRY,
        )
    if reason == BleakBluetoothNotAvailableReason.NO_BLE_CENTRAL_ROLE:
        return Guidance(
            "This Mac can't act as a Bluetooth LE central.",
            RecoveryAction.INFO,
        )
    # reason == UNKNOWN (and any future opaque value).
    return Guidance(
        "Bluetooth is unavailable for an unknown reason.",
        RecoveryAction.OPEN_BLUETOOTH,
    )


def classify_error(exc: Exception, *, context: str = "scan") -> Guidance:
    """Classify a BLE exception into user-facing guidance.

    ``context`` is ``"scan"`` or ``"connection"`` and only affects the wording
    for timeouts / generic errors. The raw exception must be logged separately
    by the caller; it is never embedded in ``display_text``.
    """
    verb = _SCAN_VERB if context == "scan" else _CONNECTION_VERB

    if isinstance(exc, BleakBluetoothNotAvailableError):
        return _guidance_for_reason(exc.reason, verb)
    if isinstance(exc, TimeoutError):
        return Guidance(
            f"Timed out {verb}. The strap may be asleep or out of range.",
            RecoveryAction.RETRY,
        )
    if isinstance(exc, (BleakError, OSError)):
        return Guidance(
            f"Bluetooth error while {verb}. Please try again.",
            RecoveryAction.RETRY,
        )
    # Unexpected fallback — caller should log the exception for triage.
    return Guidance(
        "Something unexpected went wrong. Please try again.",
        RecoveryAction.RETRY,
    )
