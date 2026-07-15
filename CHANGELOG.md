# Changelog

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

## Release Notes

This repository can build a local ad-hoc `dist/HRM Live.app` for development.
It is not a public release until signed with Developer ID, notarized, stapled,
checksummed, manually hardware-tested, and published by the repository owner.
