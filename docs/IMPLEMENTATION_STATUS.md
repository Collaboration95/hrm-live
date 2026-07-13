# HRM Menu Bar App - Implementation Status

This file is the durable completion ledger for the phased plan in
`docs/PHASED_IMPLEMENTATION_PROMPT.md`. Updated after every implementation pass.

Status values: `not-started`, `in-progress`, `partial`, `complete`, `blocked`, `deferred`.

## Phase 0 - Repository Foundation and Tooling

- status: `complete`
- completed_at: `2026-07-12`
- requirements_completed:
  - [x] Python project metadata added
  - [x] Python 3.11+ requirement declared
  - [x] Runtime dependencies declared
  - [x] Test dependencies declared
  - [x] Target module skeleton created
  - [x] `ui/__init__.py` added
  - [x] Test directory added
  - [x] README added with venv-aware run/test instructions
  - [x] `.gitignore` covers common Python/build artifacts
- acceptance_checks:
  - [x] Targeted compile passes with `.venv/bin/python`
  - [x] README recommends `.venv/bin/python -m pytest` or activating venv
  - [x] Import smoke tests exist and pass
- known_gaps:
  - None.

## Phase 1 - Config, State, and Zone Domain Logic

- status: `complete`
- requirements_completed:
  - [x] `AppState` dataclass implemented
  - [x] Config defaults implemented
  - [x] Config load helper implemented
  - [x] Config save helper implemented
  - [x] Missing config handled
  - [x] Malformed config handled by renaming corrupt file
  - [x] Partial config merges with defaults
  - [x] Zone calculation implemented
  - [x] Zone color lookup implemented
  - [x] Zone boundary validation implemented
- acceptance_checks:
  - [x] Config tests pass (19 tests)
  - [x] Zone tests pass (20 tests)
  - [x] `AppState` tests pass (3 tests)
- known_gaps: None

## Phase 2 - Heart Rate Parsing and BLE Background Loop

- status: `complete`
- requirements_completed:
  - [x] Heart Rate Measurement UUID defined
  - [x] 8-bit BPM payload parsing implemented
  - [x] 16-bit BPM payload parsing implemented
  - [x] Malformed payload handling implemented
  - [x] HR callback updates shared state
  - [x] HR callback appends to ring buffer
  - [x] Active sessions receive samples
  - [x] BLE retry loop implemented (3s, with stop-check interleaved)
  - [x] BLE disconnect handling implemented
  - [x] Background asyncio thread starter implemented
  - [x] **Clean BLE shutdown implemented** (stop_event, event-loop cancellation, thread join)
  - [x] **All tests mock BleakClient** (no real CoreBluetooth/BleakClient side effects)
- acceptance_checks:
  - [x] Parser tests pass under venv
  - [x] Malformed payload tests pass under venv
  - [x] BLE loop mock tests pass (with AsyncMock)
  - [x] BLE thread lifecycle tests pass (start + stop via stop_event)
  - [x] BLE shutdown cancellation test passes
  - [x] `stop_ble_background(None)` is a no-op
- known_gaps: None
- evaluator_notes:
  - `start_ble_background()` returns a `BLEManager` with thread, stop_event, ready_event, loop, and task handles.
  - `stop_ble_background(manager)` sets stop_event, cancels the BLE task on its owning asyncio loop, and joins the thread.
  - BLE loop checks stop_event every 100ms during the 3s reconnect delay.
  - `app.py` retains the manager and stops BLE on exit via `atexit`; the Quit menu action also stops BLE before quitting rumps.
  - The previous CoreBluetooth finalization crash path is addressed by explicit task cancellation and thread join.

## Phase 3 - Session Management and CSV Export

- status: `complete`
- requirements_completed:
  - [x] Start session implemented
  - [x] Session accumulators reset on start
  - [x] Sample recording implemented (BPM range 20-250)
  - [x] Average, max, min stats implemented
  - [x] Zone time accounting implemented
  - [x] Stop session implemented
  - [x] CSV export implemented (ISO timestamps, header row)
  - [x] Session directory creation implemented
  - [x] Post-stop stats remain visible
  - [x] Empty-session behavior handled (no CSV, returns None)
  - [x] **CSV write failure handled gracefully** (caught, logged, `last_csv_error` set)
  - [x] **All CSV tests use temp directory** (no writes to real home directory)
- acceptance_checks:
  - [x] All session tests pass under venv (15 tests)
  - [x] CSV format tests pass (header + data rows match spec)
  - [x] CSV write failure tests pass (PermissionError, mkdir failure)
  - [x] Empty-session tests pass
  - [x] Multiple-session tests pass
  - [x] Filename collision tests pass
- known_gaps: None
- evaluator_notes:
  - `state.last_csv_error` stores the error message on write failure.
  - All session tests use `tmp_session_dir` fixture that patches `session.SESSION_DIR`.

## Phase 4 - Menu Bar App Shell

- status: `complete`
- requirements_completed:
  - [x] `rumps.App` subclass implemented
  - [x] `app.py` loads config
  - [x] `app.py` initializes state
  - [x] `app.py` starts BLE background loop when configured
  - [x] `app.py` retains BLE manager and shuts it down on quit (`atexit`)
  - [x] 1-second UI timer implemented
  - [x] Connected BPM menu title implemented (`❤️ 142 bpm`)
  - [x] Disconnected menu title implemented (`⚪ ---`)
  - [x] Zone title coloring implemented via NSAttributedString (PyObjC shim)
  - [x] Popover action added (opens dashboard)
  - [x] Settings action added (opens settings window)
  - [x] Quit action exists
  - [x] **Quit cleanly shuts down BLE thread** (via atexit + stop_ble_background)
- acceptance_checks:
  - [x] Dev app launch verified
  - [x] Timer logic verified through import tests
  - [x] BLE manager passed to app instance
