"use strict";
// Run the actual app, with a manual monotonic clock and stalled HTTP polling.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
let now = 1000;
const nodes = new Map(), intervals = [], listeners = new Map();
class Element {
  constructor() { this.textContent = ""; this.options = [{}, {}]; }
  replaceChildren() {}
  append() {}
  setAttribute() {}
  removeAttribute() {}
  addEventListener() {}
}
const element = id => {
  if (!nodes.has(id)) nodes.set(id, new Element());
  return nodes.get(id);
};
const document = {hidden: true, getElementById: element,
  createElement: () => new Element(), addEventListener: (name, fn) => listeners.set(name, fn)};
const context = vm.createContext({document, console, AbortController,
  performance: {now: () => now}, setTimeout() {}, clearTimeout() {},
  setInterval(fn, duration) { intervals.push({fn, duration}); },
  fetch() { throw Error("hidden page must not poll"); },
  URL: {revokeObjectURL() {}}});
const run = code => vm.runInContext(code, context);
run(fs.readFileSync(path.resolve(__dirname, "../../ui/aa-live/app.js"), "utf8"));
const state = {instance_id: "instance", generation: 1, realtime: {
  mode: "OBSERVATION_ONLY", advice: null, strategy_eligible: false, advice_emitted: false,
  status_ttl_ms: 500, identity: {instance_id: "instance", generation: 1},
  reason: "NO_VERIFIED_TURN_EVIDENCE", source_host_age_ms: 85}};
const render = (value = state, started = now) => run(`renderRealtime(${JSON.stringify(value)}, ${started});`);

render();
assert.match(element("realtime-status").textContent, /可信的回合/);
assert.match(element("realtime-timing").textContent, /85 ms/);
assert.equal(intervals.length, 1);
assert.equal(intervals[0].duration, 50);
now = 1500;
intervals[0].fn();
assert.match(element("realtime-status").textContent, /已过期/);

// Slow response cannot mint a new validity window on arrival.
now = 2200;
render(state, 1500);
assert.match(element("realtime-status").textContent, /已过期/);

// Another instance, malformed TTL, or a claimed live action is rejected.
for (const change of [{identity: {instance_id: "other", generation: 1}},
                      {status_ttl_ms: 10000}, {advice: {action: "raise"}},
                      {strategy_eligible: true}]) {
  render({...state, realtime: {...state.realtime, ...change}});
  assert.match(element("realtime-status").textContent, /身份或格式无效/);
}

render();
listeners.get("visibilitychange")();
assert.match(element("realtime-status").textContent, /等待可信/);
assert.equal(run("realtimeExpiresAt"), null);
console.log("PASS: 8 AA realtime TTL, identity and no-advice scenarios");
