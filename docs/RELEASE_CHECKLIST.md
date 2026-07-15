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
