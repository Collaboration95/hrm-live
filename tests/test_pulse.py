"""Tests for the popover pulse timer lifecycle (no real run loop)."""

from __future__ import annotations

from hrm_live.state import AppState
from hrm_live.ui import popover as pmod


class _FakeTimer:
    def __init__(self) -> None:
        self.invalidated = False

    def invalidate(self) -> None:
        self.invalidated = True


class _FakeGauge:
    def __init__(self) -> None:
        self.alpha: float | None = None

    def setPulseAlpha_(self, alpha: float) -> None:
        self.alpha = float(alpha)


class _FakePopover:
    def __init__(self, shown: bool) -> None:
        self._shown = shown

    def isShown(self) -> bool:
        return self._shown


def _connected_popover() -> pmod.HRMPopover:
    state = AppState()
    state.update_connection(connected=True, status="connected")
    popover = pmod.HRMPopover(state)
    popover._reduce_motion_enabled = lambda: False  # type: ignore[method-assign]
    return popover


def test_sync_pulse_starts_timer_when_connected() -> None:
    popover = _connected_popover()
    scheduled: list[object] = []
    original = pmod._schedule_pulse_timer
    pmod._schedule_pulse_timer = lambda block: scheduled.append(block) or _FakeTimer()
    try:
        popover._sync_pulse()
    finally:
        pmod._schedule_pulse_timer = original
    assert popover._pulse_timer is not None
    assert len(scheduled) == 1


def test_sync_pulse_does_not_duplicate_timer() -> None:
    popover = _connected_popover()
    popover._pulse_timer = _FakeTimer()
    scheduled: list[object] = []
    original = pmod._schedule_pulse_timer
    pmod._schedule_pulse_timer = lambda block: scheduled.append(block) or _FakeTimer()
    try:
        popover._sync_pulse()
    finally:
        pmod._schedule_pulse_timer = original
    assert popover._pulse_timer is not None
    assert scheduled == []


def test_reduce_motion_stops_pulse() -> None:
    popover = _connected_popover()
    popover._reduce_motion_enabled = lambda: True  # type: ignore[method-assign]
    timer = _FakeTimer()
    popover._pulse_timer = timer
    popover._sync_pulse()
    assert timer.invalidated is True
    assert popover._pulse_timer is None


def test_disconnected_state_stops_pulse() -> None:
    popover = _connected_popover()
    popover.state.update_connection(connected=False, status="disconnected")
    timer = _FakeTimer()
    popover._pulse_timer = timer
    popover._sync_pulse()
    assert timer.invalidated is True


def test_pulse_tick_stops_when_popover_closed() -> None:
    popover = _connected_popover()
    popover._popover = _FakePopover(shown=False)  # type: ignore[assignment]
    timer = _FakeTimer()
    popover._pulse_timer = timer
    popover._pulse_tick()
    assert timer.invalidated is True
    assert popover._pulse_timer is None


def test_pulse_tick_drives_gauge_alpha_when_shown() -> None:
    popover = _connected_popover()
    popover._popover = _FakePopover(shown=True)  # type: ignore[assignment]
    gauge = _FakeGauge()
    popover._gauge_view = gauge  # type: ignore[assignment]
    popover._pulse_phase = 0.0
    popover._pulse_tick()
    assert gauge.alpha is not None
    assert -0.15 <= gauge.alpha <= 0.15


def test_teardown_invalidates_timer_and_resets_gauge() -> None:
    popover = _connected_popover()
    timer = _FakeTimer()
    gauge = _FakeGauge()
    popover._pulse_timer = timer
    popover._gauge_view = gauge  # type: ignore[assignment]
    popover.teardown()
    assert timer.invalidated is True
    assert popover._pulse_timer is None
    assert gauge.alpha == 0.0


def test_stop_pulse_is_idempotent_without_timer() -> None:
    popover = _connected_popover()
    gauge = _FakeGauge()
    popover._gauge_view = gauge  # type: ignore[assignment]
    popover._stop_pulse()  # no timer set -> safe no-op
    assert gauge.alpha == 0.0
