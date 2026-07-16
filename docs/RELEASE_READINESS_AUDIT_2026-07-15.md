# Release-readiness audit — 2026-07-15

**Audited commit:** `2b49934` (`codex/audit-hardening-fixes`)

**Audit scope:** independently verify the coding-agent handoff, identify
remaining product/release/open-source repository work, and define the next
implementation sequence. No remote action, GitHub configuration change,
signing, notarization, or release publication was performed.

## Verdict

**Do not release or publish the current bundle.** The local code-quality gate
passes, and the `src/hrm_live` migration plus most of the session-export work
are real. The P0 code defects originally found in this audit have now been
corrected locally and covered by focused automated tests, but their AppKit
behavior has not yet been proven in an interactive macOS session.

The project is therefore at **pre-release candidate**, not releasable-product
or public-release status.

## Evidence independently reproduced

| Claim | Result | Evidence |
| --- | --- | --- |
| Package migration exists | Verified | Runtime modules are only under `src/hrm_live`; root runtime modules were removed. |
| Local quality gate passes | Verified | `make check`: Ruff format/lint, mypy, 121 pytest tests, coverage, and compileall all passed. |
| Coverage requirement passes | Verified, but weak | Current run: **58.13%** against a **54%** threshold. Core UI files remain lightly covered (`menubar` 30%, `popover` 40%, `settings` 39%). |
| Explicit CSV writer exists | Verified | `finalize_session`, `export_session_csv`, sibling-temp-file replacement, captured zones, and timestamp-gap clamping are present. |
| Bundle builds and is internally signed | Verified only for development | `make verify-bundle` passed. `codesign -dv` reports `Signature=adhoc`, no TeamIdentifier. |
| Bundle is a trusted distributable app | Not verified / false | `spctl --assess --type execute --verbose` fails with `internal error in Code Signing subsystem`; ad-hoc signing is not a public-release signature. |
| App icon is bundled | Verified for development | Reproducible `scripts/build_icon.py` creates `assets/HRMLive.icns`; the built bundle contains it and `CFBundleIconFile = HRMLive.icns`. |
| CI is green | Unverified | Workflow exists but has not run on GitHub because no push was requested. |
| Manual UI and real-HRM behavior | Unverified | No recorded interactive launch, menu-bar, save-panel, or hardware test evidence. |

## P0 — code fixed locally; manual proof still required

### P0.1 Dashboard-first click is currently a no-op

**Original finding.** `HRMBarApp.__init__()` called `_install_status_button_action()`.
At that point, `rumps.App.run()` has not yet created `self._nsapp` or called
`initializeStatusBar()`. `_status_item_button()` therefore returns `None` and
the method installs nothing.

The installed rumps lifecycle confirms the order:

```text
App.__init__                 # no self._nsapp/status item
App.run
  self._nsapp = NSApp.alloc().init()
  self._nsapp.initializeStatusBar()
  events.before_start.emit()
```

Additionally, `initializeStatusBar()` sets the status item menu. A status item
with a menu uses the menu as the click behavior; merely setting a button action
is not a dependable dashboard-first implementation.

**Impact.** A normal status-item click will still open the rumps menu rather
than reliably toggling the dashboard. This misses a named README feature.

**Required fix.**

1. Call `super().__init__(..., quit_button=None)` so rumps does not append its
   own default Quit item.
2. Register a bound `_configure_status_item` callback with
   `rumps.events.before_start`; it runs after `initializeStatusBar()` has
   created the native status item.
3. In that callback, retrieve the native button, set its target/action to the
   long-lived app object, and clear the status item's rumps menu for normal
   left-click handling. The dashboard footer already supplies Settings and
   Quit, so a context-menu fallback is optional. If a fallback is kept, add a
   deliberate right-click event handler instead of attaching it as the normal
   status-item menu.
4. Ensure the callback is registered once and safely unregistered/ignored at
   teardown in tests. Do not depend on private rumps fields without a concise
   compatibility comment and a focused test seam.

**Required proof.**

- Unit test with a fake post-initialization status item: menu is cleared and
  target/action are installed only after the lifecycle callback.
- Unit test that construction alone does not claim the action was installed.
- Interactive macOS test: normal left-click opens and closes the dashboard;
  click-away closes it; Settings and Quit work from the footer.

**Local resolution.** The app now registers `_configure_status_item()` with
`rumps.events.before_start`, clears the rumps status menu after the native
status item is initialized, and then installs a retained `NSObject` bridge as
the native button target/action.
`test_status_item_is_configured_only_after_rumps_creates_it` verifies the
post-initialization configuration with fakes. The interactive proof remains
mandatory because fakes cannot prove the real AppKit click route.

### P0.2 Duplicate Quit remains in the rumps menu

**Original finding.** The app passed the default `quit_button="Quit"` to `rumps.App`
and also adds `rumps.MenuItem("Quit", callback=self._quit)` to `self.menu`.
rumps' `initializeStatusBar()` unconditionally adds its default quit item to
the menu. The source is explicit:

```python
quit_button = self._app['_quit_button']
if quit_button is not None:
    quit_button.set_callback(quit_application)
    mainmenu.add(quit_button)
```

