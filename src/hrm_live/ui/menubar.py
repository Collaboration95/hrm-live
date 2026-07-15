"""Menu bar app — rumps.App subclass with timer-driven UI updates.

This module owns the main thread / AppKit run loop. It reads shared
state but never writes to BLE or session objects (user actions delegate
to the appropriate modules).
"""

from __future__ import annotations

import logging
import threading

import objc
import rumps
from AppKit import NSAttributedString, NSColor, NSForegroundColorAttributeName

from hrm_live.ble import BLEManager, stop_ble_background
from hrm_live.state import AppState
from hrm_live.ui.popover import HRMPopover
from hrm_live.ui.settings import SettingsWindow
from hrm_live.zones import get_zone, zone_color

log = logging.getLogger(__name__)

DISCONNECTED_TITLE = "⚪ ---"
UI_REFRESH_SECONDS = 1.0


class HRMBarApp(rumps.App):
    """Main menu bar application."""

    def __init__(self, state: AppState, ble_manager: BLEManager | None = None) -> None:
        super().__init__("HRM", title=DISCONNECTED_TITLE)
        self.state = state
        self.ble_manager = ble_manager
        self._shutdown_lock = threading.Lock()
        self._shutdown_started = False
        self._quit_requested = False
        self.popover = HRMPopover(state, on_quit=self.shutdown)
        self.settings = SettingsWindow(
            state,
            on_scan=self._start_scan,
            on_cancel_scan=self._cancel_scan,
            on_config_saved=self._settings_saved,
        )
        self.popover.on_settings = self.settings.show

        # Secondary menu fallback. Normal left-click is installed directly on
        # the NSStatusItem button and toggles the dashboard first.
        self.menu = [
            rumps.MenuItem("Settings", callback=self._open_settings),
            None,
            rumps.MenuItem("Quit", callback=self._quit),
        ]

        # 1-second UI refresh timer
        self.timer = rumps.Timer(self._tick, UI_REFRESH_SECONDS)
        self.timer.start()
        self._install_status_button_action()

    # ── Timer tick ────────────────────────────────────────────────────

    def _tick(self, _sender: rumps.Timer) -> None:
        """Read shared state and update the menu bar title."""
        s = self.state.snapshot_for_ui()
        if s.connected and s.latest_bpm is not None:
            title = f"❤️ {s.latest_bpm} bpm"
            color_hex = zone_color(
                self._current_zone(s.latest_bpm, s.config),
                (s.config or {}).get("zone_colors"),
            )
            self._set_colored_title(title, color_hex)
        else:
            self._set_colored_title(DISCONNECTED_TITLE, "#888888")

        # Refresh popover content if it's open
        if self.popover.is_shown:
            self.popover.refresh()
        if self.settings.is_visible:
            self.settings.refresh_from_state()

    def _current_zone(self, bpm: int | None, config: dict | None) -> str:
        """Return the current zone string based on state / config."""
        if bpm is None:
            return "Z1"
        cfg = config or {}
        max_hr = cfg.get("max_hr", 190)
        zones_cfg = cfg.get("zones", {})
        zone_bounds = {
            "z1_max": zones_cfg.get("z1_max", 0.60),
            "z2_max": zones_cfg.get("z2_max", 0.75),
            "z3_max": zones_cfg.get("z3_max", 0.88),
        }
        return get_zone(bpm, max_hr, zone_bounds)

    # ── Colored title shim (PyObjC) ──────────────────────────────────

    def _set_colored_title(self, title: str, hex_color: str) -> None:
        """Set the menu bar title with *hex_color* via NSAttributedString.

        If PyObjC is unavailable or fails, falls back to plain ``.title``.
        """
        try:
            r = int(hex_color[1:3], 16) / 255.0
            g = int(hex_color[3:5], 16) / 255.0
            b = int(hex_color[5:7], 16) / 255.0
            color = NSColor.colorWithRed_green_blue_alpha_(r, g, b, 1.0)
            attrs = {NSForegroundColorAttributeName: color}

            button = self._status_item_button()
            if button:
                attributed = NSAttributedString.alloc().initWithString_attributes_(title, attrs)
                button.setAttributedTitle_(attributed)
                return
        except Exception:
            log.debug("Failed to set colored title, using plain text", exc_info=True)

        # Fallback
        self.title = title

    # ── Actions ──────────────────────────────────────────────────────

    def _open_popover(self, _sender: rumps.MenuItem | None = None) -> None:
        """Open the dashboard popover."""
        button = self._status_item_button()
        if button is None:
            log.error("Cannot open dashboard: menu bar status item is unavailable")
            return
        self.popover.toggle(button)

    def _status_item_button(self):
        """Return the native button owned by rumps' NSStatusItem.

        rumps keeps the status item on its private NSApplication delegate,
        rather than exposing it directly on ``rumps.App``.
        """
        nsapp = getattr(self, "_nsapp", None)
        status_item = getattr(nsapp, "nsstatusitem", None)
        return status_item.button() if status_item is not None else None

    def _install_status_button_action(self) -> None:
        """Attach left-click to the dashboard toggle.

        PyObjC maps the Objective-C selector ``status_button_clicked:`` to the
        Python method ``status_button_clicked_``.  The method must remain on
        this long-lived app object so AppKit does not call a freed callback.
        """

        button = self._status_item_button()
        if button is not None:
            button.setTarget_(self)
            button.setAction_("status_button_clicked:")

    @objc.IBAction
    def status_button_clicked_(self, sender) -> None:
        self._open_popover(sender)

    def _open_settings(self, _sender: rumps.MenuItem | None = None) -> None:
        """Open the settings window."""
        self.settings.show()

    def _start_scan(self) -> None:
        if self.ble_manager is not None:
            self.ble_manager.start_scan()

    def _cancel_scan(self) -> None:
        if self.ble_manager is not None:
            self.ble_manager.cancel_scan()

    def _settings_saved(self, old_config: dict, new_config: dict) -> None:
        """React to a successful settings save."""

        if self.ble_manager is None:
            return

        old_address = (old_config or {}).get("device_address", "")
        new_address = (new_config or {}).get("device_address", "")
        current_status = self.state.snapshot_for_ui().connection_status

        if old_address != new_address:
            if not new_address:
                self.ble_manager.disconnect()
            else:
                cached = self.ble_manager.get_cached_device(new_address)
                self.ble_manager.connect(new_address, cached_device=cached)
        elif new_address and current_status in {"disconnected", "error"}:
            cached = self.ble_manager.get_cached_device(new_address)
            self.ble_manager.connect(new_address, cached_device=cached)

        self.settings.refresh_from_state(force=True)

    def _quit(self, _sender: rumps.MenuItem | None = None) -> None:
        """Route menu Quit through the guarded shutdown coordinator."""

        self.shutdown()

    def shutdown(self, request_quit: bool = True) -> None:
        """Stop BLE once and then request application termination."""

        manager: BLEManager | None = None
        should_quit = False
        with self._shutdown_lock:
            if self._shutdown_started:
                should_quit = request_quit and not self._quit_requested
                self._quit_requested = self._quit_requested or request_quit
            else:
                self._shutdown_started = True
                self._quit_requested = request_quit
                manager = self.ble_manager
                self.ble_manager = None
                should_quit = request_quit

        if self.timer is not None:
            self.timer.stop()
        if manager is not None:
            stop_ble_background(manager)
        if should_quit:
            rumps.quit_application()
