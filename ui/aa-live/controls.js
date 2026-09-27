"use strict";
const ruleFields = {
  table_label: ["桌规名称／备注（可选）", "text"], dealt_players: ["本桌发牌人数", ["", "6", "7", "8"]],
  small_blind: ["小盲", "decimal"], big_blind: ["大盲", "decimal"], ante: ["每人前注", "decimal"],
  straddle_mode: ["Straddle 类型", {unknown:"未知", none:"没有", mandatory_utg:"UTG 强制", optional_explicit_utg:"UTG 可选（逐手确认）"}],
  straddle_amount: ["Straddle 金额", "decimal"], rake_percent: ["抽水比例", "decimal"],
  rake_cap_bb: ["抽水封顶", "decimal"],
  common_effective_stack_min_bb: ["常见有效筹码最小值", "decimal"],
  common_effective_stack_max_bb: ["常见有效筹码最大值", "decimal"],
  minimum_chip: ["最小筹码单位", "decimal"],
  rake_application: ["抽水时机", {unknown:"未知", all_pots:"所有底池", postflop_only:"见翻牌后"}],
  rake_rounding: ["抽水舍入", {unknown:"未知", exact:"精确值", floor_to_chip:"向下到筹码单位", ceil_to_chip:"向上到筹码单位"}],
  rake_distribution: ["边池抽水分配", {unknown:"未知", proportional_all_pots:"所有池按比例", main_pot_first:"主池优先"}],
  insurance: ["保险", {unknown:"未知", off:"关闭", on:"开启"}],
  bomb: ["暴击", {unknown:"未知", off:"关闭", on:"开启"}],
  mushroom: ["种蘑菇", {unknown:"未知", off:"关闭", on:"开启"}]
};
let rulesRevision = null;
let rulesBusy = false;
let issueSaving = false;
const advancedRuleFields = new Set(["minimum_chip", "rake_application", "rake_rounding", "rake_distribution", "insurance", "bomb", "mushroom"]);
const ruleUnits = {rake_percent:"%", rake_cap_bb:"BB", common_effective_stack_min_bb:"BB", common_effective_stack_max_bb:"BB"};
const ruleHints = {
  dealt_players:"物理桌位为八座；这里填写本桌发牌人数。",
  ante:"0 表示没有前注；留空表示未知。",
  rake_percent:"输入 3 表示 3%；留空表示未知。",
  rake_cap_bb:"按大盲倍数填写；0 不代表无限封顶。",
  straddle_mode:"UTG 为大盲左侧首位；其他位置的规则请保持未知。"
};
for (const [key, [title, type]] of Object.entries(ruleFields)) {
  const label = document.createElement("label"); label.textContent = title;
  const input = document.createElement(typeof type === "string" ? "input" : "select");
  input.id = `rule-${key}`;
  input.setAttribute("aria-label", title);
  if (typeof type === "string") { input.type = "text"; input.maxLength = key === "table_label" ? 100 : 32; if (type === "decimal") input.inputMode = "decimal"; input.placeholder = key === "table_label" ? "便于辨认当前牌桌" : "未知"; }
  else { const choices = Array.isArray(type) ? Object.fromEntries(type.map(v => [v, v || "未知"])) : type; for (const [value, title] of Object.entries(choices)) { const option = document.createElement("option"); option.value = value; option.textContent = title; input.append(option); } }
  if (ruleUnits[key]) {
    const wrapper = document.createElement("span"); wrapper.className = "rule-unit-input";
    const unit = document.createElement("span"); unit.className = "rule-unit"; unit.textContent = ruleUnits[key]; unit.setAttribute("aria-hidden", "true");
    wrapper.append(input, unit); label.append(wrapper);
  } else label.append(input);
  if (ruleHints[key]) {
    const hint = document.createElement("small"); hint.id = `rule-${key}-hint`; hint.textContent = ruleHints[key];
    input.setAttribute("aria-describedby", hint.id); label.append(hint);
  }
  const target = key.startsWith("common_effective_stack_") ? "rules-stack-fields" : advancedRuleFields.has(key) ? "rules-advanced-fields" : "rules-fields";
  el(target).append(label);
}
function setRulesBusy(busy) {
  rulesBusy = busy;
  for (const key of Object.keys(ruleFields)) el(`rule-${key}`).disabled = busy;
  for (const id of ["rules-save", "rules-reset"]) el(id).disabled = busy || !rulesRevision;
  el("rules-cancel").disabled = busy;
}
function openRulesEditor() {
  if (typeof showDesk === "function") showDesk("settings");
  el("rules-details").open = true;
  el("table-settings-panel").scrollIntoView?.({block:"start"});
  el("rule-table_label").focus?.({preventScroll:true});
}
function hasManualRules(doc) {
  return Object.values(doc).some(value => value !== null && value !== "" && value !== "unknown");
}
function ruleSummary(doc) {
  const amount = key => doc[key] === null || doc[key] === undefined || doc[key] === "" ? "未知" : String(doc[key]);
  const mode = ruleFields.straddle_mode[1][doc.straddle_mode] || "未知";
  const straddle = doc.straddle_mode === "none" || doc.straddle_mode === "unknown" ? mode : `${mode} ${amount("straddle_amount")}`;
  const range = doc.common_effective_stack_min_bb == null && doc.common_effective_stack_max_bb == null ? "未知" : `${amount("common_effective_stack_min_bb")}–${amount("common_effective_stack_max_bb")} BB`;
  return `发牌 ${amount("dealt_players")}人 · 盲注 ${amount("small_blind")}/${amount("big_blind")} · 前注 ${amount("ante")} · Straddle ${straddle} · 抽水 ${amount("rake_percent")}% / 封顶 ${amount("rake_cap_bb")} BB · 常见有效筹码 ${range}`;
}
function showRules(result, fill, saved = false) {
  rulesRevision = result.revision;
  if (fill) for (const key of Object.keys(ruleFields)) el(`rule-${key}`).value = result.document[key] ?? "";
  const missing = result.pending_fields.map(k => ruleFields[k]?.[0] || k);
  const configured = saved || hasManualRules(result.document);
  el("rules-status").textContent = configured ? "已保存 · 手动填写" : "未配置";
  el("rules-summary-title").textContent = result.document.table_label || (configured ? "当前桌规 · 手动填写" : "尚未配置本桌设置");
  el("rules-summary").textContent = ruleSummary(result.document);
  el("rules-feedback").textContent = missing.length ? `待补充：${missing.join("、")}。未知也可以保存。` : result.unsupported_effects.length ? "已保存；当前条件分析不支持开启的特殊机制。" : "字段已填齐 · 手动填写，尚非视觉核验；不会自动开放实战建议。";
}
async function rulesRequest(options = {}) {
  const abort = new AbortController(), timeout = setTimeout(() => abort.abort(), 10000);
  try {
    const response = await fetch("/api/rules", {...options, signal:abort.signal});
    let result;
    try { result = await response.json(); }
    catch (e) {
      if (abort.signal.aborted) throw e;
      throw Error(`服务响应无法读取（HTTP ${response.status || "未知"}）`);
    }
    if (!response.ok) throw Error(text(result.detail));
    return result;
  } catch (e) {
    if (abort.signal.aborted) throw Error("请求超时，请重新读取本桌设置确认保存结果");
    throw e;
  } finally { clearTimeout(timeout); }
}
async function loadRules(initial = false) {
  if (rulesBusy) return;
  setRulesBusy(true);
  try {
    const result = await rulesRequest({cache:"no-store"});
    if (rulesRevision && rulesRevision !== result.revision) {
      if (typeof invalidateAnalysis === "function") invalidateAnalysis("本桌设置已在其他页面更改，旧分析已失效。");
      if (typeof handRulesChanged === "function") handRulesChanged("已读取最新本桌设置，请重新核对牌局输入。");
      clearCurrent("已读取新的本桌设置。");
    }
    showRules(result, true);
    if (initial && !hasManualRules(result.document)) {
      if (typeof showDesk === "function") openRulesEditor();
      else document.addEventListener("DOMContentLoaded", openRulesEditor, {once:true});
    }
  } catch (e) {
    el("rules-feedback").textContent = `设置读取失败：${e.message}。请点击“取消修改”重新读取。`;
  } finally { setRulesBusy(false); }
}
async function saveRules(reset) {
  if (!rulesRevision || rulesBusy) return;
  setRulesBusy(true);
  if (typeof invalidateAnalysis === "function") invalidateAnalysis("正在保存本桌规则，旧分析已失效。");
  // A verified hand receipt names the rules revision it was built against, so a
  // rule save attempts to void it BEFORE the request: whichever way the save goes,
  // an input verified against the old rules must never be computed as if it were
  // verified against the new ones.
  if (typeof handRulesChanged === "function") {
    handRulesChanged(reset ? "本桌规则正在重置：上方输入的旧核对已失效，请重置后重新核对。"
                           : "本桌规则正在保存为新版本：上方输入的旧核对已失效，保存后请重新核对。");
  }
  const document = {};
  for (const [key, [, type]] of Object.entries(ruleFields)) {
    const value = reset ? (key === "table_label" ? "" : typeof type === "object" && !Array.isArray(type) ? "unknown" : "") : el(`rule-${key}`).value.trim();
    document[key] = key === "dealt_players" ? (value ? Number(value) : null) : key === "table_label" || typeof type !== "string" ? value : value || null;
  }
  try {
    const result = await rulesRequest({method:"POST", headers:{...headers,"Content-Type":"application/json"}, body:JSON.stringify({document,revision:rulesRevision})});
    showRules(result, true, !reset);
    el("rules-feedback").textContent = (reset ? "本桌设置已清空。" : "已保存到本机。") + "观察已停止，请重新开始观察。 " + el("rules-feedback").textContent;
    el("rules-details").open = !!reset;
    clearCurrent("规则已变更，重新开始后使用新桌配置。");
    await poll();
  } catch (e) {
    el("rules-feedback").textContent = `保存失败或结果未确认：${e.message}。输入已保留；请点击“取消修改”读取最新配置。`;
  } finally { setRulesBusy(false); }
}
el("rules-form").addEventListener("submit", event => { event.preventDefault(); return saveRules(false); });
el("rules-reset").addEventListener("click", () => saveRules(true));
el("rules-cancel").addEventListener("click", () => loadRules());
el("rules-edit").addEventListener("click", openRulesEditor);
el("issue-form").addEventListener("submit", async event => {
  event.preventDefault(); if (issueSaving) return; issueSaving = true; el("issue-save").disabled = true;
  try {
    const response = await fetch("/api/issues", {method:"POST", headers:{...headers,"Content-Type":"application/json"}, body:JSON.stringify({note:el("issue-note").value,category:el("issue-category").value})});
    const result = await response.json(); if (!response.ok) throw Error(text(result.detail));
    el("issue-feedback").textContent = `已保存，待复核：${result.directory}`; el("issue-note").value = "";
  } catch (e) { el("issue-feedback").textContent = `未保存：${e.message}`; }
  finally { issueSaving = false; }
});
setInterval(() => { el("issue-save").disabled = issueSaving || statusData.status !== "RUNNING" || !statusData.payload || !statusData.issue_recording_available; }, 800);
loadRules(true);
