"use strict";
// The signal window's view model (ui/aa-live/signal_view.js) for each state it shows.
const assert = require("node:assert/strict");
const path = require("node:path");
const {signalView, positions} = require(path.resolve(__dirname, "../../ui/aa-live/signal_view.js"));

const seats = states => ({seats: Object.fromEntries(states.map((state, seat) => [seat, {state}]))});
const full_ = () => seats(["active", "active", "active", "active", "active", "empty", "active", "active"]);
const eight = seats(["folded", "folded", "active", "folded", "active", "folded", "folded", "folded"]);
const stacks = values => Object.fromEntries(values.map((value, seat) => [seat, {value}]));
const running = payload => ({status: "RUNNING", source_kind: "capture-card", processing_ms: 64, payload});
const base = (extra = {}) => ({
  scene_supported: true, current_actor: 4, dealer_seat: 3,
  cards: {hero: ["4d", "4s"], board_slots: ["6h", "8s", "Kd", "8h", "2d"]},
  pot: {value: "85"}, street_v1: {street: "river"}, seat_states_v1: eight,
  stacks: stacks(["300", "250", "214", "180", "160", "90", "400", "120"]),
  hero_controls_v1: {visible: true, button: "call", call_amount: "28"},
  action_history_v1: {hand_id: 7, dealer: 3, actions: [
    {street: "flop", slot: 2, kind: "check", amount: null},
    {street: "flop", slot: 4, kind: "raise", amount: "14"},
    {street: "flop", slot: 2, kind: "call", amount: "14"},
    {street: "river", slot: 2, kind: "raise", amount: "28"}]},
  table_math_v1: {
    equity: {available: true, value: 0.31, opponents: 1},
    pot_odds: {available: true, call: "28", pot: "85", required_equity: 0.248},
    spr: {available: true, value: 1.88, effective_stack: "160"}},
  ...extra,
});

// Positions run clockwise (rising seat numbers) from the dealer over the seats dealt in.
// No names when the dealer is not a seat dealt in, or the table size is not covered.
assert.deepEqual(positions({seat_states_v1: eight, dealer_seat: 3}, {dealer: null}).hasOwnProperty(3), true);
const two = seats(["empty", "empty", "active", "empty", "active", "empty", "empty", "empty"]);
assert.deepEqual(positions({seat_states_v1: two, dealer_seat: 2}, null), {});
assert.deepEqual(positions({seat_states_v1: full_(), dealer_seat: 5}, {dealer: null}), {});
const full = seats(["active", "active", "active", "active", "active", "active", "active", "active"]);
assert.deepEqual(positions({seat_states_v1: full, dealer_seat: 3}, {dealer: 3}),
  {3: "BTN", 4: "SB", 5: "BB", 6: "UTG", 7: "UTG+1", 0: "LJ", 1: "HJ", 2: "CO"});
const six = seats(["active", "empty", "active", "active", "active", "waiting", "active", "active"]);
assert.deepEqual(positions({seat_states_v1: six, dealer_seat: 7}, null),
  {7: "BTN", 0: "SB", 2: "BB", 3: "UTG", 4: "HJ", 6: "CO"});

// Not started, and a frozen feed.
let view = signalView({status: "STOPPED"}, 0, {});
assert.equal(view.tone, "wait"); assert.equal(view.title, "还没开始");
assert.equal(view.header.health.text, "还没开始");
view = signalView({status: "STALE"}, 0, {});
assert.equal(view.tone, "warn"); assert.equal(view.title, "画面断了");
// No table on screen: calm at first (between hands), a warning when it lasts.
const blind = {};
view = signalView(running({...base(), scene_supported: false}), 0, blind);
assert.equal(view.tone, "wait"); assert.equal(view.title, "看不到牌桌");
view = signalView(running({...base(), scene_supported: false}), 9000, blind);
assert.equal(view.tone, "warn"); assert.equal(view.title, "画面看不清");
assert.match(view.note, /^已经 9 秒看不到牌桌/);

// Heads-up river: the solver mix, in words and numbers.
const memory = {};
const river = base({solver_advice_v1: {status: "ready", street: "river", hand_id: 7, decision: 4,
  to_call: "28", seconds: 1.2, pot_offset: "2",
  advice: [{action: "call", frequency: 0.57}, {action: "fold", frequency: 0.43}]}});
