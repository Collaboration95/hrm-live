# Changelog

## Unreleased

- Replace the matplotlib chart renderer with an offscreen AppKit renderer;
  the packaged app shrinks from ~122 MB to ~28 MB with no bundled numpy.
- Prompt before discarding unsaved settings changes; Reset to Defaults now
  asks for confirmation before overwriting the form.
- Add a live zone-ramp preview to the Settings Zones section that updates as
  colors, boundaries, and max HR are edited.
- Consolidate Settings device setup into one compact card (status header,
  scan + result count, Discovered picker + Use Device, read-only Address,
  editable Name).
- Classify Bluetooth failures into friendly guidance (powered off,
  permission denied, no adapter, timeouts) with a single contextual recovery
  button that opens the right System Settings pane or retries.
- Compose the menu bar title from one source of truth and add a privacy-safe
  tooltip (device name + status, never the raw BLE address).
- Make Recent Sessions actionable: click a row to open the exported CSV/JSON
  in its default app, plus a per-session zone-time mini-bar and an
  Avg/Max/transitions line.
- Add a subtle live pulse to the hero gauge while connected, disabled under
  Reduce Motion, with no leaked timers on close or quit.
- Remove stale docs (v1.5 sprint tracker, duplicate roadmap draft, shipped
  issue plans), align release copy (checklist evidence, README, roadmap
  decisions, CONTRIBUTING Python version), and commit light-mode release
  screenshots under `docs/screenshots/`.

## 0.9.0 - 2026-07-31

- **First public release candidate.** Rebranded the project around the current
  `src/hrm_live` dashboard: vibrant light color system (semantic tokens), a
  reliably-opening settings window, a glanceable heart-rate tracker, JSON
  export, saved session history, zone-transition tracking, and dashboard-first
  status-item interaction.
- Bump package/bundle version to 0.9.0.

## 0.1.0 - 2026-07-15

- Move runtime code into the `src/hrm_live` package layout.
- Add CI, Ruff formatting/linting, mypy, coverage, and expanded Make targets.
- Add dashboard-first status item routing with footer Settings and Quit.
- Route all quit paths through one idempotent shutdown coordinator.
- Replace automatic session-directory exports with user-selected CSV export.
- Keep cancelled or failed exports retryable via `Save Last Session...`.
- Store sample zones at receipt time and account zone duration with timestamp
  deltas clamped to 5 seconds per gap.
- Add locked state snapshots for UI, graph, and export reads.
- Add graph render caching keyed by snapshot/config changes.
- Quarantine syntactically valid but semantically invalid configuration files
  instead of accepting unsafe startup settings.
- Keep save-panel failures inside the AppKit callback boundary and present
  path-safe retry feedback for CSV write failures.

## Release Notes

This repository can build a local ad-hoc `dist/HRM Live.app` for development.
It is not a public release until signed with Developer ID, notarized, stapled,
checksummed, manually hardware-tested, and published by the repository owner.
