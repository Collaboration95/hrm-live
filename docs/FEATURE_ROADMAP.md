# HRM Live feature roadmap

**Scope:** first feature release after v1 packaging and Apple distribution work.

**Product direction:** HRM Live should feel like a compact fitness instrument:
calm at rest, immediately legible while moving, and deliberate in the use of
colour. The visual character can take inspiration from Teenage Engineering's
compact industrial products—strong hierarchy, precise spacing, tactile controls,
and purposeful accent colours—without copying its product or brand assets.

## Product principles

1. **Read at a glance.** A wearer should identify connection state, current BPM,
   and training zone in less than one second.
2. **One fact, one primary home.** The dashboard must not present the live BPM
   twice with equal prominence.
3. **Colour conveys state, never the only meaning.** Text and symbols remain
   legible in every macOS appearance and accessibility setting.
4. **Controls have a clear hierarchy.** There is one obvious session action;
   secondary and destructive actions never compete with it.
5. **Use native macOS interaction where it is better.** Native colour wells,
   focus rings, menus, keyboard navigation, and Dynamic Type behaviour are more
   valuable than a custom imitation.

## Evidence and current-state assessment

The July 16 screens and the current AppKit implementation identify these
concrete issues.

| Area | Evidence / cause | Product decision |
| --- | --- | --- |
| Menu-bar BPM looks dim | `menubar.py` applies the zone colour to the entire attributed status title. The Z1 default is `#888888`; against a translucent menu bar it has insufficient contrast. | Keep the BPM text system-primary/white. Show zone with a small coloured dot or templated status icon, so colour is a supplementary cue. |
| Dashboard repeats BPM | The top-left hero label and the donut's centre label both render `62` in `popover.py`. | Keep the large hero BPM as the sole numeric reading. The donut becomes a zone/progress dial with ticks and an accessible zone label but no duplicated centre number. |
| Popover is cramped and visually flat | A 280 × 620 fixed canvas combines a 36 pt hero, 110 pt gauge, 260 × 170 scaled graph, statistics, four bars, and four footer actions. The graph source is 450 × 220 and is squeezed into this canvas. | Move to a 336–360 pt dashboard with an 8 pt spacing grid, card sections, and a 16:9 graph. Avoid scaling an image to an unrelated aspect ratio. |
| Footer controls read as one cluster | Controls are placed with independent absolute frames. The first row and Save/Quit row have inconsistent action hierarchy and little visual breathing room. | Use a full-width primary session control, a separate secondary row for export and settings, and a destructive Quit action in a lower utility area or application menu. Minimum 8 pt gaps and 36–40 pt hit targets. |
| Settings alignment is inconsistent | The panel uses a sequence of manually decremented `y` coordinates; labels and values change columns between groups. Raw hex text fields are the only colour affordance. | Rebuild as grouped, two-column form sections with shared label/value columns. Replace colour strings as the main control with native `NSColorWell` controls plus editable hex values. |
| Device selection feels visually disconnected | Scan, status, selected-device menu, and apply action are separated by large blank regions and generic controls. | Treat device connection as one compact card with a scan action, result picker, connection status, and an explicit “Use device” confirmation. |

The codebase is a good functional v1 foundation: BLE ingestion, protected
shared state, zone calculation, explicit CSV export, config validation, and
an ad-hoc signing path already exist. The main gap is that presentation is
constructed as a fresh absolute-positioned view every second. That makes layout
hard to evolve, risks focus/flicker problems, and does not give visual changes
an automated regression harness.

## Release sequence

### 0. v1 completion — now

**Goal:** make the current release candidate repeatable and safe to ship.

- Keep `make check` and `make package` green from a clean tree.
- Finish the existing manual AppKit, Bluetooth hardware, signing, notarization,
  stapling, and checksum steps in `docs/RELEASE_CHECKLIST.md`.
- Restore `docs/` as versioned project documentation; release evidence and this
  roadmap must not be silently hidden by `.gitignore`.
- Record the exact macOS version, Python version, Xcode command-line tools, and
  test strap used for the release candidate.

**Exit criteria:** a fresh clean build passes bundle verification, opens on a
test Mac, connects/reconnects to a real strap, exports a readable CSV, and has
the required Apple distribution evidence.

### 1. Instrument design system and dashboard — first feature milestone

**Goal:** ship the visual quality reset before adding broad feature surface.

#### Visual system

- Define semantic tokens in one UI module: canvas, surface, primary/secondary
  text, divider, focus, success, warning, danger, and the four zone accents.
