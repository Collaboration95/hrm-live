"""Tests for session management and CSV export."""

import csv
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from state import AppState
from session import start_session, record_sample, stop_session, SESSION_DIR


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def state() -> AppState:
    s = AppState()
    s.config = {"max_hr": 190, "zones": {"z1_max": 0.60, "z2_max": 0.75, "z3_max": 0.88}}
    return s


# ── Start ───────────────────────────────────────────────────────────────

def test_start_session_resets(state: AppState) -> None:
    # Set some previous session data
    state.session_max = 150
    state.session_min = 60
    state.session_sum = 1000
    state.session_count = 10
    state.session_data = [(datetime.now(timezone.utc), 120)]
    state.zone_times = {"Z1": 10, "Z2": 20, "Z3": 5, "Z4": 0}

    start_session(state)

    assert state.session_active is True
    assert state.session_start is not None
    assert state.session_data == []
    assert state.session_max == 0
    assert state.session_min == 999
    assert state.session_sum == 0
    assert state.session_count == 0
    assert state.zone_times == {"Z1": 0, "Z2": 0, "Z3": 0, "Z4": 0}
    assert state.last_csv_path is None


# ── Record ──────────────────────────────────────────────────────────────

def test_record_noop_when_inactive(state: AppState) -> None:
    state.session_active = False
    record_sample(state, datetime.now(timezone.utc), 120)
    assert state.session_count == 0


def test_record_basic(state: AppState) -> None:
    start_session(state)
    ts = datetime.now(timezone.utc)
    record_sample(state, ts, 120)
    assert state.session_count == 1
    assert state.session_sum == 120
    assert state.session_max == 120
    assert state.session_min == 120
    assert len(state.session_data) == 1


def test_record_updates_stats(state: AppState) -> None:
    start_session(state)
    for bpm in [60, 80, 100, 120, 140]:
        record_sample(state, datetime.now(timezone.utc), bpm)
    assert state.session_count == 5
    assert state.session_sum == 500
    assert state.session_max == 140
    assert state.session_min == 60


def test_record_out_of_range_ignored(state: AppState) -> None:
    start_session(state)
    record_sample(state, datetime.now(timezone.utc), 10)  # too low
    record_sample(state, datetime.now(timezone.utc), 300)  # too high
    assert state.session_count == 0


def test_record_zone_times(state: AppState) -> None:
    """Zone time increments for samples in different zones."""
    start_session(state)
    # Z1: < 60% of 190 = < 114
    record_sample(state, datetime.now(timezone.utc), 100)
    # Z2: 114-142.5
    record_sample(state, datetime.now(timezone.utc), 130)
    # Z3: 142.5-167.2
    record_sample(state, datetime.now(timezone.utc), 150)
    # Z4: > 167.2
    record_sample(state, datetime.now(timezone.utc), 180)
    assert state.zone_times["Z1"] == 1
    assert state.zone_times["Z2"] == 1
    assert state.zone_times["Z3"] == 1
    assert state.zone_times["Z4"] == 1


# ── Stop ────────────────────────────────────────────────────────────────

def test_stop_no_active_session(state: AppState) -> None:
    result = stop_session(state)
    assert result is None


def test_stop_no_samples(state: AppState) -> None:
    start_session(state)
    result = stop_session(state)
    assert result is None
    assert state.session_active is False


def test_stop_and_csv_export(state: AppState) -> None:
    start_session(state)
    record_sample(state, datetime.now(timezone.utc), 130)
    record_sample(state, datetime.now(timezone.utc), 150)
    record_sample(state, datetime.now(timezone.utc), 180)

    result = stop_session(state)
    assert result is not None
    assert result.endswith(".csv")
    assert state.session_active is False
    assert state.last_csv_path is not None

    # Verify CSV content
    path = Path(result)
    assert path.exists()
    with open(path, "r") as f:
        reader = csv.reader(f)
        rows = list(reader)
    assert len(rows) == 4  # header + 3 samples
    assert rows[0] == ["timestamp", "bpm", "zone"]
    # Second row should have ts, bpm, zone
    assert len(rows[1]) == 3
    assert rows[1][1] == "130"
    assert rows[1][2] == "Z2"  # 130/190 ≈ 68.4% → Z2
    # Last row
    assert rows[3][1] == "180"
    assert rows[3][2] == "Z4"


def test_stop_stats_remain_after_stop(state: AppState) -> None:
    start_session(state)
    record_sample(state, datetime.now(timezone.utc), 130)
    record_sample(state, datetime.now(timezone.utc), 150)
    stop_session(state)

    # Stats remain visible
    assert state.session_max == 150
    assert state.session_min == 130
    assert state.session_sum == 280
    assert state.session_count == 2


def test_new_session_clears_previous_stats(state: AppState) -> None:
    start_session(state)
    record_sample(state, datetime.now(timezone.utc), 130)
    stop_session(state)

    # New session
    start_session(state)
    assert state.session_count == 0
    assert state.session_max == 0
    assert state.session_min == 999


# ── CSV collision ───────────────────────────────────────────────────────

def test_csv_filename_collision(state: AppState) -> None:
    """Two sessions stopped in the same minute get different filenames."""
    start_session(state)
    record_sample(state, datetime.now(timezone.utc), 130)
    p1 = Path(stop_session(state))

    start_session(state)
    record_sample(state, datetime.now(timezone.utc), 140)
    p2 = Path(stop_session(state))

    assert p1 != p2
    assert p1.exists()
    assert p2.exists()


# ── Session directory ───────────────────────────────────────────────────

def test_session_dir_created(state: AppState) -> None:
    """Session directory is created on first stop."""
    # Use a temp directory for testing
    with tempfile.TemporaryDirectory() as d:
        with patch("session.SESSION_DIR", Path(d) / "sessions"):
            start_session(state)
            record_sample(state, datetime.now(timezone.utc), 130)
            path = stop_session(state)
            assert path is not None
            assert Path(path).parent.exists()
