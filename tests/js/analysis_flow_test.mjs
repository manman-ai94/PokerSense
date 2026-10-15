// End-to-end interaction harness: the shipped form and the shipped analysis
// panel, driven together against a real backend, all the way to a kernel result.
//
// Read this as the product flow the review asked for:
//   fill the form → verify → hand the document to the analysis panel → the
//   panel really POSTs /api/analysis → the real spawned worker runs the real
//   kernel → the real report comes back from /api/status → the shipped renderer
//   shows it → change the input and the result is invalidated → a late report
//   for the old input is refused → re-verify and recompute for a new result.
//
// Usage: node analysis_flow_test.mjs <base-url>

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";
import { createDom, click, fire } from "./dom_stub.mjs";

const base = (process.argv[2] || "").replace(/\/$/, "");
if (!base.startsWith("http://127.0.0.1:")) {
  console.log(JSON.stringify({name: "base_url", ok: false, detail: base}));
  process.exit(2);
}
const here = dirname(fileURLToPath(import.meta.url));
const read = name => readFileSync(join(here, "..", "..", "ui", "aa-live", name),
                                  "utf8");
const checks = [];
const check = (name, ok, detail = "") => {
  const item = {name, ok: !!ok, detail: String(detail)};
  checks.push(item);
  console.log(JSON.stringify(item));
  return item;
};

const dom = createDom();
const {document, el} = dom;
const known = value => value !== null && value !== undefined && value !== "UNKNOWN";
const text = value => !known(value) ? "未知"
  : typeof value === "object" ? JSON.stringify(value) : String(value);
const calls = [];
async function fetchStub(path, options = {}) {
  calls.push({path, method: (options.method || "GET").toUpperCase()});
  const response = await fetch(base + path, options);
  const body = await response.text();
  return {ok: response.ok, status: response.status, text: async () => body,
          json: async () => JSON.parse(body)};
}
const downloads = [];
class BlobStub {
  constructor(parts, options = {}) { this.parts = parts; this.type = options.type; }
}
const statusData = {status: "IDLE", table_rules: {revision: 0}, generation: 0,
                    payload: null, issue_recording_available: false};
const KNOWN_LABELS = {check: "过牌", fold: "弃牌", call: "跟注", bet: "下注",
                      raise: "加注"};
const context = vm.createContext({
  document, el, text,
  translated: value => KNOWN_LABELS[String(value).toLowerCase()] || String(value),
  headers: {"X-AA-Live": "1"}, statusData, fetch: fetchStub, console,
  JSON, Number, String, Object, Array, Error, Math, Date, Map, Set, Boolean,
  setTimeout, clearTimeout, setInterval: () => 0, clearInterval: () => {},
  URL: {createObjectURL: blob => { downloads.push(blob); return "blob:stub"; },
        revokeObjectURL() {}},
  Blob: BlobStub, showDesk() {}, selectedReview: null, deskRequest: async () => null,
});
// analysis.js first: the panel owns the bindings the form writes into.
vm.runInContext(read("analysis.js"), context, {filename: "analysis.js"});
vm.runInContext(read("hand_input.js"), context, {filename: "hand_input.js"});
const run = expression => vm.runInContext(expression, context);
const feedback = () => el("hand-status").textContent;
const gaps = () => el("hand-gaps").textContent;
const results = () => el("analysis-results").textContent;
const analysisStatus = () => el("analysis-status").textContent;
const exportEnabled = () => el("analysis-export").disabled === false;

const SEATS = [
  {seat_id: 0, status: "ACTIVE", stack: "200", hand_committed: "20"},
  {seat_id: 1, status: "ACTIVE", stack: "200", hand_committed: "20"},
  {seat_id: 2, status: "ACTIVE", stack: "200", hand_committed: "20"},
  {seat_id: 3, status: "FOLDED", stack: "200", hand_committed: "10"},
  {seat_id: 4, status: "FOLDED", stack: "200", hand_committed: "10"},
  {seat_id: 5, status: "FOLDED", stack: "200", hand_committed: "10"}];
