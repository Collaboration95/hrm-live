"""BLE heart-rate monitor ingestion.

Handles the GATT Heart Rate Measurement characteristic (0x2A37),
parses 8-bit and 16-bit BPM payloads, and runs a background asyncio
event loop with auto-reconnect.

Lifecycle
---------
Use ``start_ble_background(state, address)`` to start the thread.
Use ``stop_ble_background(manager)`` to cleanly shut it down.
The manager tuple ``(thread, stop_event)`` is returned by start.
"""

from __future__ import annotations

import asyncio
import threading
import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Callable

from bleak import BleakClient
from bleak.exc import BleakError

from state import AppState
from session import record_sample

log = logging.getLogger(__name__)

# Standard BLE Heart Rate Measurement UUID
HEART_RATE_UUID = "00002a37-0000-1000-8000-00805f9b34fb"


@dataclass
class BLEManager:
    """Handle for a running BLE background loop."""

    thread: threading.Thread
    stop_event: threading.Event
    ready_event: threading.Event
    loop: asyncio.AbstractEventLoop | None = None
    task: asyncio.Task | None = None

# ── Parsing ──────────────────────────────────────────────────────────────


def parse_heart_rate(data: bytearray) -> int | None:
    """Parse BPM from a Heart Rate Measurement payload.

    Returns the BPM integer, or ``None`` for malformed packets.

    Byte 0: flags
      bit 0: 0 = 8-bit BPM at data[1]; 1 = 16-bit LE at data[1:3]
    """
    if not data or len(data) < 2:
        return None

    flags = data[0]
    if flags & 0x01:
        # 16-bit little-endian
        if len(data) < 3:
            return None
        return int.from_bytes(data[1:3], "little")
    else:
        # 8-bit
        return data[1]


# ── Callback ─────────────────────────────────────────────────────────────


def _make_callback(state: AppState) -> Callable:
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


# ── BLE loop ─────────────────────────────────────────────────────────────


async def ble_loop(
    state: AppState,
    address: str,
    stop_event: threading.Event | None = None,
) -> None:
    """Async BLE connection loop with auto-reconnect.

    Connects to *address* and maintains the connection.  When
    disconnected it waits 3 seconds and retries.  Loops until
    *stop_event* is set.
    """
    if not address:
        log.info("No device address configured; BLE loop idle.")
        return

    def should_stop() -> bool:
        return stop_event is not None and stop_event.is_set()

    while not should_stop():
        try:
            async with BleakClient(address) as client:
                log.info("Connected to %s", address)
                state.connected = True
                callback = _make_callback(state)
                await client.start_notify(HEART_RATE_UUID, callback)
                while client.is_connected and not should_stop():
                    await asyncio.sleep(1)
        except (BleakError, OSError, asyncio.TimeoutError) as exc:
            log.warning("BLE error: %s", exc)
        except Exception as exc:
            log.exception("Unexpected BLE error: %s", exc)
        finally:
            state.connected = False
            if not should_stop():
                log.info("Disconnected; retrying in 3 seconds...")
                # Sleep in short intervals so we respond promptly to stop_event
                for _ in range(30):
                    if should_stop():
                        return
                    await asyncio.sleep(0.1)


# ── Lifecycle manager ───────────────────────────────────────────────────


def start_ble_background(state: AppState, address: str) -> BLEManager:
    """Start the BLE asyncio loop in a background daemon thread.

    Returns a ``BLEManager`` that can be passed to ``stop_ble_background()``
    for controlled shutdown.

    Does **not** touch AppKit or rumps.
    """
    manager = BLEManager(
        thread=None,  # type: ignore[arg-type]
        stop_event=threading.Event(),
        ready_event=threading.Event(),
    )
    thread = threading.Thread(
        target=_run_async_loop,
        args=(state, address, manager),
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
    """Signal a BLE background thread to stop and wait for it.

    If *manager* is ``None`` this is a no-op.
    """
    if manager is None:
        return

    manager.stop_event.set()

    if manager.ready_event.wait(timeout=0.5) and manager.loop is not None:
        def _cancel_task() -> None:
            if manager.task is not None and not manager.task.done():
                manager.task.cancel()

        try:
            manager.loop.call_soon_threadsafe(_cancel_task)
        except RuntimeError:
            # Loop may already be closed by a fast failure or empty-address exit.
            pass

    if manager.thread.is_alive():
        manager.thread.join(timeout=join_timeout)
        if manager.thread.is_alive():
            log.warning("BLE thread did not stop within %.1f seconds", join_timeout)


def _run_async_loop(
    state: AppState,
    address: str,
    manager: BLEManager,
) -> None:
    """Run the asyncio event loop in the current thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    manager.loop = loop
    try:
        manager.task = loop.create_task(ble_loop(state, address, manager.stop_event))
        manager.ready_event.set()
        loop.run_until_complete(manager.task)
    except asyncio.CancelledError:
        log.info("BLE loop cancelled.")
    finally:
        manager.stop_event.set()
        # Cancel any pending tasks and close the loop
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
        except Exception:
            pass
        loop.close()
        log.info("BLE event loop closed.")
