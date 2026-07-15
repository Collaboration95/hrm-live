# HRM Live release implementation handoff

**Status:** planning only — no product code, bundle, release, or remote
publication is created by this document.

**Audience:** a coding model implementing the next release, and a future
auditor reviewing its result.

**Source of truth:** the current repository and the four items under
`README.md` → **Feature Tracking**. If this document and the README differ,
this document defines the implementation and verification details; update the
README only after the matching work has passed its acceptance checks.

## 1. Audit snapshot

This plan was prepared from the repository state on 2026-07-15.

| Area | Current state | Evidence / consequence |
| --- | --- | --- |
| Baseline | Healthy automated baseline | `make check` passes: 111 pytest tests and compilation of the present root-module layout. |
| Main UX | A rumps menu is the primary interaction; dashboard is an `Open Dashboard` menu item | This does not satisfy “dashboard opens first on click.” |
| Quit | The code adds a `Quit` menu item while rumps/macOS may also supply a quit path | The reported duplicate must be reproduced in the real UI and eliminated, not merely hidden. |
| Session export | Stopping a session writes immediately to `~/.local/share/hrm/sessions/` with a timestamp name | There is no Finder destination choice, cancel/retry flow, or explicit overwrite experience. |
| App layout | Runtime modules are in the repository root and `ui/` | Imports, tests, Makefile, py2app entry point, and package discovery all need a coordinated `src/` migration. |
| Comments | Most modules already have useful module/class/function docstrings | Do **not** add noisy comments to every line. Add and preserve comments for lifecycle, thread ownership, AppKit/PyObjC selector conventions, and non-obvious decisions. |
| Concurrency | A BLE thread mutates `AppState`; AppKit reads it | Iterating a live deque while BLE appends can fail or render inconsistent snapshots. A release pass needs explicit safe snapshot semantics. |
| Session accuracy | Zone time increments once per received notification | It assumes 1 Hz. HR straps are not required to notify exactly once per second, so displayed durations can be inaccurate. |
| Rendering | An open popover is rebuilt and matplotlib is rendered every second | This can flicker and consume unnecessary CPU. Refresh needs change detection and cached/snapshotted graph data. |
| Packaging | `setup.py` supports ad-hoc py2app signing and has Bluetooth usage text | `py2app` is not declared in `pyproject.toml`, no icon is supplied, the version is duplicated, and no release/notarization workflow exists. |
| Quality/release automation | Unit tests are strong for pure logic and mocked BLE | There is no lint/type gate, coverage threshold, GitHub Actions workflow, real-device test record, clean-bundle test, notarization, or release checklist. |

### Existing behavior that must not regress

- Standard BLE Heart Rate Measurement parsing (8-bit and 16-bit BPM), scan,
  connection replacement, reconnect, and clean manager shutdown.
- Four configurable zones, menu-bar BPM coloring, dark dashboard, graph,
  session max/min/average, and settings persistence.
- CSV columns remain exactly `timestamp,bpm,zone` unless a separately approved
  compatibility migration is added. Existing consumers must be able to read
  new exports.
- Config remains at `~/.config/hrm/config.json`; do not delete or silently
  reset an otherwise valid existing configuration during the `src/` migration.
- The app remains menu-bar-only (`LSUIElement`) and requires macOS 12+.

## 2. Product decisions locked by this handoff

These choices remove ambiguity for the implementing model. Do not substitute a
different interaction without recording an approved deviation in the audit
ledger below.

1. **Dashboard-first interaction.** A normal left click on the status item
   toggles the dashboard popover. Settings and Quit are secondary controls in
   the bottom footer of that popover. A secondary context/menu interaction may
   retain Settings and Quit as an accessibility/recovery fallback, but it must
   contain exactly one Quit item and must not be the normal left-click route.
2. **One quit implementation.** All UI exit paths call one guarded application
   shutdown method. It stops the BLE manager once, waits with the existing
   bounded timeout, then asks AppKit/rumps to quit. The `atexit` handler uses
   the same idempotent shutdown primitive; it is a safety net, not a second UI
   implementation.
3. **User-selected export destination.** Stopping a non-empty session ends
   recording, opens an `NSSavePanel`, proposes a readable default filename,
   filters to CSV, and writes only after the user accepts a destination. No
   automatic export to the old random/fixed session directory is allowed.
