# spec.md — HRM Menu Bar App

## Overview
A macOS menu bar app that connects to a Bluetooth HRM strap (Decathlon, standard BLE
GATT Heart Rate profile), displays live BPM in the menu bar, and opens a popover
with a zone gauge, HR graph, and session stats on click.

---

## Scope
- **In scope**: Decathlon HRM strap via BLE, macOS menu bar, popover, settings window,
  session CSV export
- **Out of scope (v1)**: Apple Watch / HealthKit integration, multi-device support,
  historical session browser, cloud sync

---

## Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.11+ | Existing PoC is in Python + Bleak |
| Menu bar | `rumps` | Clean Python abstraction over NSStatusBar |
| BLE | `bleak` | Async, cross-platform, proven with HR straps |
| Config | `json` in `~/.config/hrm/config.json` | Simple, human-editable |
| Session data | CSV in `~/.local/share/hrm/sessions/` | Lightweight, portable |
| Packaging | `py2app` (later) | Drag-to-Applications `.app` bundle |
| Appearance | Dark mode only | macOS system dark mode |

---

## Architecture

Two-thread model. `rumps` owns the main thread with the AppKit run loop.
Bleak requires an asyncio event loop, which runs in a dedicated background thread.
They communicate via a shared plain Python object (no queue needed — one writer,
one reader, reads are non-critical).

```
Main thread (rumps)           Background thread (asyncio)
──────────────────            ──────────────────────────
rumps.App.run()               asyncio.new_event_loop()
  │                             │
  ├─ rumps.Timer (1s)           ├─ BleakClient(DEVICE_ADDRESS)
  │    └─ reads shared_state    │    └─ auto-reconnect loop
  │                             │
  ├─ menu bar title update      ├─ start_notify(HR_UUID, callback)
  ├─ popover render             │    └─ parses GATT 0x2A37
  └─ settings window            └─ writes → shared_state
```

### Shared state object
```python
@dataclass
class AppState:
    latest_bpm: int | None = None
    connected: bool = False
    ring_buffer: deque = field(default_factory=lambda: deque(maxlen=600))
    # 600 samples @ 1Hz = 10 min window
    session_active: bool = False
    session_start: datetime | None = None
    session_data: list[tuple[datetime, int]] = field(default_factory=list)
    session_max: int = 0
    session_min: int = 999
    session_sum: int = 0
    session_count: int = 0
    zone_times: dict[str, int] = field(default_factory=lambda: {
        "Z1": 0, "Z2": 0, "Z3": 0, "Z4": 0
    })
```

---

## BLE / Device

- **Profile**: Standard BLE Heart Rate Measurement (GATT characteristic `0x2A37`)
- **Device address**: Hardcoded in `config.json` as `device_address` (dev mode)
- **Connection strategy**: `BleakClient` in a `while True` loop — on disconnect,
  wait 3s and retry silently forever
- **Parsing**: Byte 0 = flags. Bit 0 = 0 → BPM is `data[1]` (8-bit).
  Bit 0 = 1 → BPM is `int.from_bytes(data[1:3], "little")` (16-bit)

```python
HEART_RATE_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

async def ble_loop(state: AppState, address: str):
    while True:
        try:
            async with BleakClient(address) as client:
                state.connected = True
                await client.start_notify(HEART_RATE_UUID, 
                    lambda s, d: hr_callback(s, d, state))
                while client.is_connected:
                    await asyncio.sleep(1)
        except Exception:
            state.connected = False
            await asyncio.sleep(3)
```

---

## Menu Bar Item

| State | Display |
|---|---|
| Connected | `❤️ 142 bpm` — heart emoji + BPM + "bpm", colored by zone |
| Disconnected / no data | `⚪ ---` — grey circle + dashes |

Zone color is applied to the **text color** of the title string via NSAttributedString
(accessible via `rumps` title assignment or PyObjC shim).

---

## Zone Model

Default: 4-zone model based on % of max HR. All values user-configurable.

| Zone | Default % of Max HR | Default color |
|---|---|---|
| Z1 — Recovery | < 60% | Grey `#888` |
| Z2 — Aerobic | 60–75% | Green `#4CAF50` |
| Z3 — Threshold | 75–88% | Orange `#FF9800` |
| Z4 — VO2 Max | > 88% | Red `#F44336` |

Max HR default: 190 (configurable in settings).

Zone for current BPM:
```python
def get_zone(bpm: int, max_hr: int, zones: dict) -> str:
    pct = bpm / max_hr
    if pct < zones["z1_max"]: return "Z1"
    elif pct < zones["z2_max"]: return "Z2"
    elif pct < zones["z3_max"]: return "Z3"
    else: return "Z4"
```

---

## Popover

Opens on click of the menu bar item. Fixed width ~280px. Sections top to bottom:

### 1. Hero section
- Large BPM number (e.g. `142`) — font size ~36px
- Zone label underneath (e.g. `Z3 — Threshold`)
- Circular donut gauge showing current zone visually (SVG or `drawRect:` in PyObjC)
  - 4 segments colored by zone; current zone segment highlighted/filled

