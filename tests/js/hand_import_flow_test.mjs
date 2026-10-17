// U1-R2 harness: the import/batch-fill entry points, the unknown/provenance
// boundary and the triple identity cross-check - all with the shipped scripts
// unchanged, in a DOM stub, against the real backend.
//
// The product flow it drives, in the reviewer's words:
//   compute hand A -> import an incomplete hand B -> A must not be reused ->
//   the human fills and confirms B -> compute B for real.
// Plus: out-of-order import responses, an edit or a clear during an import, a
// failed import, CSV replacement, unknown vs confirmed-empty history, the
// original candidate and the source, and a result whose identity does not match.
//
// Usage: node hand_import_flow_test.mjs <base-url> <record-a> <record-b>

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";
import { createDom, click, fire } from "./dom_stub.mjs";

const base = (process.argv[2] || "").replace(/\/$/, "");
const RECORD_A = process.argv[3] || "";
const RECORD_B = process.argv[4] || "";
const RECORD_C = process.argv[5] || "";
if (!base.startsWith("http://127.0.0.1:") || !RECORD_A || !RECORD_B
    || !RECORD_C) {
  console.log(JSON.stringify({name: "arguments", ok: false, detail: base}));
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
const hooks = {delay: {}, rewrite: {}};
async function fetchStub(path, options = {}) {
  calls.push({path, method: (options.method || "GET").toUpperCase()});
  if (hooks.delay[path]) await new Promise(r => setTimeout(r, hooks.delay[path]));
  const response = await fetch(base + path, options);
  const body = await response.text();
  const rewrite = hooks.rewrite[path];
  return {ok: response.ok, status: response.status, text: async () => body,
          json: async () => rewrite ? rewrite(JSON.parse(body)) : JSON.parse(body)};
}
const downloads = [];
class BlobStub {
  constructor(parts, options = {}) { this.parts = parts; this.type = options.type; }
}
const KNOWN_LABELS = {check: "过牌", fold: "弃牌", call: "跟注", bet: "下注",
                      raise: "加注"};
const statusData = {status: "IDLE", table_rules: {revision: 0}, generation: 0,
                    payload: null, issue_recording_available: false};
const sandbox = {
  document, el, text,
  translated: value => KNOWN_LABELS[String(value).toLowerCase()] || String(value),
  headers: {"X-AA-Live": "1"}, statusData, fetch: fetchStub, console,
  JSON, Number, String, Object, Array, Error, Math, Date, Map, Set, Boolean,
  setTimeout, clearTimeout, setInterval: () => 0, clearInterval: () => {},
  URL: {createObjectURL: blob => { downloads.push(blob); return "blob:stub"; },
        revokeObjectURL() {}},
  Blob: BlobStub, showDesk() {}, selectedReview: null, deskRequest: async () => null,
};
const context = vm.createContext(sandbox);
vm.runInContext(read("analysis.js"), context, {filename: "analysis.js"});
vm.runInContext(read("hand_input.js"), context, {filename: "hand_input.js"});
const run = expression => vm.runInContext(expression, context);
// Feature probes: this harness also has to run against an older head to show a
// genuine red, so a function that does not exist yet must fail a check instead
// of aborting the whole run.
const exposed = name => run(`typeof ${name}`) !== "undefined";
const callSourceChanged = id => {
  if (!exposed("handSourceChanged")) return false;
  run(`handSourceChanged(${JSON.stringify(id)})`);
  return true;
};
const feedback = () => el("hand-status").textContent;
const gaps = () => el("hand-gaps").textContent;
const results = () => el("analysis-results").textContent;
const analysisStatus = () => el("analysis-status").textContent;
// An import voids the shown result at once with HAND_VOIDED; 350 ms later the
// debounced cancel it scheduled replaces that line with CANCELLED_LINE. Which
// one is showing depends on how long the import's fetch took (a slow Windows
// runner sees the second), so accept exactly those two void lines and nothing
// else: any other status means the result was not voided by the import.
const CANCELLED_LINE = "输入已变更或分析已取消，请重新计算。";
const voidedStatus = () => exposed("HAND_VOIDED")
  && [run("HAND_VOIDED"), CANCELLED_LINE].includes(analysisStatus());
const exportEnabled = () => el("analysis-export").disabled === false;
const analysisPosts = () => calls.filter(call => call.path === "/api/analysis"
                                          && call.method === "POST").length;
const select = record => { run(`selectedReview = ${JSON.stringify(record)}`); };

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

// Invoke the shipped handlers synchronously, the way a keystroke would.
const touch = (node, type = "input") => {
  for (const handler of node.handlers[type] || []) handler({});
};
function typeHand(overrides = {}) {
  el("hand-hero").value = overrides.hero ?? "Qs Qd";
  el("hand-board").value = overrides.board ?? "2c 4d 7h 9s Jc";
  el("hand-hero-seat").value = overrides.heroSeat ?? "0";
  el("hand-order").value = overrides.order ?? "1,2,0";
  el("hand-pot").value = overrides.pot ?? "130";
  el("hand-targets").value = overrides.targets ?? "20,40,80";
  el("hand-max-agg").value = overrides.maxAgg ?? "2";
  el("hand-ended").checked = overrides.ended ?? true;
  el("hand-use-rules").checked = overrides.useRules ?? true;
  el("hand-no-history").checked = false;
  el("hand-fees").value = overrides.fees ?? "confirmed_zero";
  run(`handFillRows("seats", ${JSON.stringify(overrides.seats ?? SEATS)})`);
  run(`handFillRows("history", ${JSON.stringify(overrides.history ?? HISTORY)})`);
  run(`handFillRows("ranges", ${JSON.stringify(overrides.ranges ?? RANGES)})`);
  run(`handFillRows("weights", ${JSON.stringify(overrides.weights ?? WEIGHTS)})`);
  // The human typed the cards, so the shipped edit handlers really run.
  touch(el("hand-hero"));
}
const rowCount = block => run(`handRows("${block}").length`);
const fieldValue = id => el(id).value;

let state = null;
async function refresh() {
  state = await (await fetch(base + "/api/status")).json();
  statusData.status = state.status;
  statusData.table_rules = state.table_rules;
  statusData.generation = state.generation;
  return state;
}
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
    await refresh();
    last = state.analysis;
    run("renderAnalysis")(last, state);
    const job = expectJob ?? run("acceptedAnalysisId");
    if (run("acceptedAnalysisId") !== null && last?.job_id === job
        && last.status !== "RUNNING" && last.status !== "IDLE") return last;
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  return last;
}
const recordRef = issueId => ({
  issue: {issue_id: issueId, saved_at: "2026-09-16T10:15:30+08:00",
          preview_sha256: "0".repeat(64)}});

