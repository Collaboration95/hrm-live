import { ZONES, LABELS, SCENARIOS, DEFAULT_CONFIG, clone, zoneFor, validateConfig, profileBpm, stats, duration, applyScenario, sample, beginSession, finishSession, saveExport, serialize } from "./model.js";

const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const tokens = await fetch("tokens.json").then(r => { if (!r.ok) throw new Error("Could not load native UI tokens"); return r.json(); });
DEFAULT_CONFIG.zone_colors = clone(tokens.ZONE_COLORS_DEFAULT);
let scenario = "connected", state = applyScenario(scenario), draft = clone(state.config), playing = false, profileSecond = 0, activity = [], toastTimer;
const board = $("#preview-board");
const nativeDesign = { width: tokens.POPOVER_WIDTH, radius: 8, gap: tokens.SECTION_GAP, canvas: tokens.CANVAS, surface: tokens.SURFACE, accent: tokens.TEXT_ACCENT };
let design = clone(nativeDesign);
try { const saved = JSON.parse(localStorage.getItem("hrm-ui-lab-design")); if (saved && typeof saved === "object") { for (const key of Object.keys(design)) { const v = saved[key]; if (["canvas", "surface", "accent"].includes(key) ? /^#[0-9a-f]{6}$/i.test(v) : Number.isFinite(v) && v >= 0 && v <= 500) design[key] = v; } } } catch { /* Preview works with browser storage disabled. */ }
const bluetoothIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="m7 7 10 10-5 4V3l5 4L7 17"/></svg>';
const devices = [{ address: "DEMO-HRM-01", name: "Demo HR strap", rssi: -48 }, { address: "DEMO-HRM-02", name: "Demo running sensor", rssi: -61 }];

function notify(message) {
  $("#toast").textContent = message; $("#toast").hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => $("#toast").hidden = true, 3800);
  activity.unshift({ message, time: duration((state.time - Date.UTC(2026, 9, 8, 1, 41)) / 1000) });
  activity = activity.slice(0, 5); renderInspector();
}
function download(content, filename, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a"); a.href = url; a.download = filename; a.hidden = true; document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function setPlaying(value) {
  playing = value && !state.quit;
  $("#toggle-signal").textContent = playing ? "Ⅱ Pause signal" : "▶ Play signal";
  $("#signal-status").textContent = playing ? "Playing" : "Paused";
  $("#toggle-signal").setAttribute("aria-pressed", String(playing));
}
function setView(view) {
  $("#dashboard-frame").hidden = view === "settings";
  $("#settings-frame").hidden = view === "dashboard";
  document.querySelectorAll("[data-view]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.view === view)));
}
function fitPreview() {
  const zoom = window.innerWidth >= 1100 && $(".canvas-scroll").clientWidth < 960 ? .75 : 1;
  $("#zoom").value = String(zoom); board.style.setProperty("--zoom", zoom);
}
function selectScenario(name) {
  setPlaying(false); scenario = name; profileSecond = 0;
  state = applyScenario(name, state.config); draft = clone(state.config);
  $("#dashboard").hidden = false;
  $("#fail-export").checked = name === "export-error";
  $("#bpm-slider").value = state.bpm ?? 142;
  document.querySelectorAll("[data-scenario]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.scenario === name)));
  $("#scenario-caption").textContent = SCENARIOS.find(s => s[0] === name)?.[2] ?? name;
  if (name === "scanning") completeScan();
  renderDashboard(); renderSettings(); renderInspector();
  notify(`Loaded ${SCENARIOS.find(s => s[0] === name)?.[1] ?? name} scenario`);
}
function statusText() {
  return state.error ?? (state.status === "connected" ? `Connected — ${state.config.device_name || "Demo HR strap"}` : state.status === "disconnected" ? "Disconnected" : `${state.status[0].toUpperCase()}${state.status.slice(1)}…`);
}
function visibleGraph() { return state.graph.filter(p => p.time >= state.time - state.config.graph_window_minutes * 60000); }
function graphMarkup(points) {
  if (!points.length) return `<div class="graph-empty">${bluetoothIcon}<strong>${state.status === "error" ? "Bluetooth unavailable" : state.scan === "scanning" ? "Searching for your strap" : state.status === "connected" ? "Waiting for a reading" : "No heart-rate signal"}</strong><span>${esc(state.error || (state.status === "reconnecting" ? "Move your strap closer. Reconnecting automatically." : "Connect a heart-rate monitor to see your trend."))}</span></div>`;
  const width = 288, height = 170, x = t => 30 + (t - state.time + state.config.graph_window_minutes * 60000) / (state.config.graph_window_minutes * 60000) * 250, y = bpm => 142 - (bpm - 40) / 180 * 124;
  const lines = [60, 100, 140, 180].map(v => `<line x1="30" y1="${y(v)}" x2="280" y2="${y(v)}" stroke="var(--divider)" stroke-dasharray="2 4"/><text x="22" y="${y(v) + 3}" text-anchor="end">${v}</text>`).join("");
  const trace = points.slice(1).map((p, i) => `<path d="M${x(points[i].time).toFixed(1)},${y(points[i].bpm).toFixed(1)} L${x(p.time).toFixed(1)},${y(p.bpm).toFixed(1)}" stroke="${esc(state.config.zone_colors[zoneFor(p.bpm, state.config)])}"/>`).join("");
  return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Heart rate over the last ${state.config.graph_window_minutes} minutes"><g font-size="10" fill="var(--secondary)" font-family="inherit">${lines}<text x="30" y="165">−${state.config.graph_window_minutes} min</text><text x="155" y="165" text-anchor="middle">−${state.config.graph_window_minutes / 2} min</text><text x="280" y="165" text-anchor="end">Now</text></g><g fill="none" stroke-width="2" stroke-linecap="round">${trace}</g></svg>`;
}
function gaugeMarkup(bpm, zone) {
  const color = state.config.zone_colors[zone], radius = 64, circumference = 2 * Math.PI * radius;
  const fraction = bpm === null ? 0 : Math.min(bpm / state.config.max_hr, 1);
  const ticks = Object.values(state.config.zones).map(pct => { const a = pct * 2 * Math.PI - Math.PI / 2; return `<line x1="${82 + 73 * Math.cos(a)}" y1="${82 + 73 * Math.sin(a)}" x2="${82 + 78 * Math.cos(a)}" y2="${82 + 78 * Math.sin(a)}" stroke="var(--secondary)" stroke-width="2"/>`; }).join("");
  return `<div class="gauge"><svg viewBox="0 0 164 164" aria-hidden="true"><circle cx="82" cy="82" r="64" fill="none" stroke="var(--surface-alt)" stroke-width="14"/><circle cx="82" cy="82" r="64" fill="none" stroke="${esc(color)}" stroke-width="14" stroke-linecap="round" stroke-dasharray="${fraction * circumference} ${circumference}" transform="rotate(-90 82 82)"/>${ticks}</svg><div class="gauge-value"><strong>${bpm ?? "—"}</strong><small>BEATS / MIN</small></div></div><p class="zone-caption" style="color:${bpm === null ? "var(--secondary)" : esc(color)}">${bpm === null ? "Waiting for a signal" : `${zone} · ${LABELS[ZONES.indexOf(zone)]}`}</p><div class="live-tag">${bpm === null ? state.status : `${Math.round(bpm / state.config.max_hr * 100)}% of max heart rate`}</div>`;
}
function renderDashboard() {
  const focus = document.activeElement?.id;
  const bpm = state.status === "connected" ? state.bpm : null, zone = zoneFor(bpm ?? 0, state.config), sessionStats = stats(state.session), points = visibleGraph();
  const values = points.map(p => p.bpm), average = values.length ? Math.round(values.reduce((a,b) => a+b, 0) / values.length) : null;
  $("#menu-title").textContent = bpm === null ? "♡ — ○" : `♥ ${bpm} bpm ●`;
  $("#menu-title").setAttribute("aria-label", bpm === null ? `Heart rate monitor ${state.status}` : `${bpm} beats per minute, ${zone}, connected`);
  $("#dashboard").innerHTML = `<header class="native-header"><span class="native-status ${esc(state.status)}"></span><span class="device-title">${esc(statusText())}</span><button id="open-settings" class="native-button">⚙ Settings</button></header>
    <section class="card hero-card" aria-label="Live heart rate">${gaugeMarkup(bpm, zone)}</section>
    <section class="card"><div class="card-heading"><h2>Heart-rate trend</h2><span class="caption">Last ${state.config.graph_window_minutes} min</span></div><div class="trend-summary"><div><span>Average</span><strong>${average ?? "—"}${average === null ? "" : " bpm"}</strong></div><div><span>Range</span><strong>${values.length ? `${Math.min(...values)}–${Math.max(...values)}` : "—"}</strong></div></div><div class="segmented">${[5,10,30].map(m => `<button data-window="${m}" aria-pressed="${m === state.config.graph_window_minutes}">${m} min</button>`).join("")}</div><div class="graph">${graphMarkup(points)}</div></section>
    <section class="card"><div class="card-heading"><h2>Session</h2><span class="session-state ${state.active ? "recording" : ""}">${state.active ? "● Recording" : sessionStats.count ? "Completed" : "Not recording"}</span></div><div class="elapsed">${sessionStats.count ? duration(sessionStats.duration) : "00:00"}</div><div class="session-stats"><span>Avg <b>${sessionStats.count ? Math.round(sessionStats.average) : "—"}</b></span><span>Max <b>${sessionStats.max || "—"}</b></span><span>Min <b>${sessionStats.min || "—"}</b></span><span><b>${sessionStats.count}</b> samples</span></div><div class="zone-bars">${ZONES.map(z => `<div class="zone-bar"><strong style="color:${esc(state.config.zone_colors[z])}">${z}</strong><div class="zone-track"><span style="width:${sessionStats.duration ? state.session.zoneTimes[z] / sessionStats.duration * 100 : 0}%;background:${esc(state.config.zone_colors[z])}"></span></div><time>${duration(state.session.zoneTimes[z])}</time></div>`).join("")}</div></section>
    <section class="action-area"><button id="session-action" class="native-button primary" ${!state.active && (state.status !== "connected" || state.quit) ? "disabled" : ""}>${state.active ? "Stop & save" : "Start session"}</button>${state.pending ? '<button id="retry-export" class="native-button">Save last session…</button>' : ""}<div class="export-feedback ${state.exportError ? "error" : ""}">${esc(state.exportError || (state.saved ? `Saved: ${state.saved}` : ""))}</div><div class="utility-row"><span class="caption" style="color:var(--secondary);font-size:11px">All data stays local</span><button id="quit-preview" class="quit-button">Quit HRM Live</button></div></section>
    <section class="card recent-card"><div class="card-heading"><h2>Recent sessions</h2><span class="caption">${state.recent.length ? `Latest ${Math.min(4, state.recent.length)} of ${state.recent.length}` : ""}</span></div>${state.recent.length ? state.recent.slice(0,4).map(r => { const s = stats(r.session); return `<div class="recent-row"><div class="recent-title">${esc(r.name || "Session awaiting export")}</div><div class="recent-meta">${duration(s.duration)} · Avg ${Math.round(s.average)} · Max ${s.max}</div><div class="mini-zones">${ZONES.map(z => `<span style="width:${s.duration ? r.session.zoneTimes[z] / s.duration * 100 : 0}%;background:${esc(state.config.zone_colors[z])}"></span>`).join("")}</div><div class="recent-actions"><button class="native-button small" data-recent="open" data-id="${r.id}" ${r.name ? "" : "disabled"}>Open</button><button class="native-button small" data-recent="reveal" data-id="${r.id}" ${r.name ? "" : "disabled"}>Reveal</button><button class="native-button small danger" data-recent="delete" data-id="${r.id}">Delete</button></div></div>`; }).join("") : '<p class="empty-recent">Your completed workouts will appear here.</p>'}</section>`;
  $("#quit-overlay").hidden = !state.quit;
  if (focus) document.getElementById(focus)?.focus({ preventScroll: true });
  $("#bpm-output").innerHTML = `${state.bpm ?? "—"} <small>bpm</small>`;
  renderInspector(); updateDeviceStatus();
}
function renderSettings() {
  $("#settings-content").innerHTML = `<section class="settings-section"><h2>Device</h2><div class="device-card"><div class="device-heading"><span class="native-status ${esc(state.status)}" id="settings-dot"></span><span id="settings-status">${esc(statusText())}</span><span id="settings-dirty" class="settings-dirty" hidden>Unsaved</span></div><div class="scan-row"><button type="button" id="scan-action" class="native-button small">Scan for HRMs</button><span id="scan-status"></span></div><div class="picker-row"><select id="device-picker" aria-label="Discovered heart rate monitors"></select><button id="use-device" type="button" class="native-button small">Use device</button></div><div class="form-row"><label for="device-address">Address</label><input id="device-address" name="device_address" value="${esc(draft.device_address)}" readonly></div><div class="form-row"><label for="device-name">Name</label><input id="device-name" name="device_name" value="${esc(draft.device_name)}"></div><p id="recovery-copy" class="recovery-message" ${state.error ? "" : "hidden"}>${esc(state.error)}</p><button id="recover-device" type="button" class="native-button small" ${state.error ? "" : "hidden"}>Allow Bluetooth (simulate)</button></div></section>
    <section class="settings-section"><h2>Heart rate</h2><div class="form-row"><label for="max-hr">Maximum heart rate</label><div class="field-unit"><input id="max-hr" name="max_hr" type="number" min="1" step="1" value="${draft.max_hr}"><span>bpm</span></div></div><span class="field-error" id="max-hr-error"></span></section>
    <section class="settings-section"><h2>Zone boundaries</h2>${["z1_max","z2_max","z3_max"].map((key,i) => `<div class="form-row"><label for="${key}">Z${i+1} / Z${i+2} boundary</label><div class="field-unit"><input id="${key}" name="${key}" type="number" min="1" max="99" step="1" value="${Math.round(draft.zones[key] * 100)}"><span>%</span></div></div>`).join("")}<span class="field-error" id="zones-error"></span><div id="zone-ramp" class="zone-ramp"></div><p>Four zones, as a percentage of your maximum heart rate.</p></section>
    <section class="settings-section"><h2>Zone colors</h2>${ZONES.map((z,i) => `<div class="form-row"><label for="color-${z}">${z} · ${LABELS[i]}</label><div class="color-field"><input id="picker-${z}" data-zone-picker="${z}" type="color" value="${esc(draft.zone_colors[z])}" aria-label="${z} color picker"><input id="color-${z}" name="color_${z}" type="text" value="${esc(draft.zone_colors[z])}" maxlength="7" aria-label="${z} hex color"></div></div><span class="field-error" id="color-${z}-error"></span>`).join("")}</section>
    <section class="settings-section"><h2>Graph</h2><div class="form-row"><label for="graph-window">Time window</label><select id="graph-window" name="graph_window_minutes">${[5,10,30].map(m => `<option value="${m}" ${m === draft.graph_window_minutes ? "selected" : ""}>${m} minutes</option>`).join("")}</select></div></section>`;
  updateDeviceStatus(); validateDraft();
}
function readDraft() {
  const form = $("#settings-form"), values = new FormData(form);
  draft = { device_address: values.get("device_address"), device_name: values.get("device_name"), max_hr: Number(values.get("max_hr")), zones: Object.fromEntries(["z1_max","z2_max","z3_max"].map(k => [k, Number(values.get(k)) / 100])), zone_colors: Object.fromEntries(ZONES.map(z => [z, String(values.get(`color_${z}`)).toUpperCase()])), graph_window_minutes: Number(values.get("graph_window_minutes")) };
}
function isDirty() { return JSON.stringify(draft) !== JSON.stringify(state.config); }
function validateDraft() {
  const errors = validateConfig(draft);
  $("#max-hr-error").textContent = errors.max_hr ?? ""; $("#zones-error").textContent = errors.zones ?? "";
  for (const z of ZONES) { $(`#color-${z}-error`).textContent = errors[z] ?? ""; if (!errors[z]) $(`#picker-${z}`).value = draft.zone_colors[z]; }
  const bounds = [0, draft.zones.z1_max, draft.zones.z2_max, draft.zones.z3_max, 1];
  $("#zone-ramp").innerHTML = ZONES.map((z,i) => `<span style="flex:${Math.max(0.01,bounds[i+1]-bounds[i])};background:${errors[z] ? "#aaa" : esc(draft.zone_colors[z])}"></span>`).join("");
  $("#save-settings").disabled = Object.keys(errors).length > 0;
  $("#settings-dirty").hidden = !isDirty();
  return errors;
}
function updateDeviceStatus() {
  if (!$("#scan-status")) return;
  $("#settings-status").textContent = statusText(); $("#settings-dot").className = `native-status ${state.status}`;
  $("#scan-action").textContent = state.scan === "scanning" ? "Cancel scan" : state.scan === "idle" ? "Scan for HRMs" : "Scan again";
  $("#scan-status").textContent = state.scan === "scanning" ? "Scanning…" : state.scan === "complete" ? `${state.devices.length} devices found` : state.scan === "cancelled" ? "Scan cancelled" : "Find a nearby strap";
  const selected = $("#device-picker").value;
  $("#device-picker").innerHTML = state.devices.length ? state.devices.map(d => `<option value="${esc(d.address)}">♥ ${esc(d.name)} (${d.rssi} dBm)</option>`).join("") : '<option value="">No devices found</option>';
  if (state.devices.some(d => d.address === selected)) $("#device-picker").value = selected;
  $("#device-picker").disabled = !state.devices.length; $("#use-device").disabled = !state.devices.length;
  $("#recovery-copy").textContent = state.error || ""; $("#recovery-copy").hidden = !state.error; $("#recover-device").hidden = !state.error;
}
let scanRevision = 0;
function completeScan() {
  const current = state, revision = ++scanRevision;
  setTimeout(() => { if (current !== state || revision !== scanRevision || state.scan !== "scanning" || state.quit) return; state.devices = clone(devices); state.scan = "complete"; updateDeviceStatus(); renderInspector(); notify("Scan complete · 2 demo straps found"); }, 1400);
}
function connectDevice() {
  if (!state.config.device_address) { state.status = "disconnected"; state.bpm = null; renderDashboard(); return; }
  state.status = "connecting"; state.error = null; renderDashboard();
  const current = state;
  setTimeout(() => { if (state !== current || state.quit) return; state.status = "connected"; state.bpm = Number($("#bpm-slider").value); sample(state,state.bpm); renderDashboard(); notify(`Connected to ${state.config.device_name || "demo strap"}`); }, 900);
}
function openExport() {
  if (!state.pending) return;
  const s = stats(state.pending); $("#export-summary").textContent = `${duration(s.duration)} · ${s.count} samples · ${Math.round(s.average)} bpm average`;
  $("#export-dialog").showModal();
}
async function confirm(title, copy) {
  const dialog = $("#confirm-dialog"); $("#confirm-title").textContent = title; $("#confirm-copy").textContent = copy;
  dialog.returnValue = "cancel"; dialog.showModal();
  return new Promise(resolve => dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true }));
}
function renderInspector() {
  const s = stats(state.session);
  $("#state-inspector").innerHTML = [["Connection",state.quit ? "Quit" : state.status],["Heart rate",state.bpm === null ? "—" : `${state.bpm} bpm`],["Zone",state.bpm === null ? "—" : zoneFor(state.bpm,state.config)],["Session",state.active ? "Recording" : "Idle"],["Samples",s.count],["Pending export",state.pending ? "Yes" : "No"],["Saved sessions",state.recent.length]].map(([k,v]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("");
  $("#activity").innerHTML = activity.map(a => `<li>${esc(a.message)}<time>${a.time} · simulated time</time></li>`).join("");
}
function applyDesign() {
  for (const [key,value] of Object.entries(design)) board.style.setProperty(key === "width" ? "--frame-width" : `--${key}`, ["width","radius","gap"].includes(key) ? `${value}px` : value);
  if (board.classList.contains("dark")) {
    if (design.canvas === nativeDesign.canvas) board.style.setProperty("--canvas", "#242528");
    if (design.surface === nativeDesign.surface) board.style.setProperty("--surface", "#303236");
  }
  $("#frame-width").value = design.width; $("#card-radius").value = design.radius; $("#section-gap").value = design.gap;
  $("#width-output").textContent = `${design.width} px`; $("#radius-output").textContent = `${design.radius} px`; $("#gap-output").textContent = `${design.gap} px`; $("#dashboard-dimensions").textContent = `${design.width} px`;
  for (const key of ["canvas","surface","accent"]) { $(`#design-${key}`).value = design[key]; $(`#hex-${key}`).textContent = design[key].toUpperCase(); }
  try { localStorage.setItem("hrm-ui-lab-design", JSON.stringify(design)); } catch { /* Optional local design preferences. */ }
}
function advance() {
  const count = Number($("#speed").value), profile = $("#profile").value;
  for (let i = 0; i < count; i++) { profileSecond++; sample(state,profileBpm(profile,profileSecond,Number($("#bpm-slider").value))); }
  if (state.bpm !== null && profile !== "manual") $("#bpm-slider").value = state.bpm;
  renderDashboard();
}

$("#scenarios").innerHTML = SCENARIOS.map(([id,title,description,color]) => `<button class="scenario" data-scenario="${id}" aria-pressed="${id === scenario}"><span class="scenario-dot ${color}"></span><span>${title}<small>${description}</small></span></button>`).join("");
$("#design-colors").innerHTML = [["canvas","Canvas"],["surface","Cards"],["accent","Accent"]].map(([key,label]) => `<label class="design-color"><input id="design-${key}" type="color" value="${design[key]}" data-design-color="${key}" aria-label="${label} color"><span>${label}</span><code id="hex-${key}">${design[key]}</code></label>`).join("");
$("#scenarios").addEventListener("click", e => { const b = e.target.closest("[data-scenario]"); if (b) selectScenario(b.dataset.scenario); });
$("#view-nav").addEventListener("click", e => { const b = e.target.closest("[data-view]"); if (b) setView(b.dataset.view); });
$("#dashboard").addEventListener("click", async e => {
  const b = e.target.closest("button"); if (!b) return;
  if (b.dataset.window) { state.config.graph_window_minutes = Number(b.dataset.window); draft.graph_window_minutes = state.config.graph_window_minutes; $("#graph-window").value = draft.graph_window_minutes; renderDashboard(); validateDraft(); }
  if (b.id === "open-settings") { setView("both"); $("#settings-frame").scrollIntoView({ block: "nearest", inline: "nearest", behavior: board.classList.contains("reduce-motion") || matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }); }
  if (b.id === "session-action") { if (state.active) { finishSession(state); renderDashboard(); notify("Session stopped · choose an export format"); openExport(); } else { beginSession(state); renderDashboard(); notify("Session recording started"); } }
  if (b.id === "retry-export") openExport();
  if (b.id === "quit-preview") { state.quit = true; setPlaying(false); renderDashboard(); notify("Preview app quit · simulator stopped"); }
  if (b.dataset.recent) {
    const r = state.recent.find(r => r.id === Number(b.dataset.id)); if (!r) return;
    if (b.dataset.recent === "open") { download(serialize(r.session,r.format),r.name,r.format === "csv" ? "text/csv" : "application/json"); notify(`Opened ${r.name} as a browser download`); }
    if (b.dataset.recent === "reveal") notify(`Demo export: ${r.name} · browser downloads replace Finder in this preview`);
    if (b.dataset.recent === "delete" && await confirm("Delete this recent session?", "This removes the demo history entry. Downloaded files remain unchanged.")) { state.recent = state.recent.filter(item => item.id !== r.id); renderDashboard(); notify("Recent session removed"); }
  }
});
$("#settings-form").addEventListener("input", e => { if (e.target.dataset.zonePicker) $(`#color-${e.target.dataset.zonePicker}`).value = e.target.value.toUpperCase(); readDraft(); validateDraft(); });
$("#settings-form").addEventListener("submit", e => { e.preventDefault(); readDraft(); if (Object.keys(validateDraft()).length) return; const old = state.config.device_address; state.config = clone(draft); notify("Settings saved in the preview"); validateDraft(); renderDashboard(); if (old !== state.config.device_address || state.status !== "connected") connectDevice(); });
$("#settings-content").addEventListener("click", e => {
  const id = e.target.closest("button")?.id;
  if (id === "scan-action") { if (state.scan === "scanning") { state.scan = "cancelled"; notify("Scan cancelled"); } else { state.scan = "scanning"; state.devices = []; completeScan(); notify("Scanning for demo straps"); } updateDeviceStatus(); }
  if (id === "use-device") { const device = state.devices.find(d => d.address === $("#device-picker").value); if (!device) return; $("#device-address").value = device.address; $("#device-name").value = device.name; readDraft(); validateDraft(); notify("Device selected · save changes to connect"); }
  if (id === "recover-device") { state.error = null; if (!state.config.device_address) state.config = clone(DEFAULT_CONFIG); connectDevice(); notify("Bluetooth permission granted in simulation"); }
});
async function closeSettings() { if (isDirty() && !await confirm("Discard unsaved changes?", "Your preview settings have not been saved.")) return; draft = clone(state.config); renderSettings(); setView("dashboard"); }
$("#close-settings").addEventListener("click",closeSettings); $("#cancel-settings").addEventListener("click",closeSettings);
$("#reset-settings").addEventListener("click", () => { draft = clone(DEFAULT_CONFIG); renderSettings(); notify("Default settings loaded · save to apply"); });
$("#download-session").addEventListener("click", () => {
  if (!state.pending) return;
  const format = $("#export-format").value, name = ($("#export-name").value.trim().replace(/[\\/\x00-\x1f]/g,"_") || "HRM Live demo session") + `.${format}`, data = serialize(state.pending,format);
  if (saveExport(state,name,format,$("#fail-export").checked)) { download(data,name,format === "csv" ? "text/csv" : "application/json"); notify(`Saved ${name}`); } else notify("Export failed · turn off simulated failure and retry");
  $("#export-dialog").close(); renderDashboard();
});
$("#export-dialog").addEventListener("close", () => { if (state.pending && !state.exportError) notify("Export cancelled · last session is still available"); });
$("#toggle-signal").addEventListener("click", () => setPlaying(!playing)); $("#step-signal").addEventListener("click",advance);
$("#bpm-slider").addEventListener("input", () => { $("#profile").value = "manual"; if (state.status === "connected") sample(state,Number($("#bpm-slider").value)); renderDashboard(); });
$("#profile").addEventListener("change", () => profileSecond = 0);
$("#zoom").addEventListener("change", () => board.style.setProperty("--zoom",$("#zoom").value));
$("#appearance").addEventListener("click", () => { const dark = board.classList.toggle("dark"); applyDesign(); $("#appearance").setAttribute("aria-pressed",String(dark)); $("#appearance").textContent = dark ? "☀ Light appearance" : "☾ Dark appearance"; });
for (const [id,key] of [["frame-width","width"],["card-radius","radius"],["section-gap","gap"]]) $(`#${id}`).addEventListener("input",e => { design[key] = Number(e.target.value); applyDesign(); });
$("#design-colors").addEventListener("input",e => { if (e.target.dataset.designColor) { design[e.target.dataset.designColor] = e.target.value; applyDesign(); } });
$("#show-bounds").addEventListener("change",e => board.classList.toggle("show-bounds",e.target.checked));
$("#reduce-motion").addEventListener("change",e => board.classList.toggle("reduce-motion",e.target.checked));
$("#reset-design").addEventListener("click", () => { design = clone(nativeDesign); applyDesign(); notify("Native design tokens restored"); });
$("#export-design").addEventListener("click", () => { download(JSON.stringify({ prototype: "HRM Live UI Lab", native_tokens: tokens, design, config: state.config },null,2),"hrm-live-ui-design.json","application/json"); notify("Design values exported for implementation"); });
$("#reset-lab").addEventListener("click", () => { state.config = clone(DEFAULT_CONFIG); design = clone(nativeDesign); board.classList.remove("dark","show-bounds","reduce-motion"); applyDesign(); $("#appearance").setAttribute("aria-pressed","false"); $("#appearance").textContent = "☾ Dark appearance"; $("#show-bounds").checked = false; $("#reduce-motion").checked = false; fitPreview(); $("#profile").value = "steady"; $("#speed").value = "1"; activity = []; setView("both"); selectScenario("connected"); });
$("#relaunch").addEventListener("click", () => selectScenario("connected"));
$("#menu-title").addEventListener("click", () => { $("#dashboard").hidden = !$("#dashboard").hidden; });
document.addEventListener("keydown", e => { if (e.target.closest("input,select,textarea,button,a") || $("dialog[open]")) return; if (e.code === "Space") { e.preventDefault(); setPlaying(!playing); } if (e.key.toLowerCase() === "r") $("#reset-lab").click(); });
setInterval(() => { if (playing && !state.quit) advance(); },1000);
fitPreview();
applyDesign(); renderDashboard(); renderSettings(); renderInspector();
notify("UI Lab ready · choose a scenario or play the signal");
