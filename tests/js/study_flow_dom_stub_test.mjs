// Real interaction test for ui/aa-live/study.js against a running backend.
//
// The shipped study.js file is evaluated unchanged inside a minimal DOM stub,
// then driven through the product flow: load the SYNTHETIC example, read the
// numbers, save an independent record, list records, reopen the same record,
// supersede an in-flight open with a later one, and hit the rejection path.
//
// Usage: node study_flow_dom_stub_test.mjs <base-url>
// Output: one JSON object per line; the last line has ok/exiting verdicts.

import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const base = (process.argv[2] || "").replace(/\/$/, "");
const recordsDir = process.argv[3] || "";
if (!base.startsWith("http://127.0.0.1:")) {
  console.log(JSON.stringify({name: "base_url", ok: false, detail: base}));
  process.exit(2);
}
const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..", "..");
const source = readFileSync(join(repo, "ui", "aa-live", "study.js"), "utf8");
const checks = [];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const check = (name, ok, detail = "") => checks.push({name, ok: !!ok, detail: String(detail)});
const texts = {};

let innerHTMLWrites = 0;
const elements = new Map();
function makeElement(tag) {
  const node = {
    tagName: tag, children: [], attributes: {}, handlers: {},
    _text: "", className: "", hidden: false, disabled: false, value: "",
    checked: false, open: false, type: "",
    get textContent() {
      return this._text + this.children.map(child => child.textContent).join("");
    },
    set textContent(value) { this._text = String(value); this.children = []; },
    append(...nodes) { this._text = ""; for (const item of nodes) this.children.push(item); },
    replaceChildren(...nodes) { this._text = ""; this.children = []; for (const item of nodes) this.children.push(item); },
    addEventListener(type, handler) { (this.handlers[type] ||= []).push(handler); },
    setAttribute(name, value) { this.attributes[name] = value; },
    querySelectorAll() { return []; }
  };
  Object.defineProperty(node, "innerHTML", {
    get() { return "<stub>"; },
    set() { innerHTMLWrites += 1; }
  });
  return node;
}
const document = {
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, makeElement("div"));
    return elements.get(id);
  },
  createElement(tag) { return makeElement(tag); }
};
const el = id => document.getElementById(id);
const labels = {fold:"弃牌", check:"过牌", call:"跟注", bet:"下注", raise:"加注"};
const known = value => value !== null && value !== undefined && value !== "UNKNOWN";
const text = value => !known(value) ? "未知" : typeof value === "object" ? JSON.stringify(value) : String(value);

const calls = [];
const delays = [];
let inFlight = 0;
async function fetchStub(path, options = {}) {
  calls.push({path, method: (options.method || "GET").toUpperCase()});
  inFlight += 1;
  const pending = delays.find(item => !item.used && path.includes(item.match));
  const controller = new AbortController();
  let timer;
  try {
    if (pending) { pending.used = true; await sleep(pending.ms); }
    timer = setTimeout(() => controller.abort(), 10000);
    const response = await fetch(base + path, {...options, signal: controller.signal});
    const body = await response.text();
    return {ok: response.ok, status: response.status, text: async () => body,
            json: async () => JSON.parse(body)};
  } finally { clearTimeout(timer); inFlight -= 1; }
}
const context = vm.createContext({
  document, el, text, labels, headers: {"X-AA-Live": "1"}, statusData: {},
  fetch: fetchStub, console, setTimeout, clearTimeout, JSON, Number, String, Math,
  Array, Object, Promise, Error, encodeURIComponent, Date
});
vm.runInContext(source, context, {filename: "study.js"});
const run = expression => vm.runInContext(expression, context);
const click = async id => {
  for (const handler of el(id).handlers.click || []) await handler({});
};
const fire = async (id, type, event = {}) => {
  let ran = 0;
  for (const handler of el(id).handlers[type] || []) { ran += 1; await handler(event); }
  return ran;
};
const recordText = () => el("study-content").textContent;
const feedback = () => el("study-feedback").textContent;
const tagged = () => el("study-source-tag").textContent;

