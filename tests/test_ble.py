"""Tests for BLE HR parsing and connection loop.

These tests do not require Bluetooth hardware.  The BLE loop is tested
via mock/monkeypatch.  No real BleakClient is ever instantiated.
"""

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ble import (
    parse_heart_rate,
    _make_callback,
    HEART_RATE_UUID,
    start_ble_background,
    stop_ble_background,
)
from state import AppState


# ── Parsing ─────────────────────────────────────────────────────────────


def test_parse_8bit_bpm() -> None:
    """Bit 0 = 0 → BPM is data[1]."""
    data = bytearray([0x00, 0x7F])  # flags=0, bpm=127
    assert parse_heart_rate(data) == 127


def test_parse_8bit_bpm_zero() -> None:
    data = bytearray([0x00, 0x00])
    assert parse_heart_rate(data) == 0


def test_parse_8bit_bpm_max() -> None:
    data = bytearray([0x00, 0xFF])
    assert parse_heart_rate(data) == 255


def test_parse_16bit_bpm() -> None:
    """Bit 0 = 1 → BPM is uint16 little-endian at data[1:3]."""
    data = bytearray([0x01, 0x8C, 0x00])  # 0x008C = 140
    assert parse_heart_rate(data) == 140


def test_parse_16bit_bpm_high() -> None:
    data = bytearray([0x01, 0xE8, 0x03])  # 0x03E8 = 1000
    assert parse_heart_rate(data) == 1000


def test_parse_empty_payload() -> None:
    assert parse_heart_rate(bytearray()) is None


def test_parse_too_short_8bit() -> None:
    # Only flags byte, no BPM
    data = bytearray([0x00])
    assert parse_heart_rate(data) is None


def test_parse_too_short_16bit() -> None:
    # flags=0x01, but only 1 byte of data after flags
    data = bytearray([0x01, 0x8C])
    assert parse_heart_rate(data) is None


# ── Callback integration ────────────────────────────────────────────────


def test_callback_updates_state() -> None:
    state = AppState()
    cb = _make_callback(state)
    cb(0, bytearray([0x00, 0x55]))  # 85 BPM
    assert state.latest_bpm == 85
    assert len(state.ring_buffer) == 1
    assert state.ring_buffer[0][1] == 85


def test_callback_malformed_does_not_crash() -> None:
    state = AppState()
    state.latest_bpm = 72
    cb = _make_callback(state)
    cb(0, bytearray([0x00]))  # too short
    # State should be unchanged
    assert state.latest_bpm == 72
    assert len(state.ring_buffer) == 0


def test_callback_multiple_samples() -> None:
    state = AppState()
    cb = _make_callback(state)
    for bpm in range(60, 180, 10):
        cb(0, bytearray([0x00, bpm]))
    assert len(state.ring_buffer) == 12
    assert state.latest_bpm == 170


def test_callback_ring_buffer_capped() -> None:
    state = AppState()
    cb = _make_callback(state)
    for i in range(1000):
        cb(0, bytearray([0x00, 100 + (i % 50)]))
    assert len(state.ring_buffer) == 600


# ── BLE loop mock tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ble_loop_no_address() -> None:
    """BLE loop returns immediately when address is empty."""
    from ble import ble_loop

    state = AppState()
    await ble_loop(state, "")
    # Should not crash, should not connect


@pytest.mark.asyncio
async def test_ble_loop_connect_and_notify() -> None:
    """Test BLE loop with a mocked BleakClient and stop via cancellation."""
    from ble import ble_loop

    state = AppState()
    state.config = {
        "max_hr": 190,
        "zones": {"z1_max": 0.60, "z2_max": 0.75, "z3_max": 0.88},
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.is_connected = True
    mock_client.address = "AA:BB:CC:DD:EE:FF"

    stop_event = threading.Event()

    with patch("ble.BleakClient", return_value=mock_client):
        task = asyncio.create_task(
            ble_loop(state, "AA:BB:CC:DD:EE:FF", stop_event)
        )
        await asyncio.sleep(0.1)
        stop_event.set()
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, StopIteration):
            pass

    # Should have connected and set up notification
    assert mock_client.start_notify.called
    args = mock_client.start_notify.call_args[0]
    assert args[0] == HEART_RATE_UUID


# ── Thread lifecycle ────────────────────────────────────────────────────


def test_start_ble_background_no_address() -> None:
    """Thread starter handles empty address gracefully and stops cleanly."""
    state = AppState()
    mgr = start_ble_background(state, "")
    assert mgr is not None
    thread, stop_event = mgr
    assert thread.daemon is True
    assert thread.name == "ble-asyncio"
    # Thread should exit quickly since address is empty
    thread.join(timeout=2)
    assert not thread.is_alive()
    stop_ble_background(mgr)


def test_start_ble_background_creates_daemon() -> None:
    """Thread starter returns a daemon thread with stop capability."""
    state = AppState()

    # Create an async mock client
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.is_connected = False  # Don't enter notify loop

    with patch("ble.BleakClient", return_value=mock_client):
        mgr = start_ble_background(state, "AA:BB:CC:DD:EE:FF")
        assert mgr is not None
        thread, stop_event = mgr
        assert thread.daemon is True
        assert thread.name == "ble-asyncio"

        # Wait a tiny bit for the async loop to start
        import time
        time.sleep(0.2)

        # Stop cleanly
        stop_ble_background(mgr, join_timeout=2)
        assert not thread.is_alive()


def test_stop_ble_background_none() -> None:
    """stop_ble_background(None) is a no-op."""
    stop_ble_background(None)  # should not raise


def test_ble_loop_stops_on_stop_event() -> None:
    """The BLE loop returns when stop_event is set (not via cancellation)."""
    state = AppState()
    stop_event = threading.Event()

    # Create an async mock client that keeps is_connected=True
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.is_connected = True

    with patch("ble.BleakClient", return_value=mock_client):
        mgr = start_ble_background(state, "AA:BB:CC:DD:EE:FF")
        import time
        time.sleep(0.3)

        # Stop should cause ble_loop to exit on its own
        stop_ble_background(mgr, join_timeout=3)
        thread, _ = mgr
        assert not thread.is_alive()
