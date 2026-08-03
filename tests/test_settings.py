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
