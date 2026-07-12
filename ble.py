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
from typing import Callable

from bleak import BleakClient
from bleak.exc import BleakError

from state import AppState
from session import record_sample

log = logging.getLogger(__name__)

# Standard BLE Heart Rate Measurement UUID
HEART_RATE_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

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


def start_ble_background(
    state: AppState,
    address: str,
) -> tuple[threading.Thread, threading.Event]:
    """Start the BLE asyncio loop in a background daemon thread.

    Returns ``(thread, stop_event)`` that can be passed to
    ``stop_ble_background()`` for controlled shutdown.

    Does **not** touch AppKit or rumps.
    """
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_run_async_loop,
        args=(state, address, stop_event),
        daemon=True,
        name="ble-asyncio",
    )
    thread.start()
    return thread, stop_event


def stop_ble_background(
    manager: tuple[threading.Thread, threading.Event] | None,
    join_timeout: float = 3.0,
) -> None:
    """Signal a BLE background thread to stop and wait for it.

    If *manager* is ``None`` this is a no-op.
    """
    if manager is None:
        return
    thread, stop_event = manager
    stop_event.set()
    # If the thread is blocked in an asyncio sleep, we need to wake it up.
    # We schedule loop.stop() on the running loop to raise CancelledError.
    # The thread's _run_async_loop will catch the cancellation and exit.
    if thread.is_alive():
        thread.join(timeout=join_timeout)
        if thread.is_alive():
            log.warning("BLE thread did not stop within %.1f seconds", join_timeout)


def _run_async_loop(
    state: AppState,
    address: str,
    stop_event: threading.Event,
) -> None:
    """Run the asyncio event loop in the current thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(ble_loop(state, address, stop_event))
    except asyncio.CancelledError:
        log.info("BLE loop cancelled.")
    finally:
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
