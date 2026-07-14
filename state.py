"""Shared application state dataclass.

This module defines AppState, the single shared state object used for
communication between the BLE background thread and the main UI thread.
No AppKit, rumps, or bleak imports happen at module level.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class DiscoveredDevice:
    """Immutable BLE scan result published to the UI."""

    address: str
    name: str
    rssi: int | None
    heart_rate_capable: bool


@dataclass
class AppState:
    """Thread-safe* shared state for the HRM app.

    *Safe under the assumption of one writer (BLE thread) and one reader
    (main thread / rumps Timer). No locks are used because partial reads
    are non-critical — the UI may briefly show stale data, which is
    acceptable for this use case.
    """

    # Latest heart rate
    latest_bpm: int | None = None

    # Whether a BLE connection is currently established
    connected: bool = False

    # Connection lifecycle and errors exposed to the UI
    connection_status: str = "disconnected"
    connection_error: str | None = None

    # Scan lifecycle and results exposed to the UI
    scan_status: str = "idle"
    scan_results: tuple[DiscoveredDevice, ...] = ()
    scan_error: str | None = None
    scan_generation: int = 0

    # Ring buffer of (timestamp, bpm) samples, max 600 = 10 min @ 1 Hz
    ring_buffer: deque = field(
        default_factory=lambda: deque(maxlen=600)
    )

    # Session management
    session_active: bool = False
    session_start: datetime | None = None
    session_data: list[tuple[datetime, int]] = field(default_factory=list)

    # Session running stats
    session_max: int = 0
    session_min: int = 999
    session_sum: int = 0
    session_count: int = 0

    # Per-zone accumulated time in seconds
    zone_times: dict[str, int] = field(
        default_factory=lambda: {"Z1": 0, "Z2": 0, "Z3": 0, "Z4": 0}
    )

    # Last CSV path written (None if never saved)
    last_csv_path: str | None = None

    # Last CSV export error, retained for the UI after a failed save
    last_csv_error: str | None = None

    # Current config snapshot (updated when settings are saved)
    config: dict | None = None
