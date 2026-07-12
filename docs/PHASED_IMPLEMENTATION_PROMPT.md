# HRM Menu Bar App - Phased Implementation Prompt

This document is the implementation handoff for the HRM menu bar app described
in `docs/SPEC.md`. Treat `docs/SPEC.md` as the source of product truth and this
document as the build plan, acceptance checklist, and future evaluation rubric.

The project starts from a minimal repository. Build incrementally, keep each
phase shippable, and update `docs/IMPLEMENTATION_STATUS.md` every time a
requirement is completed, deferred, blocked, or changed.

## Agent Operating Rules

1. Read `docs/SPEC.md`, this file, and `docs/IMPLEMENTATION_STATUS.md` before
   making changes.
2. Implement phases in order unless a later phase is explicitly needed to make
   an earlier phase testable.
3. Keep each phase small enough that it can be reviewed independently.
4. Prefer simple Python modules matching the file structure in `docs/SPEC.md`.
5. Do not add future-scope features to v1:
   - Apple Watch or HealthKit integration
   - Multi-device support
   - Historical session browser
   - Cloud sync
   - BLE device scanning UI, except for disabled or clearly v2 placeholder UI
6. After each phase, run the checks listed for that phase and record the result
   in `docs/IMPLEMENTATION_STATUS.md`.
7. If hardware is unavailable, add test seams and mock BLE data so core behavior
   can still be verified.
8. Any intentional deviation from `docs/SPEC.md` must be recorded in the status
   ledger with the reason and review impact.

## Required Completion Storage

Future evaluation depends on a durable project-local record of what was built.
The implementation agent must maintain `docs/IMPLEMENTATION_STATUS.md`.

For every phase, store:

- `status`: `not-started`, `in-progress`, `complete`, `blocked`, or `deferred`
- `completed_at`: ISO timestamp or `TBD`
- `commit`: commit hash or `TBD`
- `files_changed`: list of important files changed
- `requirements_completed`: checklist copied from this document
- `acceptance_checks`: command or manual check plus pass/fail result
- `known_gaps`: explicit remaining gaps, if any
- `evaluator_notes`: details a future evaluator should know

Do not mark a phase complete unless all must-have requirements and acceptance
criteria for that phase are satisfied or an approved deviation is documented.

## Target V1 Architecture

The expected module layout is:

```text
app.py
state.py
ble.py
config.py
zones.py
session.py
ui/
  __init__.py
  menubar.py
  popover.py
  graph.py
  settings.py
tests/
  ...
docs/
  SPEC.md
  PHASED_IMPLEMENTATION_PROMPT.md
  IMPLEMENTATION_STATUS.md
```

Runtime model:

- `rumps` owns the macOS main thread and AppKit run loop.
- `bleak` runs in an asyncio event loop on a dedicated background thread.
- BLE code writes to shared `AppState`.
- UI code reads `AppState` on the main thread via a timer.
- Config persists to `~/.config/hrm/config.json`.
- Sessions export CSV files to `~/.local/share/hrm/sessions/`.

## Phase 0 - Repository Foundation and Tooling

Goal: create a maintainable Python project skeleton without implementing BLE or
UI behavior yet.

### Requirements

- Add Python project metadata:
  - `pyproject.toml` or equivalent dependency metadata
  - Python version requirement of 3.11 or newer
  - runtime dependencies from the spec:
    - `rumps>=0.4.0`
    - `bleak>=0.21.0`
    - `matplotlib>=3.8.0`
    - `pyobjc-core`
    - `pyobjc-framework-Cocoa`
  - test dependencies such as `pytest`
- Add initial module files matching the target architecture.
- Add `ui/__init__.py` so UI modules import cleanly.
- Add a basic test directory.
- Add a README or update existing docs with:
  - how to install dependencies
  - how to run tests
  - how to run the app in dev mode
  - where config and session files are stored
- Add `.gitignore` entries for:
  - Python caches
  - virtual environments
  - build and dist outputs
  - generated session data if any local test data is stored in repo

### Acceptance Criteria