const HISTORY = [
  {actor: 1, kind: "bet", target: "20"}, {actor: 2, kind: "call", target: "0"}];
const RANGES = [
  {seat_id: 1, combo: "JhJd", weight: "1"}, {seat_id: 1, combo: "TcTd", weight: "3"},
  {seat_id: 2, combo: "7c7s", weight: "1"}, {seat_id: 2, combo: "KhTh", weight: "3"}];
const WEIGHTS = [
  {seat_id: 1, key: "check", weight: "1"}, {seat_id: 1, key: "bet", weight: "2"},
  {seat_id: 1, key: "call", weight: "9"}, {seat_id: 1, key: "fold", weight: "1"},
  {seat_id: 2, key: "check", weight: "1"}, {seat_id: 2, key: "call", weight: "9"},
  {seat_id: 2, key: "fold", weight: "1"}];

function fill(overrides = {}) {
  el("hand-hero").value = overrides.hero ?? "Qs Qd";
  el("hand-board").value = overrides.board ?? "2c 4d 7h 9s Jc";
  el("hand-hero-seat").value = overrides.heroSeat ?? "0";
  el("hand-order").value = overrides.order ?? "1,2,0";
  el("hand-pot").value = overrides.pot ?? "130";
  el("hand-targets").value = overrides.targets ?? "20,40,80";
  el("hand-max-agg").value = overrides.maxAgg ?? "2";
  el("hand-ended").checked = overrides.ended ?? true;
  el("hand-use-rules").checked = overrides.useRules ?? true;
  el("hand-fees").value = overrides.fees ?? "confirmed_zero";
  run(`handFillRows("seats", ${JSON.stringify(overrides.seats ?? SEATS)})`);
  run(`handFillRows("history", ${JSON.stringify(overrides.history ?? HISTORY)})`);
  run(`handFillRows("ranges", ${JSON.stringify(overrides.ranges ?? RANGES)})`);
  run(`handFillRows("weights", ${JSON.stringify(overrides.weights ?? WEIGHTS)})`);
}