// --- 0. wiring -----------------------------------------------------------
check("both_shipped_scripts_loaded",
      run("handWired") === true && exposed("handImportRecord")
      && exposed("handSourceChanged") && exposed("handMarkRevised"),
      "analysis.js + hand_input.js in one global scope");
const rules = await (await fetch(base + "/api/rules")).json();
statusData.table_rules = {revision: rules.revision};
check("saved_table_rules_are_ready", rules.conditional_analysis_ready === true,
      `revision=${String(rules.revision).slice(0, 12)}`);

// --- 1. compute hand A for real -----------------------------------------
typeHand();
await click(el("hand-build"));
check("hand_a_verifies", run("handBuilt") !== null, feedback().slice(0, 60));
await click(el("hand-compute"));
const reportA = await pollRender();
check("hand_a_computes_and_renders",
      reportA?.status === "COMPLETE" && results().includes("条件净 EV")
      && exportEnabled(), `status=${reportA?.status}`);
const postsBefore = analysisPosts();
const draftAfterA = run("analysisDraftSource");

// --- 2. import an INCOMPLETE hand B -------------------------------------
select(recordRef(RECORD_B));
const importedB = await run("handImportRecord()");
check("the_incomplete_import_is_accepted_as_candidates",
      importedB !== null && importedB.gaps.length >= 1,
      `gaps=${(importedB?.gaps || []).length}`);
check("the_import_clears_the_previous_hand",
      fieldValue("hand-hero") === "2h 3d" && fieldValue("hand-board") === ""
      && fieldValue("hand-hero-seat") === "" && fieldValue("hand-order") === ""
      && fieldValue("hand-pot") === "" && el("hand-ended").checked === false
      && el("hand-fees").value === "unknown" && rowCount("seats") === 0
      && rowCount("history") === 0 && rowCount("ranges") === 0
      && rowCount("weights") === 0,
      `hero=${fieldValue("hand-hero")} board=${fieldValue("hand-board")} `
      + `seats=${rowCount("seats")} ranges=${rowCount("ranges")} `
      + `ended=${el("hand-ended").checked} fees=${el("hand-fees").value}`);
