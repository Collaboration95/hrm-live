"""Tests for BLE HR parsing and connection loop.

These tests do not require Bluetooth hardware.  The BLE loop is tested
via mock/monkeypatch.  No real BleakClient is ever instantiated.
"""

import asyncio
import threading
from dataclasses import dataclass
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ble import (
    BLEManager,
    HEART_RATE_SERVICE_UUID,
    parse_heart_rate,
    _make_callback,
    HEART_RATE_UUID,
    bluetooth_unavailable_message,
    connection_failure_message,
    format_discovered_device_label,
    normalize_discovered_device,
    start_ble_background,
    stop_ble_background,
    scan_failure_message,
    sort_discovered_devices,
)
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakBluetoothNotAvailableReason
from state import AppState
from state import DiscoveredDevice


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


# ── Discovery helpers ───────────────────────────────────────────────────


def test_normalize_discovered_device_for_named_device() -> None:
    device = _device("ADDR-1", "Runner Pod")
    advertisement = _advertisement(local_name="Runner Pod", service_uuids=[], rssi=-61)
    discovered = normalize_discovered_device(device, advertisement)

    assert discovered is not None
    assert discovered.address == "ADDR-1"
    assert discovered.name == "Runner Pod"
    assert discovered.rssi == -61
    assert discovered.heart_rate_capable is False


def test_normalize_discovered_device_for_unnamed_hr_device() -> None:
    device = _device("ADDR-2", None)
    advertisement = _advertisement(
        local_name=None,
        service_uuids=[HEART_RATE_SERVICE_UUID],
        rssi=-48,
    )
    discovered = normalize_discovered_device(device, advertisement)

    assert discovered is not None
    assert discovered.name == ""
    assert discovered.heart_rate_capable is True


def test_normalize_discovered_device_filters_unnamed_non_hr() -> None:
    device = _device("ADDR-3", None)
    advertisement = _advertisement(local_name=None, service_uuids=[], rssi=-80)

    assert normalize_discovered_device(device, advertisement) is None


def test_sort_discovered_devices_prioritizes_hr_then_rssi() -> None:
    devices = (
        DiscoveredDevice("ADDR-1", "Runner Pod", -61, False),
        DiscoveredDevice("ADDR-2", "", -48, True),
        DiscoveredDevice("ADDR-3", "Alpha", -33, True),
    )

    ordered = sort_discovered_devices(devices)

    assert [device.address for device in ordered] == ["ADDR-3", "ADDR-2", "ADDR-1"]


def test_format_discovered_device_label_uses_fallback_names() -> None:
    unnamed_hr = DiscoveredDevice("ADDR-2", "", -48, True)
    unnamed_ble = DiscoveredDevice("ADDR-4", "", None, False)

    assert format_discovered_device_label(unnamed_hr) == "♥ Unnamed HR device (-48 dBm)"
    assert format_discovered_device_label(unnamed_ble) == "Unnamed BLE device"


def test_bluetooth_unavailable_messages_are_concise() -> None:
    assert "Bluetooth is off" in bluetooth_unavailable_message(
        BleakBluetoothNotAvailableReason.POWERED_OFF,
        action="scan again",
    )
    assert scan_failure_message(RuntimeError("boom")) == "Bluetooth scan failed. Try again."
    assert connection_failure_message(RuntimeError("boom")) == "Bluetooth connection failed. Retrying."


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


# ── Scan controller ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_worker_publishes_incremental_results() -> None:
    state = AppState()
    manager = BLEManager(state)

    with patch("ble.BleakScanner", FakeScanner):
        await manager._scan_worker(0.0)

    assert state.scan_status == "complete"
    assert state.scan_error is None
    assert state.scan_generation >= 3
    assert [device.address for device in state.scan_results] == ["ADDR-2", "ADDR-1"]
    assert state.scan_results[0].name == "Polar H10"
    assert state.scan_results[0].heart_rate_capable is True
    assert manager.get_cached_device("ADDR-2") is not None