- `python -m compileall .` succeeds.
- `pytest` succeeds, even if only smoke tests exist.
- Importing each top-level module succeeds without launching the app.
- No module starts BLE, opens UI, reads config, or writes files at import time.
- The repository has a clear command path for a new contributor to run tests.

### Checks and Edge Cases

- Verify import side effects by importing modules in tests.
- Confirm the project still works when optional macOS-only libraries are not
  available in a CI-like environment, if tests are expected to run there.
- Avoid requiring Bluetooth hardware for any Phase 0 check.

## Phase 1 - Config, State, and Zone Domain Logic

Goal: implement deterministic core logic that does not require macOS UI or BLE
hardware.

### Requirements

- Implement `AppState` as a dataclass with fields from `docs/SPEC.md`.
- Implement a config model and load/save helpers in `config.py`.
- Default config values:
  - `device_address`: placeholder string or empty value requiring user edit
  - `max_hr`: `190`
  - `zones.z1_max`: `0.60`
  - `zones.z2_max`: `0.75`
  - `zones.z3_max`: `0.88`
  - colors:
    - `Z1`: `#888888`
    - `Z2`: `#4CAF50`
    - `Z3`: `#FF9800`
    - `Z4`: `#F44336`
  - `graph_window_minutes`: `10`
- Use `~/.config/hrm/config.json` by default.
- Create the config directory if it does not exist when saving.
- On missing config, return defaults without crashing.
- On malformed config, fail gracefully:
  - preserve or ignore the broken file according to implementation choice
  - return defaults or a validation error that the UI can display
  - document the behavior in tests and status notes
- Implement zone helpers in `zones.py`:
  - calculate current zone from BPM, max HR, and configured boundaries
  - return zone labels and colors
  - validate monotonic boundaries
- Ensure zone boundary semantics match the spec:
  - below `z1_max` is `Z1`
  - at or above `z1_max` and below `z2_max` is `Z2`
  - at or above `z2_max` and below `z3_max` is `Z3`
  - at or above `z3_max` is `Z4`

### Acceptance Criteria

- Unit tests cover config defaults, load, save, malformed JSON, and directory
  creation.
- Unit tests cover every zone boundary and color lookup.
- `AppState.ring_buffer` max length is 600 by default.
- `AppState.zone_times` initializes with `Z1` through `Z4`.
- Domain modules are platform-light and testable without launching AppKit.

### Checks and Edge Cases

- `max_hr <= 0` must be rejected or sanitized.
- Zone boundaries must be increasing and within `(0, 1)`.
- BPM values of `0`, negative values, and implausibly high values should not
  corrupt state. Prefer validation at the ingestion boundary.
- Config files with missing keys should merge with defaults.
- Config files with extra keys should not break loading.

## Phase 2 - Heart Rate Parsing and BLE Background Loop

Goal: implement the BLE ingestion path and make it testable without an actual
strap.

### Requirements

- Implement `HEART_RATE_UUID` exactly as:
  `00002a37-0000-1000-8000-00805f9b34fb`.
- Implement Heart Rate Measurement parsing:
  - byte 0 is flags
  - if bit 0 is `0`, BPM is unsigned 8-bit at `data[1]`
  - if bit 0 is `1`, BPM is unsigned 16-bit little-endian at `data[1:3]`
- Reject malformed packets without crashing:
  - empty payload
  - missing 8-bit BPM byte
  - missing second 16-bit BPM byte
- Implement callback behavior:
  - update `state.latest_bpm`
  - set or preserve `state.connected` appropriately
  - append timestamped BPM to the ring buffer
  - if a session is active, delegate to session update logic
- Implement `ble_loop(state, address)`:
  - use `BleakClient(address)` in a retry loop
  - set `state.connected = True` only when connected and notification setup
    succeeds
  - call `start_notify(HEART_RATE_UUID, callback)`
  - while connected, sleep asynchronously
  - on disconnect or exception, set `state.connected = False`
  - wait about 3 seconds before retrying
- Implement a thread starter used by `app.py`:
  - creates a new asyncio event loop
  - runs BLE loop in a dedicated daemon or managed background thread
  - does not touch AppKit or rumps from the BLE thread

