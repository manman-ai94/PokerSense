"use strict";
const el = id => document.getElementById(id);
const headers = {"X-AA-Live": "1"};
const states = {STOPPED:"已停止", STARTING:"正在启动", RUNNING:"正在观察", STOPPING:"正在停止", ENDED:"回放结束", ERROR:"发生错误", STALE:"画面已过期"};
const labels = {preflop:"翻前", flop:"翻牌", turn:"转牌", river:"河牌", UNKNOWN:"未知", ACTIVE:"参与候选", FOLDED:"弃牌候选", ALL_IN:"全下候选", DEALT_IN_CANDIDATE:"已发牌候选", FOLDED_CANDIDATE:"弃牌候选", WAITING_NEXT_HAND:"等待下一手", WAITING_POST_OR_PASS:"等待入局", WAITING_CANDIDATE:"等待候选", EMPTY_CANDIDATE:"空座候选", EMPTY:"空座候选", fold:"弃牌", check:"过牌", call:"跟注", bet:"下注", raise:"加注", all_in:"全下"};
let localEpoch = 0, requestId = 0, serverGeneration = -1, sequence = -1;
let serverInstance = null;
let lastProgress = 0, statusData = {}, pending = false, pollAbort = null;
let previewAbort = null, previewUrl = null, previewId = 0, modeTouched = false;
let realtimeExpiresAt = null;
const monotonicNow = () => globalThis.performance?.now?.() ?? Date.now();
function clearRealtime(reason = "本次无法建议：等待可信的回合计时与已验证策略。") {
  realtimeExpiresAt = null;
  el("realtime-status").textContent = reason;
  el("realtime-timing").textContent = "剩余行动时间未知；不要等待本页面作出决策。";
}
function renderRealtime(state, requestStarted) {
  const value = state.realtime;
  if (!value || value.mode !== "OBSERVATION_ONLY" || value.advice !== null ||
      value.strategy_eligible !== false || value.advice_emitted !== false ||
      !Number.isFinite(value.status_ttl_ms) || value.status_ttl_ms <= 0 ||
      value.status_ttl_ms > 500 || value.identity?.generation !== state.generation ||
      value.identity?.instance_id !== state.instance_id) {
    clearRealtime("本次无法建议：实时状态身份或格式无效。"); return;
  }
  // Count the entire HTTP roundtrip against TTL; response arrival never
  // restarts the server's validity window. This watchdog is independent of poll.
  realtimeExpiresAt = requestStarted + value.status_ttl_ms;
  if (monotonicNow() >= realtimeExpiresAt) { realtimeWatchdog(); return; }
  const reasons = {NO_CURRENT_OBSERVATION:"当前没有有效画面", SOURCE_TIME_UNKNOWN:"源画面时间未绑定",
    SOURCE_STALE:"源画面已过期", NO_VERIFIED_TURN_EVIDENCE:"未获得可信的回合起点或倒计时"};
  el("realtime-status").textContent = `本次无法建议：${reasons[value.reason] || "实时条件未满足"}。`;
  el("realtime-timing").textContent = Number.isFinite(value.source_host_age_ms) ?
    `本机来源年龄 ${Math.ceil(value.source_host_age_ms)} ms；采集卡之前的延迟与剩余行动时间未知。` :
    "剩余行动时间未知；当前没有通过验收的实时策略。";
}
function realtimeWatchdog() {
  if (realtimeExpiresAt !== null && monotonicNow() >= realtimeExpiresAt)
    clearRealtime("实时状态已过期，本次无法建议。");
}
const known = value => value !== null && value !== undefined && value !== "UNKNOWN";
const text = value => !known(value) ? "未知" : typeof value === "object" ? JSON.stringify(value) : String(value);
const translated = value => labels[value] || text(value);
function error(message = "") { el("error").textContent = message; el("error").hidden = !message; }
function indicator(label, type = "neutral") { el("connection").textContent = label; el("connection").className = `status ${type}`; }
function clearPreview(message = "当前无可用预览") {
  ++previewId; if (previewAbort) previewAbort.abort(); previewAbort = null;
  el("preview").hidden = true; el("preview").removeAttribute("src");
  el("preview-large").hidden = true; el("preview-large").removeAttribute("src");
  el("preview-expand").disabled = true;
  el("preview-large-empty").textContent = message; el("preview-large-empty").hidden = false;
  if (previewUrl) URL.revokeObjectURL(previewUrl); previewUrl = null;
  el("preview-empty").textContent = message; el("preview-empty").hidden = false;
}
function cards(id, values, count) {
  const nodes = [];
  for (let i = 0; i < count; i++) {
    const value = Array.isArray(values) ? values[i] : null;
    const card = document.createElement("span"); card.className = "playing-card unknown";
    const match = typeof value === "string" && /^([2-9TJQKA])([cdhs])$/i.exec(value);
    if (match) {
      const suit = match[2].toLowerCase(); card.className = `playing-card ${"dh".includes(suit) ? "red" : ""}`;
      const rank = document.createElement("span"), symbol = document.createElement("small");
      rank.textContent = match[1].toUpperCase() === "T" ? "10" : match[1].toUpperCase();
      symbol.textContent = {c:"♣", d:"♦", h:"♥", s:"♠"}[suit]; card.append(rank, symbol);
      card.setAttribute("aria-label", value);
    } else { card.textContent = "?"; card.setAttribute("aria-label", "未知牌"); }
    nodes.push(card);
  }
  el(id).replaceChildren(...nodes);
}
function seatCards(row = {}) {
  const nodes = [], wagers = row.street_wagers || {}, causal = row.causal_street_wagers_v2?.wagers || {};
  for (let seat = 0; seat < 8; seat++) {
    const box = document.createElement("article"); box.className = `seat${seat === 4 ? " hero-seat" : ""}${row.current_actor === seat ? " acting" : ""}`;
    const heading = document.createElement("h3"); heading.textContent = `座位 ${seat}`;
    const badge = document.createElement("span"); badge.textContent = [seat === 4 ? "HERO" : "", row.dealer_seat === seat ? "庄" : ""].filter(Boolean).join(" · "); heading.append(badge);
    const list = document.createElement("dl");
    for (const [name, value] of [["筹码", row.stacks?.[seat]?.value], ["可见投入", wagers[seat]], ["时序投入", causal[seat]]]) {
      const pair = document.createElement("div"), dt = document.createElement("dt"), dd = document.createElement("dd");
      dt.textContent = name; dd.textContent = text(value); pair.append(dt, dd); list.append(pair);
    }
    const participation = document.createElement("p"); participation.className = "participation";
    const state = row.participation?.slots?.[seat];
    participation.textContent = state?.conflict ? "参与线索冲突" : translated(state?.current);
    box.append(heading, list, participation); nodes.push(box);
  }
  el("seats").replaceChildren(...nodes);
}
function listBlockers(values) {
  el("blockers").replaceChildren(...values.map(value => { const li = document.createElement("li"); li.textContent = value; return li; }));
}
function phaseDescription(row) {
  const phase = row.hand_phase || {}, ledger = phase.current_ledger ?? row.hand_ledger_v2 ?? {};
  const previous = phase.historical_ledger || {};
  if (["WAITING_NEXT_HAND_CANDIDATE", "POT_CLEAR_PENDING"].includes(phase.phase)) {
    return `结算／清台候选 · ${phase.phase === "POT_CLEAR_PENDING" ? "正在确认" : "等待下一手"}。历史累计投入 ${text(previous.observed_total)}；历史待解释差额 ${text(previous.unallocated_difference)}。当前差额不计算，资金归属尚未核实。`;
  }
  if (["SUSPENDED", "WAITING_OPENING"].includes(phase.phase)) return "当前牌局上下文不足，等待新的完整开局；历史证据保留。";
  const prefix = phase.phase === "SETTLEMENT_CANDIDATE" ? "已观察到现金回流（结算候选）" : row.observed_state_v2?.observed_epoch ? "已观察到开局候选" : "未见完整开局，等待下一手";
  return `${prefix} · 可追溯投入 ${text(ledger.observed_total)} · 与显示底池差额 ${text(ledger.unallocated_difference)}（未解释，不能作为抽水或盈利）`;
}
function clearCurrent(reason) {
  clearRealtime();
  cards("hero", null, 2); cards("board", null, 5); seatCards(); clearPreview();
  for (const id of ["pot", "street", "actor", "dealer"]) el(id).textContent = "未知";
  for (const id of ["sequence", "source-frame", "latency", "coverage"]) el(id).textContent = "—";
  el("quality").textContent = "无当前有效帧"; el("freshness").textContent = reason;
  const empty = document.createElement("p"); empty.className = "muted"; empty.textContent = "当前无动作候选"; el("actions").replaceChildren(empty);
  listBlockers(["等待当前帧与完整牌局输入"]);
  el("state-closure").textContent = "等待完整开局上下文。";
  el("call-price").textContent = "未知";
  el("river-live-results").replaceChildren();
  el("river-live-status").textContent = "等待完整河牌和跟注价格";
}
function controls() {
  const active = ["STARTING", "RUNNING", "STALE", "STOPPING"].includes(String(statusData.status).toUpperCase());
  const replay = statusData.replay_available === true, capture = statusData.capture_available === true;
  const runningOptions = statusData.source_options || {};
  if (active && ["capture-card", "development-replay"].includes(runningOptions.mode)) {
    el("mode").value = runningOptions.mode; modeTouched = true;
    if (Number.isInteger(runningOptions.device_index)) el("device").value = runningOptions.device_index;
    if (["MSMF", "DSHOW"].includes(runningOptions.api)) el("api").value = runningOptions.api;
  }
  el("mode").options[0].disabled = !replay; el("mode").options[1].disabled = !capture;
  if (!modeTouched && !active && !pending) el("mode").value = replay ? "development-replay" : capture ? "capture-card" : "development-replay";
  const useCapture = el("mode").value === "capture-card";
  el("mode").disabled = active || pending;
  el("device").disabled = el("api").disabled = !useCapture || active || pending;
  el("start").disabled = active || pending || statusData.connection_failed === true || !(useCapture ? capture : replay) || statusData.profile?.ready === false;
  el("stop").disabled = !active && !pending;
  el("availability").textContent = [replay ? "已登记开发回放可用" : "未配置开发回放", capture ? "采集入口已配置，点击开始才打开设备" : "采集入口未开放（启动服务时需明确启用）"].join(" · ");
}
function render(row, state) {
  if (row.scene_supported !== true) { clearCurrent("当前画面不受支持或有遮挡，字段已清空。"); return; }
  clearPreview();
  const observed = row.observed_state_v2 || {};
  cards("hero", row.cards?.hero, 2); cards("board", row.cards?.board_slots, 5); seatCards(row);
  el("pot").textContent = text(row.pot?.value); el("street").textContent = translated(observed.street_candidate);
  el("actor").textContent = Number.isInteger(row.current_actor) ? `座位 ${row.current_actor}` : "未知";
  el("dealer").textContent = Number.isInteger(row.dealer_seat) ? `座位 ${row.dealer_seat}` : Number.isInteger(row.dealer_observation_v2?.dealer_seat) ? `单帧候选 ${row.dealer_observation_v2.dealer_seat}（等待开局）` : "未知";
  el("state-closure").textContent = phaseDescription(row);
  el("call-price").textContent = text(row.hero_controls_v1?.call_amount);
  renderRiverStudy(row.river_strategy_v1);
  el("sequence").textContent = text(state.sequence); el("source-frame").textContent = text(state.source_frame ?? row.frame);
  el("latency").textContent = Number.isFinite(state.processing_ms) ? `${state.processing_ms.toFixed(0)} ms` : "未记录";
  const fields = [row.cards?.hero, row.board_count, row.pot?.value, row.current_actor, row.dealer_seat, observed.street_candidate];
  for (let seat = 0; seat < 8; seat++) fields.push(row.stacks?.[seat]?.value, row.street_wagers?.[seat]);
  el("coverage").textContent = `${fields.filter(known).length} / 22`;
  el("quality").textContent = row.context_only ? "开局前滚 · 不计入验收" : "识别候选 · 未完成验收";
  el("freshness").textContent = `当前帧 · ${known(row.pts_seconds) ? `来源时间 ${text(row.pts_seconds)} 秒 · ` : ""}牌局 ${text(observed.observed_epoch)}`;
  const reasons = [], authority = row.strategy_input_authority?.fields || {};
  const names = {hand_boundary:"牌局边界",cards:"牌面",pot:"底池",stacks:"筹码",street_wagers:"本轮投入",hand_commitments:"整手投入",actions:"完整行动",participation:"参与状态",dealer:"庄位",action_line:"行动线"};
  for (const [key, name] of Object.entries(names)) if (authority[key] !== true) reasons.push(`${name}尚未核验`);
  if (observed.complete_legal_state !== true) reasons.push("完整合法状态尚未闭合");
  const supplied = row.strategy_blockers || row.missing_fields || [];
  if (Array.isArray(supplied)) for (const value of supplied) if (typeof value === "string") reasons.push(value);
  listBlockers([...new Set(reasons)].slice(0, 14));
  const emptyAction = document.createElement("p"); emptyAction.className = "muted"; emptyAction.textContent = "当前无动作候选";
  el("actions").replaceChildren(emptyAction);
  const actions = Array.isArray(row.interpreted_action_history) ? row.interpreted_action_history : Array.isArray(row.action_history_candidate) ? row.action_history_candidate : Array.isArray(row.observed_actions_v2) ? row.observed_actions_v2 : [];
  if (actions.length) el("actions").replaceChildren(...actions.slice(-48).reverse().map(action => {
    const node = document.createElement("span"); node.className = "action-item";
    const kind = action.semantic_kind;
    const actionLabel = kind ? `${translated(kind)}${action.all_in ? "（全下）" : ""}${["bet","raise"].includes(kind) && action.target_total != null ? ` 至 ${action.target_total}` : ""}` : `${translated(action.kind)}字样（上下文待核）`;
    const sourceFrame = Number.isInteger(action.source_confirmation_frame) ? action.source_confirmation_frame : "未绑定";
    node.textContent = `座位 ${text(action.slot)} · ${actionLabel} · 本次支出 ${text(action.amount)} · 来源确认帧 ${sourceFrame} / 处理序号 ${text(action.confirmed_at ?? action.frame)}${kind && !action.semantic_street ? " · 街道待定" : ""}`; return node;
  }));
  else if (row.glyphs) {
    const nodes = Object.entries(row.glyphs).filter(([, value]) => known(value)).map(([seat, value]) => {
      const node = document.createElement("span"); node.className = "action-item"; node.textContent = `座位 ${seat} · 字样 ${text(value)}`; return node;
    });
    if (nodes.length) el("actions").replaceChildren(...nodes);
  }
}
function renderRiverStudy(study) {
  el("river-live-results").replaceChildren();
  if (study?.status !== "CONDITIONAL_STUDY" || !study.result) {
    el("river-live-status").textContent = study?.reasons?.slice(0,2).join("；") || "等待完整河牌和跟注价格";
    return;
  }
  const result=study.result;
  el("river-live-status").textContent=`来源帧 ${text(study.source_frame)} · ${study.opponent_seats.length}名全下对手候选 · 条件计算`;
  const amount=document.createElement("p");amount.className="river-bound-number";
  amount.textContent=`跟注毛收益下界：${text(result.call_gross_lower?.decimal)}`;
  const detail=document.createElement("p");detail.className="footnote";
  detail.textContent=result.strength_evidence.unbeaten ? `已检查全部合法单手组合；在全额争池、跟注结束行动的前提下，最差分得比例至少 ${text(result.share_floor?.exact)}。` : "存在能击败这副牌的合法组合。该下界不是平均收益，也不构成弃牌建议；仍需对手范围。";
  const fees=document.createElement("p");fees.className="footnote";
  fees.textContent=result.max_hero_deduction_for_nonnegative_bound ? `上述前提成立时，个人额外扣款不超过 ${text(result.max_hero_deduction_for_nonnegative_bound.decimal)}，该下界仍非负。实际费用、底池资格尚未核实，不代表胜率或盈利保证。` : "费用未知，未计算净收益保证；不支持当前输入外的后续下注。";
  el("river-live-results").append(amount,detail,fees);
}
async function preview(epoch, gen, seq) {
  const ticket = ++previewId, abort = new AbortController(); previewAbort = abort;
  const timeout = setTimeout(() => abort.abort(), 1800);
  try {
    const response = await fetch("/api/preview.jpg", {headers, cache:"no-store", signal:abort.signal});
    if (!response.ok) return;
    const blob = await response.blob();
    if (epoch !== localEpoch || gen !== serverGeneration || seq !== sequence || ticket !== previewId) return;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(blob);
    for (const id of ["preview", "preview-large"]) { el(id).src = previewUrl; el(id).hidden = false; }
    el("preview-empty").hidden = true; el("preview-large-empty").hidden = true; el("preview-expand").disabled = false;
  } catch (_) { /* A missing preview never preserves a previous frame. */ }
  finally { clearTimeout(timeout); }
}
async function poll() {
  if (pending || document.hidden) return;
  const requestStarted = monotonicNow();
  const epoch = localEpoch, ticket = ++requestId, abort = new AbortController(); pollAbort = abort;
  const timeout = setTimeout(() => abort.abort(), 2500);
  try {
    const response = await fetch("/api/status", {headers, cache:"no-store", signal:abort.signal});
    if (!response.ok) throw Error(`HTTP ${response.status}`);
    const state = await response.json();
    if (epoch !== localEpoch || ticket !== requestId) return;
    if (typeof state.instance_id === "string" && state.instance_id !== serverInstance) {
      serverInstance = state.instance_id; serverGeneration = -1; sequence = -1;
      clearCurrent("服务已重启，等待当前实例的画面。");
      if (typeof invalidateAnalysis === "function") invalidateAnalysis("服务已重启，旧分析已失效。");
    }
    const status = String(state.status).toUpperCase();
    const hasCurrentPayload = status === "RUNNING" && state.payload;
    if (!Number.isInteger(state.generation) || hasCurrentPayload && !Number.isInteger(state.sequence)) throw Error("服务状态缺少有效版本标识");
    const incomingSequence = Number.isInteger(state.sequence) ? state.sequence : -1;
    if (state.generation < serverGeneration || hasCurrentPayload && state.generation === serverGeneration && incomingSequence < sequence) return;
    if (state.generation !== serverGeneration) { clearCurrent("来源已切换，等待当前画面。"); sequence = -1; }
    const advanced = state.generation !== serverGeneration || incomingSequence !== sequence;
    serverGeneration = state.generation; sequence = incomingSequence; if (advanced) lastProgress = Date.now();
    statusData = state; controls(); error(state.error ? text(state.error) : "");
    if (typeof handRulesRevisionSeen === "function") handRulesRevisionSeen();
    if (typeof renderAnalysis === "function") renderAnalysis(state.analysis, state);
    el("profile").textContent = typeof state.profile === "string" ? state.profile : JSON.stringify(state.profile ?? "未配置", null, 2);
    el("source-kind").textContent = state.source_kind === "capture-card" ? "实体采集卡" : state.source_kind === "development-replay" ? "开发回放 · 非现场" : text(state.source_kind);
    if (status !== "RUNNING" || !state.payload || Date.now() - lastProgress > 3000) {
      const stale = status === "RUNNING" && state.payload;
      indicator(stale ? "画面已过期" : states[status] || status, ["ERROR", "STALE"].includes(status) || stale ? "bad" : "neutral");
      clearCurrent(stale ? "超过 3 秒没有新识别结果，已清空当前字段。" : `${states[status] || status}；等待新的有效帧。`); return;
    }
    indicator("正在观察 · 候选", "good");
    if (advanced) { render(state.payload, state); preview(epoch, serverGeneration, sequence); }
    renderRealtime(state, requestStarted);
  } catch (failure) {
    if (epoch !== localEpoch || ticket !== requestId) return;
    clearCurrent("服务连接中断或读取失败，已清空当前字段与预览。"); indicator("连接异常", "bad"); error(`读取状态失败：${failure.message}`);
    statusData = {...statusData, connection_failed:true}; controls(); sequence = -1; serverGeneration = -1;
    if (typeof clearAnalysis === "function") clearAnalysis("服务已断开，当前分析结果已隐藏。");
  } finally { clearTimeout(timeout); if (pollAbort === abort) pollAbort = null; }
}
async function command(action) {
  const epoch = ++localEpoch; ++requestId; if (pollAbort) pollAbort.abort();
  if (typeof invalidateAnalysis === "function") invalidateAnalysis("来源正在启动或停止，旧分析已失效。");
  clearCurrent(action === "start" ? "正在启动，等待第一帧。" : "正在停止，当前字段已清空。"); error(); pending = true; controls();
  const abort = new AbortController(), timeout = setTimeout(() => abort.abort(), 15000);
  try {
    const body = action === "start" ? {mode:el("mode").value, device_index:Number(el("device").value), api:el("api").value, fps:30} : {};
    const response = await fetch(`/api/${action}`, {method:"POST", headers:{...headers,"Content-Type":"application/json"}, body:JSON.stringify(body), signal:abort.signal});
    const result = await response.json(); if (epoch !== localEpoch) return;
    if (!response.ok) throw Error(text(result.error ?? result.detail ?? `HTTP ${response.status}`));
    sequence = -1; indicator(action === "start" ? "正在启动" : "已请求停止");
  } catch (failure) { if (epoch === localEpoch) { error(`操作未确认：${failure.message}。正在重新查询服务状态。`); indicator("正在核对运行状态", "warning"); } }
  finally { clearTimeout(timeout); if (epoch === localEpoch) { pending = false; controls(); await poll(); } }
}
el("start-form").addEventListener("submit", event => { event.preventDefault(); if (!el("start").disabled) command("start"); });
el("stop").addEventListener("click", () => command("stop"));
el("mode").addEventListener("change", () => { modeTouched = true; controls(); });
el("preview").addEventListener("error", () => clearPreview("当前预览解码失败"));
el("preview-large").addEventListener("error", () => clearPreview("当前预览解码失败"));
el("preview-expand").addEventListener("click", () => {
  if (previewUrl && !el("preview-expand").disabled && !el("preview-dialog").open) el("preview-dialog").showModal();
});
el("preview-close").addEventListener("click", () => el("preview-dialog").close());
document.addEventListener("visibilitychange", () => {
  ++requestId; if (pollAbort) pollAbort.abort(); clearCurrent("页面重新获得焦点后获取新画面。"); sequence = -1;
  if (!document.hidden) poll();
});
async function tick() { await poll(); setTimeout(tick, 250); }
setInterval(realtimeWatchdog, 50);
clearCurrent("尚未开始观察；没有显示历史牌面。"); tick();