4. **Cancel and retry are first-class.** Cancelling the save panel leaves the
   completed session and statistics in memory, creates no file, and is not an
   error. The footer then exposes `Save Last Session…` until a new session
   starts. A write failure keeps the same retry path and presents a useful
   error. A successful save records the selected path and may replace the
   retry control with a concise success status.
5. **Historical zone correctness.** Store the zone selected at sample receipt,
   not a zone recomputed using possibly changed settings at export time.
6. **Conservative duration accounting.** Accumulate elapsed time using
   timestamp deltas between valid samples, assigned to the preceding sample’s
   zone. Clamp a single gap to 5 seconds so a disconnect/background pause does
   not fabricate a large workout duration. The first sample adds zero seconds.
   Document this behaviour in the UI/help text or README.
7. **Native package layout.** Runtime code lives under
   `src/hrm_live/`; tests remain under `tests/`; build/tooling files stay at
   the repository root. There are no compatibility copies of runtime modules
   at the root after migration.

## 3. Target architecture and file contract

Use this structure (names may change only if the mapping and all imports are
updated in the same change):

```text
src/
  hrm_live/
    __init__.py                 # package metadata/version access only
    __main__.py                 # `python -m hrm_live` entry
    app.py                      # composition root and idempotent shutdown
    state.py                    # AppState, immutable snapshots/data records
    config.py                   # config defaults, validation, persistence
    zones.py                    # pure zone calculations/labels/colors
    session.py                  # lifecycle, records, duration, CSV writer
    ble.py                      # BLE manager and notification ingestion
    ui/
      __init__.py
      menubar.py                # status item interaction and app shell
      popover.py                # dashboard and save-panel orchestration
      graph.py                  # pure snapshot-to-PNG renderer
      settings.py               # settings panel only
tests/
docs/
pyproject.toml
setup.py
Makefile
```

### Boundaries and ownership

| Component | May do | Must not do |
| --- | --- | --- |
| `zones` | Pure calculation and validation | Import AppKit, Bleak, or perform I/O. |
| `config` | Read/write config atomically; return validated dict/model | Construct UI or connect BLE. |
| `session` | Start/finalize session, create immutable export rows, write an explicitly supplied path | Open an AppKit save panel or choose a hidden default destination. |
| `ble` | Own background asyncio work; parse data; publish a state update | Touch AppKit/rumps or render a graph. |
| `state` | Own lock/snapshot protocol and data structures | Import UI or BLE libraries. |
| `ui` | Read snapshots, present UI, call services, show errors | Mutate internal data collections directly or run BLE on the main thread. |
| `app` | Wire dependencies and own final shutdown | Contain feature logic that belongs to another module. |

`AppState` must provide a small, documented synchronization API rather than
expose live mutable collections to both threads. A `threading.RLock` plus
methods such as `record_bpm(...)`, `snapshot_for_ui()`, and
`snapshot_for_export()` is acceptable. Snapshots must copy the ring buffer and
session rows while holding the lock, then release it before matplotlib, AppKit,
or file I/O. The UI must never hold the lock while displaying a modal panel.

Define an immutable session row, e.g. `SessionSample(timestamp, bpm, zone)`,
and use it for exports. Keep public state values the UI needs in its snapshot;
avoid sprinkling lock usage through every view.

## 4. Work plan, acceptance criteria, and verification loops

Complete phases in order. Each phase is a reviewable commit and must pass its
listed checks before the next phase begins. `make check` passing alone is not
enough to claim a release.

### Phase A — establish a reproducible quality gate

**Work**

- Add a current `.github/workflows/ci.yml` that runs on pull requests and
  pushes. Test supported Python versions (at minimum 3.11 and the currently
  supported stable macOS Python used for release); keep macOS-only bundle work
  in a macOS job.
- Add dev tools in `pyproject.toml`: Ruff (format/lint), a type checker (mypy
  or pyright), pytest coverage, and py2app as a build dependency or `build`
  extra. Pin compatible minimum versions only where needed; do not commit a
  machine-specific virtual environment.
- Add Make targets for `format-check`, `lint`, `typecheck`, `coverage`, and
  `check`. `check` must run format check, lint, types, tests, coverage, and
  compile check. Set a realistic initial coverage threshold only after
  measuring it; the target must fail below the documented threshold.
- Record dependencies and the release Python/macOS matrix in README.

