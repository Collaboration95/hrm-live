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
from AppKit import (
    NSAttributedString,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
)
from Foundation import NSObject

from hrm_live.ble import BLEManager, stop_ble_background
from hrm_live.state import AppState
from hrm_live.ui.popover import HRMPopover
from hrm_live.ui.settings import SettingsWindow
from hrm_live.ui.tokens import menu_accessibility_label, status_dot_colour, zone_accent
from hrm_live.zones import get_zone, zone_label

log = logging.getLogger(__name__)

DISCONNECTED_TITLE = "♡ ---"
UI_REFRESH_SECONDS = 1.0

# ── Status dot characters (visible without colour) ───────────────────────

DOT_CHARS = {
    "connected": "●",  # Filled circle
    "connecting": "◌",  # Dotted circle (scanning/connecting)
    "reconnecting": "◌",  # Dotted circle
    "disconnected": "○",  # Open circle
    "error": "○",  # Open circle (changes colour)
}


class _StatusButtonTarget(NSObject):
    """Objective-C bridge that forwards an NSStatusBar button action to Python."""

    def initWithApp_(self, app: HRMBarApp) -> _StatusButtonTarget:
        self = objc.super(_StatusButtonTarget, self).init()
        if self is not None:
            self._app = app
        return self

    @objc.IBAction
    def statusButtonClicked_(self, sender) -> None:
        """Forward the Objective-C ``statusButtonClicked:`` selector."""

        self._app._open_popover(sender)


class HRMBarApp(rumps.App):
    """Main menu bar application."""

    def __init__(self, state: AppState, ble_manager: BLEManager | None = None) -> None:
        # rumps otherwise appends its own Quit item during ``run()``. The
        # dashboard footer owns the sole visible quit route so BLE shutdown is
        # always coordinated by this class.
        super().__init__("HRM", title=DISCONNECTED_TITLE, quit_button=None)
        self.state = state
        self.ble_manager = ble_manager
        self._shutdown_lock = threading.Lock()
        self._shutdown_started = False
        self._quit_requested = False
        self._status_item_configured = False
        self._status_button_target: _StatusButtonTarget | None = None
        self.popover = HRMPopover(state, on_quit=self.shutdown)
        self.settings = SettingsWindow(
            state,
            on_scan=self._start_scan,
            on_cancel_scan=self._cancel_scan,
            on_config_saved=self._settings_saved,
        )
        self.popover.on_settings = self.settings.show

        # 1-second UI refresh timer
        self.timer = rumps.Timer(self._tick, UI_REFRESH_SECONDS)
        self.timer.start()

        # rumps creates the native status item inside ``App.run()``, after this
        # constructor returns. Registering at ``before_start`` makes the
        # dashboard-first action run after that creation step rather than
        # silently doing nothing during construction.
        rumps.events.before_start.register(self._configure_status_item)

    # ── Timer tick ────────────────────────────────────────────────────

    def _tick(self, _sender: rumps.Timer) -> None:
        """Read shared state and update the menu bar title."""
        s = self.state.snapshot_for_ui()

        zone = self._current_zone(s.latest_bpm, s.config) if s.latest_bpm is not None else "Z1"
        colors_cfg = (s.config or {}).get("zone_colors", {})
        dot_color = status_dot_colour(s.connection_status)
        dot_char = DOT_CHARS.get(s.connection_status, "○")

        # Build title: BPM text in system primary colour, zone dot in zone/status colour
        if s.connected and s.latest_bpm is not None:
            zone_col = zone_accent(zone, colors_cfg)
            z_label = zone_label(zone)
            text_part = f"♥ {s.latest_bpm} bpm {z_label}"
        else:
            zone_col = dot_color
            text_part = DISCONNECTED_TITLE

        self._set_dual_colour_title(text_part, dot_char, zone_col if s.connected else dot_color)

        log.debug("Menu tick: status=%s", s.connection_status)

        # Accessibility
        a11y_label = menu_accessibility_label(
            s.latest_bpm if s.connected else None,
            zone,
            zone_label(zone),
            s.connection_status,
        )
        button = self._status_item_button()
        if button:
            button.setAccessibilityLabel_(a11y_label)

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

    # ── Dual-colour attributed title ─────────────────────────────────

    def _set_dual_colour_title(self, text: str, dot: str, dot_hex: str) -> None:
        """Set the menu bar title with white text + a coloured status/zone dot.

        The BPM text and heart are drawn in system label colour (white in
        dark mode, black in light).  The trailing dot character uses the
        zone or status colour as a supplementary cue.
        """
        try:
            button = self._status_item_button()
            if button is None:
                self.title = f"{text} {dot}"
                return

            full = f"{text} {dot}"

            # White/system text colour for the main portion
            primary = NSColor.labelColor()
            text_attrs = {
                NSForegroundColorAttributeName: primary,
                NSFontAttributeName: NSFont.menuBarFontOfSize_(0),
            }

            # Zone/status colour for the dot
            dr = int(dot_hex[1:3], 16) / 255.0
            dg = int(dot_hex[3:5], 16) / 255.0
            db = int(dot_hex[5:7], 16) / 255.0
            dot_col = NSColor.colorWithRed_green_blue_alpha_(dr, dg, db, 1.0)
            dot_attrs = {
                NSForegroundColorAttributeName: dot_col,
                NSFontAttributeName: NSFont.menuBarFontOfSize_(0),
            }

            attributed = NSAttributedString.alloc().initWithString_attributes_(full, text_attrs)
            # Apply dot colour to the last character (the dot)
            dot_range = (len(full) - 1, 1)
            attributed.addAttributes_range_(dot_attrs, dot_range)

            button.setAttributedTitle_(attributed)
        except Exception:
            log.debug("Failed to set dual-colour title, using plain text", exc_info=True)
            self.title = f"{text} {dot}"

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

    def _configure_status_item(self) -> bool:
        """Install dashboard-first status-item behavior after rumps setup.

        AppKit targets must be Objective-C objects. ``_StatusButtonTarget`` is
        retained on this long-lived app object and maps the
        ``statusButtonClicked:`` selector back to ``_open_popover()``.

        rumps assigns a menu while initializing its status item. Clearing that
        menu is required: otherwise macOS consumes a normal click to open the
        menu instead of sending the button action below. Settings and Quit are
        available from the dashboard footer.
        """

        if self._status_item_configured:
            return True

        nsapp = getattr(self, "_nsapp", None)
        status_item = getattr(nsapp, "nsstatusitem", None)
        if status_item is None:
            log.error("Cannot configure dashboard click: status item is unavailable")
            return False

        button = status_item.button()
        if button is None:
            log.error("Cannot configure dashboard click: status button is unavailable")
            return False

        status_item.setMenu_(None)
        if self._status_button_target is None:
            self._status_button_target = _StatusButtonTarget.alloc().initWithApp_(self)
        button.setTarget_(self._status_button_target)
        button.setAction_("statusButtonClicked:")
        self._status_item_configured = True
        return True

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
        rumps.events.before_start.unregister(self._configure_status_item)
        if manager is not None:
            stop_ble_background(manager)
        if should_quit:
            rumps.quit_application()
