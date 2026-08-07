# HRM Live — macOS Menu Bar Heart Rate Monitor

A macOS menu bar app that connects to a Bluetooth HRM strap (e.g.
Decathlon), displays live BPM in the menu bar, and provides a popover
with a zone gauge, HR graph, and session recording.

## Features

- **Live BPM** in the menu bar, color-coded by heart rate zone
- **Popover dashboard** with large BPM display, donut gauge, rolling HR
  graph, session stats, and start/stop controls
- **BLE HRM support** for standard GATT Heart Rate Measurement (0x2A37)
- **4-zone model** with configurable boundaries and colors
- **Live zone preview** in Settings that updates the ramp and BPM cutoffs as
  you edit colors, boundaries, or max HR
- **Unsaved-changes protection** in Settings (discard confirmation and a
  confirmed Reset to Defaults)
- **Session recording** with user-selected CSV and JSON export
- **Saved session history** for reopening recent sessions and exported files
- **Configurable settings** (max HR, zone boundaries, colors, graph window)
- **Native AppKit rendering** — no matplotlib/numpy dependency (app ≈ 28 MB)

## Requirements

- macOS 12+ (Monterey or later)
- Python 3.14 for runtime and CI.
- A BLE heart rate monitor strap (optional — app works in disconnected mode)

## Installation

```bash
# Clone the repository
git clone https://github.com/Collaboration95/hrm-live.git
cd hrm-live

# Create a virtual environment and install dependencies
make venv
make install
```

## Startup Instructions

Use the Makefile from the repository root for normal development workflows.

Run the app in development mode:

```bash
make run
```

The app will appear in the menu bar. If no device address is configured,
it will show a grey disconnected indicator.

Run the automated checks:

```bash
make check
```

Build the macOS `.app` bundle:

```bash
make package
```

The bundle is created at `dist/HRM Live.app`. `make package` also verifies
the bundle signature, embedded entitlements, and Info.plist metadata.

Install the repo-local git hooks once per clone:

```bash
make install-hooks
```

The pre-commit hook runs formatting, linting, and type checking before a
commit is allowed through.

Open the built app:

```bash
open "dist/HRM Live.app"
```

Useful Makefile targets:

```bash
make help           # Show all available targets
make format-check   # Check Ruff formatting
make lint           # Run Ruff lint
make typecheck      # Run mypy
make test           # Run pytest
make coverage       # Run pytest with coverage threshold
make compile        # Compile-check Python files
make icon           # Regenerate the packaged macOS icon
make build          # Build dist/HRM Live.app
make verify-bundle  # Verify an existing app bundle
make clean          # Remove generated build/test artifacts
```

## Running Tests

Run the default test suite:

```bash
make test
```

Or run verbose tests:

```bash
make test-verbose
```

With coverage:

```bash
make coverage
```

The current coverage gate is 60%, with the suite measuring ~77% locally (236 tests).

## Configuration

Config file: `~/.config/hrm/config.json`

Default settings:
- Device address: empty (must be set before BLE will connect)
- Max HR: 190 bpm
- Zone boundaries: Z1 < 60%, Z2 < 75%, Z3 < 88%, Z4 ≥ 88%
- Zone colors: Z1 grey, Z2 green, Z3 orange, Z4 pink

## Session Data

Stopping a non-empty session opens a Finder save dialog. No CSV or JSON is
written until you choose a destination. Cancelling keeps the completed session
in local history and exposes `Save Last Session...` until a new session starts.

Completed sessions stay available in the recent-session history, so you can
reopen a prior summary, reveal an existing export in Finder, and retry a
failed save without re-recording the workout.

Session duration is based on timestamp deltas between valid heart-rate
samples, assigned to the previous sample's zone. A single notification gap is
clamped to 5 seconds so disconnects or sleep do not create inflated workout
durations. The first sample adds zero seconds.

JSON export includes the zone-transition count plus app and export schema
versions alongside the recorded samples.

Format:
```csv
timestamp,bpm,zone
2025-08-10T07:34:12,142,Z3
```

## Screenshots

Light-mode release captures live in [`docs/screenshots/`](docs/screenshots/):

- [`dashboard-light.png`](docs/screenshots/dashboard-light.png) — the dashboard
  popover: hero gauge with live BPM, 16:9 AppKit trend graph, session card,
  recent sessions with zone-time bars, and the action area.
- [`settings-zones.png`](docs/screenshots/settings-zones.png) — Settings zones
  section: boundary percent fields, native `NSColorWell`s + hex fields, and the
  live zone-ramp preview with BPM cutoffs.
- [`settings-device.png`](docs/screenshots/settings-device.png) — the compact
  Device setup card: connection status, Scan button + live result count,
  Discovered picker + Use Device, read-only Address, and editable Name.

Each screenshot also has a `-1x` variant. Regenerate them with
`python scripts/capture_screenshots.py`.

## GitHub Workflow

The repository uses GitHub-native labels and a small milestone set.

- Issue labels: `bug`, `enhancement`, `documentation`, `dependencies`,
  `good first issue`, `help wanted`
- PR size labels: `size: xs`, `size: s`, `size: m`, `size: l`, `size: xl`
- Milestone: `v1.6 — Session Confidence`

Pull requests should link the tracking issue and include screenshots for UI
changes.

## Project Structure

```
src/
  hrm_live/
    __init__.py
    __main__.py     # python -m hrm_live
    app.py          # Composition root and shutdown coordinator
    state.py        # Locked AppState and immutable snapshots
    config.py       # Config load/save/validate
    zones.py        # Zone calculation helpers
    session.py      # Session lifecycle and explicit CSV + JSON export
    ble.py          # BLE HR parsing and connection loop
    ui/
      menubar.py    # Status item and shutdown routing
      popover.py    # Dashboard and save-panel orchestration
      graph.py      # HR graph rendering (offscreen AppKit -> PNG)
      settings.py   # Settings window
      tokens.py     # Semantic design tokens (colors, type, spacing)
tests/
  ...
docs/
  RELEASE_CHECKLIST.md   # Release-candidate sign-off and evidence record
  FEATURE_ROADMAP.md     # Product roadmap and feature milestones
```

## Privacy And Limitations

HRM Live keeps Bluetooth readings, settings, and session data local to your
Mac unless you explicitly export a CSV. The app is for fitness display and
record keeping only; it is not a medical device and does not promise medical
accuracy.

## Open-source project

Please read [Contributing](CONTRIBUTING.md), [Security](SECURITY.md), the
[Code of Conduct](CODE_OF_CONDUCT.md), and [Support](SUPPORT.md) before opening
an issue or pull request. Do not publish BLE identifiers, session data,
certificates, tokens, or other secrets in public issues.

## Release Status

Local ad-hoc `.app` builds are supported for development. Public distribution
requires a Developer ID Application certificate, notarization, stapling, a
checksum, and explicit GitHub release authorization. Those credentials are not
stored in this repository.

## License

MIT

## Release Tracking

Implementation status and the manual AppKit, hardware, and distribution
checks for the current release candidate are tracked in
`docs/RELEASE_CHECKLIST.md`. This is not a released build until that checklist
is complete.