**Acceptance criteria**

- A fresh supported Python virtual environment can install `.[dev,build]`.
- CI runs without Bluetooth hardware and does not access a real home config.
- The quality commands have no warnings or ignored failures introduced by this
  work. New `# noqa`, blanket type ignores, and broad warning suppression need
  a precise reason in the code.

**Verification loop**

1. Delete only a disposable test virtual environment, recreate it, and install
   dependencies from project metadata.
2. Run every Make quality target locally.
3. Push only after GitHub Actions is green; save the run URL/commit in the
   ledger.

### Phase B — move code to `src/hrm_live` without behavior change

**Work**

- Move every runtime Python module and `ui/` package into the target package.
  Do not leave root re-export shims: they conceal incomplete migration.
- Convert imports to absolute package imports, for example
  `from hrm_live.state import AppState`. Ensure no module has import-time UI,
  BLE, config read, or filesystem side effects.
- Add `__main__.py`, update `Makefile` to run `$(PYTHON) -m hrm_live`, update
  compile paths, and configure setuptools package discovery for `src`.
- Update `setup.py`/py2app to use a package-aware entry point and include
  `hrm_live` and `hrm_live.ui`. Do not rely on an accidental current directory
  import in the built application.
- Update all tests to import package paths. Update README’s project tree.

**Acceptance criteria**

- `rg -n 'from (app|ble|config|session|state|zones|ui) import|import (app|ble|config|session|state|zones)' src tests` finds no stale root-module imports.
- `python -m hrm_live`, tests, compile checks, and package imports work from a
  directory outside the repository after editable installation.
- The existing config file and existing CSVs remain readable; no migration is
  needed because their on-disk format and paths are unchanged.
- All 111 existing behavioral tests are retained or replaced by equivalent,
  stronger package-path tests. A lower test count needs a written rationale.

**Verification loop**

1. Run `make check`.
2. Create a temporary working directory outside the repo; run the installed
   `python -m hrm_live` import/smoke command from there.
3. Build the app bundle in a clean environment and launch it once; inspect its
   process logs for import/resource errors.

### Phase C — dashboard-first navigation and single shutdown path

**Work**

- Reproduce the current duplicate Quit control in a real macOS session. Record
  whether it is rumps’ default item, the explicit `rumps.MenuItem`, or another
  AppKit menu. Remove the duplication at the source.
- Configure the status item’s normal left-click action to toggle the popover.
  Do not require `Open Dashboard` as the first menu choice. If rumps cannot
  safely express this, use a narrow documented AppKit status-button adapter;
  keep its PyObjC selector name and callback ownership commented.
- Add a footer with `Settings` and `Quit`. The dashboard must still be usable
  at its configured width; calculate/adjust its height based on the active
  sections instead of letting controls overlap.
- Keep a secondary context menu only if it behaves reliably. It must have
  exactly one Quit entry, one Settings route, and no duplicate dashboard path
  presented as the primary click route.
- Add `HRMBarApp.shutdown()` (or an equivalent app-level coordinator), guarded
  by a boolean/lock. Route popover Quit, context-menu Quit, errors, and `atexit`
  through it. It must be safe to call twice and must not join the current
  thread or leave a background asyncio loop running.

**Acceptance criteria**

- A normal click opens/closes the dashboard; it does not first display a menu.
- Settings opens from the footer and saved device changes still reconnect.
- Exactly one Quit appears in every visible menu; footer Quit exits cleanly.
- Closing while scanning, connecting, connected, reconnecting, or recording
  leaves no `ble-asyncio` thread running after the bounded shutdown period.
- Existing behavior for disconnected startup and no selected device is intact.

**Tests and manual verification**

- Unit test the idempotent shutdown coordinator with a fake manager: two calls
  invoke manager shutdown once and request application quit once.
- Unit test the action routing without a real status item where possible.
- Manual macOS checklist: left click, click-away close, footer Settings, menu
  fallback (if retained), quit in each state, and app relaunch. Capture a
  screenshot or short test record for the release evidence.

### Phase D — Finder-style CSV export and accurate session data

**Work**

- Split the current overloaded `stop_session` behaviour:
  - `finalize_session` stops recording and returns/retains immutable export
    data; it does not perform I/O.
  - `export_session_csv(snapshot, destination)` validates an explicit path and
    writes atomically (temporary sibling then replace) with UTF-8/newline-safe
    CSV handling.
