"""Thread-safe state and immutable snapshots for HRM Live.

The BLE asyncio thread is the primary producer and the AppKit main thread is
the primary consumer.  AppState therefore owns a small RLock-protected API so
UI rendering and CSV export copy data under the lock, then perform slow work
after the lock is released.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from hrm_live.zones import get_zone

log = logging.getLogger(__name__)

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
    recent_sessions: tuple[RecentSessionRecord, ...]
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
    zone_transition_count: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.rows

    @property
    def duration_seconds(self) -> float:
        """Total session duration from zone time accumulation."""
        return sum(self.zone_times.values())


@dataclass(frozen=True)
class RecentSessionRecord:
    """Persisted archive entry for a finalized session."""

    session_id: str
    session_start: datetime | None
    archived_at: datetime
    session_max: int
    session_min: int
    session_sum: int
    session_count: int
    zone_times: dict[str, float]
    zone_transition_count: int = 0
    export_path: str | None = None
    export_format: str | None = None
    exported_at: datetime | None = None

    @property
    def duration_seconds(self) -> float:
        return sum(self.zone_times.values())

    @property
    def average_bpm(self) -> float:
        return self.session_sum / self.session_count if self.session_count else 0.0

    @property
    def has_export(self) -> bool:
        return self.export_path is not None

    @classmethod
    def from_snapshot(
        cls,
        snapshot: ExportSnapshot,
        *,
        session_id: str,
        archived_at: datetime,
    ) -> RecentSessionRecord:
        return cls(
            session_id=session_id,
            session_start=snapshot.session_start,
            archived_at=archived_at,
            session_max=snapshot.session_max,
            session_min=snapshot.session_min,
            session_sum=snapshot.session_sum,
            session_count=snapshot.session_count,
            zone_times=dict(snapshot.zone_times),
            zone_transition_count=snapshot.zone_transition_count,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecentSessionRecord:
        def _parse_dt(value: Any) -> datetime | None:
            if value in {None, ""}:
                return None
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(str(value))

        zone_times = data.get("zone_times", {})
        if not isinstance(zone_times, dict):
            raise ValueError("recent session zone_times must be an object")

        return cls(
            session_id=str(data["session_id"]),
            session_start=_parse_dt(data.get("session_start")),
            archived_at=_parse_dt(data.get("archived_at")) or datetime.now(UTC),
            session_max=int(data.get("session_max", 0)),
            session_min=int(data.get("session_min", 0)),
            session_sum=int(data.get("session_sum", 0)),
            session_count=int(data.get("session_count", 0)),
            zone_times={str(zone): float(seconds) for zone, seconds in zone_times.items()},
            zone_transition_count=int(data.get("zone_transition_count", 0)),
            export_path=data.get("export_path") or None,
            export_format=data.get("export_format") or None,
            exported_at=_parse_dt(data.get("exported_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_start": self.session_start.isoformat() if self.session_start else None,
            "archived_at": self.archived_at.isoformat(),
            "session_max": self.session_max,
            "session_min": self.session_min,
            "session_sum": self.session_sum,
            "session_count": self.session_count,
            "zone_times": dict(self.zone_times),
            "zone_transition_count": self.zone_transition_count,
            "export_path": self.export_path,
            "export_format": self.export_format,
            "exported_at": self.exported_at.isoformat() if self.exported_at else None,
        }

    def with_export(self, path: str, fmt: str | None = None) -> RecentSessionRecord:
        return replace(
            self,
            export_path=path,
            export_format=fmt,
            exported_at=datetime.now(UTC),
        )

    def display_summary(self) -> str:
        """Return a compact human-readable summary for the dashboard."""

        started = self.session_start or self.archived_at
        stamp = started.strftime("%b %d %H:%M")
        duration = _format_duration_short(self.duration_seconds)
        status = (
            self.export_format.upper()
            if self.export_format
            else ("Saved" if self.export_path else "Pending save")
        )
        return f"{stamp} · {duration} · {self.session_count} samples · {status}"


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
    _pending_export_session_id: str | None = field(default=None, init=False)
    _last_zone: str | None = field(default=None, init=False)
    _zone_transition_count: int = field(default=0, init=False)
    _recent_sessions: list[RecentSessionRecord] = field(default_factory=list, init=False)
    _recent_sessions_path: Path | None = field(default=None, init=False, repr=False)

    def record_bpm(self, timestamp: datetime, bpm: int) -> bool:
        """Record a BLE sample and update active session state.

        Returns ``True`` when the sample is valid and recorded.  Invalid BPMs
        and backward session timestamps are ignored while preserving existing
        state.

        Tracks zone transitions during active sessions.
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

            # Track zone transitions
            if self._last_zone is not None and zone != self._last_zone:
                self._zone_transition_count += 1
                log.debug("Zone transition recorded")
            self._last_zone = zone

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
            self._pending_export_session_id = None
            self._last_zone = None
            self._zone_transition_count = 0

    def finalize_session(self) -> ExportSnapshot | None:
        """Stop recording and retain an export snapshot without file I/O."""

        with self._lock:
            if not self.session_active:
                return self._pending_export
            self.session_active = False
            snapshot = self._make_export_snapshot_locked()
            if snapshot.is_empty:
                self._pending_export = None
                self._pending_export_session_id = None
                self.last_csv_path = None
                self.last_csv_error = None
                return None

            session_id = uuid4().hex
            archived_at = datetime.now(UTC)
            self._pending_export = snapshot
            self._pending_export_session_id = session_id
            self.last_csv_path = None
            self.last_csv_error = None
            self._recent_sessions.append(
                RecentSessionRecord.from_snapshot(
                    snapshot,
                    session_id=session_id,
                    archived_at=archived_at,
                )
            )
            self._recent_sessions = self._recent_sessions[-20:]
            self._persist_recent_sessions_locked()

            return snapshot

    def pending_export_snapshot(self) -> ExportSnapshot | None:
        """Return retained completed-session data for save retry."""

        with self._lock:
            return self._pending_export

    def mark_export_success(self, path: str, fmt: str | None = None) -> None:
        """Record a successful destination and clear retryable export data."""

        with self._lock:
            self.last_csv_path = path
            self.last_csv_error = None
            self._pending_export = None
            session_id = self._pending_export_session_id
            self._pending_export_session_id = None
            if session_id is not None:
                self._mark_recent_session_export_locked(session_id, path, fmt=fmt)
                self._persist_recent_sessions_locked()

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

    def set_recent_sessions_path(self, path: Path | None) -> None:
        """Set the persistence location for archived recent sessions."""

        with self._lock:
            self._recent_sessions_path = path

    def load_recent_sessions(self) -> None:
        """Load persisted recent sessions from disk, if available."""

        with self._lock:
            path = self._recent_sessions_path
        if path is None or not path.exists():
            return

        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, list):
                raise ValueError("recent sessions file must contain a list")
            sessions = [
                RecentSessionRecord.from_dict(item) for item in payload if isinstance(item, dict)
            ]
        except Exception:
            log.exception("Failed to load recent sessions from %s", path)
            _safely_rename_corrupt(path)
            return

        with self._lock:
            self._recent_sessions = sessions[-20:]

    def persist_recent_sessions(self) -> None:
        """Write archived recent sessions to disk, best-effort."""

        with self._lock:
            self._persist_recent_sessions_locked()

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
                recent_sessions=tuple(self._recent_sessions),
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
            zone_transition_count=self._zone_transition_count,
        )

    def recent_sessions(self) -> tuple[RecentSessionRecord, ...]:
        """Return the list of recent completed sessions (oldest first)."""
        with self._lock:
            return tuple(self._recent_sessions)

    def delete_recent_session(self, session_id: str) -> bool:
        """Delete a recent session entry by id and persist the archive."""

        with self._lock:
            before = len(self._recent_sessions)
            self._recent_sessions = [
                session for session in self._recent_sessions if session.session_id != session_id
            ]
            if len(self._recent_sessions) == before:
                return False
            if self._pending_export_session_id == session_id:
                self._pending_export = None
                self._pending_export_session_id = None
            self._persist_recent_sessions_locked()
            return True

    def _zone_for_bpm(self, bpm: int) -> str:
        cfg = self.config or {}
        zones_cfg = cfg.get("zones", {})
        zone_bounds = {
            "z1_max": zones_cfg.get("z1_max", 0.60),
            "z2_max": zones_cfg.get("z2_max", 0.75),
            "z3_max": zones_cfg.get("z3_max", 0.88),
        }
        return get_zone(bpm, cfg.get("max_hr", 190), zone_bounds)

    def _mark_recent_session_export_locked(
        self,
        session_id: str,
        path: str,
        *,
        fmt: str | None = None,
    ) -> None:
        for idx in range(len(self._recent_sessions) - 1, -1, -1):
            session = self._recent_sessions[idx]
            if session.session_id == session_id:
                export_fmt = fmt or Path(path).suffix.lstrip(".").lower() or None
                self._recent_sessions[idx] = session.with_export(path, export_fmt)
                return

    def _persist_recent_sessions_locked(self) -> None:
        path = self._recent_sessions_path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps([session.to_dict() for session in self._recent_sessions], indent=2)
                + "\n",
                encoding="utf-8",
            )
            tmp.replace(path)
        except Exception:
            log.exception("Failed to persist recent sessions to %s", path)


def _copy_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    if config is None:
        return None
    copied: dict[str, Any] = {}
    for key, value in config.items():
        copied[key] = _copy_config(value) if isinstance(value, dict) else value
    return copied


def _safely_rename_corrupt(path: Path) -> None:
    """Rename a corrupt archive file so the user can inspect it later."""

    if not path.exists():
        return
    counter = 0
    while True:
        suffix = ".corrupt" if counter == 0 else f".corrupt.{counter}"
        dst = path.with_name(path.name + suffix)
        if not dst.exists():
            path.rename(dst)
            return
        counter += 1


def _format_duration_short(seconds: float) -> str:
    total = max(int(round(seconds)), 0)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