### 2. HR Graph
- Line graph of HR over the last N minutes (default 10, configurable)
- X-axis: time (rolling window), Y-axis: BPM
- Horizontal colored bands showing zone boundaries
- Rendered with matplotlib → PNG → displayed as NSImage, or via CoreGraphics

### 3. Session Stats (visible only when session is active or just ended)
```
Session: 00:34:12
Avg: 138 bpm   Max: 167 bpm   Min: 112 bpm
─────────────────────────────────────────
Z1 ████░░░░░░░░  04:12
Z2 ██████████░░  18:30
Z3 ████████░░░░  09:20
Z4 ██░░░░░░░░░░  02:10
```

### 4. Controls
- `[▶ Start Session]` / `[■ Stop Session]` button — toggles session state
- `[⚙ Settings]` button — opens Settings window

---

## Settings Window

Separate `NSPanel` (non-activating, stays on top). Opened from popover.

### Sections

**Device**
- Device address (text field, editable)
- `[Scan for devices]` button (v2 — not in v1)

**Heart Rate Zones**
- Max HR (number input, default 190)
- Zone boundaries as % of max HR (4 sliders or number inputs):
  - Z1/Z2 boundary (default 60%)
  - Z2/Z3 boundary (default 75%)
  - Z3/Z4 boundary (default 88%)
- Zone colors (4 color wells, one per zone)

**Display**
- Graph time window (dropdown: 5 min / 10 min / 30 min)

**Actions**
- `[Save]` — writes to `~/.config/hrm/config.json`
- `[Reset to defaults]`

---

## Session Management

A session is a user-delimited recording period.

**Start**: User taps `[▶ Start Session]` in popover.
- `state.session_active = True`
- `state.session_start = datetime.now()`
- Clears all session accumulators (avg, max, min, zone times)

**During**: Every HR sample while active:
- Appended to `state.session_data` as `(timestamp, bpm)`
- Updates running max/min/sum/count and zone_times

**Stop**: User taps `[■ Stop Session]`.
- `state.session_active = False`
- Writes CSV to `~/.local/share/hrm/sessions/YYYY-MM-DD_HH-MM.csv`
- Stats remain visible in popover until next session starts

**CSV format**:
```
timestamp,bpm,zone
2025-08-10T07:34:12,142,Z3
2025-08-10T07:34:13,141,Z3
...
```

---

## Config File

Location: `~/.config/hrm/config.json`

```json
{
  "device_address": "XX:XX:XX:XX:XX:XX",
  "max_hr": 190,
  "zones": {
    "z1_max": 0.60,
    "z2_max": 0.75,
    "z3_max": 0.88
  },
  "zone_colors": {
    "Z1": "#888888",
    "Z2": "#4CAF50",
    "Z3": "#FF9800",
    "Z4": "#F44336"
  },
  "graph_window_minutes": 10
}
```

---

## File Structure

```
hrm-bar/
├── app.py              # Entry point — starts BLE thread, runs rumps app
├── state.py            # AppState dataclass
├── ble.py              # Bleak connection loop + HR callback
├── ui/
│   ├── menubar.py      # rumps.App subclass + Timer
│   ├── popover.py      # Popover layout and rendering
│   ├── graph.py        # HR graph rendering (matplotlib or CoreGraphics)
│   └── settings.py     # Settings NSPanel
├── zones.py            # Zone logic (get_zone, zone_color)
├── session.py          # Session start/stop/save logic
├── config.py           # Load/save config.json
├── setup.py            # py2app build config (later)
└── spec.md             # This file
```

---

## Key Dependencies

```
rumps>=0.4.0
bleak>=0.21.0
matplotlib>=3.8.0   # for graph rendering
pyobjc-core         # for attributed string (colored title text)
pyobjc-framework-Cocoa
```

---

## Known Constraints & Gotchas

1. **rumps + asyncio**: `rumps.App.run()` blocks the main thread. Bleak must run in
   a `threading.Thread` with its own event loop. Never call Bleak from the main thread.

2. **Colored menu bar text**: `rumps` `.title` only accepts a plain string. To colorize
   the BPM number by zone, use `PyObjC` to set an `NSAttributedString` on the
   `NSStatusItem.button.attributedTitle`. One small shim needed.

3. **Graph rendering**: `matplotlib` with `Agg` backend renders to PNG bytes in memory.
   Those bytes → `NSImage` → displayed in the popover. Keep renders < 100ms.
   Alternative: draw with CoreGraphics directly via PyObjC for better performance.

4. **macOS Bluetooth permission**: First launch will prompt for Bluetooth access.
   App must declare `NSBluetoothAlwaysUsageDescription` in its `Info.plist`.

5. **py2app + Bleak**: Bleak uses `CoreBluetooth` under the hood on macOS.
   Ensure `pyobjc` is bundled and the entitlement `com.apple.security.device.bluetooth`
   is in the `.entitlements` file.

---

## Future Considerations (not v1)

- Apple Watch HR via HealthKit (requires WatchKit companion app — different project)
- Device scanning UI (scan for nearby BLE HR devices, pick from list)
- Launch at login (LSSharedFileList or `launchd` plist)
- Session history browser window
- HR zone alerts / macOS notifications (e.g. "You've been in Z4 for 5 min")
- Export to Garmin Connect / Strava via their APIs