let state = null;
async function refresh() {
  state = await (await fetch(base + "/api/status")).json();
  statusData.status = state.status;
  statusData.table_rules = state.table_rules;
  statusData.generation = state.generation;
  return state;
}
// Deliver whatever the panel would next render, exactly as app.js does.
async function deliver() {
  await refresh();
  run("renderAnalysis")(state.analysis, state);
  return state.analysis;
}
// Wait for one specific job to reach a terminal status. Matching on the job id
// matters: a status poll can still be serving the previous job's report.
async function settle(expectJob, limits = 200) {
  for (let index = 0; index < limits; index += 1) {
    await refresh();
    const job = expectJob ?? run("acceptedAnalysisId");
    const analysis = state.analysis;
    if (job !== null && analysis?.job_id === job && analysis.status !== "RUNNING"
        && analysis.status !== "IDLE") return analysis;
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  return state.analysis;
}
// The page's own polling loop calls renderAnalysis(state.analysis, state); this
// mirrors it so a late report for an invalidated input is really delivered.
// The compute button only clicks the panel's start button; its handler then
// cancels the old job and posts the new one. A status poll sent before that post
// lands can come back after it, naming the previous job, and the panel then
// drops the new one as replaced (seen on a loaded CI machine). So wait until the
// panel's own start request has finished, as a person would, before polling.
async function startSettled() {
  for (let index = 0; index < 400 && run("analysisBusy"); index += 1) {
    await new Promise(resolve => setTimeout(resolve, 50));
  }
}
async function pollRender(expectJob) {
  await startSettled();
  let last = null;
  for (let index = 0; index < 200; index += 1) {
    last = await deliver();
    const job = expectJob ?? run("acceptedAnalysisId");
    if (run("acceptedAnalysisId") !== null && last?.job_id === job
        && last.status !== "RUNNING" && last.status !== "IDLE") return last;
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  return last;
}

check("both_shipped_scripts_loaded",
      run("handWired") === true && typeof run("invalidateAnalysis") === "function"
      && typeof run("handCompute") === "function",
      "hand_input.js + analysis.js in one global scope");
check("form_starts_with_no_verified_input",
      run("handBuilt") === null && run("handExpectedInput") === null
      && run("acceptedAnalysisId") === null,
      "nothing is computed from a blank form");

const rules = await (await fetch(base + "/api/rules")).json();
statusData.table_rules = {revision: rules.revision};
check("saved_table_rules_are_ready", rules.conditional_analysis_ready === true,
      `revision=${String(rules.revision).slice(0, 12)}`);

// --- 1. input → kernel → result -------------------------------------------
fill();
await click(el("hand-build"));
check("the_form_accepts_a_filled_ended_hand", run("handBuilt") !== null,
      feedback().slice(0, 70));
const firstInputSha = run("handExpectedInput");
await click(el("hand-compute"));
check("compute_binds_the_form_identity_before_the_request",
      run("analysisExpectedInput") === firstInputSha
      && run("analysisDraftSource")?.kind === "hand_input_form"
      && el("analysis-input").value.includes("\"manual_hypothesis\""),
      `expected=${String(run("analysisExpectedInput")).slice(0, 12)} `
      + `draft=${run("analysisDraftSource")?.kind} `
      + `status=${analysisStatus().slice(0, 40)}`);
await new Promise(resolve => setTimeout(resolve, 600));
check("compute_hands_the_document_to_the_analysis_panel",
      run("acceptedAnalysisId") !== null,
      `job=${String(run("acceptedAnalysisId")).slice(0, 12)} `
      + `status=${analysisStatus().slice(0, 60)}`);
check("the_panel_really_posted_the_analysis",
      calls.some(call => call.path === "/api/analysis" && call.method === "POST"),
      `${calls.filter(c => c.path === "/api/analysis").length} posts`);
const firstReport = await pollRender();
check("the_real_kernel_returned_a_complete_result",
      firstReport?.status === "COMPLETE"
      && firstReport?.result?.root_actions?.length > 0,
      `status=${firstReport?.status} error=${firstReport?.error}`);
check("the_result_is_rendered_from_the_real_report",
      results().includes("条件净 EV") && exportEnabled()
      && results().includes("跟注"),
      results().replace(/\s+/g, " ").slice(0, 90));
check("the_report_input_matches_the_verified_form_input",
      run("analysisBinding")?.input_sha256 === firstReport?.input_sha256
      && run("analysisBinding")?.expected_input_sha256 === firstInputSha,
      `job=${String(run("acceptedAnalysisId")).slice(0, 12)}`);
// The form hashes with the same canonical JSON the panel's backend uses, so the
// identity the human verified and the identity the report was computed from are
// the same string, not two hashes that merely both exist.
check("the_form_identity_and_the_backend_identity_agree",
      run("analysisBinding")?.expected_input_sha256
      === run("analysisBinding")?.input_sha256,
      `form=${String(run("analysisBinding")?.expected_input_sha256).slice(0, 12)} `
      + `backend=${String(run("analysisBinding")?.input_sha256).slice(0, 12)}`);
check("nothing_claims_this_is_live_advice",
      results().includes("不是整手收益") && firstReport.strategy_eligible === false
      && firstReport.advice_emitted === false,
      "manual hypothesis only");
const firstEvs = results();


// --- 2. the export carries the form identity ------------------------------
await click(el("analysis-export"));
const exported = downloads[0] && JSON.parse(downloads[0].parts.join(""));
check("the_export_carries_the_form_input_identity",
      exported?.draft_source?.kind === "hand_input_form"
      && exported?.draft_source?.input_sha256 === firstInputSha
      && exported?.report?.job_id === run("acceptedAnalysisId"),
      `sha=${String(exported?.draft_source?.input_sha256).slice(0, 12)}`);

// --- 3. changing the input invalidates the shown result -------------------
await fire(el("hand-hero"), "input");
check("changing_the_form_clears_the_rendered_result",
      results() === "" && exportEnabled() === false
      && analysisStatus().includes("失效"),
      analysisStatus().slice(0, 50));
check("changing_the_form_also_drops_the_panel_identity",
      run("analysisExpectedInput") === null, "binding cleared");

// --- 4. a late report for the old input must not be displayed -------------
// A different pot, so the abandoned input is not the same document as step 1.
const SEATS_RAISED = SEATS.map(row =>
  row.status === "ACTIVE" ? {...row, hand_committed: "40"} : row);
await new Promise(resolve => setTimeout(resolve, 400));
fill({seats: SEATS_RAISED, pot: "190"});
await click(el("hand-build"));
const lateInputSha = run("handExpectedInput");
check("the_abandoned_input_is_a_different_document",
      run("handBuilt") !== null && lateInputSha !== firstInputSha,
      String(lateInputSha).slice(0, 12));
await click(el("hand-compute"));
await new Promise(resolve => setTimeout(resolve, 400));
await refresh();
const lateJob = run("acceptedAnalysisId");
check("the_second_analysis_started",
      lateJob !== null && results() === "" && exportEnabled() === false,
      `job=${String(lateJob).slice(0, 12)} status=${state.analysis?.status}`);
// The human edits the form while the worker is still running.
await fire(el("hand-hero"), "input");
check("editing_during_a_running_analysis_clears_it",
      run("acceptedAnalysisId") === null && results() === ""
      && exportEnabled() === false,
      analysisStatus().slice(0, 50));
const late = await settle(lateJob);
check("the_late_report_really_was_for_the_abandoned_input",
      late?.job_id === lateJob && late?.input_sha256
      && late.input_sha256 !== firstReport.input_sha256,
      `${String(late?.input_sha256).slice(0, 12)} ≠ ${String(firstReport.input_sha256).slice(0, 12)}`);
// Deliver it exactly the way the page's polling loop would.
await deliver();
check("the_late_report_is_refused_not_displayed",
      results() === "" && exportEnabled() === false
      && run("analysisReport") === null && run("acceptedAnalysisId") === null,
      `late=${late?.status} rendered=${results().length} chars`);

// --- 5. re-verify and recompute: a new input gives a new result -----------
fill({hero: "2h 3d"});
await click(el("hand-build"));
const secondInputSha = run("handExpectedInput");
check("the_changed_hand_verifies_as_a_different_input",
      run("handBuilt") !== null && secondInputSha !== firstInputSha,
      `${String(firstInputSha).slice(0, 8)} → ${String(secondInputSha).slice(0, 8)}`);
await click(el("hand-compute"));
const secondReport = await pollRender();
check("recomputing_produces_a_result_for_the_new_input",
      secondReport?.status === "COMPLETE" && results().includes("条件净 EV")
      && exportEnabled(),
      `status=${secondReport?.status}`);
check("the_new_result_differs_from_the_first",
      results() !== firstEvs && secondReport.input_sha256 !== firstReport.input_sha256,
      "different cards, different numbers");
check("the_second_report_is_bound_to_the_second_input",
      run("analysisBinding").expected_input_sha256 === secondInputSha,
      String(run("analysisBinding").expected_input_sha256).slice(0, 12));

// --- 6. an out-of-band identity change invalidates an accepted result -----
run("analysisExpectedInput = 'someone-else'");
run("renderAnalysis")(secondReport, state);
check("a_result_whose_input_identity_moved_is_invalidated",
      results() === "" && exportEnabled() === false
      && analysisStatus().includes("身份"),
      analysisStatus().slice(0, 50));

check("no_innerhtml_used", dom.state.innerHTMLWrites === 0,
      `writes=${dom.state.innerHTMLWrites}`);
check("only_the_real_endpoints_were_called",
      calls.every(call => call.path.startsWith("/api/")
                  || call.path.startsWith("/hand_input")),
      `${[...new Set(calls.map(c => c.path))].join(",")}`);

const failed = checks.filter(item => !item.ok);
console.log(JSON.stringify({
  name: "verdict", ok: failed.length === 0, passed: checks.length - failed.length,
  failed: failed.length, requests: calls.length, base,
}));
process.exit(failed.length === 0 ? 0 : 1);
