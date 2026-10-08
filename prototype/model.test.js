import test from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_CONFIG, clone, zoneFor, validateConfig, profileBpm, newSession, record, stats, applyScenario, sample, beginSession, finishSession, saveExport, serialize } from "./model.js";

test("zone boundaries match the native four-zone semantics", () => {
  const config = clone(DEFAULT_CONFIG); config.max_hr = 200;
  assert.equal(zoneFor(119, config), "Z1"); assert.equal(zoneFor(120, config), "Z2");
  assert.equal(zoneFor(150, config), "Z3"); assert.equal(zoneFor(176, config), "Z4");
});
test("settings reject invalid order, numbers, and colors", () => {
  const c = clone(DEFAULT_CONFIG); c.zones.z1_max = .9; c.max_hr = NaN; c.zone_colors.Z1 = "#abc";
  assert.deepEqual(Object.keys(validateConfig(c)), ["max_hr", "zones", "Z1"]);
  assert.deepEqual(validateConfig(DEFAULT_CONFIG), {});
});
test("profiles are deterministic and bounded", () => {
  for (const p of ["steady","warmup","intervals","recovery","manual"]) for (const t of [0,20,600]) {
    assert.equal(profileBpm(p,t),profileBpm(p,t)); assert.ok(profileBpm(p,t) >= 40 && profileBpm(p,t) <= 220);
  }
});
test("recording clamps gaps and attributes time to the previous zone", () => {
  const s = newSession(); record(s,0,90,DEFAULT_CONFIG); record(s,30000,180,DEFAULT_CONFIG);
  assert.equal(s.zoneTimes.Z1,5); assert.equal(stats(s).duration,5);
  assert.equal(record(s,20000,120,DEFAULT_CONFIG),false);
});
test("disconnect retains recording data without inventing signal samples", () => {
  const s = applyScenario("recording"), count = s.session.rows.length;
  s.status = "reconnecting"; sample(s,190,30); assert.equal(s.session.rows.length,count);
  s.status = "connected"; sample(s,150); assert.equal(s.session.rows.length,count+1);
});
test("cancelled and failed exports retain immutable retry data", () => {
  const s = applyScenario("recording"), pending = finishSession(s), before = clone(pending);
  s.session.rows[0].bpm = 200; assert.deepEqual(s.pending,before);
  assert.equal(saveExport(s,"session.csv","csv",true),false); assert.deepEqual(s.pending,before);
  assert.equal(saveExport(s,"session.csv","csv"),true); assert.equal(s.pending,null); assert.equal(s.recent[0].name,"session.csv");
});
test("CSV and JSON contain the intended sample data", () => {
  const s = applyScenario("pending");
  const csv = serialize(s.pending,"csv"); assert.ok(csv.startsWith("timestamp,bpm,zone\r\n"));
  assert.equal(csv.trim().split("\r\n").length,s.pending.rows.length+1);
  const json = JSON.parse(serialize(s.pending,"json")); assert.equal(json.prototype,true); assert.equal(json.samples.length,s.pending.rows.length);
});
test("a new session resets counters and stale export feedback", () => {
  const s = applyScenario("export-error"); beginSession(s);
  assert.equal(s.pending,null); assert.equal(s.exportError,null); assert.equal(s.session.rows.length,1);
});
test("quit stops recording updates and scenarios do not share mutable config", () => {
  const a = applyScenario("connected"), b = applyScenario("connected");
  a.config.max_hr = 200; assert.equal(b.config.max_hr,190);
  a.quit = true; const count = a.graph.length; sample(a,180); assert.equal(a.graph.length,count);
});