check("wiring_ran", run("studyWired") === true, "studyWired");
// Wiring loads the example list, then the record list, over HTTP; on a busy
// machine that is not done in any fixed time, so wait for both (at most 10 s).
const wiringDone = () => el("study-example").children.length > 0
  && calls.some(call => call.path === "/api/study/records") && inFlight === 0;
for (const until = Date.now() + 10000; !wiringDone() && Date.now() < until;) await sleep(20);
check("examples_loaded",
      el("study-example").children.length === 1
      && el("study-example").children[0].textContent.includes("合成示例")
      && el("study-example").children[0].textContent.includes("非真实牌局"),
      el("study-example").textContent.slice(0, 80));
check("example_marked_unavailable_never_selected", el("study-load").disabled === false,
      "load enabled for an available example");

el("study-example").value = "range-sensitivity-synthetic-v1";
await click("study-load");
const preview = recordText();
check("preview_is_labeled_synthetic", preview.includes("合成研究示例 · 非本桌 · 非真实对局"),
      preview.slice(0, 40));
check("preview_shows_three_factors",
      ["×0.5", "×1", "×2"].every(item => preview.includes(item)), "factor labels");
check("preview_shows_readable_and_exact_values",
      preview.includes("-0.1607") && preview.includes("-30444/189457")
      && preview.includes("35.6915") && preview.includes("54.6486")
      && preview.includes("筹码"), "decimals and exact fractions");
check("preview_shows_baseline_columns",
      preview.includes("差 vs 手工参考") && preview.includes("差 vs 过牌/弃牌")
      && preview.includes("差 vs 过牌/跟注"), "baseline columns");
check("preview_shows_main_paths", preview.includes("主要终局路径贡献差")
      && preview.includes("仅冻结策略侧可达"), "path rows");
check("preview_shows_missing_items", preview.includes("缺失项") &&
      preview.includes("未绑定任何观测牌局记录"), "missing items");
check("preview_shows_fixed_claims",
      preview.includes("固定说明") && preview.includes("不是归一化之后的概率倍数"),
      "fixed claims");
check("preview_not_yet_saved", tagged().includes("未保存"), tagged());
check("raw_identity_exposed",
      el("study-raw").textContent.includes("\"bound_record_id\": null")
      && el("study-raw").textContent.includes("SYNTHETIC_STUDY_EXAMPLE"),
      "raw pre");

await click("study-save");
const firstId = (feedback().match(/\d{8}T\d{6}-[a-f0-9]{12}/) || [""])[0];
const firstContent = recordText();
check("saved_as_independent_record", !!firstId
      && feedback().includes("未绑定任何观测牌局"), feedback().slice(0, 80));
check("saved_status_label", tagged().includes("当前版本"), tagged());
check("saved_record_listed", [...el("study-record-select").children]
      .some(option => option.value === firstId), firstId);

await click("study-record-refresh");
await click("study-save");
const secondId = [...el("study-record-select").children]
  .map(option => option.value).filter(id => id && id !== firstId)[0];
check("two_records_available", !!firstId && !!secondId
      && el("study-record-select").children.length >= 2, `${firstId} / ${secondId}`);

el("study-record-select").value = firstId;
await click("study-record-open");
const reopened = recordText();
const reopenedState = run("({id: studyCurrent.record_id, status: studyCurrent.content_status})");
check("reopen_identical_content", reopened === firstContent, "content equality");
check("reopen_identical_identity", reopenedState.id === firstId
      && reopenedState.status === "CURRENT", JSON.stringify(reopenedState));
check("reopen_keeps_label", tagged().includes("当前版本"), tagged());

delays.push({match: `/api/study/records/${firstId}`, ms: 600, used: false});
const stale = run(`studyOpenRecord(${JSON.stringify(firstId)})`);
await sleep(60);
const fresh = run(`studyOpenRecord(${JSON.stringify(secondId)})`);
await Promise.all([stale, fresh]);
await sleep(700);
const after = run("({id: studyCurrent.record_id, status: studyCurrent.content_status})");
check("late_response_does_not_overwrite", after.id === secondId,
      `current=${after.id} stale=${firstId} fresh=${secondId}`);
check("late_response_kept_the_newer_label", tagged().includes("当前版本")
      && recordText().includes(secondId), tagged());