view = signalView(running(river), 1000, memory);
assert.equal(view.tone, "call");
assert.equal(view.verdict.word, "跟注"); assert.equal(view.verdict.size, "28");
assert.equal(view.verdict.note, "混合打法：大多数时候跟注，有时弃牌");
assert.deepEqual(view.verdict.mix.map(item => [item.text, item.percent, item.tone]),
  [["跟注 28", "57%", "call"], ["弃牌", "43%", "fold"]]);
assert.deepEqual(view.tags, ["河牌", "轮到你", "已等 0 秒"]);
assert.equal(view.price, "CO 下注，跟注要 28");
assert.deepEqual(view.numbers.map(item => [item.label, item.value]),
  [["要赢多少才不亏", "25%"], ["对随机牌能赢", "31%"], ["有效筹码", "160"]]);
assert.equal(view.numbers[0].note, "跟 28，底池会到 113");
assert.deepEqual(view.basis, ["单挑求解器 · 1.2 秒算完", "对手范围按 AA 真人打法推算",
  "底池比规则多 2，已算进去", "只显示建议，不替你点"]);
assert.equal(view.header.health.text, "采集卡 · 识别正常 · 64 毫秒");
assert.deepEqual(view.log.map(line => [line.street, line.text, line.yourTurn]), [
  ["翻牌", "CO 过牌 · 你下注 14 · CO 跟注 14", false],
  ["河牌", "CO 下注 28", true]]);
const hero = view.seats[4];
assert.equal(hero.name, "SB · 你"); assert.equal(hero.stack, "160"); assert.equal(hero.out, false);
assert.equal(view.seats[2].bet, "28"); assert.equal(view.seats[0].out, true);
// The wait keeps counting while the decision stays the same...
view = signalView(running(river), 4600, memory);
assert.deepEqual(view.tags, ["河牌", "轮到你", "已等 3 秒"]);
// ...and starts again for your next decision.
const next = base({action_history_v1: {...river.action_history_v1, actions: [
  ...river.action_history_v1.actions, {street: "river", slot: 4, kind: "call", amount: "28"}]}});
view = signalView(running(next), 5000, memory);
assert.equal(view.tags[2], "已等 0 秒");

// A big bet that covers the stack reads as all in; a narrow top choice says so.
view = signalView(running(base({solver_advice_v1: {status: "ready", street: "turn", to_call: "0",
  advice: [{action: "bet", frequency: 0.98, chips: "160", to: "160"}, {action: "check", frequency: 0.02}]}})), 0, {});
assert.equal(view.tone, "allin"); assert.equal(view.verdict.word, "全下");
assert.equal(view.verdict.size, "160"); assert.equal(view.verdict.note, "求解器每次都这样打");
// A choice taken under 1% of the time is left out of the bar.
assert.deepEqual(view.verdict.mix.map(item => item.percent), ["98%", "2%"]);
view = signalView(running(base({solver_advice_v1: {status: "ready", street: "turn", to_call: "0",
  advice: [{action: "check", frequency: 0.4}, {action: "bet", frequency: 0.35, chips: "40", to: "40"},
    {action: "bet", frequency: 0.25, chips: "80", to: "80"}]}})), 0, {});
assert.equal(view.verdict.note, "混合打法：过牌和下注都常用，过牌稍多");

// Preflop: each option's value, best first.
const pre = base({street_v1: {street: "preflop"}, cards: {hero: ["Kc", "Tc"], board_slots: [null, null, null, null, null]},
  action_history_v1: {hand_id: 8, dealer: 3, actions: [{street: "preflop", slot: 6, kind: "raise", amount: "4"}]},
  hero_controls_v1: {visible: true, button: "call", call_amount: "4"},
  solver_advice_v1: {status: "ready", street: "preflop", seconds: 0.003, to_call: "4",
    options: [{action: "raise", chips: 3.2, big_blinds: 1.6, to: "14", chips_in: "14"},
      {action: "call", chips: 0.8, big_blinds: 0.4, chips_in: "4"},
      {action: "fold", chips: 0, big_blinds: 0}]}});
view = signalView(running(pre), 0, {});
assert.equal(view.tone, "raise"); assert.equal(view.verdict.word, "加注到"); assert.equal(view.verdict.size, "14");
assert.equal(view.verdict.note, "比跟注 4 多赢 1.2 大盲，比弃牌多赢 1.6 大盲");
assert.deepEqual(view.verdict.options.map(item => [item.text, item.value, item.best, item.width]),
  [["加注到 14", "+1.6 大盲", true, 100], ["跟注 4", "+0.4 大盲", false, 25], ["弃牌", "0.0 大盲", false, 0]]);
