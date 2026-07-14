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
- **Session recording** with CSV export
- **Configurable settings** (max HR, zone boundaries, colors, graph window)

## Requirements

- macOS 12+ (Monterey or later)
- Python 3.11+
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
make test           # Run pytest
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
pip install pytest-cov
pytest --cov=. --cov-report=term-missing
```

## Configuration

Config file: `~/.config/hrm/config.json`

Default settings:
- Device address: empty (must be set before BLE will connect)
- Max HR: 190 bpm
- Zone boundaries: Z1 < 60%, Z2 < 75%, Z3 < 88%, Z4 ≥ 88%
- Zone colors: Z1 grey, Z2 green, Z3 orange, Z4 red

## Session Data

Recorded sessions are saved as CSV files in `~/.local/share/hrm/sessions/`.

Format:
```csv
timestamp,bpm,zone
2025-08-10T07:34:12,142,Z3
```

## Project Structure

```
app.py              # Entry point
state.py            # Shared AppState dataclass
config.py           # Config load/save/validate
zones.py            # Zone calculation helpers
session.py          # Session management & CSV export
ble.py              # BLE HR parsing & connection loop
ui/
  __init__.py
  menubar.py        # rumps.App subclass
  popover.py        # Popover dashboard
  graph.py          # HR graph rendering (matplotlib)
  settings.py       # Settings window
tests/
  ...
docs/
  SPEC.md
  PHASED_IMPLEMENTATION_PROMPT.md
  IMPLEMENTATION_STATUS.md
```

## License

MIT
