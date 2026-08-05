#!/usr/bin/env python3
"""Render release screenshots to docs/screenshots/ (light mode, 1x + 2x).

The dashboard and settings views are AppKit views, so this script builds the
real view hierarchies offscreen (no window server interaction needed beyond
the shared NSApplication) and rasterizes them to PNG via
``cacheDisplayInRect:toBitmapImageRep:``.

Usage:  python scripts/capture_screenshots.py
"""

from __future__ import annotations

import math
import sys
from datetime import UTC, datetime, timedelta

from AppKit import (
    NSApplication,
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSCalibratedRGBColorSpace,
)

from hrm_live.state import AppState, DiscoveredDevice, RecentSessionRecord
from hrm_live.ui.popover import HRMPopover
from hrm_live.ui.settings import SettingsWindow

OUT_DIR = "docs/screenshots"

CONFIG = {
    "device_address": "F8:1D:78:2C:4E:9A",
    "device_name": "Polar H10",
    "max_hr": 190,
    "zones": {"z1_max": 0.60, "z2_max": 0.75, "z3_max": 0.88},
    "zone_colors": {
        "Z1": "#8E8E93",
        "Z2": "#34C759",
        "Z3": "#FF9F0A",
        "Z4": "#FF375F",
    },
    "graph_window_minutes": 10,
}

ZONE_TIMES = {"Z1": 42.0, "Z2": 318.0, "Z3": 181.0, "Z4": 59.0}


def _bpm_curve(t: float) -> int:
    """A plausible 10-minute warmup->steady ramp, 118-176 bpm."""
    base = 118 + 44 * (1 - math.exp(-t / 240.0))
    wave = 6 * math.sin(t / 55.0)
    return int(round(max(110, min(180, base + wave))))


def _populate_state() -> AppState:
    state = AppState()
    state.set_config(dict(CONFIG))
    state.update_connection(
        latest_bpm=141,
        connected=True,
        status="connected",
        error=None,
    )

    now = datetime.now(UTC).replace(microsecond=0)
    start = now - timedelta(minutes=10)
    samples = []
    for i in range(600):
        samples.append((start + timedelta(seconds=i), _bpm_curve(i)))
    state.ring_buffer.extend(samples)
    state._ring_revision = 1  # noqa: SLF001

    state.session_active = True
    state.session_start = start
    state.session_max = 178
    state.session_min = 118
    state.session_sum = 141 * 600
    state.session_count = 600
    state.zone_times = dict(ZONE_TIMES)

    def _record(i: int, started: datetime, seconds: int) -> RecentSessionRecord:
        return RecentSessionRecord(
            session_id=f"shot-{i}",
            session_start=started,
            archived_at=started + timedelta(seconds=seconds),
            session_max=178 - i * 5,
            session_min=118,
            session_sum=141 * seconds,
            session_count=seconds,
            zone_times=dict(ZONE_TIMES),
            zone_transition_count=3,
            export_path=f"~/Workouts/hrm-2026-07-{15 + i:02d}-0630.csv",
            export_format="csv",
            exported_at=started + timedelta(seconds=seconds + 3),
        )

    state._recent_sessions = [  # noqa: SLF001
        _record(0, start, 600),
        _record(1, start - timedelta(hours=22), 480),
        _record(2, start - timedelta(hours=46), 390),
    ]
    return state


def _render_view(view, path: str, scale: int = 2) -> None:
    bounds = view.bounds()
    w = int(bounds.size.width * scale)
    h = int(bounds.size.height * scale)
    rep = _new_bitmap_rep(w, h)
    view.cacheDisplayInRect_toBitmapImageRep_(bounds, rep)
    _write_rep(rep, path, w, h)


def _new_bitmap_rep(w: int, h: int) -> NSBitmapImageRep:
    return NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, w, h, 8, 4, True, False, NSCalibratedRGBColorSpace, 0, 0
    )


def _write_rep(rep, path: str, w: int, h: int) -> None:
    data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    data.writeToFile_atomically_(path, True)
    print(f"  wrote {path} ({w}x{h}px)")


def _render_crop(view, rect, path: str, scale: int = 2) -> None:
    """Render *view* then crop the point rect (bottom-up coords)."""
    from AppKit import NSImage

    bounds = view.bounds()
    w = int(bounds.size.width * scale)
    h = int(bounds.size.height * scale)
    rep = _new_bitmap_rep(w, h)
    view.cacheDisplayInRect_toBitmapImageRep_(bounds, rep)

    (rx, ry), (rw, rh) = rect
    img = NSImage.alloc().initWithSize_((w, h))
    img.addRepresentation_(rep)
    out = NSImage.alloc().initWithSize_((rw * scale, rh * scale))
    out.lockFocus()
    img.drawInRect_fromRect_operation_fraction_(
        ((0, 0), (rw * scale, rh * scale)),
        ((rx * scale, ry * scale), (rw * scale, rh * scale)),
        1,
        1.0,
    )
    out.unlockFocus()
    final = NSBitmapImageRep.alloc().initWithData_(out.TIFFRepresentation())
    _write_rep(final, path, int(rw * scale), int(rh * scale))


def capture_dashboard(state: AppState) -> None:
    print("dashboard-light")
    popover = HRMPopover(state)
    root = popover._build_view()  # noqa: SLF001
    # Force the graph placeholder off and the graph image on (refresh normally
    # happens on the 1 s tick; render once here).
    popover._popover = type("Fake", (), {"isShown": lambda self: True})()  # noqa: SLF001
    popover.refresh()
    _render_view(root, f"{OUT_DIR}/dashboard-light.png", scale=2)
    _render_view(root, f"{OUT_DIR}/dashboard-light-1x.png", scale=1)


def capture_settings(state: AppState) -> None:
    state.update_scan(
        status="complete",
        results=(
            DiscoveredDevice("F8:1D:78:2C:4E:9A", "Polar H10", -48, True),
            DiscoveredDevice("AA:BB:CC:11:22:33", "HRM strap", -61, True),
        ),
        error=None,
        bump_generation=True,
    )
    window = SettingsWindow(
        state,
        on_scan=lambda: None,
        on_cancel_scan=lambda: None,
    )
    window._build_panel()  # noqa: SLF001
    window.refresh_from_state(force=True)

    # Paint the scroll document white so the transparent view reads like the
    # real panel window.
    content = window._content_view  # noqa: SLF001
    content.setWantsLayer_(True)
    content.layer().setBackgroundColor_(
        __import__("hrm_live.ui.settings", fromlist=["_ns_color"])._ns_color("#FFFFFF").CGColor()
    )

    print("settings-zones")
    _render_view(content, f"{OUT_DIR}/settings-zones.png", scale=2)
    _render_view(content, f"{OUT_DIR}/settings-zones-1x.png", scale=1)

    print("settings-device")
    card = window._device_card  # noqa: SLF001
    if card is not None:
        rect = card.frame()
        _render_crop(content, rect, f"{OUT_DIR}/settings-device.png", scale=2)
        _render_crop(content, rect, f"{OUT_DIR}/settings-device-1x.png", scale=1)


def main() -> None:
    _ = NSApplication.sharedApplication()
    state = _populate_state()
    import os

    os.makedirs(OUT_DIR, exist_ok=True)
    capture_dashboard(state)
    capture_settings(state)
    print("done")


if __name__ == "__main__":
    sys.exit(main())
