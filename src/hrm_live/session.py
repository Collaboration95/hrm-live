"""Session lifecycle and explicit CSV/JSON export.

Stopping a session finalizes immutable rows in memory.  File export only
happens when the UI supplies a destination selected by the user.

Supports both CSV (row-level samples) and JSON (summary + samples) export
formats.  JSON includes session metadata (duration, average, max, zone
breakdown) alongside the full sample list for downstream analysis.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from hrm_live.state import AppState, ExportSnapshot

log = logging.getLogger(__name__)
Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """Return the default timezone-aware session clock."""

    return datetime.now(UTC)


def start_session(state: AppState, clock: Clock = utc_now) -> None:
    """Start a new session and clear any retryable completed session."""

    started_at = clock()
    state.start_session(started_at)
    log.info("Session started at %s", started_at.isoformat())


def record_sample(state: AppState, timestamp: datetime, bpm: int) -> None:
    """Compatibility wrapper for tests and BLE ingestion."""

    if not state.record_bpm(timestamp, bpm):
        log.warning("Ignoring invalid or non-monotonic BPM sample: bpm=%s", bpm)


def finalize_session(state: AppState) -> ExportSnapshot | None:
    """Stop recording and return retained export data, without file I/O."""

    snapshot = state.finalize_session()
    if snapshot is None:
        return None
    log.info(
        "Session finalized: %d samples, avg %.1f",
        snapshot.session_count,
        snapshot.session_sum / snapshot.session_count if snapshot.session_count else 0,
    )
    return snapshot


def retryable_export(state: AppState) -> ExportSnapshot | None:
    """Return the last completed session if it still needs saving."""

    return state.pending_export_snapshot()


def suggested_filename(
    prefix: str = "HRM Live", extension: str = "csv", clock: Clock = utc_now
) -> str:
    """Return a Finder-friendly filename for NSSavePanel."""

    return f"{prefix} {clock().strftime('%Y-%m-%d %H-%M')}.{extension}"


def suggested_csv_filename(clock: Clock = utc_now) -> str:
    """Return a Finder-friendly CSV filename for NSSavePanel."""
    return suggested_filename(extension="csv", clock=clock)


def suggested_json_filename(clock: Clock = utc_now) -> str:
    """Return a Finder-friendly JSON filename for NSSavePanel."""
    return suggested_filename(extension="json", clock=clock)


def normalize_csv_destination(destination: str | os.PathLike[str]) -> Path:
    """Validate and normalize a user-selected CSV destination."""

    path = Path(destination).expanduser()
    if not str(path):
        raise ValueError("Choose a CSV file destination.")
    if path.exists() and path.is_dir():
        raise ValueError("Choose a CSV file, not a folder.")
    if path.suffix.lower() != ".csv":
        path = path.with_suffix(path.suffix + ".csv") if path.suffix else path.with_suffix(".csv")
    return path


def export_session_csv(
    snapshot: ExportSnapshot,
    destination: str | os.PathLike[str],
) -> Path:
    """Atomically write *snapshot* to an explicit CSV destination."""

    if snapshot.is_empty:
        raise ValueError("Cannot export an empty session.")

    path = normalize_csv_destination(destination)
    return _write_csv(snapshot, path)


def export_session_json(
    snapshot: ExportSnapshot,
    destination: str | os.PathLike[str],
) -> Path:
    """Atomically write *snapshot* to an explicit JSON destination.

    Unlike CSV export, JSON includes a summary envelope with session
    metadata alongside the full sample list.
    """

    if snapshot.is_empty:
        raise ValueError("Cannot export an empty session.")

    path = _normalize_json_destination(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(_build_json_payload(snapshot), handle, indent=2, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        finally:
            log.exception("Failed to export JSON to %s", path)
        raise
    return path


def _write_csv(snapshot: ExportSnapshot, path: Path) -> Path:
    """Write CSV rows atomically to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["timestamp", "bpm", "zone"])
            for sample in snapshot.rows:
                writer.writerow([sample.timestamp.isoformat(), sample.bpm, sample.zone])
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        finally:
            log.exception("Failed to write CSV to %s", path)
        raise
    return path


def _build_json_payload(snapshot: ExportSnapshot) -> dict:
    """Build a JSON-serializable session payload with summary + samples."""
    elapsed = sum(snapshot.zone_times.values()) if snapshot.zone_times else 0
    avg = snapshot.session_sum / snapshot.session_count if snapshot.session_count else 0

    samples = [
        {
            "timestamp": s.timestamp.isoformat(),
            "bpm": s.bpm,
            "zone": s.zone,
        }
        for s in snapshot.rows
    ]

    return {
        "session": {
            "start": snapshot.session_start.isoformat() if snapshot.session_start else None,
            "duration_seconds": elapsed,
            "sample_count": snapshot.session_count,
            "average_bpm": round(avg, 1),
            "max_bpm": snapshot.session_max,
            "min_bpm": snapshot.session_min,
        },
        "zone_breakdown": {
            zone: round(seconds, 1) for zone, seconds in snapshot.zone_times.items()
        },
        "samples": samples,
        "export_schema_version": 1,
    }


def _normalize_json_destination(destination: str | os.PathLike[str]) -> Path:
    """Validate and normalize a user-selected JSON destination."""
    path = Path(destination).expanduser()
    if not str(path):
        raise ValueError("Choose a JSON file destination.")
    if path.exists() and path.is_dir():
        raise ValueError("Choose a JSON file, not a folder.")
    if path.suffix.lower() != ".json":
        path = path.with_suffix(path.suffix + ".json") if path.suffix else path.with_suffix(".json")
    return path
