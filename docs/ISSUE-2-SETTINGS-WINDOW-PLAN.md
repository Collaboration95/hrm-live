# Issue 2 — Settings button opens a real settings window

## Problem

Clicking `Settings` closes the transient dashboard popover but, in the
reported behavior, does not leave a visible settings window. The callback
selector is present and an existing headless test confirms that the callback
is invoked, so the likely defect is in AppKit window presentation/lifecycle:
the settings view is created as a non-activating panel immediately after a
transient popover closes.

## Baseline evidence

- `HRMPopover.open_settings_` closes the popover and calls `on_settings`.
- `HRMBarApp` wires that callback to `SettingsWindow.show`.
- `SettingsWindow` uses `NSPanel` with
  `NSWindowStyleMaskNonactivatingPanel`, then calls
  `makeKeyAndOrderFront_`/`orderFrontRegardless`.
- `close()` drops the panel object, while the app timer may still inspect
  visibility during the transition.
- Native reproduction and the diagnostic log showed the callback was reached,
  then `_build_panel()` crashed at `NSPopUpButton.initWithFrame_pullsDown_`
  because it received a flat four-value tuple rather than an AppKit `NSRect`.

## Plan

1. Normalize every settings frame passed to PyObjC constructors so panel
   creation completes on macOS.
2. Make the settings panel a normal activatable floating utility window: it
   must be able to become key, stay visible when the menu-bar app loses focus,
   and not be dismissed by the transient popover lifecycle.
3. Make repeated Settings clicks idempotent: reuse and raise an existing
   panel instead of rebuilding it, while retaining the current form values.
4. Preserve the current callback contract and refresh behavior so settings
   remain synchronized with `AppState` and BLE scan status.
5. Add regression tests for frame normalization and presentation
   flags/lifecycle and keep the
   existing callback-order test.
6. Verify manually from the actual menu bar: open dashboard, click Settings,
   confirm the panel is visible and interactive, close it, then reopen it.

## Acceptance criteria

- One click closes the popover and visibly opens `HRM Settings`.
- The panel is frontmost, key, interactive, and remains visible after the
  popover has disappeared.
- A second click raises the same panel rather than creating duplicate windows.
- Closing settings does not quit the app or lose the current configuration.
- Existing scan, save, cancel, and validation behavior is unchanged.

## Verification

- Headless tests cover the window style/presentation contract through injected
  fake AppKit objects.
- macOS smoke test covers first open, repeated open, close, and reopen.
- Full regression suite confirms no changes to menu-bar routing or config save
  semantics.