@pytest.mark.asyncio
async def test_scan_cancel_sets_cancelled_without_touching_connection() -> None:
    state = AppState()
    state.connection_status = "connected"
    manager = BLEManager(state)

    with patch("ble.BleakScanner", FakeScanner):
        task = asyncio.create_task(manager._scan_worker(1.0))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert state.scan_status == "cancelled"
    assert state.connection_status == "connected"


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
    """Thread starter keeps the controller loop alive without a device."""
    state = AppState()
    mgr = start_ble_background(state, "")
    assert mgr is not None
    assert mgr.thread.daemon is True
    assert mgr.thread.name == "ble-asyncio"
    assert mgr.ready_event.wait(timeout=2)
    assert mgr.thread.is_alive()
    stop_ble_background(mgr)
    assert not mgr.thread.is_alive()


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
        assert mgr.thread.daemon is True
        assert mgr.thread.name == "ble-asyncio"
        assert mgr.ready_event.wait(timeout=2)

        # Wait a tiny bit for the async loop to start
        import time
        time.sleep(0.2)

        # Stop cleanly
        stop_ble_background(mgr, join_timeout=2)
        assert mgr.stop_event.is_set()
        assert not mgr.thread.is_alive()


def test_connect_uses_cached_ble_device_when_available() -> None:
    state = AppState()
    mgr = start_ble_background(state, "")

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.is_connected = False
    cached_device = _device("AA:BB:CC:DD:EE:FF", "Polar H10")

    with patch("ble.BleakClient", return_value=mock_client) as client_ctor:
        assert mgr.ready_event.wait(timeout=2)
        mgr.connect("AA:BB:CC:DD:EE:FF", cached_device=cached_device)
        import time

        time.sleep(0.2)
        stop_ble_background(mgr, join_timeout=2)

    assert client_ctor.call_args is not None
    assert client_ctor.call_args[0][0] is cached_device


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
        assert mgr.stop_event.is_set()
        assert not mgr.thread.is_alive()


def test_stop_ble_background_cancels_loop_task() -> None:
    """stop_ble_background asks the owning event loop to cancel the BLE task."""
    state = AppState()

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.is_connected = True

    with patch("ble.BleakClient", return_value=mock_client):
        mgr = start_ble_background(state, "AA:BB:CC:DD:EE:FF")
        assert mgr.ready_event.wait(timeout=2)
        stop_ble_background(mgr, join_timeout=3)

    assert mgr.stop_event.is_set()
    assert not mgr.thread.is_alive()
    assert mgr.task is None or mgr.task.done()
# ── Test helpers ────────────────────────────────────────────────────────


def _device(address: str, name: str | None = None) -> BLEDevice:
    return BLEDevice(address, name, None)


def _advertisement(
    *,
    local_name: str | None,
    service_uuids: list[str],
    rssi: int,
) -> AdvertisementData:
    return AdvertisementData(
        local_name=local_name,
        manufacturer_data={},
        service_data={},
        service_uuids=service_uuids,
        tx_power=None,
        rssi=rssi,
        platform_data=(),
    )


@dataclass
class FakeScanner:
    detection_callback: Callable[[BLEDevice, AdvertisementData], None] | None = None
    scanning_mode: str = "active"

    async def __aenter__(self):
        if self.detection_callback is not None:
            self.detection_callback(
                _device("ADDR-1", "Runner Pod"),
                _advertisement(local_name="Runner Pod", service_uuids=[], rssi=-61),
            )
            self.detection_callback(
                _device("ADDR-2", None),
                _advertisement(
                    local_name=None,
                    service_uuids=[HEART_RATE_SERVICE_UUID],
                    rssi=-48,
                ),
            )
            self.detection_callback(
                _device("ADDR-2", "Polar H10"),
                _advertisement(
                    local_name="Polar H10",
                    service_uuids=[HEART_RATE_SERVICE_UUID],
                    rssi=-83,
                ),
            )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False
