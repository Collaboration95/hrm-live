# HRM Live v1.5 Sprint — Progress Tracker

## Session Info
- **Started:** 2026-07-16
- **Base branch:** `feature-v1.5-sprint`
- **Target:** Complete all roadmap priorities (P0–P3) per FEATURE_ROADMAP.md

---

## Legend
- ✅ Done / merged to `feature-v1.5-sprint`
- 🔄 In progress
- ⬜ Not started

---

## P0 — Release repeatability & docs
**Branch:** `feat/v1.5-p0`
| Item | Status | Notes |
|------|--------|-------|
| Restore versioned `docs/` (un-gitignore, track FEATURE_ROADMAP.md + RELEASE_CHECKLIST.md) | ⬜ | |
| Ensure `make check` is green from clean tree | ⬜ | |
| Add signing/build hardening (py2app __pycache__, entitlements) | ⬜ | |
| Verify clean `make package` | ⬜ | |

## P1 — Instrument design system & dashboard
**Branch:** `feat/v1.5-p1`
### Visual System
| Item | Status | Notes |
|------|--------|-------|
| Define semantic UI tokens module (canvas, surface, text, divider, focus, status, zone accents) | ⬜ | |
| Use warm near-black surfaces in dashboard, native adaptive colours in settings | ⬜ | |
| Compact type scale (12 caption, 14 label, 18 section value, 42–48 BPM hero) | ⬜ | |
| 8pt spatial grid (16pt outer, 12-16pt card, 8pt inline, 16-24pt section gaps) | ⬜ | |
| Colour contrast targets (4.5:1 normal, 3:1 large text) | ⬜ | |

### Menu Bar
| Item | Status | Notes |
|------|--------|-------|
| Render `♥ 62 bpm` using `labelColor`/white, not zone colour | ⬜ | |
| Compact zone dot/icon with accessible label | ⬜ | |
| Connection state variants (connected, reconnecting, disconnected, error) | ⬜ | |
| Test light/dark, Increase Contrast, Reduce Transparency | ⬜ | |

### Dashboard Information Architecture
| Item | Status | Notes |
|------|--------|-------|
| Header: connection dot, device name/status, gear button | ⬜ | |
| Hero card: large BPM, BPM unit, zone name, dial with zone ticks (no number in centre) | ⬜ | |
| Trend card: range selector (5/10/30 min), 16:9 graph, legend | ⬜ | |
| Session card: elapsed time, avg/max metrics, zone-time bars | ⬜ | |
| Action area: primary Start/Stop button, secondary Save row, settings in header, Quit in utility | ⬜ | |
| Persist view objects (update values, don't rebuild every tick) | ⬜ | |
| Graph rendered at 16:9, throttle expensive redraws | ⬜ | |
| Empty/scanning/connecting/no-data/export-failure layouts | ⬜ | |

### Settings & Personalised Zones
| Item | Status | Notes |
|------|--------|-------|
| Grouped two-column form sections (Device, HR, Zones, Graph) | ⬜ | |
| Scrollable/auto-layout content, tolerates font-size changes | ⬜ | |
| Save/Reset/Cancel with unsaved-changes awareness | ⬜ | |
| Native NSColorWell for each zone colour | ⬜ | |
| Live swatch + validated hex field for each colour | ⬜ | |
| Zone boundaries as percent fields with inline validation | ⬜ | |
| Compact dashboard zone preview in settings | ⬜ | |
| Graph interval as constrained popup/segmented (5, 10, 30) | ⬜ | |
| Device card: scan, result picker, connection status, "Use device" confirmation | ⬜ | |
| Permission/BT-off/reconnect guidance | ⬜ | |

## P2 — Architecture & quality
**Branch:** `feat/v1.5-p2`
| Item | Status | Notes |
|------|--------|-------|
| Presentation model/view-model layer (convert UISnapshot → display state) | ⬜ | |
| Break popover.py into dashboard sections + reusable UI primitives | ⬜ | |
| Decouple graph data from raster rendering | ⬜ | |
| Structured privacy-safe logs for scan/connect/reconnect/export | ⬜ | |
| Unit tests for presentation logic, failure states, config migrations, BLE reconnection | ⬜ | |
| Tests for semantic colours, accessibility labels, zone validation | ⬜ | |
| Visual regression screenshot tests (light/dark, a11y text sizes) | ⬜ | |
| End-to-end smoke test with simulated HR stream | ⬜ | |
| Coverage floor raised from 58% | ⬜ | |
| VoiceOver labels, focus order, keyboard equivalents verified | ⬜ | |
| Increase Contrast / Reduce Motion / Reduce Transparency support | ⬜ | |

## P3 — Training utility & session value
**Branch:** `feat/v1.5-p3`
| Item | Status | Notes |
|------|--------|-------|
| Configurable zone alerts (enter/leave) with quiet default + mute | ⬜ | |
| Pause/resume session state | ⬜ | |
| Post-session summary (duration, avg, max, time-in-zone) | ⬜ | |
| JSON summary alongside CSV export | ⬜ | |
| Recent-session list with Finder reveal + delete | ⬜ | |
| Stable export schema version | ⬜ | |

---

## Merge History
| Branch | Merged | PR/Notes |
|--------|--------|----------|
| `feat/v1.5-p0` | ⬜ | |
| `feat/v1.5-p1` | ⬜ | |
| `feat/v1.5-p2` | ⬜ | |
| `feat/v1.5-p3` | ⬜ | |

---

## Final PR to `main`
**Status:** ⬜ Not yet created
