#!/usr/bin/env python3
"""HRM Live — macOS menu bar heart rate monitor.

Entry point. Loads config, initializes shared state, starts the BLE
background thread, and runs the
rumps app on the main thread.

On quit the BLE thread is stopped cleanly to avoid CoreBluetooth
callbacks surviving into Python finalization.
"""

from __future__ import annotations

import atexit
import logging
import sys

import config as cfg_mod
from state import AppState
from ui.menubar import HRMBarApp

log = logging.getLogger(__name__)

# Global handle for the BLE manager so the quit handler can stop it.
_ble_manager = None


def main() -> None:
    global _ble_manager

    _setup_logging()

    # Load config
    config = cfg_mod.load_config()
    log.info("Config loaded: max_hr=%s, device=%s",
             config.get("max_hr"), config.get("device_address", "(none)")[:8])

    # Initialize shared state
    state = AppState()
    state.config = config

    # Start the persistent BLE background thread even when no device is saved.
    device_addr = config.get("device_address", "")
    from ble import start_ble_background
    _ble_manager = start_ble_background(state, device_addr)
    if device_addr:
        log.info("BLE thread started with initial device %s", device_addr[:8])
    else:
        log.info("BLE thread started without an initial device")

    # Register atexit shutdown for BLE thread
    atexit.register(_shutdown_ble)

    # Create and run the menu bar app (blocks on main thread)
    app = HRMBarApp(state, ble_manager=_ble_manager)
    log.info("Starting HRM menu bar app...")
    app.run()


def _shutdown_ble() -> None:
    """Stop the BLE background thread if it is running."""
    if _ble_manager is not None:
        from ble import stop_ble_background
        log.info("Shutting down BLE background thread...")
        stop_ble_background(_ble_manager)
        log.info("BLE background thread stopped.")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


if __name__ == "__main__":
    main()
