# HRM Live UI Lab

An interactive HTML workspace for iterating on the dashboard and settings without
launching the macOS app or connecting a Bluetooth strap. No npm install, backend,
or macOS dependencies are needed.

From the repository root:

```sh
make prototype
```

Open **http://127.0.0.1:8765**. Use `PROTOTYPE_PORT=8766` to choose another port.
Stop the server with Ctrl+C. Reload the browser after editing the HTML/CSS/JS.

## What you can explore

- Dashboard, menu-bar title and settings, together or separately; zoom and
  light/dark appearance.
- Ten selectable connection/session scenarios, including scanning, denied
  permission, recording, pending exports and export failures.
- Deterministic signal profiles, manual BPM, single-step updates and accelerated
  playback. Graphs use the configured 5/10/30-minute window and four zone colors.
- Start/stop recording, session statistics, zone time, CSV/JSON downloads, cancel
  and retry behavior, recent-session open/reveal/delete, quit and relaunch.
- Simulated discovery and device selection, editable name, maximum heart rate,
  ordered zone boundaries, native browser color pickers and validated hex values.
- Live width, card radius, spacing and surface/accent edits; component outlines;
  exportable design values. Design preferences stay in this browser's local storage.

The preview uses synthetic data. It does not read the app's config, session files
or BLE devices. Browser downloads replace native save panels/Finder. Exported JSON
is marked `prototype: true` and is a preview schema, not the native export contract.
Web controls and text metrics approximate AppKit rather than reproducing it exactly.

## Editing

| File | Purpose |
| --- | --- |
| `index.html` | Design workspace, artboards and dialogs |
| `styles.css` | Lab styling and app components |
| `app.js` | Rendering, controls, simulation playback and downloads |
| `model.js` | Pure simulation, session lifecycle, zones and validation |
| `tokens.json` | Native semantic tokens, exported by `scripts/export_ui_tokens.py` |

`make prototype` regenerates `tokens.json` by reading literal constants from the
native source without importing AppKit. Use the **Restore native tokens** button
to clear local design overrides after changing native tokens. Canvas width starts
at the native 344 px; settings starts at 440 px. The preview also explores the
compact device card and recent-session interactions on the preserved
`prep/public-release-readiness` branch. It is a design workspace, not proof that
every preview interaction has shipped in the native app.

**Export design** downloads the current design values, app settings and native
token baseline. It does not write Python source. Apply approved changes to the
native token/view modules and verify them in AppKit before release.

## Verification

```sh
make prototype-check   # Node.js 18+; no third-party packages
make check             # Native Python quality gate
```

Model tests cover zone boundaries, validation, deterministic signals, time-gap
clamping, disconnects, recording resets and export retries. Browser smoke checks
should also cover scenario selection, invalid settings, scan/cancel/connect,
record/export/cancel/retry, color and layout edits, keyboard controls and mobile
layouts. Simulation does not replace real hardware or native accessibility tests.
