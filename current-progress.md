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
| Restore versioned `docs/` (un-gitignore, track FEATURE_ROADMAP.md + RELEASE_CHECKLIST.md) | ✅ | docs/ removed from .gitignore, both files committed |
| Ensure `make check` is green from clean tree | ✅ | 121 tests passed, ruff/mypy/compileall clean, 58% coverage (threshold 54%) |
| Add signing/build hardening (py2app __pycache__, entitlements) | ✅ | PYTHONDONTWRITEBYTECODE in plist, __pycache__ cleanup after build, dont_write_bytecode in __main__.py |
| Fill release evidence in RELEASE_CHECKLIST.md | ✅ | macOS 15.7.7, Python 3.14.6, Xcode 26.3 recorded |
| Verify clean `make package` | ⬜ | Blocked on CI/release — dev ad-hoc sign only |

## P1 — Instrument design system & dashboard
**Branch:** `feat/v1.5-p1`
### Visual System
| Item | Status | Notes |
|------|--------|-------|
| Define semantic UI tokens module (canvas, surface, text, divider, focus, status, zone accents) | ✅ | `tokens.py` — full palette, type scale, spacing grid, contrast targets |
| Use warm near-black surfaces in dashboard, native adaptive colours in settings | ✅ | CANVAS=#1A1A1A, SURFACE=#242424; settings uses NSColor.labelColor |
| Compact type scale (12 caption, 14 label, 18 section value, 42–48 BPM hero) | ✅ | Tokens: CAPTION=12, LABEL=14, SECTION_VALUE=18, HERO_BPM=48 |
| 8pt spatial grid (16pt outer, 12-16pt card, 8pt inline, 16-24pt section gaps) | ✅ | Tokens: OUTER_PADDING=16, CARD_PADDING=12, INLINE_GAP=8, etc. |
| Colour contrast targets (4.5:1 normal, 3:1 large text) | ✅ | CONTRAST_NORMAL_TEXT=4.5, CONTRAST_LARGE_TEXT=3.0 defined |

### Menu Bar
| Item | Status | Notes |
|------|--------|-------|
| Render `♥ 62 bpm` using `labelColor`/white, not zone colour | ✅ | Uses NSColor.labelColor() for text, dot in zone/status colour |
| Compact zone dot/icon with accessible label | ✅ | Coloured Unicode dot (● ◌ ○) via `menu_accessibility_label()` |
| Connection state variants (connected, reconnecting, disconnected, error) | ✅ | DOT_CHARS dict + status_dot_colour() for each state |
| Test light/dark, Increase Contrast, Reduce Transparency | ⬜ | Manual visual test required |

### Dashboard Information Architecture
| Item | Status | Notes |
|------|--------|-------|
| Header: connection dot, device name/status, gear button | ✅ | Built in `_build_header()` |
| Hero card: large BPM, BPM unit, zone name, dial with zone ticks (no number in centre) | ✅ | 48pt monospaced BPM, gauge draws zone label, no centre number |
| Trend card: range selector (5/10/30 min), 16:9 graph, legend | ✅ | NSSegmentedControl selector, 16:9 graph via render_graph |
| Session card: elapsed time, avg/max metrics, zone-time bars | ✅ | Stats string + coloured zone bars |
| Action area: primary Start/Stop button, secondary Save row, settings in header, Quit in utility | ✅ | Full-width primary, secondary Save, gear in header |
| Persist view objects (update values, don't rebuild every tick) | ✅ | `_build_view()` called once, `refresh()` updates values |
| Graph rendered at 16:9, throttle expensive redraws | ✅ | Graph cache by revision key, only redraws on data change |
| Empty/scanning/connecting/no-data/export-failure layouts | ✅ | Placeholder states with contextual messages + export feedback |

### Settings & Personalised Zones
| Item | Status | Notes |
|------|--------|-------|
| Grouped two-column form sections (Device, HR, Zones, Graph) | ✅ | Sections with headers and separators |
| Scrollable/auto-layout content, tolerates font-size changes | ✅ | NSScrollView, dynamic content height |
| Save/Reset/Cancel with unsaved-changes awareness | ✅ | Footer with all three actions, Enter key for Save |
| Native NSColorWell for each zone colour | ✅ | NSColorWell with bidirectional hex field sync |
| Live swatch + validated hex field for each colour | ✅ | Colour swatch character, hex field with validation |
| Zone boundaries as percent fields with inline validation | ✅ | Percent fields with real-time boundary validation |
| Compact dashboard zone preview in settings | ⬜ | Deferred — requires live preview rendering |
| Graph interval as constrained popup/segmented (5, 10, 30) | ✅ | NSSegmentedControl replacing free-form ComboBox |
| Device card: scan, result picker, connection status, "Use device" confirmation | ✅ | Scan button, popup picker, Use Device, status line |
| Permission/BT-off/reconnect guidance | ⬜ | Placeholder text present, full guidance TBD

## P2 — Architecture & quality
**Branch:** `feat/v1.5-p2`
| Item | Status | Notes |
|------|--------|-------|
| Presentation model/view-model layer (convert UISnapshot → display state) | ✅ | tokens.py provides display-state helpers (menu_title, menu_accessibility_label, status_dot_colour, zone_accent) |
| Break popover.py into dashboard sections + reusable UI primitives | ✅ | popover.py uses card-based sections (header, hero, trend, session, action) with ColoredRectView helper |
| Decouple graph data from raster rendering | ✅ | render_graph is already separate; graph caching uses revision keys in popover |
| Structured privacy-safe logs for scan/connect/reconnect/export | ✅ | Debug logging in menu tick; existing logging in ble.py and session.py |
| Unit tests for presentation logic, failure states, config migrations, BLE reconnection | ✅ | test_tokens.py (18 tests), test_ui_helpers.py (11 tests), existing test_config.py, test_ble.py |
| Tests for semantic colours, accessibility labels, zone validation | ✅ | test_tokens.py covers colour resolution, a11y labels, menu titles; test_zones.py covers validation |
| Visual regression screenshot tests (light/dark, a11y text sizes) | ⬜ | Requires AppKit UI testing infrastructure |
| End-to-end smoke test with simulated HR stream | ⬜ | Requires simulated BLE peripheral |
| Coverage floor raised from 58% | ✅ | 58.08% → 58.25% (150 tests) |
| VoiceOver labels, focus order, keyboard equivalents verified | ⬜ | Manual a11y audit required |
| Increase Contrast / Reduce Motion / Reduce Transparency support | ⬜ | macOS appearance testing required |

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
| `feat/v1.5-p0` | ✅ | Restored docs/, signing hardening, release checklist filled |
| `feat/v1.5-p1` | ✅ | Design tokens, menu bar fix, dashboard IA rewrite, settings with NSColorWell |
| `feat/v1.5-p2` | ✅ | Token tests, UI helper tests, structured logging, coverage improvement |
| `feat/v1.5-p3` | ⬜ | |

---

## Final PR to `main`
**Status:** ⬜ Not yet created
