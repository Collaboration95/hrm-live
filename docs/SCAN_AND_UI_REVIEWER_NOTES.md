# Scan and UI Reviewer Notes

This change set implements the scan-and-settings workflow from
`docs/SCAN_AND_UI_IMPLEMENTATION_PLAN.md` without widening scope.

## Design decisions

- BLE now starts a single persistent asyncio loop at app launch, even when no
  device address is configured.
- Scan and connection work are separate tasks on that one loop.
- Connection replacement uses a generation guard so stale task finalizers do
  not overwrite the new task's state.
- Scan results are published as immutable `DiscoveredDevice` tuples and are
  deduplicated by BLE address.
- Scan selection is preserved by address, not by display text.
- The settings window keeps scan logic injectable; it does not import or own
  Bleak.
- Saving settings remains the explicit commit point. The menu-bar controller
  decides whether the new config should connect, disconnect, or no-op.
- `device_name` is persisted as an optional string and remains empty for
  manually typed addresses unless the address matches a scanned device.
- Dark popover buttons use explicit attributed titles with white foreground
  text and accessibility labels.

## Notes for reviewers

- `ble.py` still exposes `ble_loop()` for legacy test compatibility, but the
  app uses `BLEManager`.
- Scan status and connection status are serialized through `AppState`; the UI
  only reads those snapshots on the main thread.
- The settings panel refreshes only when visible and when scan or connection
  state changes, which keeps the one-second timer cheap.
- Empty successful scans are treated as a normal state, not an error.

## Verification performed

- `pytest -q`
- `.venv/bin/python -m compileall app.py state.py ble.py config.py zones.py
  session.py ui tests setup.py`

## Pending checks

- Native visual smoke testing of the popover/settings windows.
- Packaged app build and launch validation.
- Bluetooth hardware validation with a real strap.
