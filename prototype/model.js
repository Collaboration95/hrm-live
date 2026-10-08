// Browser-only simulation. This module has no DOM, Bluetooth, or storage access.
export const ZONES = ["Z1", "Z2", "Z3", "Z4"];
export const LABELS = ["Recovery", "Aerobic", "Threshold", "VO2 Max"];
export const SCENARIOS = [
  ["connected", "Connected", "Aerobic · live readings", "green"],
  ["disconnected", "Disconnected", "No strap selected", "gray"],
  ["scanning", "Scanning", "Discover nearby straps", "blue"],
  ["connecting", "Connecting", "Waiting for a signal", "amber"],
  ["reconnecting", "Reconnecting", "Strap temporarily out of range", "amber"],
  ["permission", "Permission denied", "Bluetooth recovery", "red"],
  ["recording", "Recording", "Workout in progress", "green"],
  ["pending", "Pending export", "Stopped · ready to save", "blue"],
  ["export-error", "Export failed", "Retry without losing samples", "red"],
  ["recent", "Recent sessions", "Saved workout history", "purple"],
];
export const DEFAULT_CONFIG = { device_address: "DEMO-HRM-01", device_name: "Demo HR strap", max_hr: 190, zones: { z1_max: .6, z2_max: .75, z3_max: .88 }, zone_colors: { Z1: "#8E8E93", Z2: "#34C759", Z3: "#FF9F0A", Z4: "#FF375F" }, graph_window_minutes: 10 };
const epoch = Date.UTC(2026, 9, 8, 1, 41);
export const clone = value => JSON.parse(JSON.stringify(value));
export function zoneFor(bpm, config = DEFAULT_CONFIG) {
  if (bpm <= 0 || config.max_hr <= 0) return "Z1";
  const pct = bpm / config.max_hr;
  return pct < config.zones.z1_max ? "Z1" : pct < config.zones.z2_max ? "Z2" : pct < config.zones.z3_max ? "Z3" : "Z4";
}
export function validateConfig(config) {
  const errors = {};
  if (!Number.isInteger(config.max_hr) || config.max_hr <= 0) errors.max_hr = "Enter a positive whole number.";
  const { z1_max: a, z2_max: b, z3_max: c } = config.zones;
  if (!(0 < a && a < b && b < c && c < 1)) errors.zones = "Boundaries must increase: 0 < Z1 < Z2 < Z3 < 100%.";
  for (const zone of ZONES) if (!/^#[0-9a-f]{6}$/i.test(config.zone_colors[zone])) errors[zone] = "Use a six-digit hex color.";
  if (![5, 10, 30].includes(config.graph_window_minutes)) errors.graph = "Choose 5, 10, or 30 minutes.";
  return errors;
}
export function profileBpm(profile, second, manual = 142) {
  const ripple = Math.sin(second / 9) * 2;
  return Math.round(Math.max(40, Math.min(220, profile === "manual" ? manual : profile === "warmup" ? 80 + Math.min(second / 4, 75) + ripple : profile === "intervals" ? 130 + 45 * (Math.sin(second / 15) > 0 ? 1 : 0) + ripple : profile === "recovery" ? Math.max(65, 170 - second / 3) + ripple : 142 + ripple)));
}
export function newSession() { return { rows: [], zoneTimes: Object.fromEntries(ZONES.map(z => [z, 0])) }; }
export function record(session, time, bpm, config) {
  const prior = session.rows.at(-1);
  if (prior && time <= prior.time) return false;
  if (!Number.isInteger(bpm) || bpm < 25 || bpm > 240) return false;
  if (prior) session.zoneTimes[prior.zone] += Math.min((time - prior.time) / 1000, 5);
  session.rows.push({ time, bpm, zone: zoneFor(bpm, config) });
  return true;
}
export function stats(session) {
  const values = session.rows.map(r => r.bpm);
  return { count: values.length, average: values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0, min: values.length ? Math.min(...values) : 0, max: values.length ? Math.max(...values) : 0, duration: Object.values(session.zoneTimes).reduce((a, b) => a + b, 0) };
}
export function duration(seconds) {
  const n = Math.floor(seconds), h = Math.floor(n / 3600), m = Math.floor(n / 60) % 60, s = n % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
export function createState(config = DEFAULT_CONFIG) {
  return { config: clone(config), time: epoch, bpm: 142, status: "connected", error: null, scan: "idle", devices: [], graph: [], active: false, session: newSession(), pending: null, recent: [], saved: null, exportError: null, quit: false };
}
export function sample(state, bpm, seconds = 1) {
  state.time += seconds * 1000;
  if (state.status !== "connected" || state.quit) return;
  state.bpm = bpm;
  state.graph.push({ time: state.time, bpm });
  state.graph = state.graph.slice(-1800);
  if (state.active) record(state.session, state.time, bpm, state.config);
}
export function beginSession(state) {
  if (state.status !== "connected" || state.quit) return false;
  state.session = newSession(); state.active = true; state.pending = null; state.exportError = null; state.saved = null;
  record(state.session, state.time, state.bpm, state.config);
  return true;
}
export function finishSession(state) {
  if (!state.active) return state.pending;
  state.active = false;
  if (!state.session.rows.length) return null;
  state.pending = clone(state.session);
  const id = Math.max(state.time, ...state.recent.map(r => r.id + 1));
  state.recent.unshift({ id, session: clone(state.session), name: null, format: null });
  state.recent = state.recent.slice(0, 20);
  return state.pending;
}
export function saveExport(state, filename, format, fail = false) {
  if (!state.pending) return false;
  if (fail) { state.exportError = "Could not write the session. Choose a different destination and try again."; return false; }
  const recent = state.recent.find(r => r.name === null);
  if (recent) { recent.name = filename; recent.format = format; }
  state.saved = filename; state.pending = null; state.exportError = null;
  return true;
}
export function serialize(session, format) {
  if (format === "csv") return "timestamp,bpm,zone\r\n" + session.rows.map(r => `${new Date(r.time).toISOString()},${r.bpm},${r.zone}`).join("\r\n") + "\r\n";
  return JSON.stringify({ prototype: true, ...stats(session), zone_times: session.zoneTimes, samples: session.rows.map(r => ({ timestamp: new Date(r.time).toISOString(), bpm: r.bpm, zone: r.zone })) }, null, 2);
}
export function applyScenario(name, config = DEFAULT_CONFIG) {
  const state = createState(config);
  if (["connected", "recording", "pending", "export-error", "recent", "reconnecting"].includes(name)) {
    if (["recording", "pending", "export-error", "recent"].includes(name)) beginSession(state);
    for (let i = 0; i < 420; i++) sample(state, Math.round(97 + 49 * Math.min(i / 200, 1) + 7 * Math.sin(i / 28)));
    state.bpm = 142;
  }
  if (["pending", "export-error", "recent"].includes(name)) finishSession(state);
  if (name === "export-error") saveExport(state, "", "csv", true);
  if (name === "recent") {
    saveExport(state, "Morning workout.csv", "csv");
    state.recent.push({ id: epoch - 86400000, session: clone(state.session), name: "Recovery session.json", format: "json" });
  }
  if (["disconnected", "scanning", "connecting", "reconnecting"].includes(name)) { state.status = name === "scanning" ? "disconnected" : name; state.bpm = null; }
  if (name === "disconnected") { state.config.device_address = ""; state.config.device_name = ""; }
  if (name === "scanning") state.scan = "scanning";
  if (name === "permission") { state.status = "error"; state.error = "Bluetooth access is denied. Allow HRM Live in Privacy & Security → Bluetooth."; state.bpm = null; }
  return state;
}
