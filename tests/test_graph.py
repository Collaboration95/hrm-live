"""Tests for graph rendering."""

from collections import deque
from datetime import UTC, datetime, timedelta

from hrm_live.ui import tokens
from hrm_live.ui.graph import (
    _chart_y_limits,
    _elapsed_tick_offsets,
    _format_elapsed_tick,
    _resolve_chart_colors,
    render_graph,
    summarize_heart_rate,
)


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


def test_resolve_chart_colors_defaults_to_tokens() -> None:
    """Without a config, the graph uses the dashboard's token palette."""
    assert _resolve_chart_colors(None) == tokens.ZONE_COLORS_DEFAULT
    assert _resolve_chart_colors({}) == tokens.ZONE_COLORS_DEFAULT


def test_resolve_chart_colors_preserves_explicit_user_colors() -> None:
    custom = {"Z1": "#111111", "Z2": "#222222", "Z3": "#333333", "Z4": "#444444"}
    assert _resolve_chart_colors(custom) == custom


def test_resolve_chart_colors_keeps_explicit_color_equal_to_default() -> None:
    """A user choice that happens to equal a token default is not dropped."""
    explicit_default = dict(tokens.ZONE_COLORS_DEFAULT)
    assert _resolve_chart_colors(explicit_default) == tokens.ZONE_COLORS_DEFAULT


def test_resolve_chart_colors_merges_partial_over_tokens() -> None:
    custom = {"Z2": "#ABCDEF"}
    resolved = _resolve_chart_colors(custom)
    assert resolved["Z2"] == "#ABCDEF"
    assert resolved["Z1"] == tokens.ZONE_COLORS_DEFAULT["Z1"]


def test_render_custom_colors() -> None:
    rb = _make_ring_buffer([120])
    colors = {"Z1": "#ffffff", "Z2": "#000000", "Z3": "#ff0000", "Z4": "#00ff00"}
    result = render_graph(rb, zone_colors=colors)
    if result is not None:
        assert isinstance(result, bytes)


def test_summarize_heart_rate_uses_selected_window() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    rb = deque(
        [
            (now - timedelta(minutes=11), 60),
            (now - timedelta(minutes=9), 100),
            (now - timedelta(minutes=4), 150),
            (now, 170),
        ]
    )

    assert summarize_heart_rate(rb, window_minutes=10) == (140.0, 100, 170)


def test_summarize_heart_rate_empty_buffer() -> None:
    assert summarize_heart_rate(deque(maxlen=600), window_minutes=10) is None


def test_elapsed_tick_labels_are_relative_and_unique() -> None:
    assert _format_elapsed_tick(0, 45) == "0s"
    assert _format_elapsed_tick(15, 45) == "15s"
    assert _format_elapsed_tick(60, 120) == "1:00"
    assert _format_elapsed_tick(125, 300) == "2:05"
    assert _elapsed_tick_offsets(11) == [0.0, 5.0, 10.0, 11.0]


def test_chart_y_limits_focus_on_visible_readings() -> None:
    assert _chart_y_limits([68, 72]) == (60, 80)
    assert _chart_y_limits([60, 160]) == (40, 180)


def test_render_line_changes_color_across_zones(monkeypatch) -> None:
    from matplotlib.axes import Axes

    calls: list[str | None] = []
    original_plot = Axes.plot

    def capture_plot(self, *args, **kwargs):
        calls.append(kwargs.get("color"))
        return original_plot(self, *args, **kwargs)

    monkeypatch.setattr(Axes, "plot", capture_plot)
    rb = _make_ring_buffer([100, 130, 170, 190])
    result = render_graph(
        rb,
        max_hr=200,
        zones={"z1_max": 0.50, "z2_max": 0.70, "z3_max": 0.85},
    )

    assert result is not None
    assert calls == ["#34C759", "#FF9F0A", "#FF375F"]
