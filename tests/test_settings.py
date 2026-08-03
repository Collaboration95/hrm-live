"""Tests for settings window unsaved-changes handling (no modal panels)."""

from __future__ import annotations

from unittest.mock import patch

from hrm_live.state import AppState
from hrm_live.ui.settings import SettingsWindow, _SettingsDelegate

NS_ALERT_FIRST_BUTTON = 1000  # Discard / Reset
NS_ALERT_SECOND_BUTTON = 1001  # Cancel


def _make_window() -> SettingsWindow:
    return SettingsWindow(AppState())


def test_window_starts_clean() -> None:
    assert _make_window()._dirty is False


def test_mark_dirty_flags_unsaved_edits() -> None:
    window = _make_window()
    window._mark_dirty()
    assert window._dirty is True


def test_clean_window_closes_without_prompt() -> None:
    assert _make_window()._window_should_close() is True


def test_dirty_window_discard_confirmed_closes() -> None:
    window = _make_window()
    window._mark_dirty()
    with patch("hrm_live.ui.settings.NSAlert") as alert_cls:
        alert = alert_cls.alloc().init()
        alert.runModal.return_value = NS_ALERT_FIRST_BUTTON
        assert window._window_should_close() is True
    alert.setMessageText_.assert_called_once_with("Discard unsaved changes?")
    alert.addButtonWithTitle_.assert_any_call("Discard")
    alert.addButtonWithTitle_.assert_any_call("Cancel")


def test_dirty_window_cancel_keeps_open() -> None:
    window = _make_window()
    window._mark_dirty()
    with patch("hrm_live.ui.settings.NSAlert") as alert_cls:
        alert = alert_cls.alloc().init()
        alert.runModal.return_value = NS_ALERT_SECOND_BUTTON
        assert window._window_should_close() is False


def test_close_settings_keeps_window_open_when_cancelled() -> None:
    window = _make_window()
    window._mark_dirty()
    window._panel = object()  # type: ignore[assignment]
    with patch("hrm_live.ui.settings.NSAlert") as alert_cls:
        alert = alert_cls.alloc().init()
        alert.runModal.return_value = NS_ALERT_SECOND_BUTTON
        window.close_settings_(None)
    assert window._panel is not None


def test_reset_defaults_requires_confirmation() -> None:
    window = _make_window()
    with patch("hrm_live.ui.settings.NSAlert") as alert_cls:
        alert = alert_cls.alloc().init()
        alert.runModal.return_value = NS_ALERT_SECOND_BUTTON
        window.reset_defaults_(None)
    # Cancelled: the form still has no controls (nothing was applied).
    assert not window._controls
    assert window._dirty is False


def test_reset_defaults_confirmed_marks_dirty() -> None:
    window = _make_window()
    with patch("hrm_live.ui.settings.NSAlert") as alert_cls:
        alert = alert_cls.alloc().init()
        alert.runModal.return_value = NS_ALERT_FIRST_BUTTON
        window.reset_defaults_(None)
    assert window._dirty is True


def test_sync_from_config_clears_dirty() -> None:
    window = _make_window()
    window._mark_dirty()
    window._controls = {}
    window._sync_config_fields()
    assert window._dirty is False


def test_delegate_marks_dirty_on_text_change() -> None:
    window = _make_window()
    delegate = _SettingsDelegate.alloc().initWithOwner_(window)
    delegate.controlTextDidChange_(None)
    assert window._dirty is True


def test_delegate_window_should_close_forwards() -> None:
    window = _make_window()
    delegate = _SettingsDelegate.alloc().initWithOwner_(window)
    assert delegate.windowShouldClose_(None) is True


# ── Live zone preview ─────────────────────────────────────────────────


class _FakeField:
    def __init__(self, value: str) -> None:
        self._value = value

    def stringValue(self) -> str:
        return self._value

    def setStringValue_(self, value: str) -> None:
        self._value = value


class _FakePreview:
    def __init__(self) -> None:
        self.data: tuple | None = None

    def refreshWithColors_zones_maxHr_(self, colors: dict, zones: dict, max_hr: int) -> None:
        self.data = (colors, zones, max_hr)


def _window_with_controls() -> SettingsWindow:
    window = _make_window()
    window._controls = {
        "max_hr": _FakeField("190"),
        "zone_z1_max": _FakeField("60"),
        "zone_z2_max": _FakeField("75"),
        "zone_z3_max": _FakeField("88"),
        "color_Z1": _FakeField("#8E8E93"),
        "color_Z2": _FakeField("#34C759"),
        "color_Z3": _FakeField("#FF9F0A"),
        "color_Z4": _FakeField("#FF375F"),
    }
    return window


def test_update_preview_pushes_current_values() -> None:
    window = _window_with_controls()
    preview = _FakePreview()
    window._preview_view = preview  # type: ignore[assignment]
    window._update_preview()
    colors, zones, max_hr = preview.data  # type: ignore[misc]
    assert zones == {"z1_max": 0.6, "z2_max": 0.75, "z3_max": 0.88}
    assert max_hr == 190
    assert colors["Z1"] == "#8E8E93"
    assert colors["Z4"] == "#FF375F"


def test_update_preview_ignores_invalid_values() -> None:
    window = _window_with_controls()
    preview = _FakePreview()
    window._preview_view = preview  # type: ignore[assignment]
    window._controls["max_hr"].setStringValue_("abc")
    window._update_preview()
    assert preview.data is None


def test_update_preview_falls_back_for_invalid_hex() -> None:
    window = _window_with_controls()
    preview = _FakePreview()
    window._preview_view = preview  # type: ignore[assignment]
    window._controls["color_Z2"].setStringValue_("not-a-hex")
    window._update_preview()
    colors, _, _ = preview.data  # type: ignore[misc]
    assert colors["Z2"] == "#34C759"  # default used for an invalid hex


def test_update_preview_without_view_is_safe() -> None:
    window = _window_with_controls()
    window._update_preview()  # _preview_view is None -> no crash