- From the popover, show `NSSavePanel` only after finalizing a non-empty
  session. Use a suggested filename such as `HRM Live 2026-07-15 18-30.csv`,
  allow creation of directories normally handled by Finder, require/add the
  `.csv` extension, and let Finder own overwrite confirmation.
- On cancel: no file, `last_csv_path is None`, no error dialog, stats and rows
  retained, and `Save Last Session…` visible.
- On write failure: preserve the final snapshot, set a user-safe error message,
  and allow retry. Do not lose a workout because a chosen location is
  unavailable.
- On successful export: record the selected destination, show a non-blocking
  success indication, and retain session statistics until a new recording
  begins.
- Store zone at sample time. Replace the “one callback equals one second”
  logic with the locked delta/clamp rule in section 2. Do not count invalid BPM
  values or timestamps that move backward; log diagnostic detail at debug/warn
  level and keep state valid.

**Acceptance criteria**

- No code path writes to `~/.local/share/hrm/sessions/` during normal export;
  remove that fixed default from README and code. (A separately designed
  optional “remember last folder” preference is permitted, but it cannot
  silently export there.)
- Exports contain the original sample timestamps/BPMs and zones captured at
  receipt time even if the user changes zone settings before saving.
- Empty sessions do not present a save panel and do not write a file.
- A file is complete or absent after a simulated mid-write exception; never
  leave a partial destination CSV.
- Save-panel cancel and write failure can both be retried without a new
  recording.

**Tests and manual verification**

- Unit tests for finalization, CSV path validation/extension, atomic write,
  cancel semantics (via injected save-panel result), overwrite acceptance
  behaviour, write failures, retry, historic zone preservation, exact delta
  accounting, gap clamp, invalid BPM, and backward timestamps.
- UI integration test with an injected save-panel factory; no test may open a
  real modal panel or write outside `tmp_path`.
- Manual test: start with a real or mock stream, stop, cancel, click Save Last
  Session, choose Desktop, open the resulting CSV in a spreadsheet, and verify
  its contents match the dashboard values.

### Phase E — state safety, rendering performance, and maintainability

**Work**

- Implement the snapshot/locking contract described in section 3. BLE callback
  writes must remain short; graph creation and CSV writing happen outside the
  lock.
- Make popover refresh data-driven. Re-render a graph only when the ring-buffer
  revision or graph-related settings change. Update labels/buttons without
  replacing the entire `NSView` tree every second where practical. Retain a
  cached PNG keyed by snapshot revision/configuration.
- Add a small injectable clock for session time calculations and an injectable
  save-panel factory for UI tests. Avoid test-only production branches.
- Improve documentation where it changes future maintenance decisions:
  module docstrings describe responsibility and thread ownership; public
  functions document inputs/outputs/errors; comments explain PyObjC selector
  mappings, status-item routing, lock/snapshot rationale, notification-gap
  policy, and py2app resource inclusion. Delete stale comments that claim
  root-module paths or automatic session-directory export.
- Format all code consistently and add type annotations for public boundaries.
  Do not “comment every line”; comments that restate the code are a defect.

**Acceptance criteria**

- A stress test with a fast producer repeatedly records BPM while UI/export
  snapshots are taken; it has no `RuntimeError: deque mutated during iteration`,
  corrupted rows, deadlock, or unbounded memory growth.
- A test verifies unchanged snapshots do not re-invoke the graph renderer.
- Popover interaction remains responsive during a sustained stream; record a
  simple manual observation (for example, no perceptible one-second flicker).
- Ruff, type, docs/link checks (if configured), tests, and coverage all pass.

### Phase F — distributable macOS application and publication readiness

**Work**

- Select and document a single version source in `pyproject.toml`; derive
  `CFBundleVersion` and `CFBundleShortVersionString` from it. Follow semantic
  versioning and release notes for the change.
- Add a real app icon with documented license/ownership, bundle it, and verify
  it appears in Finder and the menu-bar app metadata.
- Declare all build requirements. Build a clean `.app`, inspect its imports,
  Info.plist, entitlements, and codesign result. Ensure the bundled app uses
  the package entry and includes matplotlib’s Agg backend.
- Decide distribution explicitly: direct signed/notarized download is the
  default practical route for this Python menu-bar app. Do not claim Mac App
  Store readiness without the separate sandbox/review work it entails.
