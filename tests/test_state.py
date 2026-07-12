"""Tests for AppState dataclass."""

from state import AppState


def test_default_initialization() -> None:
    s = AppState()
    assert s.latest_bpm is None
    assert s.connected is False
    assert len(s.ring_buffer) == 0
    assert s.ring_buffer.maxlen == 600
    assert s.session_active is False
    assert s.session_start is None
    assert s.session_data == []
    assert s.session_max == 0
    assert s.session_min == 999
    assert s.session_sum == 0
    assert s.session_count == 0
    assert s.zone_times == {"Z1": 0, "Z2": 0, "Z3": 0, "Z4": 0}
    assert s.last_csv_path is None
    assert s.config is None


def test_ring_buffer_maxlen() -> None:
    s = AppState()
    assert s.ring_buffer.maxlen == 600


def test_ring_buffer_overflow() -> None:
    s = AppState()
    for i in range(700):
        s.ring_buffer.append((i, 100 + (i % 50)))
    assert len(s.ring_buffer) == 600