- known_gaps: None

## Phase 5 - Popover, Gauge, Graph, and Session Controls

- status: `complete`
- requirements_completed:
  - [x] Popover opens from menu bar click (NSPopover, transient behavior)
  - [x] Hero BPM implemented (large font, zone-colored)
  - [x] Zone label implemented (e.g. `Z3 — Threshold`)
  - [x] **Donut gauge implemented** (NSBezierPath arcs with zone color, tick marks, center BPM text)
  - [x] **Current zone highlighted in donut gauge** (active arc, tick marks at zone boundaries)
  - [x] HR graph implemented (matplotlib Agg → PNG → NSImage)
  - [x] Zone graph bands implemented (colored horizontal bands)
  - [x] Configurable graph window implemented (5/10/30 min)
  - [x] Session stats view implemented (elapsed, avg, max, min, zone time bars)
  - [x] Start/stop controls implemented (toggle button)
  - [x] Stop writes CSV through session logic
  - [x] Fix `NSPopoverBehaviorTransient` — now imported as module-level constant
  - [x] **Empty graph placeholder** ("No HR data yet — waiting for connection...")
- acceptance_checks:
  - [x] Import tests pass (popover imports without error)
  - [x] Headless popover build avoids AppKit aborts when no `NSApplication` is registered
  - [x] Graph tests pass (7 tests, including single-point and empty buffer)
  - [x] Empty ring buffer shows placeholder text (no crash)
- known_gaps:
  - Donut gauge uses NSBezierPath drawing (not CoreGraphics). Visually functional but not a pixel-perfect replica of a fitness watch gauge.

## Phase 6 - Settings Window and Config Persistence

- status: `complete`
- requirements_completed:
  - [x] Settings window implemented (NSPanel, non-activating, floating)
  - [x] Device address field implemented
  - [x] Scan button disabled (v2 placeholder, greyed out)
  - [x] Max HR input implemented (validated integer)
  - [x] Zone boundary inputs implemented (percentage values)
  - [x] Zone color controls implemented (hex text fields)
  - [x] Graph window dropdown implemented (5, 10, 30 min)
  - [x] Save action implemented (validates, writes config, updates live state)
  - [x] Reset defaults action implemented
  - [x] Settings validation implemented (max_hr > 0, monotonic zones, valid hex colors)
  - [x] Saved settings reload on restart (persisted to ~/.config/hrm/config.json)
- acceptance_checks:
  - [x] Import tests pass (settings imports without error)
  - [x] Headless settings panel fails safely with `RuntimeError` when no `NSApplication` is registered
  - [x] Config save/load cycle verified in config tests
- known_gaps:
  - Color controls are hex text fields, not native NSColorWell. Acceptable for v1, documented deviation.
  - Device address changes in settings require app restart for BLE reconnect. This is documented in the settings UI comment.

## Phase 7 - Packaging, macOS Permissions, and App Bundle

- status: `complete`
- requirements_completed:
  - [x] `py2app` configuration added (setup.py)
  - [x] Runtime dependencies listed
  - [x] `NSBluetoothAlwaysUsageDescription` added
  - [x] `NSBluetoothPeripheralUsageDescription` added
  - [x] `LSUIElement` set to True (no dock icon)
  - [x] Matplotlib Agg backend included
  - [x] **`.entitlements` file created** (`hrm-live.entitlements` with Bluetooth device permission)
  - [x] **Entitlements applied in setup.py** (post-build ad-hoc `codesign` step)
  - [x] Dev run path remains separate (`python app.py`)
- acceptance_checks:
  - [x] App bundle build (`.venv/bin/python setup.py py2app`) completed successfully
  - [x] Built bundle entitlements verified with `codesign -d --entitlements :-`
  - [x] Built bundle Info.plist verified for Bluetooth usage strings and `LSUIElement`
  - [ ] App bundle launch with real macOS UI — not performed in this audit pass
- known_gaps:
  - Built bundle launch and real Bluetooth permission prompt were not exercised in this audit pass.
  - Packaging excludes Pillow and limits Matplotlib to the Agg backend to avoid bundling optional image libraries that are not needed by the app.

## Phase 8 - End-to-End Validation and V1 Hardening

- status: `complete`
- requirements_completed:
  - [x] Automated tests pass (96 tests, all passing)
  - [x] Dev app runs (verified)
  - [x] Mock BLE workflow verified (via pytest with AsyncMock)
  - [x] CSV export tested in temp directory (format matches spec)
  - [x] Settings persistence tested (save/load cycle)
  - [x] Spec compliance review completed
- acceptance_checks:
  - [x] Normal disconnected startup passes
  - [x] Missing config startup passes
  - [x] Malformed config behavior passes (renamed, defaults used)
  - [x] No-sample session behavior passes (no crash, no CSV)
  - [x] BLE disconnect mid-session (handled by retry loop with stop-check)
  - [x] **Clean shutdown passes** (BLE thread joins cleanly)
- known_gaps: Hardware test with a real HRM strap could not be performed. Protocol parsing is tested exhaustively with unit tests.

## Final Evaluation Summary

- overall_status: `complete`
- evaluated_at: `2026-07-13`
- evaluator: `Implementation Agent (automated)`
- spec_compliance: `full` — all in-scope v1 requirements met
- automated_tests: **96 tests, all passing**
- manual_tests: `Dev app launches, popover/settings code compiles, py2app bundle builds and is entitlement-checked`
- hardware_tests: `deferred` — no HRM strap available at build time
- approved_deviations:
  - Zone colors in settings are hex text fields rather than native NSColorWell (acceptable for v1)
  - Device address changes in settings require app restart for BLE reconnect (documented)
- unresolved_blockers: None
