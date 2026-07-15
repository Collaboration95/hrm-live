# Implementation Notes

> Historical implementation record. The current independent release decision,
> P0 defects, and ordered remediation plan are in
> [`docs/RELEASE_READINESS_AUDIT_2026-07-15.md`](docs/RELEASE_READINESS_AUDIT_2026-07-15.md).
> This file must not be used as evidence that the app is release-ready.

## Summary

Implemented the HRM Live release handoff as a local, tested implementation.
The work is not a public release because CI has not been run after push,
manual real-device testing is pending, Gatekeeper assessment fails for the
ad-hoc bundle, and Developer ID/notarization credentials were not provided.

## Completed Locally

- Added CI workflow and local quality gate:
  - Ruff format check
  - Ruff lint
  - mypy
  - pytest
  - pytest-cov with a measured 54% initial threshold
  - compileall
- Migrated runtime code to `src/hrm_live`.
- Added `python -m hrm_live` and `hrm-live` console entry points.
- Removed root runtime modules.
- Updated py2app packaging to use the package entry.
- Added locked `AppState` mutation/snapshot API.
- Added immutable `SessionSample`, `UISnapshot`, and `ExportSnapshot`.
- Replaced automatic session-directory export with explicit user-selected CSV
  export.
- Added cancel/retry handling with `Save Last Session...`.
- Added atomic CSV writes using a sibling temp file and replace.
- Stored zone at sample receipt time.
- Changed zone duration accounting to timestamp deltas assigned to the
  previous sample's zone, clamped at 5 seconds per gap.
- Dashboard elapsed session display now uses those accumulated clamped zone
  seconds rather than wall-clock time.
- Backward timestamps are rejected before updating latest BPM or the graph
  ring buffer.
- Added graph rendering cache keyed by ring-buffer revision and graph config.
- Routed BLE lifecycle updates and settings reads through the synchronized
  state API/snapshots.
- Added dashboard-first status-button action and a guarded shutdown
  coordinator.
- Added footer Settings and Quit controls.
- Added release notes, privacy notes, and release checklist.
- Built and verified a local ad-hoc `.app` bundle.

## Verification Run

Commands run and passing:

```bash
.venv/bin/python -m pip install -e ".[dev,build]"
make check
rg -n 'from (app|ble|config|session|state|zones|ui) import|import (app|ble|config|session|state|zones)' src tests
/Users/speedpowermac/Documents/projects/CODE_MAIN/personal/hrm-live/.venv/bin/python -c "import hrm_live; import hrm_live.app; import hrm_live.ble; print(hrm_live.__version__)"
make build
make verify-bundle
```

`make check` result:

- 111 tests passed.
- Coverage: 56.72%, required threshold 54%.
- Ruff format/lint passed.
- mypy passed.
- compileall passed.
- No blanket pytest warning suppression is configured.

Bundle verification:

- `make build` completed for `dist/HRM Live.app`.
- `make verify-bundle` passed `codesign --verify --deep --strict` and
  Info.plist Bluetooth/LSUIElement checks.

## Remaining Blockers

- GitHub Actions was added but not pushed/run, so there is no green CI URL.
- Manual real UI checklist is pending:
  - status item left-click opens dashboard directly
  - exactly one Quit in each visible menu surface
  - footer Settings
  - click-away close
  - quit while disconnected/scanning/connecting/connected/reconnecting/recording
- Real HR strap validation is pending.
- Manual cancel/retry/Desktop CSV/spreadsheet validation is pending.
- `spctl --assess --type execute --verbose "dist/HRM Live.app"` failed for the
  ad-hoc local bundle with `internal error in Code Signing subsystem`.
- Developer ID signing, notarization, stapling, checksum, and publication
  authorization are missing.
- Generated project-owned icon PNG sources exist under
  `assets/HRMLive.iconset`, but `iconutil` rejected them as `Invalid Iconset`;
  the bundle is therefore still using the default icon.
- The popover still rebuilds the NSView tree during refresh. Graph rendering is
  cached, but full incremental AppKit view updates remain future hardening.

## External Inspection

A separate `gpt-5.4-mini` Codex task was requested against the current working
tree for inspection. Its queued client id is:

`client-new-thread:d7f3570e-19ca-452d-81ab-5f47da61d56c`

That queued task was not readable before completion of this implementation.
The available multi-agent runtime did not expose `gpt-5.4-mini`, so a
read-only fallback inspector (`gpt-5.4`, agent `019f664b-6e7a-7421-a77d-86b7b6c79093`)
was spawned and reported:

- Dashboard duration used wall-clock/raw first-last sample time.
- Backward timestamps updated latest BPM and ring buffer before rejection.
- BLE/settings did not fully use the synchronized state API.
- Icon, warning suppression, and docs/release-state issues remained.

The first three code issues and the warning/docs issues were fixed in the
follow-up pass. The icon remains a Phase F blocker because `iconutil` rejects
the generated iconset in this environment.
