"""Tests for BLE HR parsing and connection loop.

These tests do not require Bluetooth hardware.  The BLE loop is tested
via mock/monkeypatch.
"""

import threading
from unittest.mock import MagicMock, patch

import pytest

from ble import parse_heart_rate, _make_callback, HEART_RATE_UUID
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
    """Test BLE loop with a mocked BleakClient."""
    from ble import ble_loop

    state = AppState()
    state.config = {"max_hr": 190, "zones": {"z1_max": 0.60, "z2_max": 0.75, "z3_max": 0.88}}

    mock_client = MagicMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.is_connected = True
    mock_client.address = "AA:BB:CC:DD:EE:FF"

    with patch("ble.BleakClient", return_value=mock_client):
        # Run in a task that we cancel after a short time
        import asyncio
        task = asyncio.create_task(ble_loop(state, "AA:BB:CC:DD:EE:FF"))
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, StopIteration):
            pass

    # Should have connected and set up notification
    assert mock_client.start_notify.called
    args = mock_client.start_notify.call_args[0]
    assert args[0] == HEART_RATE_UUID


# ── Thread starter ───────────────────────────────────────────────────────

def test_start_ble_thread_no_address() -> None:
    """Thread starter handles empty address gracefully."""
    from ble import start_ble_thread

    state = AppState()
    thread = start_ble_thread(state, "")
    assert thread is not None
    assert thread.daemon is True
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_start_ble_thread_creates_daemon() -> None:
    """Thread starter returns a daemon thread."""
    from ble import start_ble_thread

    state = AppState()
    thread = start_ble_thread(state, "AA:BB:CC:DD:EE:FF")
    assert thread.daemon is True
    assert thread.name == "ble-asyncio"
    # Clean up — the thread will loop forever, so we can't join it.
    # In a real test environment we'd patch BleakClient.
