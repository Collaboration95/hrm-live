"""Tests for the pure motion policy (Issue 12)."""

from __future__ import annotations

import pytest

from hrm_live.ui.motion import should_pulse


def test_connected_with_motion_allowed_pulses() -> None:
    assert should_pulse("connected", reduce_motion=False) is True


def test_reduce_motion_blocks_pulse_even_when_connected() -> None:
    assert should_pulse("connected", reduce_motion=True) is False


@pytest.mark.parametrize(
    "status", ["disconnected", "connecting", "reconnecting", "error", "mystery"]
)
def test_non_connected_statuses_never_pulse(status: str) -> None:
    assert should_pulse(status, reduce_motion=False) is False
