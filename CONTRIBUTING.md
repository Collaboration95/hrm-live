# Contributing to HRM Live

Thanks for contributing. HRM Live is a macOS menu-bar app that reads a
standard BLE heart-rate monitor; its native AppKit and Bluetooth lifecycle
constraints deserve small, well-tested changes.

## Before opening a pull request

1. Use macOS and Python 3.11 or newer.
2. Create the development environment and install all local checks:

   ```bash
   make venv
   make install
   make check
   ```

3. Keep runtime code in `src/hrm_live/` and tests in `tests/`.
4. Do not require a real BLE device, a real home directory, a modal AppKit
   panel, signing credentials, or network access in automated tests. Use
   dependency injection, fakes, and `tmp_path` instead.
5. Add focused tests for behavior changes and update user/release documents
   when behavior, privacy, compatibility, or release requirements change.

## Change guidelines

- Preserve the main-thread AppKit / background-thread BLE boundary. Read
  shared state through `AppState` snapshots; do not expose live mutable data to
  UI rendering or export I/O.
- Keep normal left-click dashboard-first. Do not add a second visible Quit
  route or bypass `HRMBarApp.shutdown()`.
- Session CSV export must remain user-selected, atomic, and retryable after a
  write failure. Do not reintroduce automatic export to a fixed directory.
- Avoid unrelated reformatting and generated build files. `dist/`, `build/`,
  virtual environments, local config, and exported sessions do not belong in
  commits.
- Use the repository's conventional commit format, for example
  `fix(session): preserve retry feedback`.

## Pull requests

Describe the user-visible change, tests run, macOS/Python version, and any
manual AppKit or hardware evidence. For BLE fixes, say whether a real standard
Heart Rate Measurement device was used and never include device addresses,
session CSV data, certificates, or secrets.
