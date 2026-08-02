# Issue 3 — Make the heart-rate tracker glanceable and vibrant

## Problem

The current tracker presents a small blue line over dark, low-contrast zone
bands. It omits the most useful summary context, uses tiny axis labels, and
forces the user to infer the current state from several disconnected numbers.
The attached Zones reference leads with a clear Heart Rate title, a large
average, an explicit min–max range, and a saturated line whose color follows
the heart-rate zone.

## Baseline evidence

- The trend card only contains a title, time-range buttons, and a chart.
- `graph.py` draws one cyan line regardless of the point's zone.
- Zone bands are darkened by alpha over a dark background and the axis labels
  are rendered at a small size.
- The session card has average/min/max, but that information is below the
  graph and is only available when a recording is active.

## Plan

1. Add an always-visible tracker summary inside the trend card: average BPM
   and min–max range for the selected graph window, with an empty-state
   placeholder when no reading exists.
2. Render a light chart with clearer zone bands and a saturated HR stroke.
   Color each line segment by its zone so transitions are visible without
   reading the axis.
3. Increase chart legibility: stronger axis text, clean grid/boundaries,
   preserved BPM unit label, and a stable plot area for one-point and
   multi-point data.
4. Keep the existing 5/10/30-minute range controls and graph cache behavior;
   invalidate the cache when data, configuration, or range changes.
5. Add pure helper tests for selected-window statistics and graph rendering
   tests that exercise zone colors and empty/single-point behavior.
6. Verify connected, disconnected, live-changing, and session states on macOS
   without changing session recording/export behavior.

## Acceptance criteria

- Average and min–max range are readable at a glance above the graph.
- The live line visibly changes color when readings cross zones.
- Zone bands are subtle but distinguishable on the light canvas and do not
  overpower the data line.
- 5/10/30-minute controls still change the selected window.
- No data renders a useful placeholder; one point renders without crashing.
- Existing session stats, export, and graph caching remain intact.

## Verification

- Unit tests cover deterministic average/min/max calculations and filtered
  windows.
- PNG render tests cover empty, single-point, multi-zone, and custom-color
  paths.
- Manual smoke test compares the result against the attached reference for
  hierarchy, contrast, and visual emphasis.

## Follow-up correction — axis labels and scale

The native smoke test exposed two problems in the first tracker iteration:
short traces displayed the same wall-clock minute on every X-axis tick, and a
fixed 0–maximum-HR Y-axis compressed low-intensity readings into a flat strip.
The renderer now uses relative elapsed labels with clean tick intervals and
automatically focuses the Y-axis on the visible BPM range while retaining
zone-band context.
