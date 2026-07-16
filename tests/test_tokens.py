"""Tests for the semantic design tokens module."""

from __future__ import annotations

from hrm_live.ui.tokens import (
    STATUS_CONNECTED,
    STATUS_DISCONNECTED,
    STATUS_ERROR,
    STATUS_RECONNECTING,
    ZONE_COLORS_DEFAULT,
    menu_accessibility_label,
    menu_title,
    status_dot_colour,
    zone_accent,
)


class TestStatusDotColour:
    def test_connected_returns_green(self) -> None:
        assert status_dot_colour("connected") == STATUS_CONNECTED

    def test_connecting_returns_orange(self) -> None:
        assert status_dot_colour("connecting") == STATUS_RECONNECTING

    def test_reconnecting_returns_orange(self) -> None:
        assert status_dot_colour("reconnecting") == STATUS_RECONNECTING

    def test_disconnected_returns_grey(self) -> None:
        assert status_dot_colour("disconnected") == STATUS_DISCONNECTED

    def test_error_returns_red(self) -> None:
        assert status_dot_colour("error") == STATUS_ERROR

    def test_unknown_status_returns_grey(self) -> None:
        assert status_dot_colour("unknown") == STATUS_DISCONNECTED


class TestZoneAccent:
    def test_returns_config_colour_when_available(self) -> None:
        cfg = {"Z1": "#FF0000", "Z2": "#00FF00"}
        assert zone_accent("Z1", cfg) == "#FF0000"
        assert zone_accent("Z2", cfg) == "#00FF00"

    def test_falls_back_to_default(self) -> None:
        assert zone_accent("Z1", None) == ZONE_COLORS_DEFAULT["Z1"]
        assert zone_accent("Z3", {}) == ZONE_COLORS_DEFAULT["Z3"]

    def test_falls_back_when_zone_not_in_config(self) -> None:
        cfg = {"Z1": "#FF0000"}
        assert zone_accent("Z2", cfg) == ZONE_COLORS_DEFAULT["Z2"]

    def test_unknown_zone_returns_fallback_grey(self) -> None:
        assert zone_accent("Z5", None) == "#888888"


class TestMenuTitle:
    def test_connected_with_bpm(self) -> None:
        assert menu_title(72, "connected") == "♥ 72 bpm"

    def test_connected_no_bpm(self) -> None:
        assert menu_title(None, "connected") == "♡ ---"

    def test_disconnected(self) -> None:
        assert menu_title(None, "disconnected") == "♡ ---"

    def test_error(self) -> None:
        assert menu_title(72, "error") == "♡ ---"


class TestMenuAccessibilityLabel:
    def test_connected_with_bpm(self) -> None:
        label = menu_accessibility_label(72, "Z2", "Aerobic", "connected")
        assert "72" in label
        assert "beats per minute" in label
        assert "Z2" in label
        assert "Aerobic" in label
        assert "connected" in label

    def test_disconnected(self) -> None:
        label = menu_accessibility_label(None, "Z1", "Recovery", "disconnected")
        assert "heart rate monitor disconnected" in label.lower()

    def test_error_state(self) -> None:
        label = menu_accessibility_label(None, "Z1", "Recovery", "error")
        assert "error" in label

    def test_reconnecting(self) -> None:
        label = menu_accessibility_label(None, "Z1", "Recovery", "reconnecting")
        assert "reconnecting" in label
