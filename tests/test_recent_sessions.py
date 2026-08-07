"""Tests for recent-session popover behavior (open, zone summary, delete)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hrm_live.state import AppState, RecentSessionRecord
from hrm_live.ui.popover import HRMPopover, recent_second_line, recent_zone_fractions

ZONE_TIMES = {"Z1": 30.0, "Z2": 60.0, "Z3": 10.0, "Z4": 0.0}


class _FakeSender:
    def __init__(self, tag: int) -> None:
        self._tag = tag

    def tag(self) -> int:
        return self._tag


def _archive_state(tmp_path) -> AppState:
    state = AppState()
    state.set_recent_sessions_path(tmp_path / "recent_sessions.json")
    state.start_session(datetime(2026, 7, 15, tzinfo=UTC))
    state.record_bpm(datetime(2026, 7, 15, 0, 0, 1, tzinfo=UTC), 120)
    state.record_bpm(datetime(2026, 7, 15, 0, 0, 2, tzinfo=UTC), 150)
    assert state.finalize_session() is not None
    return state


def test_recent_second_line_summarises_avg_max_transitions() -> None:
    record = RecentSessionRecord(
        session_id="s1",
        session_start=None,
        archived_at=datetime(2026, 7, 15, tzinfo=UTC),
        session_max=178,
        session_min=120,
        session_sum=270,
        session_count=2,
        zone_times=ZONE_TIMES,
        zone_transition_count=3,
    )
    line = recent_second_line(record)
    assert "Avg 135" in line
    assert "Max 178" in line
    assert "3 transitions" in line


def test_recent_zone_fractions_normalise_to_one() -> None:
    fractions = recent_zone_fractions(ZONE_TIMES)
    assert [zone for zone, _ in fractions] == ["Z1", "Z2", "Z3", "Z4"]
    assert sum(frac for _, frac in fractions) == pytest.approx(1.0)
    assert dict(fractions)["Z1"] == pytest.approx(0.3)


def test_recent_zone_fractions_missing_keys_default_to_zero() -> None:
    fractions = recent_zone_fractions({"Z2": 5.0})  # missing Z1/Z3/Z4
    assert dict(fractions)["Z1"] == 0.0
    assert dict(fractions)["Z4"] == 0.0


def test_recent_zone_fractions_empty_is_all_zero() -> None:
    fractions = recent_zone_fractions({})
    assert [frac for _, frac in fractions] == [0.0] * 4


def test_open_recent_session_opens_export_via_injected_factory(tmp_path) -> None:
    state = _archive_state(tmp_path)
    state.mark_export_success(str(tmp_path / "run.csv"), "csv")
    opened: list[str] = []
    popover = HRMPopover(state, open_url_factory=opened.append)
    popover.open_recent_session_(_FakeSender(0))
    assert opened == [str(tmp_path / "run.csv")]


def test_open_recent_session_gated_on_has_export(tmp_path) -> None:
    state = _archive_state(tmp_path)  # finalized but not marked exported
    opened: list[str] = []
    popover = HRMPopover(state, open_url_factory=opened.append)
    popover.open_recent_session_(_FakeSender(0))
    assert opened == []


def test_open_recent_session_ignores_out_of_range_tag(tmp_path) -> None:
    state = _archive_state(tmp_path)
    state.mark_export_success(str(tmp_path / "run.csv"), "csv")
    opened: list[str] = []
    popover = HRMPopover(state, open_url_factory=opened.append)
    popover.open_recent_session_(_FakeSender(7))
    assert opened == []
    popover.open_recent_session_(object())  # tag() raises -> safe no-op
    assert opened == []


def test_delete_recent_session_removes_from_history(tmp_path) -> None:
    state = _archive_state(tmp_path)
    popover = HRMPopover(state)
    assert popover.delete_recent_session_(_FakeSender(0)) is None
    assert state.snapshot_for_ui().recent_sessions == ()


def test_reveal_recent_session_uses_finder_for_export(tmp_path) -> None:
    state = _archive_state(tmp_path)
    state.mark_export_success(str(tmp_path / "run.csv"), "csv")
    revealed: list[object] = []
    popover = HRMPopover(state)
    popover._reveal_in_finder = lambda path: revealed.append(path)  # type: ignore[method-assign]
    popover.reveal_recent_session_(_FakeSender(0))
    assert revealed
