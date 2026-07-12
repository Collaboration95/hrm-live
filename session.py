"""Session management — start, record, stop, and CSV export.

Session data is accumulated in ``AppState`` and written to
``~/.local/share/hrm/sessions/YYYY-MM-DD_HH-MM.csv`` on stop.
"""

from __future__ import annotations

import csv
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from state import AppState
from zones import get_zone

log = logging.getLogger(__name__)

SESSION_DIR = Path.home() / ".local" / "share" / "hrm" / "sessions"


# ── Session lifecycle ────────────────────────────────────────────────────


def start_session(state: AppState) -> None:
    """Start a new session.

    Resets all accumulators and marks the session as active.
    """
    state.session_active = True
    state.session_start = datetime.now(timezone.utc)
    state.session_data.clear()
    state.session_max = 0
    state.session_min = 999
    state.session_sum = 0
    state.session_count = 0
    state.zone_times = {"Z1": 0, "Z2": 0, "Z3": 0, "Z4": 0}
    state.last_csv_path = None
    log.info("Session started at %s", state.session_start.isoformat())


def record_sample(state: AppState, timestamp: datetime, bpm: int,
                 config: dict[str, Any] | None = None) -> None:
    """Record a BPM sample into the active session.

    No-op if ``session_active`` is ``False``.

    *config* is optional — if provided, its ``max_hr`` and ``zones``
    keys are used for zone classification; otherwise defaults are used.
    """
    if not state.session_active:
        return

    # Validate BPM range — reject unreasonable values
    if bpm < 20 or bpm > 250:
        log.warning("Ignoring out-of-range BPM: %d", bpm)
        return

    state.session_data.append((timestamp, bpm))
    state.session_count += 1
    state.session_sum += bpm

    if bpm > state.session_max:
        state.session_max = bpm
    if bpm < state.session_min:
        state.session_min = bpm

    # Resolve config for zone classification
    if config is None:
        cfg = state.config or {}
    else:
        cfg = config
    max_hr = cfg.get("max_hr", 190)
    zones_cfg = cfg.get("zones", {})
    zone_bounds = {
        "z1_max": zones_cfg.get("z1_max", 0.60),
        "z2_max": zones_cfg.get("z2_max", 0.75),
        "z3_max": zones_cfg.get("z3_max", 0.88),
    }

    # Zone time accounting — at 1 Hz each sample ≈ 1 second
    zone = get_zone(bpm, max_hr, zone_bounds)
    state.zone_times[zone] = state.zone_times.get(zone, 0) + 1


def stop_session(state: AppState, max_hr: int = 190,
                 zones: dict[str, float] | None = None) -> str | None:
    """Stop the active session and write CSV.

    Returns the path to the written CSV, or ``None`` if no session was
    active or no samples were collected.

    Stats remain visible in state until the next ``start_session()``.
    """
    if not state.session_active:
        return None

    state.session_active = False
    log.info(
        "Session stopped: %d samples, avg %.1f",
        state.session_count,
        state.session_sum / state.session_count if state.session_count else 0,
    )

    if state.session_count == 0:
        state.last_csv_path = None
        return None

    # Write CSV
    csv_path = _write_csv(state, max_hr, zones or {})
    state.last_csv_path = str(csv_path)
    return str(csv_path)


# ── CSV export ───────────────────────────────────────────────────────────


def _write_csv(state: AppState, max_hr: int,
               zones: dict[str, float]) -> Path:
    """Write session data to a CSV file and return the path.

    Filename collision avoidance: if two sessions stop in the same
    minute, a counter suffix is appended.
    """
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    base_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
    path = SESSION_DIR / f"{base_ts}.csv"
    counter = 1
    while path.exists():
        path = SESSION_DIR / f"{base_ts}_{counter}.csv"
        counter += 1

    zone_bounds = {
        "z1_max": zones.get("z1_max", 0.60),
        "z2_max": zones.get("z2_max", 0.75),
        "z3_max": zones.get("z3_max", 0.88),
    }

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "bpm", "zone"])
        for ts, bpm in state.session_data:
            z = get_zone(bpm, max_hr, zone_bounds)
            writer.writerow([ts.isoformat(), bpm, z])

    log.info("Session exported to %s", path)
    return path