**Impact.** The current secondary menu has duplicate Quit controls. The
default one bypasses the app's guarded BLE shutdown route, so it is not merely
a cosmetic duplicate.

**Required fix and proof.** Fix with P0.1's `quit_button=None`; retain at most
one explicitly routed Quit action where a fallback menu is intentionally
provided. Add a test using rumps-compatible fakes and complete the interactive
check in every listed connection state.

**Local resolution.** The app now passes `quit_button=None`, does not install
a normal rumps menu, and retains footer Quit as the sole visible exit route.
The guarded shutdown coordinator remains the only application quit callback.

### P0.3 Failed CSV export hides its error and successful export stays pending

**Original finding.** In `HRMPopover._build_view()`, the retry-button condition matched
whenever `pending_export` exists and `last_csv_path is None`. A failed write
sets `last_csv_error` but leaves `pending_export`, so the later `elif
s.last_csv_error` is unreachable. The user sees a retry button without the
promised useful error message.

`AppState.mark_export_success()` also does not clear `_pending_export`, despite
`ExportSnapshot` being documented as retained only until saved or superseded.
The invisible retry button is masked by `last_csv_path`, but programmatic
re-finalization/retry can still see the already-saved payload.

**Required fix.**

- Render the error and the retry control together after a failed save. Make
  the error concise, path-safe, and accessible.
- On successful export, atomically record the path and clear the pending
  export. Preserve only the display statistics/session rows needed by the
  dashboard; do not keep a retryable export snapshot.
- Add tests for: UI state after an injected write failure (error + retry),
  retry success clearing pending data, and no duplicate export after success.

**Local resolution.** `_export_feedback()` now renders a failure message and
retry control together. `mark_export_success()` clears the pending export.
Save-panel failures are now caught before they can escape a native AppKit
callback; file-system failures are logged locally but mapped to concise,
path-safe dashboard feedback. Focused tests verify the error/retry feedback,
successful-save state cleanup, save-panel containment, and path-safe write
failure feedback.

## P1 — required for a releasable product

### P1.1 Real app and hardware acceptance

Automated tests cannot prove AppKit/rumps event handling, `NSSavePanel`,
Bluetooth permissions, or CoreBluetooth behavior. Run and record the complete
manual checklist in `docs/RELEASE_CHECKLIST.md` on the release candidate:

- clean local launch with no saved device;
- dashboard click/click-away/footer Settings/footer Quit;
- scan/select/connect and live BPM with a real standard HR strap;
- strap power-off/on reconnect;
- session start/stop, cancel save, retry save, successful Desktop save, and
  spreadsheet inspection of `timestamp,bpm,zone`;
- change device and confirm reconnect;
- quit while disconnected, scanning, connecting, connected, reconnecting,
  recording, and after a pending export; verify no `ble-asyncio` thread;
- relaunch and verify saved settings.

Record macOS, app version, Python version, strap model, firmware (if visible),
date, tester, and result. A failed manual case is a release blocker until
fixed and re-tested.

### P1.2 Valid project icon — resolved locally

The original `iconutil` conversion from `assets/HRMLive.iconset` was rejected
as `Invalid Iconset`, so the initial development bundle used the default
Python app icon. This is resolved locally without relying on that conversion:
`scripts/build_icon.py` uses Pillow to generate the valid, project-owned
`assets/HRMLive.icns` from the existing 1024px source artwork. The build extra
declares Pillow, py2app consumes that `.icns`, and `make verify-bundle` asserts
that `CFBundleIconFile` is `HRMLive.icns`.

**Verification recorded.** `file assets/HRMLive.icns` and the copy in the
built bundle report a macOS icon with an ICNS table of contents. `make build &&
make verify-bundle` passed with a valid ad-hoc code signature and sealed
resources. This resolves the default-icon defect; it does not make the
ad-hoc bundle trusted for public distribution (P1.3 still applies).

### P1.3 Trusted distribution artifact

Ad-hoc signing proves only that the bundle's internal signature structure is
consistent. Before public release, obtain owner authorization plus a Developer
ID Application certificate and notarization credentials, then:

1. build from a clean tagged commit;
2. sign with Developer ID (not `-`), validate all nested code, and create a
   ZIP or DMG;
3. notarize the exact artifact, wait for an accepted result, staple it, and
   rerun Gatekeeper assessment;
4. publish the SHA-256 checksum and signed artifact only after the above passes.

The current Gatekeeper failure is expected for an ad-hoc artifact but remains
hard evidence that it is not release-ready.

### P1.4 CI evidence

The workflow is a reasonable start: Ubuntu quality on Python 3.11/3.12 and a
macOS 14 bundle smoke job. Once you create/push the GitHub repository, require
both checks on the default branch and record the green run URL against the
release commit. Do not present a workflow file as evidence of a successful CI
run.

## P2 — public open-source repository readiness

These do not replace P0/P1 product gates, but should be completed before
announcing a public repository.