- Use warm near-black surfaces in the dashboard and native adaptive colours in
  settings. Do not hard-code white/grey text where AppKit semantic colours are
  appropriate.
- Use a compact type scale: 12 caption, 14 label, 18 section value, 42–48 BPM
  hero; prefer tabular/monospaced digits for live values if supported by the
  selected system font.
- Adopt an 8 pt spatial grid: 16 pt outer padding, 12–16 pt card padding,
  8 pt inline gaps, and 16–24 pt section gaps.
- Define colour contrast targets: 4.5:1 for normal text and 3:1 for large text
  and non-text state indicators. Test Z1 explicitly because grey is the current
  failure case.

#### Menu bar

- Render `♥ 62 bpm` using `labelColor`/white rather than the zone colour.
- Add a compact zone dot or icon whose accessible label says, for example,
  “62 beats per minute, zone 1, recovery, connected.”
- Provide connected, reconnecting, disconnected, and error variants that remain
  distinguishable without colour and without relying on an emoji glyph.
- Check appearance in both light and dark menu bars, Increase Contrast, Reduce
  Transparency, and with the menu bar hidden/shown.

#### Dashboard information architecture

1. **Header:** connection dot, device name/status, and a gear button.
2. **Hero card:** one large BPM value, `BPM` unit, zone name, and a dial with
   zone ticks but no number in its centre.
3. **Trend card:** short labelled range selector (5 / 10 / 30 min), readable
   16:9 graph, and a legend only where it adds meaning.
4. **Session card:** elapsed time as the lead metric; average and maximum as
   secondary metrics; simple, labelled zone-time bars.
5. **Action area:** one full-width `Start session` / `Stop & save` primary
   button; an 8 pt separated secondary row for `Save last session` when needed.
   Settings belongs in the header, and Quit moves to a lower-priority utility
   location.

- Persist view objects and update their values rather than replacing the whole
  `NSViewController` each timer tick.
- Render the graph at its displayed aspect ratio; throttle expensive redraws to
  meaningful data or window changes, not every UI tick.
- Add empty, scanning, connecting, reconnecting, no-data, and export-failure
  layouts to the design review, not just the connected happy path.

**Exit criteria:** no duplicate primary BPM, all actions have 36 pt or larger
hit areas, Z1 menu-bar text is readable, dashboard screenshots are approved in
light/dark macOS, and keyboard focus/order is verified.

### 2. Settings and personalised zones — second feature milestone

**Goal:** turn configuration from a developer form into a clear setup flow.

#### Settings layout

- Use sections: **Device**, **Heart rate**, **Zones**, **Graph**, and a fixed
  footer. Use a shared 120–140 pt label column and aligned value controls.
- Make the panel content scrollable or adopt automatic layout constraints; it
  must tolerate system font-size changes and localized text without clipping.
- Place `Save changes` as the anchored primary action, `Reset to defaults` as
  secondary, and include `Cancel`/close behaviour that makes unsaved changes
  explicit.
- Replace the editable `NSComboBox` graph interval with a constrained native
  popup/segmented control (5, 10, 30 minutes); this prevents invalid free-form
  values.

#### Device setup

- Put scan state directly beside the scan button: `Scan`, spinner/progress,
  result count, and cancellation action.
- Let the result picker show device name, HR-service confidence, and signal
  strength. Keep its selection and `Use device` confirmation together.
- Provide clear permission, Bluetooth-off, and reconnect guidance with a retry
  path. Never surface raw exception text.

#### Colour and zone editor

- Use a native `NSColorWell` for each zone. It opens the macOS colour panel
  (including the colour wheel) and defaults to the saved zone colour. This is
  preferable to sending users to an external colour-picker site: it works
  offline, preserves privacy, and participates in the system accessibility
  model.
- Pair each well with a live swatch and an optional validated `#RRGGBB` field
  for precise entry. Changing one updates the other before save.
- Show zone boundaries as percent fields with a small ordered visual ramp. Mark
  invalid ordering inline (`Z1/Z2 must be lower than Z2/Z3`) instead of only in
  an alert after Save.
- Include a compact preview of the dashboard zone bars/dial so personalisation
  is visible before committing it.

**Exit criteria:** settings are operable with keyboard only, the colour wheel
round-trips valid hex values, validation is inline and precise, and no control
is visually misaligned at supported system font sizes.

### 3. Training utility and session value — third feature milestone

**Goal:** make HRM Live more useful than a live number while preserving its
fast, local-first character.

- Add configurable zone alerts (enter/leave zone; optional audio/haptic-like
  system feedback) with a quiet default and an obvious global mute.