check("the_import_voids_the_verified_receipt",
      run("handBuilt") === null && run("handExpectedInput") === null
      && el("hand-compute").disabled === true,
      `built=${run("handBuilt")}`);
check("the_import_voids_the_shown_result",
      results() === "" && exportEnabled() === false
      && voidedStatus(), analysisStatus().slice(0, 50));
check("the_import_reports_the_unknowns_it_could_not_fill",
      gaps().includes("需要人工补录") && gaps().includes("没有可用候选"),
      gaps().replace(/\s+/g, " ").slice(0, 100));

// --- 3. the old receipt cannot be computed ------------------------------
await click(el("hand-compute"));
check("the_old_receipt_cannot_be_computed_again",
      analysisPosts() === postsBefore && run("handBuilt") === null
      && run("handExpectedInput") === null
      && el("hand-compute").disabled === true,
      `posts=${analysisPosts()} before=${postsBefore} built=${run("handBuilt")}`);

// --- 4. fill in and confirm B, then compute B for real -------------------
typeHand({hero: "2h 3d"});
await click(el("hand-build"));
check("hand_b_verifies_after_the_human_fills_it", run("handBuilt") !== null,
      feedback().slice(0, 70));
await click(el("hand-compute"));
const draftB = run("analysisDraftSource");
const reportB = await pollRender();
check("hand_b_computes_for_real",
      reportB?.status === "COMPLETE" && results().includes("条件净 EV")
      && exportEnabled(), `status=${reportB?.status}`);
check("hand_b_is_a_different_input_from_hand_a",
      run("analysisBinding").input_sha256 !== (draftAfterA && draftAfterA.input_sha256),
      `${String(run("analysisBinding").input_sha256).slice(0, 12)}`);
check("hand_b_identity_matches_the_backend",
      run("analysisBinding").expected_input_sha256
      === run("analysisBinding").input_sha256
      && run("analysisBinding").input_sha256 === reportB.input_sha256,
      "form == accepted == report");
check("the_computation_carries_the_imported_source",
      draftB?.form_source?.issue_id === RECORD_B
      && draftB?.form_source?.revised_by_human === true
      && draftB.provenance["hand-hero"].provenance === "human_confirmed"
      && Object.keys(draftB?.provenance || {}).length > 0,
      `source=${draftB?.form_source?.issue_id}/${draftB?.form_source?.revised_by_human}`);
await click(el("analysis-export"));
const exported = downloads[0] && JSON.parse(downloads[0].parts.join(""));
check("the_export_reports_the_form_source_and_provenance",
      exported?.draft_source?.form_source?.issue_id === RECORD_B
      && exported?.draft_source?.form_source?.revised_by_human === true
      && exported?.draft_source?.provenance?.seats?.provenance === "human_confirmed",
      `keys=${Object.keys(exported?.draft_source?.provenance || {}).join(",")}`);

// --- 5. provenance from a structured snapshot ---------------------------
select(recordRef(RECORD_A));
const importedA = await run("handImportRecord()");
check("the_complete_import_fills_the_evidenced_fields",
      importedA !== null && fieldValue("hand-hero") !== ""
      && rowCount("seats") > 0,
      `hero=${fieldValue("hand-hero")} seats=${rowCount("seats")}`);
const facts = run("handFacts()");
check("imported_values_keep_their_observed_provenance",
      facts.hero_cards.provenance === "observed"
      && facts.seats.provenance === "observed"
      && facts.hero_cards.candidate !== null,
      `hero=${facts.hero_cards.provenance} seats=${facts.seats.provenance}`);
check("an_untouched_unknown_stays_unknown",
      facts.history.provenance === "unknown"
      && facts.history.value === null,
      `history=${facts.history.provenance}`);
await fire(el("hand-hero"), "input");
const edited = run("handFacts()");
check("editing_an_imported_value_confirms_it_and_keeps_the_candidate",
      edited.hero_cards.provenance === "human_confirmed"
      && edited.hero_cards.candidate !== null,
      `prov=${edited.hero_cards.provenance} cand=${edited.hero_cards.candidate !== null}`);

// --- 6. unknown vs confirmed-empty history ------------------------------
typeHand({history: []});
el("hand-no-history").checked = false;
const unknownHistory = run("handFacts()");
check("an_empty_history_is_unknown_not_confirmed_empty",
      unknownHistory.history.provenance === "unknown"
      && unknownHistory.history.value === null,
      `prov=${unknownHistory.history.provenance}`);
