# Release Checklist

## Supported Environment

- macOS 12 or later.
- Python 3.11 or later for development/runtime.
- CI quality matrix: Python 3.11 and 3.12.

## Local Development Build

```bash
make install
make check
make package
```

`make package` creates `dist/HRM Live.app` and applies ad-hoc signing with
Bluetooth entitlements. This build is for local development only.

## Direct Distribution Requirements

- Developer ID Application certificate.
- Notarization credentials stored only in CI secrets or local keychain.
- Signed ZIP or DMG artifact.
- Successful `codesign --verify --deep --strict`.
- Successful `spctl --assess --type execute --verbose`.
- Successful notarization and stapling checks.
- SHA-256 checksum.
- GitHub release authorization from the repository owner.

## Release evidence record

Complete this record for the exact commit and artifact proposed for release.
A blank, failed, or "not applicable" entry requires an explicit documented
owner decision; it is not a pass. Do not reuse evidence from a different
commit or a differently signed artifact.

| Field | Record |
| --- | --- |
| Release version / Git commit | |
| Tester and date (with timezone) | |
| macOS version and hardware | |
| Python version / py2app version | |
| Strap model and firmware, if known | |
| Artifact filename and SHA-256 | |
| GitHub Actions run URL and commit SHA | |
| Developer ID signing identity (name only; never certificate material) | |
| Notarization submission ID and accepted result URL/record | |
| Gatekeeper assessment output | |
| Final owner approval | |

### Local, reproducible checks

Record the exact output or an attached CI log for each command. The package
target uses an ad-hoc signature during development; a release artifact must be
rebuilt and signed through the authorized Developer ID process after this gate.

| Check | Required result | Result / evidence |
| --- | --- | --- |
| `make install` | Dependencies install without unpinned local edits | |
| `make check` | Ruff, mypy, 115+ tests, coverage threshold, compileall pass | |
| `make package` | Bundle builds, contains `HRMLive.icns`, verifies internal signature and Bluetooth metadata | |
| `codesign --verify --deep --strict` on final artifact | Passes after Developer ID signing | |
| `spctl --assess --type execute --verbose` on final artifact | Accepted after notarization/stapling | |

### Manual AppKit, export, and hardware acceptance

Run every row against the same release candidate. Include a short observation
and any diagnostic path in the evidence column; never store BLE addresses,
session/health data, credentials, or notarization secrets in this repository.

| Scenario | Required result | Pass / fail and evidence |
| --- | --- | --- |
| First launch, no saved device | App is menu-bar-only and remains stable while disconnected | |
| Status-item normal left-click / click-away | Dashboard opens/closes directly; no rumps menu replaces normal click | |
| Dashboard footer controls | Settings opens; exactly one visible Quit route invokes guarded shutdown | |
| BLE scan, select, connect | Standard HRM is listed, selection connects, and live BPM updates | |
| Strap off/on | State changes correctly and reconnection works without app restart | |
| Session start/stop | Stats and clamped zone durations match recorded sample behavior | |
| Save-panel cancel | No CSV is written; `Save Last Session…` remains available | |
| Export write failure then retry | Useful error and retry are shown; retry saves exactly once | |
| Successful CSV export | User-selected path contains `timestamp,bpm,zone` and opens in a spreadsheet | |
| Device setting change | Saved device change triggers the documented reconnect behavior | |
| Quit in every connection state | No crash/hang and no `ble-asyncio` thread remains | |
| Relaunch | Settings persist and no stale recording/export state returns | |

### GitHub public-repository activation

These controls are configured after the owner creates the repository; they are
not made true merely by committing files under `.github/`.

| Control | Required result | Result / evidence |
| --- | --- | --- |
| Public repository metadata | Description, topics, license, homepage, and support links are accurate | |
| Default branch protection | Pull requests required; direct pushes restricted; required checks enabled | |
| Required checks | Python quality matrix and macOS bundle job pass on the release commit | |
| Security features | Dependabot alerts/updates, secret scanning, and private vulnerability reporting enabled | |
| Community files | CONTRIBUTING, SECURITY, Code of Conduct, Support, issue forms, and PR template render on GitHub | |
| Release page | Artifact, checksum, release notes, and compatibility/security limitations are correct | |

## Manual Hardware Test

Record macOS version, Python version, app version, strap model, and strap
firmware if available.

- Scan for strap.
- Select and connect.
- Confirm live BPM updates.
- Power strap off/on and confirm reconnect.
- Left-click status item opens dashboard directly.
- Start session, stop, cancel save, retry save, and open CSV.
- Change settings and confirm reconnect when the device changes.
- Quit while disconnected, scanning, connecting, connected, reconnecting, and
  recording; confirm no `ble-asyncio` thread remains.
- Relaunch app.

## Known Limitations

- No HealthKit, Apple Watch, cloud sync, session browser, or auto-update.
- No medical accuracy claims.
- Public release is blocked until signing/notarization credentials and owner
  authorization are available.
