"""BLE heart-rate monitor ingestion and discovery."""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable
from uuid import UUID

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import (
    BleakBluetoothNotAvailableError,
    BleakBluetoothNotAvailableReason,
    BleakError,
)

from session import record_sample
from state import AppState, DiscoveredDevice

log = logging.getLogger(__name__)

# Standard BLE Heart Rate Measurement and Service UUIDs.
HEART_RATE_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
HEART_RATE_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"

DEFAULT_SCAN_TIMEOUT_SECONDS = 8.0
RECONNECT_DELAY_SECONDS = 3.0
_UUID_PARSE_FAIL = object()


@dataclass
class _ScanRecord:
    """Mutable controller-owned cache entry for a discovered device."""

    device: BLEDevice
    discovered: DiscoveredDevice
    last_seen: int


def parse_heart_rate(data: bytearray) -> int | None:
    """Parse BPM from a Heart Rate Measurement payload."""
    if not data or len(data) < 2:
        return None

    flags = data[0]
    if flags & 0x01:
        if len(data) < 3:
            return None
        return int.from_bytes(data[1:3], "little")
    return data[1]


def _make_callback(state: AppState) -> Callable[[int, bytearray], None]:
    """Return a notification callback that updates *state*."""

    def _callback(sender: int, data: bytearray) -> None:
        bpm = parse_heart_rate(data)
        if bpm is None:
            log.warning("Ignored malformed HR payload: %s", data.hex())
            return

        now = datetime.now(timezone.utc)
        state.latest_bpm = bpm
        state.ring_buffer.append((now, bpm))
        if state.session_active:
            record_sample(state, now, bpm)

    return _callback


def _normalize_uuid(value: str | None) -> str | object:
    if not value:
        return _UUID_PARSE_FAIL
    try:
        return str(UUID(str(value))).lower()
    except (TypeError, ValueError, AttributeError):
        return _UUID_PARSE_FAIL


def _advertisement_has_heart_rate_service(
    advertisement: AdvertisementData,
) -> bool:
    normalized_hr = _normalize_uuid(HEART_RATE_SERVICE_UUID)
    for service_uuid in advertisement.service_uuids:
        if _normalize_uuid(service_uuid) == normalized_hr:
            return True
    return False


def _display_name_for_device(device: DiscoveredDevice) -> str:
    if device.name:
        return device.name
    return "Unnamed HR device" if device.heart_rate_capable else "Unnamed BLE device"


def format_discovered_device_label(device: DiscoveredDevice) -> str:
    """Return the string shown in the scan result selector."""
    prefix = "♥ " if device.heart_rate_capable else ""
    rssi = f" ({device.rssi} dBm)" if device.rssi is not None else ""
    return f"{prefix}{_display_name_for_device(device)}{rssi}"


def sort_discovered_devices(
    devices: Iterable[DiscoveredDevice],
) -> tuple[DiscoveredDevice, ...]:
    """Sort confirmed HR devices first, then by RSSI, then by display name."""

    def _key(device: DiscoveredDevice) -> tuple[int, int, str, str]:
        rssi = device.rssi if device.rssi is not None else -10_000
        return (
            0 if device.heart_rate_capable else 1,
            -rssi,
            _display_name_for_device(device).casefold(),
            device.address.casefold(),
        )

    return tuple(sorted(devices, key=_key))


def normalize_discovered_device(
    device: BLEDevice,
    advertisement: AdvertisementData,
) -> DiscoveredDevice | None:
    """Normalize a BLE advertisement into a UI-friendly scan result."""

    name = advertisement.local_name or getattr(device, "name", None) or ""
    heart_rate_capable = _advertisement_has_heart_rate_service(advertisement)
    if not name and not heart_rate_capable:
        return None

    return DiscoveredDevice(
        address=device.address,
        name=name,
        rssi=advertisement.rssi if isinstance(advertisement.rssi, int) else None,
        heart_rate_capable=heart_rate_capable,
    )