### Acceptance Criteria

- Unit tests parse valid 8-bit and 16-bit HR payloads.
- Unit tests verify malformed payloads are handled without mutating state into
  an invalid value.
- Unit tests or mocks verify BLE reconnect behavior after client exceptions.
- `app.py` can start the BLE thread path without blocking the main thread.
- No BLE code is executed at import time.

### Checks and Edge Cases

- Repeated duplicate BPM samples should be accepted; HR straps may send stable
  values.
- Very fast callbacks must not grow unbounded memory. Ring buffer remains capped.
- If `device_address` is missing, app should show disconnected state and surface
  a settings path instead of crashing.
- If Bluetooth permission is denied, app should stay alive and continue retrying
  or show a useful disconnected state.
- Race tolerance: shared state is one writer and one reader. Keep mutations
  simple and avoid composite operations that could leave obvious partial state.

## Phase 3 - Session Management and CSV Export

Goal: implement start, stop, stats, zone time accounting, and export behavior.

### Requirements

- Implement `start_session(state)`:
  - set `session_active = True`
  - set `session_start` to current time
  - clear `session_data`
  - reset max, min, sum, count, and zone times
- Implement `record_sample(state, timestamp, bpm, config)`:
  - no-op for session data if `session_active` is false
  - append `(timestamp, bpm)` plus derived zone to session data
  - update max, min, sum, count
  - update average via sum/count
  - increment the active zone time in seconds for 1 Hz samples
- Implement `stop_session(state, config_or_paths)`:
  - set `session_active = False`
  - write CSV to `~/.local/share/hrm/sessions/YYYY-MM-DD_HH-MM.csv`
  - create the sessions directory if missing
  - keep final stats visible in state until the next session starts
- CSV format must be:

```csv
timestamp,bpm,zone
2025-08-10T07:34:12,142,Z3
```

- Use ISO timestamps.
- Decide how to avoid filename collisions if two sessions stop within the same
  minute. Record the chosen behavior in tests and status notes.

### Acceptance Criteria

- Unit tests cover start, record, stop, stats, zone times, and CSV output.
- Stopping a session with no samples does not crash.
- Session stats remain readable after stop.
- Starting a new session clears previous session samples and stats.
- CSV rows contain timestamp, BPM, and zone for every recorded session sample.

### Checks and Edge Cases

- Min HR should not remain `999` after a no-sample session is displayed; expose
  a user-friendly empty state or `None` internally.
- Zone time totals should not exceed session duration by more than expected
  sample granularity.
- If CSV write fails, surface the error without losing in-memory stats.
- BPM samples outside a reasonable range should be ignored or marked invalid
  before entering session stats.
- Clock changes during a session should not corrupt elapsed time calculations.
  Prefer monotonic elapsed tracking for display if practical, while preserving
  wall-clock timestamps for CSV.

## Phase 4 - Menu Bar App Shell

Goal: implement the visible menu bar item and app lifecycle without the full
popover UI.

### Requirements

- Implement `rumps.App` subclass in `ui/menubar.py`.
- `app.py` should:
  - load config
  - initialize shared state
  - start BLE background loop when a device address exists
  - create and run the rumps app on the main thread
- Add a 1-second timer that reads shared state and updates the menu bar title.
- Display states:
  - connected with BPM: heart icon or heart emoji, BPM number, and `bpm`
  - disconnected or no data: grey-circle style indicator and dashes
- Implement a PyObjC title-color shim if feasible:
  - color title text by current zone when connected
  - use grey for disconnected or no data
- If attributed title coloring is not reliable in the dev environment, keep a
  clearly isolated shim and document the limitation in status notes.
- Provide menu actions for:
  - open popover placeholder
  - settings placeholder
  - quit

### Acceptance Criteria

- The app launches as a macOS menu bar app in dev mode.
- The UI does not freeze while BLE retry loop is running.
- Timer updates title from mocked state values.
- Disconnected state is visible when no HR data is available.
- Quit exits cleanly.

### Checks and Edge Cases

- App should not crash if `rumps` or PyObjC behavior differs across macOS
  versions; isolate platform-specific code.