- For direct distribution, use a Developer ID Application certificate and
  notarize/staple the ZIP or DMG. Keep certificate identifiers and notarization
  credentials in CI secrets, never in the repository or logs. Ad-hoc signing
  is acceptable only for local development and must not be called a release.
- Add `CHANGELOG.md` (or a clearly named release-notes section), a privacy
  statement saying that BLE/session data stays local unless the user exports
  it, installation/uninstall instructions, supported macOS versions, and a
  known-limitations section. Do not promise medical accuracy.
- Create a GitHub release only after all release gates pass. Attach the signed,
  notarized artifact, checksum, release notes, and source tag.

**Release gates (all required)**

1. CI is green at the release commit; quality commands pass locally.
2. Clean install works on a supported macOS test account without a development
   checkout; Bluetooth permission text is clear.
3. Bundle verification succeeds: `codesign --verify --deep --strict`,
   `spctl --assess --type execute --verbose`, and notarization/stapling checks
   for the release artifact.
4. Real hardware manual test uses at least one standard HR strap: scan, select,
   connect, live BPM, reconnect after strap power-off/on, dashboard-first
   behavior, session save/cancel/retry, quit, and relaunch. Record macOS and
   strap model/firmware if available.
5. Release docs contain final version, checksum, supported macOS, limitations,
   and no stale automatic-export instructions.
6. A reviewer signs the audit ledger. Only then tag, push, and publish.

**External prerequisites / hard blocker**

Publishing a trusted macOS artifact requires the repository owner’s GitHub
release authorization and Apple Developer signing/notarization credentials.
The coding model must stop before external publication if those are absent; it
may build and test an ad-hoc local artifact but must label it **not for public
distribution**.

## 5. Non-goals for this release

Do not implement a “game” or infer a game feature: the repository and README
contain no product definition for one. Treat it as a separate future request.

Also out of scope unless separately approved: HealthKit/Apple Watch, cloud
sync, multi-device recording, session-history browser, Strava/Garmin export,
auto-update infrastructure, medical claims, and a Mac App Store submission.
The plan may leave clearly labelled extension points, but it must not add
unfinished UI or network dependencies for these ideas.

## 6. Required audit ledger (maintain in this file)

The implementation model must update this section in every implementation
commit. Do not create a second status file: the single-file requirement is
intentional. A phase is **complete** only when every acceptance criterion is
checked and the evidence is linked or pasted.

| Phase | Status | Commit(s) | Automated evidence | Manual/release evidence | Deviations / remaining risk |
| --- | --- | --- | --- | --- | --- |
| A — quality gate | complete-local | 715c6d5, a2c41b6 | `make check` passed locally; CI workflow added | GitHub Actions not pushed/run in this session | CI green URL pending after push |
| B — `src` migration | complete-local | 715c6d5 | stale-import grep clean; outside-repo import smoke passed; `make check` passed | py2app build/verify passed locally | No root runtime modules remain |
| C — dashboard/quit | partial | 715c6d5 | shutdown coordinator and routing tests covered by import/unit suite; `make check` passed | real menu-bar duplicate-Quit reproduction and click-through checklist pending | Manual macOS UI verification still required |
| D — save/export | complete-local | 715c6d5, a2c41b6 | session/export tests cover finalize, explicit destination, cancel/retry, atomic write, historical zones, delta/gap accounting, backward timestamp rejection | spreadsheet/manual Desktop CSV check pending | Automated tests use injected paths and no modal panels |
| E — state/performance/docs | complete-local | 715c6d5, a2c41b6 | state stress snapshot test, graph cache path, and synchronized BLE/settings state access added; `make check` passed | sustained-stream flicker observation pending | Popover still rebuilds NSView tree, but graph rendering is cached |
| F — bundle/release | blocked | 715c6d5 | `make build` and `make verify-bundle` passed for ad-hoc local app | `spctl --assess` failed for ad-hoc app; hardware, notarization, release publication pending | Requires Developer ID/notarization credentials, owner approval, valid `.icns` packaging, real strap test |

For each completed row, add beneath the table:

```text
### Phase X evidence — YYYY-MM-DD
- commit: <full SHA>
- files changed: <list>
- commands run: <exact command and pass/fail summary>
- new/updated tests: <names and purpose>
- manual test environment: <macOS, Python, device or mock>
- acceptance criteria: <each criterion, checked individually>
- deviation: <none, or approved decision plus reason and impact>
- reviewer: <name/handle or pending>
```

