"""Thread-safe state and immutable snapshots for HRM Live.

The BLE asyncio thread is the primary producer and the AppKit main thread is
the primary consumer.  AppState therefore owns a small RLock-protected API so
UI rendering and CSV export copy data under the lock, then perform slow work
after the lock is released.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import Any

from hrm_live.zones import get_zone

ZONE_ZERO: dict[str, float] = {"Z1": 0.0, "Z2": 0.0, "Z3": 0.0, "Z4": 0.0}
MAX_SESSION_GAP_SECONDS = 5.0


@dataclass(frozen=True)
class DiscoveredDevice:
    """Immutable BLE scan result published to the UI."""

    address: str
    name: str
    rssi: int | None
    heart_rate_capable: bool


@dataclass(frozen=True)
class SessionSample:
    """A single session row with the zone captured at receipt time."""

    timestamp: datetime
    bpm: int
    zone: str


@dataclass(frozen=True)
class UISnapshot:
    """Stable copy of all state needed by the UI refresh loop."""

    latest_bpm: int | None
    connected: bool
    connection_status: str
    connection_error: str | None
    scan_status: str
    scan_results: tuple[DiscoveredDevice, ...]
    scan_error: str | None
    scan_generation: int
    ring_buffer: tuple[tuple[datetime, int], ...]
    ring_revision: int
    session_active: bool
    session_start: datetime | None
    session_data: tuple[SessionSample, ...]
    session_max: int
    session_min: int
    session_sum: int
    session_count: int
    zone_times: dict[str, float]
    last_csv_path: str | None
    last_csv_error: str | None
    pending_export: tuple[SessionSample, ...]
    config: dict[str, Any] | None


@dataclass(frozen=True)
class ExportSnapshot:
    """Completed session data retained until it is saved or superseded."""

    rows: tuple[SessionSample, ...]
    session_start: datetime | None
    session_max: int
    session_min: int
    session_sum: int
    session_count: int
    zone_times: dict[str, float]

    @property
    def is_empty(self) -> bool:
        return not self.rows


@dataclass
class AppState:
    """Shared HRM state with a synchronized public mutation API."""

    latest_bpm: int | None = None
    connected: bool = False
    connection_status: str = "disconnected"
    connection_error: str | None = None
    scan_status: str = "idle"
    scan_results: tuple[DiscoveredDevice, ...] = ()
    scan_error: str | None = None
    scan_generation: int = 0
    ring_buffer: deque[tuple[datetime, int]] = field(default_factory=lambda: deque(maxlen=600))
    session_active: bool = False
    session_start: datetime | None = None
    session_data: list[SessionSample] = field(default_factory=list)
    session_max: int = 0
    session_min: int = 999
    session_sum: int = 0
    session_count: int = 0
    zone_times: dict[str, float] = field(default_factory=lambda: dict(ZONE_ZERO))
    last_csv_path: str | None = None
    last_csv_error: str | None = None
    config: dict[str, Any] | None = None

    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _last_session_sample: SessionSample | None = field(default=None, init=False)
    _ring_revision: int = field(default=0, init=False)
    _pending_export: ExportSnapshot | None = field(default=None, init=False)

    def record_bpm(self, timestamp: datetime, bpm: int) -> bool:
        """Record a BLE sample and update active session state.

        Returns ``True`` when the sample is valid and recorded.  Invalid BPMs
        and backward session timestamps are ignored while preserving existing
        state.
        """

        if bpm < 20 or bpm > 250:
            return False

        with self._lock:
            if self.ring_buffer and timestamp < self.ring_buffer[-1][0]:
                return False

            if not self.session_active:
                self.latest_bpm = bpm
                self.ring_buffer.append((timestamp, bpm))
                self._ring_revision += 1
                return True

            zone = self._zone_for_bpm(bpm)
            sample = SessionSample(timestamp=timestamp, bpm=bpm, zone=zone)

            if self._last_session_sample is not None:
                delta = (timestamp - self._last_session_sample.timestamp).total_seconds()
                if delta < 0:
                    return False
                self.zone_times[self._last_session_sample.zone] = self.zone_times.get(
                    self._last_session_sample.zone, 0.0
                ) + min(delta, MAX_SESSION_GAP_SECONDS)

            self.latest_bpm = bpm
            self.ring_buffer.append((timestamp, bpm))
            self._ring_revision += 1
            self.session_data.append(sample)
            self._last_session_sample = sample
            self.session_count += 1
            self.session_sum += bpm
            self.session_max = max(self.session_max, bpm)
            self.session_min = min(self.session_min, bpm)
            return True

    def start_session(self, started_at: datetime) -> None:
        """Reset counters and start a new recording session."""

        with self._lock:
            self.session_active = True
            self.session_start = started_at
            self.session_data.clear()
            self.session_max = 0
            self.session_min = 999
            self.session_sum = 0
            self.session_count = 0
            self.zone_times = dict(ZONE_ZERO)
            self.last_csv_path = None
            self.last_csv_error = None
            self._last_session_sample = None
            self._pending_export = None

    def finalize_session(self) -> ExportSnapshot | None:
        """Stop recording and retain an export snapshot without file I/O."""

        with self._lock:
            if not self.session_active:
                return self._pending_export
            self.session_active = False
            snapshot = self._make_export_snapshot_locked()
            self._pending_export = None if snapshot.is_empty else snapshot
            self.last_csv_path = None
            self.last_csv_error = None
            return self._pending_export

    def pending_export_snapshot(self) -> ExportSnapshot | None:
        """Return retained completed-session data for save retry."""

        with self._lock:
            return self._pending_export

    def mark_export_success(self, path: str) -> None:
        """Record a successful user-selected CSV destination."""

        with self._lock:
            self.last_csv_path = path
            self.last_csv_error = None

    def mark_export_failure(self, message: str) -> None:
        """Record a retryable CSV export error."""

        with self._lock:
            self.last_csv_path = None
            self.last_csv_error = message

    def update_connection(
        self,
        *,
        latest_bpm: int | None | object = ...,
        connected: bool | object = ...,
        status: str | object = ...,
        error: str | None | object = ...,
    ) -> None:
        """Atomically update connection fields used by the UI."""

        with self._lock:
            if latest_bpm is not ...:
                self.latest_bpm = latest_bpm  # type: ignore[assignment]
            if connected is not ...:
                self.connected = connected  # type: ignore[assignment]
            if status is not ...:
                self.connection_status = status  # type: ignore[assignment]
            if error is not ...:
                self.connection_error = error  # type: ignore[assignment]

    def update_scan(
        self,
        *,
        status: str | object = ...,
        results: tuple[DiscoveredDevice, ...] | object = ...,
        error: str | None | object = ...,
        bump_generation: bool = False,
    ) -> None:
        """Atomically update scan state and optionally bump its revision."""

        with self._lock:
            if status is not ...:
                self.scan_status = status  # type: ignore[assignment]
            if results is not ...:
                self.scan_results = results  # type: ignore[assignment]
            if error is not ...:
                self.scan_error = error  # type: ignore[assignment]
            if bump_generation:
                self.scan_generation += 1

    def set_config(self, config: dict[str, Any] | None) -> None:
        """Replace the current config snapshot."""

        with self._lock:
            self.config = _copy_config(config)

    def snapshot_for_ui(self) -> UISnapshot:
        """Copy live state for UI rendering without exposing mutable members."""

        with self._lock:
            return UISnapshot(
                latest_bpm=self.latest_bpm,
                connected=self.connected,
                connection_status=self.connection_status,
                connection_error=self.connection_error,
                scan_status=self.scan_status,
                scan_results=tuple(self.scan_results),
                scan_error=self.scan_error,
                scan_generation=self.scan_generation,
                ring_buffer=tuple(self.ring_buffer),
                ring_revision=self._ring_revision,
                session_active=self.session_active,
                session_start=self.session_start,
                session_data=tuple(self.session_data),
                session_max=self.session_max,
                session_min=self.session_min,
                session_sum=self.session_sum,
                session_count=self.session_count,
                zone_times=dict(self.zone_times),
                last_csv_path=self.last_csv_path,
                last_csv_error=self.last_csv_error,
                pending_export=(
                    self._pending_export.rows if self._pending_export is not None else ()
                ),
                config=_copy_config(self.config),
            )

    def _make_export_snapshot_locked(self) -> ExportSnapshot:
        return ExportSnapshot(
            rows=tuple(self.session_data),
            session_start=self.session_start,
            session_max=self.session_max,
            session_min=self.session_min,
            session_sum=self.session_sum,
            session_count=self.session_count,
            zone_times=dict(self.zone_times),
        )

    def _zone_for_bpm(self, bpm: int) -> str:
        cfg = self.config or {}
        zones_cfg = cfg.get("zones", {})
        zone_bounds = {
            "z1_max": zones_cfg.get("z1_max", 0.60),
            "z2_max": zones_cfg.get("z2_max", 0.75),
            "z3_max": zones_cfg.get("z3_max", 0.88),
        }
        return get_zone(bpm, cfg.get("max_hr", 190), zone_bounds)


def _copy_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    if config is None:
        return None
    copied: dict[str, Any] = {}
    for key, value in config.items():
        copied[key] = _copy_config(value) if isinstance(value, dict) else value
    return copied