- Menu title updates must run on the main thread.
- Missing config or missing device address should not prevent the app from
  launching.
- Avoid excessive redraw work in the 1-second timer.

## Phase 5 - Popover, Gauge, Graph, and Session Controls

Goal: build the primary click experience described in the spec.

### Requirements

- Implement popover window or equivalent menu bar click UI with fixed width of
  about 280 px.
- Sections from top to bottom:
  1. Hero section
  2. HR graph
  3. Session stats
  4. Controls
- Hero section:
  - large BPM number around 36 px
  - current zone label such as `Z3 - Threshold`
  - circular donut gauge with four zone segments
  - current zone visually highlighted
- HR graph:
  - rolling line graph for last N minutes
  - default graph window is 10 minutes
  - graph window is configurable
  - x-axis represents time
  - y-axis represents BPM
  - horizontal colored bands show zone boundaries
  - use matplotlib with Agg backend unless CoreGraphics is chosen intentionally
  - render to PNG bytes, then display as `NSImage`
- Session stats:
  - visible while active or after a session just ended
  - elapsed time
  - average, max, and min BPM
  - per-zone time bars and labels
- Controls:
  - start/stop session toggle
  - settings button
- Start/stop controls must call Phase 3 session logic.

### Acceptance Criteria

- Clicking the menu bar item opens the popover.
- Popover works when disconnected, connected with data, active session, and
  just-ended session.
- Graph renders from ring-buffer data without writing temporary files unless
  unavoidable.
- Graph render path stays fast enough for a responsive popover. Target under
  100 ms for normal 10-minute data.
- Start session updates UI state on the next refresh.
- Stop session writes CSV and keeps final stats visible.

### Checks and Edge Cases

- Empty ring buffer renders an empty or placeholder graph without crashing.
- One data point renders without axis errors.
- Zone boundaries should appear correctly for configured max HR.
- Long graph windows must not exceed available ring buffer unless ring buffer
  sizing is deliberately adjusted and documented.
- Reopening the popover should not create duplicate timers, leaked windows, or
  stale controls.
- Session stats should not show misleading values when there are no samples.

## Phase 6 - Settings Window and Config Persistence

Goal: implement user-editable settings and persist changes safely.

### Requirements

- Implement a separate `NSPanel` or equivalent settings window.
- Window behavior:
  - non-activating if practical
  - stays on top if practical
  - opened from popover settings control
- Device section:
  - editable device address field
  - scan button visible only if clearly disabled or marked v2/not available
- Heart Rate Zones section:
  - max HR number input
  - Z1/Z2 boundary input default 60%
  - Z2/Z3 boundary input default 75%
  - Z3/Z4 boundary input default 88%
  - zone color controls or validated color inputs for all four zones
- Display section:
  - graph time window dropdown with 5, 10, and 30 minute options
- Actions:
  - save
  - reset to defaults
- Save writes `~/.config/hrm/config.json`.
- Save validates settings before writing:
  - device address may be empty but should not crash BLE startup
  - max HR must be positive
  - zone percentages must be monotonic
  - colors must be valid hex strings if text-based
- After save:
  - UI uses new max HR, colors, and graph window
  - BLE reconnect behavior for changed device address is handled or documented

### Acceptance Criteria

- Settings window opens from popover.
- Existing config values populate the controls.
- Saving valid changes updates config on disk.
- Invalid zone boundaries are rejected with a visible error or non-crashing
  validation path.
- Reset to defaults restores default values and can be saved.
- App can restart and load the saved settings.

### Checks and Edge Cases

- User enters non-numeric max HR or percentages.
- User enters percentages out of order.
- User enters a malformed color string.
- User deletes the device address.
- Config write fails due to permissions.
- Changing graph window should not break graph rendering when existing ring
  buffer has fewer samples than requested.

## Phase 7 - Packaging, macOS Permissions, and App Bundle

Goal: prepare a v1 macOS app bundle that can be installed and run outside the
source tree.

### Requirements

