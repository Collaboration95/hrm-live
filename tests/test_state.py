"""Tests for AppState synchronization and snapshots."""

from datetime import UTC, datetime
from threading import Thread

from hrm_live.state import AppState, DiscoveredDevice


def test_default_initialization() -> None:
    s = AppState()
    assert s.latest_bpm is None
    assert s.connected is False
    assert s.connection_status == "disconnected"
    assert s.connection_error is None
    assert s.scan_status == "idle"
    assert s.scan_results == ()
    assert s.scan_error is None
    assert s.scan_generation == 0
    assert len(s.ring_buffer) == 0
    assert s.ring_buffer.maxlen == 600
    assert s.session_active is False
    assert s.session_start is None
    assert s.session_data == []
    assert s.session_max == 0
    assert s.session_min == 999
    assert s.session_sum == 0
    assert s.session_count == 0
    assert s.zone_times == {"Z1": 0.0, "Z2": 0.0, "Z3": 0.0, "Z4": 0.0}
    assert s.last_csv_path is None
    assert s.last_csv_error is None
    assert s.config is None


def test_ring_buffer_maxlen() -> None:
    s = AppState()
    assert s.ring_buffer.maxlen == 600


def test_ring_buffer_overflow() -> None:
    s = AppState()
    for i in range(700):
        s.record_bpm(datetime.now(UTC), 100 + (i % 50))
    snapshot = s.snapshot_for_ui()
    assert len(snapshot.ring_buffer) == 600


def test_discovered_device_is_frozen() -> None:
    device = DiscoveredDevice("addr", "name", -40, True)
    assert device.address == "addr"
    assert device.name == "name"
    assert device.rssi == -40
    assert device.heart_rate_capable is True


def test_snapshot_copies_ring_buffer() -> None:
    s = AppState()
    ts = datetime.now(UTC)
    s.record_bpm(ts, 120)
    snapshot = s.snapshot_for_ui()
    s.record_bpm(ts, 130)

    assert snapshot.ring_buffer == ((ts, 120),)
    assert len(s.snapshot_for_ui().ring_buffer) == 2


def test_fast_producer_and_snapshots_do_not_mutate_during_iteration() -> None:
    s = AppState()

    def produce() -> None:
        for i in range(2_000):
            s.record_bpm(datetime.now(UTC), 100 + (i % 80))

    producer = Thread(target=produce)
    producer.start()
    for _ in range(500):
        snapshot = s.snapshot_for_ui()
        tuple(snapshot.ring_buffer)
    producer.join(timeout=2)

    assert not producer.is_alive()
    assert len(s.snapshot_for_ui().ring_buffer) <= 600