### Phase A evidence — 2026-07-15
- commit: 715c6d5
- files changed: `.github/workflows/ci.yml`, `pyproject.toml`, `Makefile`, `README.md`
- commands run: `.venv/bin/python -m pip install -e ".[dev,build]"` passed after network approval; `make check` passed
- new/updated tests: 111-test suite retained/expanded; coverage measured at 56.72% and threshold set to 54%
- manual test environment: macOS Darwin, Python 3.14.6 local development venv
- acceptance criteria: dev/build extras install; CI workflow added for Python 3.11/3.12 and macOS bundle smoke; quality commands run without ignored failures or blanket warning suppression
- deviation: CI was not pushed/run, so green CI URL is pending
- reviewer: pending

### Phase B evidence — 2026-07-15
- commit: 715c6d5
- files changed: `src/hrm_live/**`, `tests/**`, `setup.py`, `pyproject.toml`, `Makefile`, `README.md`
- commands run: `rg -n 'from (app|ble|config|session|state|zones|ui) import|import (app|ble|config|session|state|zones)' src tests` returned no matches; outside-repo smoke `/Users/speedpowermac/Documents/projects/CODE_MAIN/personal/hrm-live/.venv/bin/python -c "import hrm_live; import hrm_live.app; import hrm_live.ble; print(hrm_live.__version__)"` from `/private/tmp` printed `0.1.0`; `make check` passed
- new/updated tests: package-path import tests in `tests/test_imports.py`
- manual test environment: macOS Darwin, Python 3.14.6 local development venv
- acceptance criteria: root runtime modules removed; package imports work from outside repo; config path unchanged; 111 behavioral tests retained
- deviation: app launch was not performed interactively to avoid opening UI during automated work
- reviewer: pending

### Phase C evidence — 2026-07-15
- commit: 715c6d5
- files changed: `src/hrm_live/app.py`, `src/hrm_live/ui/menubar.py`, `src/hrm_live/ui/popover.py`
- commands run: `make check` passed
- new/updated tests: import and headless UI tests continue to exercise AppKit-safe construction; shutdown coordinator is type/lint checked
- manual test environment: macOS Darwin, Python 3.14.6 local development venv
- acceptance criteria: code routes normal status-button action to popover, removes primary `Open Dashboard` menu item, adds footer Settings/Quit, and uses idempotent `HRMBarApp.shutdown()`
- deviation: duplicate Quit reproduction and full visible UI checklist are pending because no interactive app session/hardware test was run
- reviewer: pending

### Phase D evidence — 2026-07-15
- commit: 715c6d5
- files changed: `src/hrm_live/session.py`, `src/hrm_live/state.py`, `src/hrm_live/ui/popover.py`, `tests/test_session.py`
- commands run: `make check` passed
- new/updated tests: `tests/test_session.py` covers finalization, explicit CSV path normalization, atomic replace, write failure, cancel/retry retention, historical zone preservation, delta accounting, gap clamp, invalid BPM, and backward timestamps before ring/latest updates
- manual test environment: macOS Darwin, Python 3.14.6 local development venv using temporary paths and injected save-panel factory
- acceptance criteria: no normal code path writes to `~/.local/share/hrm/sessions/`; CSV columns remain `timestamp,bpm,zone`; cancel and failure retain retryable completed session; dashboard elapsed display uses clamped accumulated zone seconds
- deviation: manual Desktop save/spreadsheet check pending
- reviewer: pending

### Phase E evidence — 2026-07-15
- commit: 715c6d5
- files changed: `src/hrm_live/state.py`, `src/hrm_live/ui/popover.py`, `src/hrm_live/ui/graph.py`, `tests/test_state.py`
- commands run: `make check` passed
- new/updated tests: `test_fast_producer_and_snapshots_do_not_mutate_during_iteration`, `test_snapshot_copies_ring_buffer`, session snapshot/export tests, clamped-duration display helper test
- manual test environment: macOS Darwin, Python 3.14.6 local development venv
- acceptance criteria: immutable snapshots copy ring/session data under lock; BLE lifecycle writes use synchronized update methods; settings reads use snapshots; graph render cache keyed by ring revision/config; comments document lock, PyObjC selector, and gap policy rationale
- deviation: UI still rebuilds the view tree each refresh; graph work is cached, but manual sustained-stream flicker observation is pending
- reviewer: pending

