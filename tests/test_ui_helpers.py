"""Tests for UI helper functions (hex parsing, formatting, etc.)."""

from __future__ import annotations

from hrm_live.state import UISnapshot
from hrm_live.ui.popover import _empty_graph_placeholder, _format_td_seconds, _format_td_short
from hrm_live.ui.settings import _is_valid_hex


class TestIsValidHex:
    def test_valid_hex(self) -> None:
        assert _is_valid_hex("#FF0000") is True
        assert _is_valid_hex("#00FF00") is True
        assert _is_valid_hex("#0000FF") is True
        assert _is_valid_hex("#888888") is True
        assert _is_valid_hex("#aAbBcC") is True

    def test_invalid_hex_missing_hash(self) -> None:
        assert _is_valid_hex("FF0000") is False

    def test_invalid_hex_wrong_length(self) -> None:
        assert _is_valid_hex("#FFF") is False
        assert _is_valid_hex("#FFFFFFFF") is False

    def test_invalid_hex_not_string(self) -> None:
        assert _is_valid_hex(123) is False  # type: ignore[arg-type]
        assert _is_valid_hex(None) is False  # type: ignore[arg-type]

    def test_invalid_hex_bad_characters(self) -> None:
        assert _is_valid_hex("#GGGGGG") is False
        assert _is_valid_hex("#ZZZZZZ") is False
        assert _is_valid_hex("#!!0000") is False


class TestFormatTime:
    def test_format_td_seconds(self) -> None:
        assert _format_td_seconds(0) == "00:00:00"
        assert _format_td_seconds(30) == "00:00:30"
        assert _format_td_seconds(90) == "00:01:30"
        assert _format_td_seconds(3600) == "01:00:00"
        assert _format_td_seconds(3661) == "01:01:01"

    def test_format_td_short(self) -> None:
        assert _format_td_short(0) == "00:00"
        assert _format_td_short(30) == "00:30"
        assert _format_td_short(90) == "01:30"
        assert _format_td_short(3600) == "01:00:00"
        assert _format_td_short(3661) == "01:01:01"


class TestEmptyGraphPlaceholder:
    def test_scanning(self) -> None:
        snap = UISnapshot(
            latest_bpm=None,
            connected=False,
            connection_status="disconnected",
            connection_error=None,
            scan_status="scanning",
            scan_results=(),
            scan_error=None,
            scan_generation=1,
            ring_buffer=(),
            ring_revision=0,
            session_active=False,
            session_start=None,
            session_data=(),
            session_max=0,
            session_min=0,
            session_sum=0,
            session_count=0,
            zone_times={"Z1": 0.0, "Z2": 0.0, "Z3": 0.0, "Z4": 0.0},
            last_csv_path=None,
            last_csv_error=None,
            pending_export=(),
            recent_sessions=(),
            config=None,
        )
        msg = _empty_graph_placeholder(snap)
        assert "Scanning" in msg

    def test_connecting(self) -> None:
        snap = UISnapshot(
            latest_bpm=None,
            connected=False,
            connection_status="connecting",
            connection_error=None,
            scan_status="idle",
            scan_results=(),
            scan_error=None,
            scan_generation=0,
            ring_buffer=(),
            ring_revision=0,
            session_active=False,
            session_start=None,
            session_data=(),
            session_max=0,
            session_min=0,
            session_sum=0,
            session_count=0,
            zone_times={"Z1": 0.0, "Z2": 0.0, "Z3": 0.0, "Z4": 0.0},
            last_csv_path=None,
            last_csv_error=None,
            pending_export=(),
            recent_sessions=(),
            config={"device_name": "Polar H10"},
        )
        msg = _empty_graph_placeholder(snap)
        assert "Connecting" in msg
        assert "Polar H10" in msg

    def test_error(self) -> None:
        snap = UISnapshot(
            latest_bpm=None,
            connected=False,
            connection_status="error",
            connection_error="Bluetooth is off",
            scan_status="idle",
            scan_results=(),
            scan_error=None,
            scan_generation=0,
            ring_buffer=(),
            ring_revision=0,
            session_active=False,
            session_start=None,
            session_data=(),
            session_max=0,
            session_min=0,
            session_sum=0,
            session_count=0,
            zone_times={"Z1": 0.0, "Z2": 0.0, "Z3": 0.0, "Z4": 0.0},
            last_csv_path=None,
            last_csv_error=None,
            pending_export=(),
            recent_sessions=(),
            config=None,
        )
        msg = _empty_graph_placeholder(snap)
        assert "Bluetooth is off" in msg

    def test_no_data(self) -> None:
        snap = UISnapshot(
            latest_bpm=None,
            connected=False,
            connection_status="disconnected",
            connection_error=None,
            scan_status="idle",
            scan_results=(),
            scan_error=None,
            scan_generation=0,
            ring_buffer=(),
            ring_revision=0,
            session_active=False,
            session_start=None,
            session_data=(),
            session_max=0,
            session_min=0,
            session_sum=0,
            session_count=0,
            zone_times={"Z1": 0.0, "Z2": 0.0, "Z3": 0.0, "Z4": 0.0},
            last_csv_path=None,
            last_csv_error=None,
            pending_export=(),
            recent_sessions=(),
            config=None,
        )
        msg = _empty_graph_placeholder(snap)
        assert "waiting for connection" in msg.lower()
