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
- **Session recording** with user-selected CSV export
- **Configurable settings** (max HR, zone boundaries, colors, graph window)

## Requirements

- macOS 12+ (Monterey or later)
- Python 3.11+ for runtime; release CI tests Python 3.11 and 3.12.
- A BLE heart rate monitor strap (optional — app works in disconnected mode)

## Installation

```bash
# Clone the repository
git clone <repo-url>
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

The current initial coverage gate is 54%, measured after adding AppKit-safe
unit tests and before deeper UI automation.

## Configuration

Config file: `~/.config/hrm/config.json`

Default settings:
- Device address: empty (must be set before BLE will connect)
- Max HR: 190 bpm
- Zone boundaries: Z1 < 60%, Z2 < 75%, Z3 < 88%, Z4 ≥ 88%
- Zone colors: Z1 grey, Z2 green, Z3 orange, Z4 red

## Session Data

Stopping a non-empty session opens a Finder save dialog. No CSV is written
until you choose a destination. Cancelling keeps the completed session in
memory and exposes `Save Last Session...` until a new session starts.

Session duration is based on timestamp deltas between valid heart-rate
samples, assigned to the previous sample's zone. A single notification gap is
clamped to 5 seconds so disconnects or sleep do not create inflated workout
durations. The first sample adds zero seconds.

Format:
```csv
timestamp,bpm,zone
2025-08-10T07:34:12,142,Z3
```

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
    session.py      # Session lifecycle and explicit CSV export
    ble.py          # BLE HR parsing and connection loop
    ui/
      menubar.py    # Status item and shutdown routing
      popover.py    # Dashboard and save-panel orchestration
      graph.py      # HR graph rendering (matplotlib Agg)
      settings.py   # Settings window
tests/
  ...
docs/
  RELEASE_IMPLEMENTATION_HANDOFF.md
  RELEASE_READINESS_AUDIT_2026-07-15.md  # Current independent release status
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

## Feature Tracking

Release tracker, local implementation state:

1. Dashboard-first status item interaction: implemented in code; manual
   real-UI verification still pending.
2. Finder-style CSV saving: implemented and covered by injected-path tests;
   manual Desktop/spreadsheet verification still pending.
3. Single guarded quit path: implemented in code; manual real-UI verification
   still pending for all BLE states.
4. Native `src/hrm_live` package layout and focused comments: implemented and
   covered by local quality checks.

This is not a released build until the checklist in
`docs/RELEASE_CHECKLIST.md` is complete.