el("hand-no-history").checked = true;
const confirmedEmpty = run("handFacts()");
check("the_explicit_confirmation_makes_it_an_empty_history",
      confirmedEmpty.history.provenance === "human_confirmed"
      && Array.isArray(confirmedEmpty.history.value)
      && confirmedEmpty.history.value.length === 0,
      `prov=${confirmedEmpty.history.provenance}`);
el("hand-no-history").checked = false;

// --- 7. an empty seat id is refused, never read as seat 0 ---------------
typeHand({seats: [{seat_id: "", status: "ACTIVE", stack: "200",
                   hand_committed: "20"}, ...SEATS.slice(1)]});
const postsBeforeSeat = analysisPosts();
await click(el("hand-build"));
check("a_blank_seat_id_is_refused_in_chinese",
      feedback().includes("座位号") && run("handBuilt") === null
      && analysisPosts() === postsBeforeSeat,
      feedback().slice(0, 70));

// --- 8. CSV replacement voids the receipt too ---------------------------
typeHand();
await click(el("hand-build"));
check("hand_a_verifies_again_for_the_csv_case", run("handBuilt") !== null,
      feedback().slice(0, 50));
el("hand-csv-target").value = "seats";
el("hand-csv").value = SEATS.map(row => [row.seat_id, row.status, row.stack,
                                         row.hand_committed].join(",")).join("\n");
await click(el("hand-csv-apply"));
check("a_csv_apply_voids_the_receipt",
      run("handBuilt") === null && el("hand-compute").disabled === true
      && rowCount("seats") === SEATS.length,
      `rows=${rowCount("seats")}`);

// --- 9. an import that lands after an edit must not overwrite it --------
typeHand();
select(recordRef(RECORD_A));
hooks.delay[`/api/hand-input/facts/${RECORD_A}`] = 700;
const lateImport = run("handImportRecord()");
await new Promise(resolve => setTimeout(resolve, 120));
await fire(el("hand-hero"), "input");
el("hand-hero").value = "Ah Ad";
delete hooks.delay[`/api/hand-input/facts/${RECORD_A}`];
await lateImport;
check("an_import_landing_after_an_edit_is_dropped",
      fieldValue("hand-hero") === "Ah Ad" && run("handBuilt") === null,
      `hero=${fieldValue("hand-hero")}`);

// --- 10. an import that lands after a clear must not restore anything ---
typeHand();
const clearedImport = run("handImportRecord()");
await new Promise(resolve => setTimeout(resolve, 120));
await click(el("hand-clear"));
await clearedImport;
check("an_import_landing_after_a_clear_is_dropped",
      fieldValue("hand-hero") === "" && rowCount("seats") === 0
      && run("handBuilt") === null,
      `hero="${fieldValue("hand-hero")}" seats=${rowCount("seats")}`);

// --- 11. a failed import does not restore the old state -----------------
typeHand();
await click(el("hand-build"));
await click(el("hand-compute"));
const reportBeforeFailure = await pollRender();
check("the_hand_is_computed_before_the_failed_import",
      reportBeforeFailure?.status === "COMPLETE", `status=${reportBeforeFailure?.status}`);
select(recordRef("20260101T000000-ffffffffffff"));
const failedImport = await run("handImportRecord()");
check("a_failed_import_leaves_nothing_of_the_previous_hand",
      failedImport === null && feedback().includes("带入失败")
      && run("handBuilt") === null && results() === ""
      && exportEnabled() === false && fieldValue("hand-hero") === ""
      && rowCount("seats") === 0 && voidedStatus(),
      feedback().slice(0, 60));

// --- 12. changing the selected record voids the setup ------------------
// (a) facts that came from a record cannot survive a move to another record.
select(recordRef(RECORD_A));
check("record_a_is_imported", (await run("handImportRecord()")) !== null
      && fieldValue("hand-hero") !== "", `hero=${fieldValue("hand-hero")}`);
callSourceChanged(RECORD_B);
check("switching_to_a_different_record_voids_the_form",
      run("handBuilt") === null && fieldValue("hand-hero") === ""
      && fieldValue("hand-pot") === "" && rowCount("seats") === 0
      && rowCount("ranges") === 0 && el("hand-ended").checked === false
      && el("hand-fees").value === "unknown",
      `hero="${fieldValue("hand-hero")}" seats=${rowCount("seats")}`);
