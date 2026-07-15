"""Tests for session finalization and explicit CSV export."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

import hrm_live.session as session
from hrm_live.state import AppState


@pytest.fixture
def state() -> AppState:
    s = AppState()
    s.set_config(
        {
            "max_hr": 190,
            "zones": {"z1_max": 0.60, "z2_max": 0.75, "z3_max": 0.88},
        }
    )
    return s


def _ts(seconds: int) -> datetime:
    return datetime(2026, 7, 15, 10, 0, seconds, tzinfo=UTC)


def test_start_session_resets_completed_export(state: AppState) -> None:
    session.start_session(state, clock=lambda: _ts(0))
    session.record_sample(state, _ts(0), 130)
    assert session.finalize_session(state) is not None

    session.start_session(state, clock=lambda: _ts(10))

    assert state.session_active is True
    assert state.session_start == _ts(10)
    assert state.session_data == []
    assert state.session_count == 0
    assert state.session_max == 0
    assert state.session_min == 999
    assert state.zone_times == {"Z1": 0.0, "Z2": 0.0, "Z3": 0.0, "Z4": 0.0}
    assert session.retryable_export(state) is None


def test_finalize_no_active_session_returns_pending_export(state: AppState) -> None:
    assert session.finalize_session(state) is None
    session.start_session(state)
    session.record_sample(state, _ts(0), 130)
    snapshot = session.finalize_session(state)
    assert session.finalize_session(state) is snapshot


def test_finalize_empty_session_does_not_create_export(state: AppState) -> None:
    session.start_session(state)
    assert session.finalize_session(state) is None
    assert state.session_active is False
    assert session.retryable_export(state) is None


def test_explicit_csv_export_preserves_historical_zones(state: AppState, tmp_path: Path) -> None:
    session.start_session(state)
    session.record_sample(state, _ts(0), 130)
    state.set_config(
        {
            "max_hr": 220,
            "zones": {"z1_max": 0.80, "z2_max": 0.85, "z3_max": 0.90},
        }
    )
    session.record_sample(state, _ts(1), 130)
    snapshot = session.finalize_session(state)

    assert snapshot is not None
    path = session.export_session_csv(snapshot, tmp_path / "workout")

    assert path == tmp_path / "workout.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["timestamp", "bpm", "zone"]
    assert rows[1][1:] == ["130", "Z2"]
    assert rows[2][1:] == ["130", "Z1"]


def test_export_requires_non_empty_snapshot(state: AppState, tmp_path: Path) -> None:
    session.start_session(state)
    assert session.finalize_session(state) is None
    with pytest.raises(AttributeError):
        session.export_session_csv(None, tmp_path / "x.csv")  # type: ignore[arg-type]


def test_delta_accounting_assigns_time_to_previous_zone(state: AppState) -> None:
    session.start_session(state)
    session.record_sample(state, _ts(0), 100)
    session.record_sample(state, _ts(3), 150)
    session.record_sample(state, _ts(5), 180)

    assert state.zone_times["Z1"] == 3.0
    assert state.zone_times["Z3"] == 2.0
    assert state.zone_times["Z4"] == 0.0


def test_gap_accounting_is_clamped(state: AppState) -> None:
    session.start_session(state)
    session.record_sample(state, _ts(0), 100)
    session.record_sample(state, _ts(30), 130)

    assert state.zone_times["Z1"] == 5.0


def test_invalid_bpm_and_backward_timestamp_are_ignored(state: AppState) -> None:
    session.start_session(state)
    session.record_sample(state, _ts(10), 120)
    session.record_sample(state, _ts(11), 10)
    session.record_sample(state, _ts(9), 130)

    assert state.session_count == 1
    assert [sample.bpm for sample in state.session_data] == [120]


def test_write_failure_keeps_retryable_snapshot(state: AppState, tmp_path: Path) -> None:
    session.start_session(state)
    session.record_sample(state, _ts(0), 130)
    snapshot = session.finalize_session(state)
    assert snapshot is not None

    destination = tmp_path / "export.csv"
    with patch("os.fsync", side_effect=OSError("disk full")), pytest.raises(OSError):
        session.export_session_csv(snapshot, destination)

    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []
    assert session.retryable_export(state) is snapshot


def test_cancel_semantics_are_retryable_without_error(state: AppState) -> None:
    session.start_session(state)
    session.record_sample(state, _ts(0), 130)
    snapshot = session.finalize_session(state)

    assert snapshot is not None
    assert state.last_csv_path is None
    assert state.last_csv_error is None
    assert session.retryable_export(state) is snapshot


def test_export_replace_overwrite_is_complete(state: AppState, tmp_path: Path) -> None:
    destination = tmp_path / "existing.csv"
    destination.write_text("old partial data", encoding="utf-8")
    session.start_session(state)
    session.record_sample(state, _ts(0), 130)
    snapshot = session.finalize_session(state)
    assert snapshot is not None

    session.export_session_csv(snapshot, destination)

    assert "old partial data" not in destination.read_text(encoding="utf-8")


def test_suggested_filename_is_readable() -> None:
    def clock() -> datetime:
        return datetime(2026, 7, 15, 18, 30, tzinfo=UTC)

    assert session.suggested_csv_filename(clock=clock) == "HRM Live 2026-07-15 18-30.csv"