await run(`studyLoadExampleFor(${JSON.stringify("not-registered")})`);
check("unknown_example_is_rejected", feedback().includes("示例未载入")
      && el("study-content").hidden === true, feedback().slice(0, 60));
await run(`studyOpenRecord(${JSON.stringify("20200101T000000-aaaaaaaaaaaa")})`);
check("foreign_record_id_is_rejected", feedback().includes("记录未打开"),
      feedback().slice(0, 60));

check("no_innerhtml_used", innerHTMLWrites === 0, `writes=${innerHTMLWrites}`);
check("no_vision_or_capture_requests",
      calls.every(call => call.path.startsWith("/api/study/")
        || call.path.startsWith("/api/study/examples")),
      `${calls.length} study calls`);
check("post_carries_explicit_header",
      calls.filter(call => call.method === "POST").length > 0, "POST seen");

// --- interaction invalidation: select change, panel close, INVALID results ---
check("target_identity_helper",
      run(`studyAcceptsTarget("A", "A")`) === true
      && run(`studyAcceptsTarget("A", "B")`) === false, "studyAcceptsTarget");

el("study-record-select").value = firstId;
await run(`studyOpenRecord(${JSON.stringify(firstId)})`);
const contextTokens = ["Qs", "2c", "加注到 80", "跟注", "公开历史", "本街追加"];
check("experiment_context_rendered",
      contextTokens.every(token => recordText().includes(token)),
      `missing=${contextTokens.filter(token => !recordText().includes(token)).join(",")}`);

delays.push({match: `/api/study/records/${firstId}`, ms: 600, used: false});
const pendingOpen = run(`studyOpenRecord(${JSON.stringify(firstId)})`);
await sleep(60);
el("study-record-select").value = secondId;
await fire("study-record-select", "change", {});
await pendingOpen;
await sleep(700);
check("selection_change_invalidates_a_late_open",
      run("studyCurrent") === null && recordText() === "",
      `current=${JSON.stringify(run("studyCurrent && studyCurrent.record_id"))}`);
check("selection_change_disables_save", el("study-save").disabled === true,
      String(el("study-save").disabled));

el("study-record-select").value = firstId;
delays.push({match: `/api/study/records/${firstId}`, ms: 600, used: false});
const pendingClose = run(`studyOpenRecord(${JSON.stringify(firstId)})`);
await sleep(60);
el("study-tools").open = false;
await fire("study-tools", "toggle", {});
await pendingClose;
await sleep(700);
check("panel_close_invalidates_a_late_open",
      run("studyCurrent") === null && el("study-content").hidden === true,
      `hidden=${el("study-content").hidden}`);

if (recordsDir) {
  const recordFile = join(recordsDir, "study-records", firstId, "record.json");
  const document = JSON.parse(readFileSync(recordFile, "utf8"));
  document.view.factors[1].deltas.vs_manual_reference.display = "999999.0000";
  writeFileSync(recordFile, JSON.stringify(document, null, 2) + "\n", "utf8");
  el("study-record-select").value = firstId;
  const before = feedback();
  await run(`studyOpenRecord(${JSON.stringify(firstId)})`);
  const shown = recordText();
  check("tampered_record_is_not_rendered_as_valid",
        !shown.includes("999999") && !shown.includes("已重开")
        && el("study-save").disabled === true, shown.slice(0, 60));
  check("tampered_record_reports_an_invalid_or_history_state",
        /无效|历史/.test(feedback()) && feedback() !== before,
        feedback().slice(0, 80));
  check("tampered_record_has_no_view",
        run("studyCurrent") === null
        || run("studyCurrent.view") === null, "view withheld");
} else {
  check("tampered_record_is_not_rendered_as_valid", false,
        "records dir not provided");
  check("tampered_record_reports_an_invalid_or_history_state", false,
        "records dir not provided");
  check("tampered_record_has_no_view", false, "records dir not provided");
}

const failed = checks.filter(item => !item.ok);
for (const item of checks) console.log(JSON.stringify(item));
console.log(JSON.stringify({
  name: "verdict", ok: failed.length === 0, passed: checks.length - failed.length,
  failed: failed.length, requests: calls.length, base
}));
process.exit(failed.length === 0 ? 0 : 1);
