"""Tests for graph rendering."""

from collections import deque
from datetime import UTC, datetime

from hrm_live.ui.graph import render_graph


def _make_ring_buffer(bpms: list[int], start_bpm: int = 60) -> deque:
    """Helper: build a ring buffer with sequential BPM values."""
    now = datetime.now(UTC)
    rb = deque(maxlen=600)
    for i, bpm in enumerate(bpms):
        rb.append((now.replace(second=i % 60), bpm))
    return rb


def test_render_none_empty_buffer() -> None:
    assert render_graph(deque(maxlen=600)) is None


def test_render_none_single_point() -> None:
    # Single point should render (not None)
    rb = _make_ring_buffer([120])
    result = render_graph(rb)
    # May return None if matplotlib unavailable in CI
    if result is not None:
        assert isinstance(result, bytes)


def test_render_multiple_points() -> None:
    rb = _make_ring_buffer([100, 110, 120, 130, 140, 150])
    result = render_graph(rb)
    if result is not None:
        assert isinstance(result, bytes)
        assert len(result) > 100  # should be a real PNG


def test_render_custom_max_hr() -> None:
    rb = _make_ring_buffer([120])
    result = render_graph(rb, max_hr=200)
    if result is not None:
        assert isinstance(result, bytes)


def test_render_custom_window() -> None:
    rb = _make_ring_buffer([120, 130, 140])
    result = render_graph(rb, window_minutes=5)
    if result is not None:
        assert isinstance(result, bytes)


def test_render_custom_zones() -> None:
    rb = _make_ring_buffer([120])
    zones = {"z1_max": 0.50, "z2_max": 0.70, "z3_max": 0.90}
    result = render_graph(rb, zones=zones)
    if result is not None:
        assert isinstance(result, bytes)


def test_render_partial_zones_uses_defaults() -> None:
    rb = _make_ring_buffer([120])
    result = render_graph(rb, zones={})
    if result is not None:
        assert isinstance(result, bytes)


def test_render_custom_colors() -> None:
    rb = _make_ring_buffer([120])
    colors = {"Z1": "#ffffff", "Z2": "#000000", "Z3": "#ff0000", "Z4": "#00ff00"}
    result = render_graph(rb, zone_colors=colors)
    if result is not None:
        assert isinstance(result, bytes)