| Missing item | Why it matters | Required next step |
| --- | --- | --- |
| `SECURITY.md` | Gives researchers a private, responsible reporting route | State supported versions, response expectation, and a contact method you control; do not expose credentials. |
| `CONTRIBUTING.md` | Makes local setup, checks, style, issue expectations, and commit/PR process clear | Include `make install`, `make check`, macOS/BLE constraints, and no-real-hardware test policy. |
| `CODE_OF_CONDUCT.md` | Defines community behavior/enforcement | Adopt a maintained code of conduct and provide a project contact. |
| Issue and PR templates | Produces reproducible BLE bug reports and reviewable changes | Add bug/feature/config templates plus a PR checklist requiring tests/docs. |
| Dependabot configuration | Dependencies include native/macOS-sensitive packages | Add a weekly GitHub Actions/Python dependency update configuration; review updates in CI. |
| Repository settings record | These cannot be committed as code | Set description, topics, homepage, default branch, branch protection, required CI checks, Discussions/Issues choice, and security alerts after repository creation. Document the choices in `docs/`. |
| Support/compatibility policy | Users need an honest expectation | In README or `SUPPORT.md`, list supported macOS/Python versions, tested straps, excluded features, and that it is not medical software. |

**Local resolution.** `CONTRIBUTING.md`, `SECURITY.md`,
`CODE_OF_CONDUCT.md`, `SUPPORT.md`, bug/feature issue forms, a pull-request
template, and Dependabot configuration have been added locally. They become
active only after you create and configure the GitHub repository. Repository
settings, private vulnerability reporting, security alerts, branch protection,
and hosted CI remain owner-managed external work.

## P2 — documentation and quality-debt cleanup

1. Preserve the coding-agent implementation record in `docs/` as historical
   evidence only. The independent audit is the single current release-status
   source; do not let historical test counts or resolved defects be read as
   current evidence.
2. Keep `docs/RELEASE_IMPLEMENTATION_HANDOFF.md` clearly marked as a
   historical implementation contract and point readers to this audit.
3. Raise test coverage after P0 fixes, focusing on `menubar`, `popover`, and
   `settings`. The current 54% floor passes but is insufficient evidence for
   UI-heavy release behavior. Set a new threshold only after adding meaningful
   interaction/state tests; do not inflate it with irrelevant tests.
4. Preserve the implemented graph cache, but assess the remaining full
   `NSView` rebuild during a sustained real stream. Fix visible flicker or
   input loss before release.
5. Treat syntactically valid but semantically invalid configuration as a
   recovery case, not as trusted startup input. This is now resolved locally:
   `load_config()` validates the merged configuration, quarantines invalid JSON
   objects as `.corrupt`, and starts from defaults. Coverage includes invalid
   root, maximum-HR, zones, and color structures.

## Ordered implementation plan

1. **P0 UI lifecycle patch:** implement and test the post-status-bar callback,
   no-default-Quit configuration, and no-normal-menu behavior. Manually test
   normal click and one guarded quit path.
2. **P0 export-state patch:** fix error/retry layout and pending-export cleanup;
   add the focused tests described above.
3. **Run `make check`** and update this audit plus the handoff ledger with the
   new commit, exact command output, and remaining manual evidence.
4. **P1 icon patch (complete locally):** the reproducible `.icns` is wired
   into py2app and bundle metadata is asserted. Keep this check in every
   release-candidate build.
5. **P1 manual candidate test:** complete and record every manual/hardware
   case. Resolve failures rather than marking them “deferred.”
6. **P2 GitHub activation:** enable the committed community templates,
   Dependabot, private vulnerability reporting, security alerts, and required
   branch checks after the repository exists.
7. **User-owned GitHub setup:** create the repository, push when you decide,
   enable branch protection/security features, and obtain one green CI run.
   Do not publish a release yet.
8. **User-owned distribution setup:** obtain Developer ID/notarization access;
   make a signed/notarized candidate, pass Gatekeeper, checksum it, and only
   then create a public GitHub release.

## Post-audit local verification — 2026-07-15

- P0 implementation commit: `9fbd82c` (`fix(release): harden dashboard and
  export flow`).
- P0 code changes: status-item lifecycle, retained `NSObject` action bridge,
  default Quit removal, export error feedback, and successful-export cleanup.
- Focused tests: 32 passed (`tests/test_imports.py`, `tests/test_session.py`).
- Full local quality gate: 121 passed; Ruff, mypy, coverage (**58.13%**), and
  compileall passed.
- Local OSS repository artifacts: contribution, security, conduct, support,
  issue/PR templates, and Dependabot configuration were added.
- Local package rebuild: `make build && make verify-bundle` passed with the
  generated `HRMLive.icns`, a valid ad-hoc signature, sealed resources, and
  expected Info.plist metadata. It remains an untrusted development artifact.
- Remaining blockers are P1/P2 items in this document, especially real AppKit
  and hardware verification, green hosted CI, and Developer ID/notarization.

## Completion evidence required to change the verdict

The verdict may change to “release candidate” only when P0 is fixed, local
quality passes again, icon packaging is valid, and the manual hardware/UI
record is complete. It may change to “publicly releasable” only when that
candidate also has green CI, Developer ID signing, notarization/stapling,
Gatekeeper acceptance, checksum, and owner authorization for publication.
