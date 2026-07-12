#!/usr/bin/env python3
"""HRM Live — macOS menu bar heart rate monitor.

Entry point. Loads config, initializes shared state, starts the BLE
background thread (if a device address is configured), and runs the
rumps app on the main thread.
"""

from __future__ import annotations

import logging
import sys

import config as cfg_mod
from state import AppState
from ui.menubar import HRMBarApp

log = logging.getLogger(__name__)


def main() -> None:
    _setup_logging()

    # Load config
    config = cfg_mod.load_config()
    log.info("Config loaded: max_hr=%s, device=%s",
             config.get("max_hr"), config.get("device_address", "(none)")[:8])

    # Initialize shared state
    state = AppState()
    state.config = config

    # Start BLE background thread if a device address is configured
    device_addr = config.get("device_address", "")
    if device_addr:
        from ble import start_ble_thread
        start_ble_thread(state, device_addr)
        log.info("BLE thread started for %s", device_addr[:8])
    else:
        log.info("No device address configured — BLE thread not started")

    # Create and run the menu bar app (blocks on main thread)
    app = HRMBarApp(state)
    log.info("Starting HRM menu bar app...")
    app.run()


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


if __name__ == "__main__":
    main()