def merge_discovered_device(
    existing: _ScanRecord | None,
    device: BLEDevice,
    discovered: DiscoveredDevice,
    sequence: int,
) -> _ScanRecord:
    """Merge a scan update into the controller cache."""

    if existing is None:
        return _ScanRecord(device=device, discovered=discovered, last_seen=sequence)

    name = discovered.name or existing.discovered.name
    heart_rate_capable = existing.discovered.heart_rate_capable or discovered.heart_rate_capable
    if existing.discovered.rssi is None:
        rssi = discovered.rssi
    elif discovered.rssi is None:
        rssi = existing.discovered.rssi
    else:
        rssi = max(existing.discovered.rssi, discovered.rssi)

    merged = DiscoveredDevice(
        address=discovered.address,
        name=name,
        rssi=rssi,
        heart_rate_capable=heart_rate_capable,
    )
    return _ScanRecord(device=device, discovered=merged, last_seen=sequence)


def bluetooth_unavailable_message(
    reason: BleakBluetoothNotAvailableReason | None,
    *,
    action: str,
) -> str:
    """Return the user-facing Bluetooth availability message."""

    if reason == BleakBluetoothNotAvailableReason.POWERED_OFF:
        return f"Bluetooth is off. Turn it on and {action}."
    if reason in {
        BleakBluetoothNotAvailableReason.DENIED_BY_USER,
        BleakBluetoothNotAvailableReason.DENIED_BY_SYSTEM,
        BleakBluetoothNotAvailableReason.DENIED_BY_UNKNOWN,
    }:
        return (
            "Bluetooth access is denied. Allow HRM Live (or Python during "
            "development) in System Settings -> Privacy & Security -> Bluetooth."
        )
    if reason == BleakBluetoothNotAvailableReason.NO_BLUETOOTH:
        return "No Bluetooth adapter is available."
    if reason == BleakBluetoothNotAvailableReason.NO_BLE_CENTRAL_ROLE:
        return "This Mac cannot act as a Bluetooth LE central."
    return "Bluetooth is unavailable. Check Bluetooth and try again."


def scan_failure_message(exc: Exception) -> str:
    if isinstance(exc, BleakBluetoothNotAvailableError):
        return bluetooth_unavailable_message(exc.reason, action="scan again")
    return "Bluetooth scan failed. Try again."


def connection_failure_message(exc: Exception) -> str:
    if isinstance(exc, BleakBluetoothNotAvailableError):
        return bluetooth_unavailable_message(exc.reason, action="try again")
    return "Bluetooth connection failed. Retrying."


async def _sleep_with_stop(stop_event: threading.Event | None, seconds: float) -> None:
    """Sleep in short intervals so stop requests are serviced quickly."""

    deadline = asyncio.get_running_loop().time() + seconds
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return
        await asyncio.sleep(min(0.1, remaining))


async def ble_loop(
    state: AppState,
    address: str,
    stop_event: threading.Event | None = None,
) -> None:
    """Legacy connection loop retained for tests and compatibility."""

    if not address:
        log.info("No device address configured; BLE loop idle.")
        return

    while stop_event is None or not stop_event.is_set():
        exit_now = False
        try:
            state.latest_bpm = None
            state.connected = False
            state.connection_error = None
            state.connection_status = "connecting"
            async with BleakClient(address) as client:
                log.info("Connected to %s", address)
                callback = _make_callback(state)
                await client.start_notify(HEART_RATE_UUID, callback)
                state.connected = True
                state.connection_status = "connected"
                state.connection_error = None
                while client.is_connected and (
                    stop_event is None or not stop_event.is_set()
                ):
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except BleakBluetoothNotAvailableError as exc:
            message = scan_failure_message(exc)
            log.warning("BLE unavailable: %s", message)
            state.connection_status = "error"
            state.connection_error = message
        except (BleakError, OSError, asyncio.TimeoutError) as exc:
            log.warning("BLE error: %s", exc)
            state.connection_status = "error"
            state.connection_error = connection_failure_message(exc)
        except Exception as exc:
            log.exception("Unexpected BLE error: %s", exc)
            state.connection_status = "error"
            state.connection_error = "Bluetooth connection failed. Retrying."
        finally:
            state.connected = False
            state.latest_bpm = None
            if stop_event is not None and stop_event.is_set():
                state.connection_status = "disconnected"
                exit_now = True
            else:
                state.connection_status = "reconnecting"
                await _sleep_with_stop(stop_event, RECONNECT_DELAY_SECONDS)
        if exit_now:
            return


