# Issue 1 — Vibrant light color system

## Problem

The dashboard currently mixes a warm near-black token palette with dark values
hard-coded in the graph renderer, gauge, zone-time tracks, and button styles.
That makes the same state look muted in some components and high-contrast in
others. The attached RAM and CPU profiler references use a bright white
canvas, near-black text, neutral light-gray surfaces, and saturated system
accents.

## Baseline evidence

- `tokens.py` defines `CANVAS=#1A1A1A`, `SURFACE=#242424`, and secondary text
  in gray-on-dark values.
- `graph.py` independently paints `#1e1e1e`, `#444444`, and `#aaaaaa`, so
  changing semantic tokens alone would not update the chart.
- `popover.py` hard-codes dark tracks and dark secondary/selected button
  fills.
- The default config and zone helpers still use the older green/orange/red
  palette, so first launch and settings previews can disagree with the
  dashboard.

## Plan

1. Replace the dashboard semantic palette with the light reference palette:
   white canvas, light neutral cards/dividers, near-black primary text,
   readable secondary text, and saturated blue/green/orange/pink accents.
2. Make default config and zone fallback colors use the same palette so saved
   and unsaved states render consistently.
3. Route graph background, axes, grid/boundary lines, and HR stroke through
   the shared tokens instead of private dark literals.
4. Update custom dashboard controls, gauge ring/ticks, and zone tracks to use
   light-surface contrast while preserving the selected and primary states.
5. Add token-level regression tests for the exact palette and graph source
   behavior, then run the full quality suite.

## Acceptance criteria

- The popover root, cards, buttons, gauge, graph, and zone bars all read as a
  coherent vibrant light UI on first launch.
- Primary and secondary text remain readable on every surface; no component
  relies on dark-mode-only white text.
- Zone colors remain visually distinct and are consistent across the menu bar,
  gauge, graph, and session bars.
- Existing configurable colors remain honored.
- The complete test, lint, typecheck, compile, and coverage checks pass.

## Verification

- Unit tests assert the palette values and color fallback behavior.
- Graph tests render a PNG with the light canvas and custom colors.
- Manual macOS smoke check opens the popover in disconnected and connected
  states, including buttons and session bars.