assert.equal(view.basis[0], "翻前算法 · 不到 0.01 秒算完");
assert.equal(view.price, "UTG 加注，跟注要 4");
assert.equal(view.verdict.mix, undefined);
// From the big blind with nothing to call, calling is a check.
view = signalView(running({...pre, solver_advice_v1: {...pre.solver_advice_v1,
  options: [{action: "call", chips: 0.5, big_blinds: 0.25, chips_in: "0"}, {action: "raise", chips: -1, big_blinds: -0.5, to: "12", chips_in: "10"}]}}), 0, {});
assert.equal(view.verdict.word, "过牌"); assert.equal(view.verdict.size, null); assert.equal(view.tone, "call");
// The preflop policy can also name the check itself; options worth the same say so.
view = signalView(running({...pre, solver_advice_v1: {...pre.solver_advice_v1,
  options: [{action: "raise", chips: 4.6, big_blinds: 2.28, to: "20", chips_in: "18"},
    {action: "check", chips: 4.5, big_blinds: 2.27}]}}), 0, {});
assert.deepEqual(view.verdict.options.map(item => item.text), ["加注到 20", "过牌"]);
assert.equal(view.verdict.note, "和过牌差不多");

// Facing a bet bigger than your stack: calling is all in.
view = signalView(running(base({hero_controls_v1: {visible: true, button: "call", call_amount: "200"},
  solver_advice_v1: {status: "ready", street: "river", to_call: "200",
    advice: [{action: "call", frequency: 1}]}})), 0, {});
assert.equal(view.price, "CO 下注，跟注要 160（全下）");
assert.equal(view.verdict.size, "160");

// Cards: "?" only where a card should be and was not read; undealt slots stay blank.
view = signalView(running(base({street_v1: {street: "turn"},
  cards: {hero: ["4d", null], board_slots: ["6h", null, "Kd", null, null]}})), 0, {});
assert.deepEqual(view.cards.hero, [{rank: "4", suit: "d"}, {unread: true}]);
assert.deepEqual(view.cards.board.map(card => card && (card.unread ? "?" : card.rank)), ["6", "?", "K", "?", null]);

// Not your turn: who is thinking, no advice.
view = signalView(running(base({hero_controls_v1: {visible: false}, current_actor: 2})), 0, {});
assert.equal(view.tone, "wait"); assert.equal(view.title, "还没轮到你");
assert.deepEqual(view.tags, ["河牌", "CO 在想"]);
assert.deepEqual(view.numbers.map(item => [item.label, item.value]), [["底池", "85"], ["还在局", "2 人"]]);

// Each state that gives no advice, with the live math still shown.
const states = [
  [{status: "computing", street: "turn", hand_id: 7, decision: 3}, "busy", "正在算"],
  [{status: "idle", reason: "waiting_for_last_action"}, "info", "稍等"],
  [{status: "idle", reason: "street_not_covered", street: "flop"}, "info", "翻牌不给打法"],
  [{status: "idle", reason: "more_than_one_opponent"}, "info", "多人底池不给打法"],
  [{status: "idle", reason: "your_cards_not_read"}, "warn", "识别不全"],
  [{status: "abstain", reason: "stack_unknown"}, "warn", "识别不全"],
  [{status: "abstain", reason: "hand_incomplete"}, "info", "这一手不给建议"],
  [{status: "abstain", reason: "players_5"}, "info", "这一手不给建议"],
];
for (const [advice, tone, title] of states) {
  const seen = {};
  view = signalView(running(base({solver_advice_v1: advice})), 0, seen);
  // Right after your buttons appear a missing read is the screen settling.
  if (tone === "warn") { assert.equal(view.title, "稍等", title); assert.equal(view.tone, "info", title); }
  view = signalView(running(base({solver_advice_v1: advice})), 1600, seen);
  assert.equal(view.tone, tone, title); assert.equal(view.title, title);
  assert.equal(view.numbers[0].value, "25%", title);
  assert.equal(view.verdict, undefined, title);
}
view = signalView(running(base({solver_advice_v1: {status: "abstain", reason: "players_5"}})), 0, {});
assert.equal(view.note, "5 人桌，现在只支持 6–8 人，这一步不给建议。");
const solving = {};
signalView(running(base({solver_advice_v1: states[0][0]})), 0, solving);
view = signalView(running(base({solver_advice_v1: states[0][0]})), 2100, solving);
assert.equal(view.note, "已算 2 秒，通常 1–4 秒。先看价格：");
console.log("signal view cases passed");