class BLEManager:
    """Handle for the persistent BLE background loop."""

    def __init__(self, state: AppState, initial_address: str = "") -> None:
        self.state = state
        self.initial_address = initial_address
        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.scan_task: asyncio.Task[Any] | None = None
        self.connection_task: asyncio.Task[Any] | None = None
        self._scan_records: dict[str, _ScanRecord] = {}
        self._scan_sequence = 0
        self._scan_lock = threading.Lock()
        self._connection_generation = 0
        self._connection_address = ""
        self._connection_device: BLEDevice | None = None
        self._shutdown_requested = False

    @property
    def task(self) -> asyncio.Task[Any] | None:
        """Compatibility alias for the connection task."""

        return self.connection_task

    @task.setter
    def task(self, value: asyncio.Task[Any] | None) -> None:
        self.connection_task = value

    def start_scan(self, timeout: float = DEFAULT_SCAN_TIMEOUT_SECONDS) -> None:
        """Start a BLE scan on the controller loop."""

        if not self._loop_ready():
            return

        def _start() -> None:
            if self._shutdown_requested:
                return
            if self.scan_task is not None and not self.scan_task.done():
                return
            self.scan_task = self.loop.create_task(self._scan_worker(timeout))  # type: ignore[union-attr]

        self.loop.call_soon_threadsafe(_start)  # type: ignore[union-attr]

    def cancel_scan(self) -> None:
        """Cancel the active scan without affecting the connection task."""

        if not self._loop_ready():
            return

        def _cancel() -> None:
            if self.scan_task is not None and not self.scan_task.done():
                self.scan_task.cancel()

        self.loop.call_soon_threadsafe(_cancel)  # type: ignore[union-attr]

    def connect(
        self,
        address: str,
        cached_device: BLEDevice | None = None,
    ) -> None:
        """Start or replace the active connection task."""

        if not address:
            self.disconnect()
            return
        if not self._loop_ready():
            return

        def _queue() -> None:
            if self._shutdown_requested:
                return
            if (
                self.connection_task is not None
                and not self.connection_task.done()
                and self._connection_address == address
            ):
                return
            self.loop.create_task(  # type: ignore[union-attr]
                self._replace_connection_task(address, cached_device)
            )

        self.loop.call_soon_threadsafe(_queue)  # type: ignore[union-attr]

    def disconnect(self) -> None:
        """Cancel the active connection task only."""

        if not self._loop_ready():
            self.state.latest_bpm = None
            self.state.connected = False
            self.state.connection_status = "disconnected"
            self.state.connection_error = None
            return

        def _queue() -> None:
            if self._shutdown_requested:
                return
            self.loop.create_task(self._disconnect_connection_task())  # type: ignore[union-attr]

        self.loop.call_soon_threadsafe(_queue)  # type: ignore[union-attr]

    def shutdown(self, join_timeout: float = 3.0) -> None:
        """Cancel all work, stop the loop, and join the background thread."""

        self.stop_event.set()
        if self._loop_ready():

            def _queue() -> None:
                if self._shutdown_requested:
                    return
                self.loop.create_task(self._shutdown_async())  # type: ignore[union-attr]

            try:
                self.loop.call_soon_threadsafe(_queue)  # type: ignore[union-attr]
            except RuntimeError:
                pass

        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=join_timeout)
            if self.thread.is_alive():
                log.warning(
                    "BLE thread did not stop within %.1f seconds", join_timeout
                )

    def get_cached_device(self, address: str) -> BLEDevice | None:
        """Return the last BLEDevice object seen for *address*."""

        with self._scan_lock:
            record = self._scan_records.get(address)
            return record.device if record is not None else None

    def _loop_thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        self.ready_event.set()
        if self.stop_event.is_set() or self._shutdown_requested:
            loop.call_soon(loop.stop)
        elif self.initial_address:
            loop.call_soon(self._bootstrap_initial_connection)
        try:
            loop.run_forever()
        finally:
            try:
                pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                log.debug("BLE loop cleanup failed", exc_info=True)
            finally:
                loop.close()
                log.info("BLE event loop closed.")

    def _bootstrap_initial_connection(self) -> None:
        if self._shutdown_requested or not self.initial_address:
            return
        self._start_connection_now(self.initial_address, None)

    def _start_connection_now(
        self,
        address: str,
        cached_device: BLEDevice | None,
    ) -> None:
        self._connection_generation += 1
        generation = self._connection_generation
        self._connection_address = address
        self._connection_device = cached_device
        self.state.latest_bpm = None
        self.state.connected = False
        self.state.connection_error = None
        self.state.connection_status = "connecting"
        self.connection_task = self.loop.create_task(  # type: ignore[union-attr]
            self._connection_worker(address, cached_device, generation)
        )

    async def _replace_connection_task(
        self,
        address: str,
        cached_device: BLEDevice | None,
    ) -> None:
        self._connection_generation += 1
        generation = self._connection_generation
        self.state.latest_bpm = None
        self.state.connected = False
        self.state.connection_error = None
        self.state.connection_status = "connecting"

        old_task = self.connection_task
        if old_task is not None and not old_task.done():
            old_task.cancel()
            await asyncio.gather(old_task, return_exceptions=True)

        if self._shutdown_requested or generation != self._connection_generation:
            return
        self._start_connection_now(address, cached_device)

    async def _disconnect_connection_task(self) -> None:
        self._connection_generation += 1
        generation = self._connection_generation
        old_task = self.connection_task
        if old_task is not None and not old_task.done():
            old_task.cancel()
            await asyncio.gather(old_task, return_exceptions=True)

        if generation != self._connection_generation:
            return

        self.connection_task = None
        self._connection_address = ""
        self._connection_device = None
        self.state.latest_bpm = None
        self.state.connected = False
        self.state.connection_status = "disconnected"
        self.state.connection_error = None

    async def _shutdown_async(self) -> None:
        self._shutdown_requested = True
        tasks = [
            task
            for task in (self.scan_task, self.connection_task)
            if task is not None and not task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self.scan_task = None
        self.connection_task = None
        self.state.connected = False
        self.state.latest_bpm = None
        self.state.connection_status = "disconnected"
        self.loop.stop()  # type: ignore[union-attr]

    async def _scan_worker(self, timeout: float) -> None:
        with self._scan_lock:
            self._scan_records = {}
        self.state.scan_results = ()
        self.state.scan_error = None
        self.state.scan_status = "scanning"
        self.state.scan_generation += 1
        task = asyncio.current_task()

        def detection_callback(device: BLEDevice, advertisement: AdvertisementData) -> None:
            try:
                self._record_scan_update(device, advertisement)
            except Exception:
                log.exception("Failed to process BLE scan callback")

        try:
            scanner = BleakScanner(
                detection_callback=detection_callback,
                scanning_mode="active",
            )
            async with scanner:
                await asyncio.sleep(timeout)
            self.state.scan_status = "complete"
            self.state.scan_error = None
            self.state.scan_generation += 1
        except asyncio.CancelledError:
            self.state.scan_status = "cancelled"
            self.state.scan_generation += 1
            raise
        except BleakBluetoothNotAvailableError as exc:
            message = scan_failure_message(exc)
            log.warning("BLE scan unavailable: %s", message)
            self.state.scan_status = "error"
            self.state.scan_error = message
            self.state.scan_generation += 1
        except (BleakError, OSError, asyncio.TimeoutError) as exc:
            log.warning("BLE scan error: %s", exc)
            self.state.scan_status = "error"
            self.state.scan_error = scan_failure_message(exc)
            self.state.scan_generation += 1
        except Exception as exc:
            log.exception("Unexpected BLE scan error: %s", exc)
            self.state.scan_status = "error"
            self.state.scan_error = "Bluetooth scan failed. Try again."
            self.state.scan_generation += 1
        finally:
            if self.scan_task is task:
                self.scan_task = None

    def _record_scan_update(
        self,
        device: BLEDevice,
        advertisement: AdvertisementData,
    ) -> None:
        discovered = normalize_discovered_device(device, advertisement)
        if discovered is None:
            return

        with self._scan_lock:
            self._scan_sequence += 1
            existing = self._scan_records.get(device.address)
            merged = merge_discovered_device(
                existing,
                device,
                discovered,
                self._scan_sequence,
            )
            if existing is None or merged.discovered != existing.discovered:
                self._scan_records[device.address] = merged
                self.state.scan_results = sort_discovered_devices(
                    record.discovered for record in self._scan_records.values()
                )
                self.state.scan_generation += 1
            else:
                existing.device = device
                existing.last_seen = self._scan_sequence

    async def _connection_worker(
        self,
        address: str,
        cached_device: BLEDevice | None,
        generation: int,
    ) -> None:
        try:
            while (
                not self.stop_event.is_set()
                and not self._shutdown_requested
                and generation == self._connection_generation
            ):
                exit_now = False
                generation_changed = False
                try:
                    client_target: BLEDevice | str = cached_device or address
                    async with BleakClient(client_target) as client:
                        log.info("Connected to %s", address)
                        callback = _make_callback(self.state)
                        await client.start_notify(HEART_RATE_UUID, callback)
                        self.state.connected = True
                        self.state.connection_status = "connected"
                        self.state.connection_error = None
                        while (
                            client.is_connected
                            and not self.stop_event.is_set()
                            and not self._shutdown_requested
                            and generation == self._connection_generation
                        ):
                            await asyncio.sleep(1)
                except asyncio.CancelledError:
                    raise
                except BleakBluetoothNotAvailableError as exc:
                    message = connection_failure_message(exc)
                    log.warning("BLE unavailable: %s", message)
                    self.state.connection_status = "error"
                    self.state.connection_error = message
                except (BleakError, OSError, asyncio.TimeoutError) as exc:
                    message = connection_failure_message(exc)
                    log.warning("BLE error: %s", exc)
                    self.state.connection_status = "error"
                    self.state.connection_error = message
                except Exception as exc:
                    log.exception("Unexpected BLE error: %s", exc)
                    self.state.connection_status = "error"
                    self.state.connection_error = "Bluetooth connection failed. Retrying."
                finally:
                    self.state.connected = False
                    self.state.latest_bpm = None
                    if self.stop_event.is_set() or self._shutdown_requested:
                        self.state.connection_status = "disconnected"
                        self.state.connection_error = None
                        exit_now = True
                    elif generation != self._connection_generation:
                        generation_changed = True
                    else:
                        if self.state.connection_error is None:
                            self.state.connection_error = "Connection lost. Retrying."
                        self.state.connection_status = "reconnecting"
                        await _sleep_with_stop(self.stop_event, RECONNECT_DELAY_SECONDS)
                if exit_now or generation_changed:
                    return
        finally:
            if (
                self.connection_task is asyncio.current_task()
                and generation == self._connection_generation
            ):
                self.connection_task = None
                self._connection_address = ""
                self._connection_device = None

    def _loop_ready(self) -> bool:
        return self.loop is not None and self.ready_event.is_set()


def start_ble_background(state: AppState, address: str = "") -> BLEManager:
    """Start the persistent BLE background loop in a daemon thread."""

    manager = BLEManager(state, initial_address=address)
    thread = threading.Thread(
        target=manager._loop_thread_main,
        daemon=True,
        name="ble-asyncio",
    )
    manager.thread = thread
    thread.start()
    return manager


def stop_ble_background(
    manager: BLEManager | None,
    join_timeout: float = 3.0,
) -> None:
    """Signal a BLE background thread to stop and wait for it."""

    if manager is None:
        return
    manager.shutdown(join_timeout=join_timeout)