- Add a pause/resume session state, session notes, and a post-session summary
  with duration, average, max, and time in each zone.
- Offer a stable export schema version and optional JSON summary alongside CSV;
  do not add cloud sync by default.
- Add a small recent-session list that reveals exports in Finder, while keeping
  data local and allowing deletion.
- Consider system workout integrations only after privacy, Apple entitlement,
  and user-consent requirements are evaluated.

**Exit criteria:** new recording states have defined recovery behaviour after
disconnect/restart, exports remain backward-compatible, and a user can finish
a typical workout without manually managing files mid-flow.

### 4. Reliability, accessibility, and engineering quality — continuous

#### Architecture

- Introduce a presentation model/view-model layer that converts immutable
  `UISnapshot` data into display strings, semantic state, and layout decisions.
  Keep AppKit rendering thin and testable.
- Break `popover.py` into dashboard sections and reusable UI primitives; replace
  most frame arithmetic with constraints or a small verified layout helper.
- Decouple graph data preparation from raster rendering. Evaluate an AppKit
  drawing path for the lightweight live graph before adding another framework.
- Add structured, privacy-safe logs for scan/connect/reconnect/export events;
  BLE addresses and session rows must not be emitted by default.

#### Tests and automation

- Raise the coverage floor from 54% in deliberate increments, beginning with
  presentation logic, failure states, config migrations, and BLE reconnection.
- Add unit tests for semantic colour choices, status-title accessibility labels,
  menu-bar state variants, colour parsing/round-tripping, and zone editor
  validation.
- Add screenshot-based visual regression tests for dashboard and settings in
  light/dark mode at normal and larger accessibility text sizes. Treat the three
  supplied screens as initial before-state references, not approved baselines.
- Add an end-to-end smoke test using a deterministic simulated HR sample stream
  and a scripted export destination. Keep real-strap tests as a documented
  manual matrix.
- Run `make check`, `make package`, and a clean-build package verification in
  CI on a supported macOS runner; preserve signed/notarized release steps as
  protected manual release jobs.

#### Accessibility and privacy

- Verify VoiceOver labels, focus order, keyboard equivalents, and non-colour
  state cues for each dashboard/settings control.
- Support Increase Contrast and Reduce Motion/Transparency; avoid animation as
  the sole feedback channel.
- State clearly that readings are fitness data, not medical advice. Keep all
  measurement data local unless the user explicitly exports it.

## Work plan and prioritisation

| Priority | Work item | Why now | Dependencies |
| --- | --- | --- | --- |
| P0 | Repeatable package verification and release checklist | A feature release cannot be trusted on a non-repeatable build. | Apple distribution work |
| P0 | Restore versioned `docs/` and add this roadmap | Decisions and release evidence must survive branches. | None |
| P1 | Design tokens, menu-bar contrast, one BPM hierarchy | Fixes the most visible trust/legibility problems in the supplied screens. | Screenshot review |
| P1 | Dashboard layout and action hierarchy | Establishes the product's daily-use experience. | Design tokens |
| P1 | Settings form, native colour wells, inline validation | Makes the zone system approachable and polished. | Shared UI primitives |
| P2 | Persistent views, graph redraw strategy, presentation model | Enables quality UI work without refresh/focus regressions. | Dashboard direction |
| P2 | Visual/accessibility regression suite and higher coverage floor | Prevents polish from decaying. | Stable view structure |
| P3 | Alerts, session summary, recent sessions | Adds training value after the core is excellent. | Session UX decisions |

## Definition of done for each UI change

- The interaction has an approved light and dark macOS screenshot and a state
  matrix covering empty, loading, success, and error where relevant.
- Text contrast and hit targets meet the targets above; status is never
  communicated by colour alone.
- Keyboard navigation and VoiceOver labels are verified.
- The display logic has automated tests; AppKit-specific behaviour has either a
  UI test or a named manual test step.
- `make check` and a clean `make package` pass before merge.

## Open product decisions

1. Should v1.x remain a menu-bar-only utility, or should a compact main window
   become available for reviewing the current/recent session? ( STILL REMAIN MENU BAR UTILITY )
2. Should zone boundaries remain a four-zone model, or should the roadmap allow
   a five-zone model with migration of existing configuration? LETS scrap this 5 zone model for now completely 
3. Are audio zone alerts desirable during workouts, and what should the default
   be so the app remains unobtrusive?( this will not be used during workouts , juist to monitor HRM , so we can ignore this 
4. What is the supported macOS floor after v1, and which physical straps should
   form the permanent hardware test matrix?
 ( Lets ignore this question as well ) 
