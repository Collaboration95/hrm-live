"""Menu bar app — rumps.App subclass with timer-driven UI updates.

This module owns the main thread / AppKit run loop. It reads shared
state but never writes to BLE or session objects (user actions delegate
to the appropriate modules).
"""

from __future__ import annotations

import logging

import rumps
from AppKit import NSAttributedString, NSColor, NSForegroundColorAttributeName

from state import AppState
from zones import zone_color

from ui.popover import HRMPopover
from ui.settings import SettingsWindow

log = logging.getLogger(__name__)

DISCONNECTED_TITLE = "⚪ ---"
UI_REFRESH_SECONDS = 1.0


class HRMBarApp(rumps.App):
    """Main menu bar application."""

    def __init__(self, state: AppState) -> None:
        super().__init__("HRM", title=DISCONNECTED_TITLE)
        self.state = state
        self.popover = HRMPopover(state)
        self.settings = SettingsWindow(state)
        self.popover.on_settings = self.settings.show

        # Menu items
        self.menu = [
            rumps.MenuItem("Open Dashboard", callback=self._open_popover),
            None,  # separator
            rumps.MenuItem("Settings", callback=self._open_settings),
            None,
            rumps.MenuItem("Quit", callback=rumps.quit_application),
        ]

        # 1-second UI refresh timer
        self.timer = rumps.Timer(self._tick, UI_REFRESH_SECONDS)
        self.timer.start()

    # ── Timer tick ────────────────────────────────────────────────────

    def _tick(self, _sender: rumps.Timer) -> None:
        """Read shared state and update the menu bar title."""
        s = self.state
        if s.connected and s.latest_bpm is not None:
            title = f"❤️ {s.latest_bpm} bpm"
            color_hex = zone_color(
                self._current_zone(),
                (s.config or {}).get("zone_colors"),
            )
            self._set_colored_title(title, color_hex)
        else:
            self._set_colored_title(DISCONNECTED_TITLE, "#888888")

        # Refresh popover content if it's open
        if self.popover.is_shown:
            self.popover.refresh()

    def _current_zone(self) -> str:
        """Return the current zone string based on state / config."""
        from zones import get_zone

        s = self.state
        if s.latest_bpm is None:
            return "Z1"
        cfg = s.config or {}
        max_hr = cfg.get("max_hr", 190)
        zones_cfg = cfg.get("zones", {})
        zone_bounds = {
            "z1_max": zones_cfg.get("z1_max", 0.60),
            "z2_max": zones_cfg.get("z2_max", 0.75),
            "z3_max": zones_cfg.get("z3_max", 0.88),
        }
        return get_zone(s.latest_bpm, max_hr, zone_bounds)

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

            # Try to access the status item button
            if hasattr(self, "ns_status_item") and self.ns_status_item:
                button = self.ns_status_item.button()
                if button:
                    attributed = NSAttributedString.alloc().initWithString_attributes_(
                        title, attrs
                    )
                    button.setAttributedTitle_(attributed)
                    return
        except Exception:
            log.debug("Failed to set colored title, using plain text", exc_info=True)

        # Fallback
        self.title = title

    # ── Actions ──────────────────────────────────────────────────────

    def _open_popover(self, _sender: rumps.MenuItem | None = None) -> None:
        """Open the dashboard popover."""
        self.popover.toggle(self)

    def _open_settings(self, _sender: rumps.MenuItem | None = None) -> None:
        """Open the settings window."""
        self.settings.show()
