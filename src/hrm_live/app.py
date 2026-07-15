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

import hrm_live.config as cfg_mod
from hrm_live.ble import start_ble_background
from hrm_live.state import AppState
from hrm_live.ui.menubar import HRMBarApp

log = logging.getLogger(__name__)

# Global app handle lets atexit reuse the same guarded shutdown path.
_app: HRMBarApp | None = None


def main() -> None:
    global _app

    _setup_logging()

    # Load config
    config = cfg_mod.load_config()
    log.info(
        "Config loaded: max_hr=%s, device=%s",
        config.get("max_hr"),
        config.get("device_address", "(none)")[:8],
    )

    # Initialize shared state
    state = AppState()
    state.set_config(config)

    # Start the persistent BLE background thread even when no device is saved.
    device_addr = config.get("device_address", "")
    ble_manager = start_ble_background(state, device_addr)
    if device_addr:
        log.info("BLE thread started with initial device %s", device_addr[:8])
    else:
        log.info("BLE thread started without an initial device")

    # atexit is only a safety net; visible UI quit routes call app.shutdown().
    atexit.register(_shutdown_app)

    # Create and run the menu bar app (blocks on main thread)
    app = HRMBarApp(state, ble_manager=ble_manager)
    _app = app
    log.info("Starting HRM menu bar app...")
    app.run()


def _shutdown_app() -> None:
    """Stop background work if Python exits outside the normal Quit action."""

    if _app is not None:
        _app.shutdown(request_quit=False)


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


if __name__ == "__main__":
    main()