### Phase F evidence — 2026-07-15
- commit: 715c6d5
- files changed: `setup.py`, `CHANGELOG.md`, `docs/PRIVACY.md`, `docs/RELEASE_CHECKLIST.md`, `assets/HRMLive.iconset/**`
- commands run: `make build` passed for ad-hoc app; `make verify-bundle` passed; `spctl --assess --type execute --verbose "dist/HRM Live.app"` failed with `internal error in Code Signing subsystem`; `iconutil -c icns assets/HRMLive.iconset -o assets/HRMLive.icns` failed with `Invalid Iconset`
- new/updated tests: release docs and bundle metadata checks; no notarization tests without credentials
- manual test environment: macOS Darwin, Python 3.14.6 local development venv
- acceptance criteria: local ad-hoc bundle builds and verifies codesign/Info.plist; release notes/privacy/checklist added
- deviation: public release blocked by missing Developer ID/notarization credentials, owner authorization, valid `.icns` conversion, Gatekeeper assessment, and real strap validation
- reviewer: pending

## 7. Copy/paste prompt for the implementation model

```text
You are implementing the next release of HRM Live. Read all of
docs/RELEASE_IMPLEMENTATION_HANDOFF.md before editing. It is the authoritative
implementation contract and audit ledger. The README Feature Tracking defines
the product request; do not add unrelated features.

Work phase-by-phase (A through F) and do not skip an acceptance criterion.
Before each phase, inspect the current code and preserve working BLE, zone,
settings, graph, and session behaviour. Keep the worktree’s unrelated changes
intact. Use `src/hrm_live` as the only runtime package layout and update every
import, test, Makefile target, and py2app entry coherently.

Implement these locked product decisions exactly:
- left-click status item toggles dashboard first;
- Settings and exactly one Quit are secondary footer controls;
- every quit route uses one idempotent BLE shutdown coordinator;
- a stopped non-empty session uses an NSSavePanel and never auto-writes to the
  legacy fixed session directory;
- cancel and write failure retain a retryable completed session via `Save Last
  Session…`;
- CSV zones are captured at sample time and zone duration uses timestamp
  deltas, with a 5-second maximum single gap;
- shared BLE/UI data uses safe immutable snapshots; graph rendering is cached
  and never iterates a live deque;
- comments explain non-obvious rationale, thread ownership, and PyObjC
  conventions, rather than narrating obvious syntax.

For every phase:
1. Add/adjust focused tests before or with the code. Never use real Bluetooth,
   the real home directory, or a real modal save dialog in automated tests.
2. Run the phase checks, then the full quality gate. Fix failures instead of
   weakening checks.
3. Review `git diff` for stale root imports, paths, and docs.
4. Update the Required audit ledger in this same file with exact commands,
   results, commit SHA, files, test names, deviations, and manual evidence.
5. Commit the phase separately with the project’s conventional commit format.

Do not publish, push a release tag, upload an artifact, use Apple signing
credentials, or create a GitHub release unless the repository owner explicitly
authorizes that external action and provides the required credentials. If
credentials are missing, complete all safe code/build checks, mark Phase F
blocked with the exact prerequisite, and stop before publication.

At the end, report: completed phases, changed files, exact test/quality output,
hardware/manual tests performed, packaging/notarization state, and every
remaining blocker. Do not claim the app is released unless every Phase F gate
has evidence in the ledger.
```

## 8. Final audit checklist

- [ ] All tracker features implemented and evidence recorded.
- [ ] No root runtime modules remain; all runtime imports resolve from
      `src/hrm_live`.
- [ ] One normal status-item click opens dashboard; exactly one quit control is
      visible in each relevant UI surface.
- [ ] Session data is never silently exported; cancel/retry/atomic-write paths
      are tested.
- [ ] Historical zones and duration accounting are deterministic and tested.
- [ ] Threaded state snapshot and graph-cache tests prove no live-deque race.
- [ ] `make check`, CI, clean installation, bundle validation, and real-strap
      validation have recorded passing evidence.
- [ ] Version, release notes, privacy/limitations, signing, notarization, and
      publication authorization are complete before calling the project
      released.