// (b) a purely hand-typed form keeps its values - nothing of it came from a
// record - but its receipt never survives a source change.
await click(el("hand-clear"));
typeHand();
await click(el("hand-build"));
check("verified_before_the_record_change", run("handBuilt") !== null,
      feedback().slice(0, 50));
callSourceChanged(RECORD_B);
check("a_manual_form_keeps_its_values_and_only_loses_the_receipt",
      run("handBuilt") === null && fieldValue("hand-hero") === "Qs Qd"
      && rowCount("seats") === SEATS.length
      && el("hand-compute").disabled === true,
      `hero="${fieldValue("hand-hero")}" built=${run("handBuilt")}`);

// --- 13. two imports completing out of order ----------------------------
typeHand();
hooks.delay[`/api/hand-input/facts/${RECORD_A}`] = 700;
select(recordRef(RECORD_A));
const slowA = run("handImportRecord()");
select(recordRef(RECORD_B));
const fastB = run("handImportRecord()");
await fastB;
await slowA;
delete hooks.delay[`/api/hand-input/facts/${RECORD_A}`];
check("an_out_of_order_import_cannot_clobber_the_newer_target",
      fieldValue("hand-hero") === "2h 3d"
      && exposed("handSource") && run("handSource").issue_id === RECORD_B,
      `hero=${fieldValue("hand-hero")} `
      + `source=${exposed("handSource") ? run("handSource").issue_id : "n/a"}`);

// --- 14. the three identities are really cross-checked ------------------
typeHand();
await click(el("hand-build"));
const verifiedIdentity = run("handExpectedInput");
await click(el("hand-compute"));
const reportForIdentity = await pollRender();
check("the_real_report_identity_matches_everywhere",
      reportForIdentity?.status === "COMPLETE"
      && run("analysisBinding").expected_input_sha256 === verifiedIdentity
      && run("analysisBinding").input_sha256 === verifiedIdentity
      && reportForIdentity.input_sha256 === verifiedIdentity
      && results() !== "" && exportEnabled(),
      "form == accepted == report");
// An abnormal response whose report carries a DIFFERENT identity must not render.
const foreign = {...reportForIdentity, input_sha256: "b".repeat(64)};
run("renderAnalysis")(foreign, state);
check("a_report_with_a_foreign_identity_is_refused",
      results() === "" && exportEnabled() === false
      && analysisStatus().includes("身份"),
      analysisStatus().slice(0, 60));
// And one that omits the identity must not slip through the gap either.
await click(el("hand-build"));
await click(el("hand-compute"));
const again = await pollRender();
check("the_identity_check_does_not_break_a_legitimate_run",
      again?.status === "COMPLETE" && results() !== "" && exportEnabled(),
      `status=${again?.status}`);
const anonymous = {...again, input_sha256: null};
run("renderAnalysis")(anonymous, state);
check("a_report_without_an_identity_is_refused_not_skipped",
      results() === "" && exportEnabled() === false
      && analysisStatus().includes("身份"),
      analysisStatus().slice(0, 60));

// --- 15. a mismatched start identity is rejected before accepting -------
typeHand();
await click(el("hand-build"));
hooks.rewrite["/api/analysis"] = value => ({...value, input_sha256: "c".repeat(64)});
await click(el("hand-compute"));
await startSettled();
check("a_start_response_for_a_different_input_is_rejected",
      run("acceptedAnalysisId") === null && results() === ""
      && analysisStatus().includes("不是同一份"),
      analysisStatus().slice(0, 70));
delete hooks.rewrite["/api/analysis"];

// --- 16. UNKNOWN blocks keep their candidate without becoming facts -----
select(recordRef(RECORD_C));
const importedC = await run("handImportRecord()");
check("the_mid_street_record_imports_only_what_it_has",
      importedC !== null && fieldValue("hand-hero") !== ""
      && rowCount("seats") === 0 && rowCount("history") === 0,
      `hero=${fieldValue("hand-hero")} seats=${rowCount("seats")} `
      + `history=${rowCount("history")}`);