- Add `setup.py` or equivalent `py2app` configuration.
- Include required dependencies in the app bundle:
  - `rumps`
  - `bleak`
  - `matplotlib`
  - PyObjC packages
- Add macOS Bluetooth usage description:
  - `NSBluetoothAlwaysUsageDescription`
- Add Bluetooth entitlement if sandboxing/signing path requires it:
  - `com.apple.security.device.bluetooth`
- Ensure matplotlib backend and resources work inside the bundle.
- Document build command and expected output path.
- Keep packaging separate from dev-mode run path.

### Acceptance Criteria

- `python setup.py py2app` or documented build command produces an `.app`.
- Launching the `.app` shows the menu bar item.
- First launch presents or supports Bluetooth permission correctly.
- App does not crash because bundled imports are missing.
- Config and session paths still point to user home directories, not inside the
  app bundle.

### Checks and Edge Cases

- Clean machine or clean virtual environment build.
- App launched from Finder, not only terminal.
- Bluetooth permission denied.
- Missing HR strap at launch.
- Matplotlib font/cache behavior inside bundled app.

## Phase 8 - End-to-End Validation and V1 Hardening

Goal: verify the full v1 workflow against the spec and document remaining known
limitations.

### Requirements

- Run automated test suite.
- Run app in dev mode.
- Run app from packaged bundle if Phase 7 is complete.
- Validate with a real Decathlon BLE HRM strap if available.
- Validate with mocked BLE samples if hardware is unavailable.
- Exercise complete workflow:
  - launch app
  - disconnected state appears
  - connect to strap or mock data
  - live BPM appears
  - zone color/label updates
  - popover opens
  - graph updates
  - start session
  - collect samples
  - stop session
  - CSV is written
  - settings change persists across restart
- Update `docs/IMPLEMENTATION_STATUS.md` with final evaluation summary.

### Acceptance Criteria

- All in-scope v1 requirements from `docs/SPEC.md` are either complete or have
  documented approved deviations.
- Automated tests pass.
- Manual validation results are recorded.
- At least one CSV export is manually inspected and matches required format.
- No known crash exists for normal disconnected startup, missing config,
  malformed config, or no samples in a session.

### Checks and Edge Cases

- BLE strap disconnects mid-session.
- App quits while session is active.
- App restarts after malformed config.
- User starts and stops multiple sessions in one minute.
- Very low, very high, or invalid BPM payloads.
- Popover opened repeatedly during BLE reconnect attempts.

## Final V1 Evaluation Checklist

Use this checklist when judging whether the implementation matches the spec.

- Menu bar app exists and runs on macOS.
- BLE HRM strap support uses standard GATT characteristic `0x2A37`.
- BLE loop runs on background asyncio thread.
- rumps/AppKit run loop remains on the main thread.
- Live BPM appears in the menu bar.
- Disconnected/no-data state appears clearly.
- Current zone is calculated from configurable max HR and boundaries.
- Menu bar title color follows the current zone, or documented platform
  limitation exists.
- Popover includes hero BPM, zone label, donut gauge, graph, session stats, and
  controls.
- Graph uses last N minutes and displays zone bands.
- Settings window persists device address, max HR, zones, colors, and graph
  window.
- Sessions can start and stop.
- Session stats include elapsed time, average, max, min, and zone time.
- CSV export writes timestamp, bpm, and zone rows.
- Config path is `~/.config/hrm/config.json`.
- Session path is `~/.local/share/hrm/sessions/`.
- v1 excludes future-scope features unless clearly isolated and documented.
- `docs/IMPLEMENTATION_STATUS.md` is current and accurate.

## Suggested Commit Boundaries

Use one commit per completed phase when practical:

- `chore(project): scaffold Python app structure`
- `feat(core): add config state and zone logic`
- `feat(ble): ingest heart rate measurements`
- `feat(session): record and export HR sessions`
- `feat(menubar): show live BPM status item`
- `feat(popover): add HR dashboard and controls`
- `feat(settings): persist editable app settings`
- `build(mac): package app with Bluetooth permissions`
- `test(app): validate v1 workflow`

Each non-trivial commit should include a body explaining why the change exists
and how it satisfies the relevant phase.
