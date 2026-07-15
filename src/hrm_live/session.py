"""Session lifecycle and explicit CSV export.

Stopping a session finalizes immutable rows in memory.  File export only
happens when the UI supplies a destination selected by the user.
"""

from __future__ import annotations

import csv
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


def suggested_csv_filename(clock: Clock = utc_now) -> str:
    """Return a Finder-friendly CSV filename for NSSavePanel."""

    return f"HRM Live {clock().strftime('%Y-%m-%d %H-%M')}.csv"


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
    """Atomically write *snapshot* to an explicit CSV destination.

    The destination is replaced only after a complete sibling temp file has
    been flushed and fsynced, preventing partial CSVs after mid-write failures.
    """

    if snapshot.is_empty:
        raise ValueError("Cannot export an empty session.")

    path = normalize_csv_destination(destination)
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
            log.exception("Failed to export CSV to %s", path)
        raise
    return path