const retained = exposed("handOrigin") ? run("handOrigin") : {};
const IMPORTED_SEATS_CANDIDATE = retained.seats?.candidate ?? null;
check("unknown_blocks_keep_their_candidate_without_becoming_facts",
      retained.seats?.provenance === "unknown"
      && retained.seats?.candidate != null
      && JSON.stringify(retained.seats.candidate).includes("wagers")
      && retained.history?.provenance === "unknown"
      && Array.isArray(retained.history?.candidate)
      && retained.history.candidate.length === 1
      && run('(() => { try { handFacts(); return "built"; } '
             + 'catch (e) { return "refused"; } })()') === "refused",
      `seats=${retained.seats?.provenance}/cand=${
        retained.seats?.candidate != null} `
      + `history=${retained.history?.provenance}/cand=${
        JSON.stringify(retained.history?.candidate)} `
      + "-> the hand is still not buildable");
check("the_unknown_blocks_did_not_fill_the_controls",
      rowCount("seats") === 0 && rowCount("history") === 0
      && fieldValue("hand-order") === "" && fieldValue("hand-hero-seat") === "",
      "a candidate is not a confirmed value");
// The human now fills those two fields by hand, as the gaps instruct.
run(`handFillRows("seats", ${JSON.stringify(SEATS)})`);
run('handAddRow("history", {actor: "1", kind: "bet", target: "20"}, true)');
run('handAddRow("history", {actor: "2", kind: "call", target: "0"}, true)');
touch(run('el("hand-rows-history")').children[0]
  .querySelectorAll("input,select")[0]);
const filled = run("handFacts()");
check("a_human_fill_keeps_the_imported_candidate",
      filled.history.provenance === "human_confirmed"
      && Array.isArray(filled.history.value) && filled.history.value.length === 2
      && Array.isArray(filled.history.candidate)
      && filled.history.candidate.length === 1
      && filled.seats.provenance === "human_confirmed"
      && filled.seats.candidate !== null,
      `history=${filled.history.provenance}/value=${
        (filled.history.value || []).length}/cand=${
        Array.isArray(filled.history.candidate)} `
      + `seats=${filled.seats.provenance}/cand=${filled.seats.candidate !== null}`);
// Finish the hand with hand-typed values and really compute it.
el("hand-hero-seat").value = "0";
el("hand-order").value = "1,2,0";
el("hand-pot").value = "130";
el("hand-targets").value = "20,40,80";
el("hand-max-agg").value = "2";
el("hand-ended").checked = true;
el("hand-fees").value = "confirmed_zero";
run(`handFillRows("ranges", [
  {seat_id: 1, combo: "JhJd", weight: "1"}, {seat_id: 1, combo: "AsAc", weight: "3"},
  {seat_id: 2, combo: "KhKd", weight: "1"}, {seat_id: 2, combo: "QhQd", weight: "3"}])`);
run(`handFillRows("weights", [
  {seat_id: 1, key: "check", weight: "1"}, {seat_id: 1, key: "bet", weight: "2"},
  {seat_id: 1, key: "call", weight: "9"}, {seat_id: 1, key: "fold", weight: "1"},
  {seat_id: 2, key: "check", weight: "1"}, {seat_id: 2, key: "call", weight: "9"},
  {seat_id: 2, key: "fold", weight: "1"}])`);
await click(el("hand-build"));
check("the_mid_street_hand_completes_after_the_human_fills_it",
      run("handBuilt") !== null,
      (feedback() + ' | ' + gaps()).replace(/\s+/g, ' ').slice(0, 160));
await click(el("hand-compute"));
const candidateReport = await pollRender();
check("the_export_carries_the_unknown_blocks_candidate",
      candidateReport?.status === "COMPLETE"
      && run("analysisDraftSource")?.provenance?.history?.candidate != null
      && run("analysisDraftSource")?.provenance?.seats?.candidate != null
      && run("analysisDraftSource")?.provenance?.history?.provenance
         === "human_confirmed",
      `status=${candidateReport?.status} prov=${
        run("analysisDraftSource")?.provenance?.history?.provenance}`);

check("no_innerhtml_used", dom.state.innerHTMLWrites === 0,
      `writes=${dom.state.innerHTMLWrites}`);
check("no_unexpected_endpoint",
      calls.every(call => call.path.startsWith("/api/")),
      `${[...new Set(calls.map(c => c.path))].join(",")}`);

const failed = checks.filter(item => !item.ok);
console.log(JSON.stringify({
  name: "verdict", ok: failed.length === 0, passed: checks.length - failed.length,
  failed: failed.length, requests: calls.length, base,
}));
process.exit(failed.length === 0 ? 0 : 1);
