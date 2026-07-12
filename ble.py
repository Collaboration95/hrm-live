"""BLE heart-rate monitor ingestion.

Handles the GATT Heart Rate Measurement characteristic (0x2A37),
parses 8-bit and 16-bit BPM payloads, and runs a background asyncio
event loop with auto-reconnect.
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


async def ble_loop(state: AppState, address: str) -> None:
    """Async BLE connection loop with auto-reconnect.

    Runs forever, connecting and reconnecting to *address*.
    Sets ``state.connected = True`` only when notifications are active.
    """
    if not address:
        log.info("No device address configured; BLE loop idle.")
        return

    while True:
        try:
            async with BleakClient(address) as client:
                log.info("Connected to %s", address)
                state.connected = True
                callback = _make_callback(state)
                await client.start_notify(HEART_RATE_UUID, callback)
                while client.is_connected:
                    await asyncio.sleep(1)
        except (BleakError, OSError, asyncio.TimeoutError) as exc:
            log.warning("BLE error: %s", exc)
        except Exception as exc:
            log.exception("Unexpected BLE error: %s", exc)
        finally:
            state.connected = False
            log.info("Disconnected; retrying in 3 seconds...")
            await asyncio.sleep(3)


# ── Thread starter ───────────────────────────────────────────────────────


def start_ble_thread(state: AppState, address: str) -> threading.Thread:
    """Start the BLE asyncio loop in a dedicated daemon thread.

    Returns the thread handle (already started).  Does **not** touch
    AppKit or rumps.
    """
    thread = threading.Thread(
        target=_run_async_loop,
        args=(state, address),
        daemon=True,
        name="ble-asyncio",
    )
    thread.start()
    return thread


def _run_async_loop(state: AppState, address: str) -> None:
    """Run the asyncio event loop in the current thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(ble_loop(state, address))
    finally:
        loop.close()
