"use strict";
// The signal window's view model (ui/aa-live/signal_view.js) for each state it shows.
const assert = require("node:assert/strict");
const path = require("node:path");
const {signalView, positions, gradeView, sessionView} = require(path.resolve(__dirname, "../../ui/aa-live/signal_view.js"));

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
// From the capture card it may be the wrong device (the Mac camera).
assert.match(view.note, /换一个设备编号/);

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
// With the opponent's range from the solve, equity against it replaces equity against random cards.
view = signalView(running(base({solver_advice_v1: {...river.solver_advice_v1,
  range_equity: {value: 0.21, hands: 312}}})), 1000, {});
assert.deepEqual([view.numbers[1].label, view.numbers[1].value, view.numbers[1].note],
  ["你对他的范围能赢", "21%", "按 AA 真人打法推算，他还可能有 312 种牌"]);
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
// After you acted: the last graded step stays up until your next turn.
const preflopGrade = {at: 1700000000, hand_id: "hand_9", street: "preflop", hero: ["Kc", "Tc"],
  board: [null, null, null, null, null], pot: "13", to_call: "4", stack: "160", dealer: 3,
  dealt: [0, 2, 3, 4, 5, 6, 7], facing: {slot: 6, kind: "raise", amount: "4", raises: 1},
  action: {kind: "call", amount: "4"}, chosen: "call", lost_big_blinds: 1.2, grade: "slip",
  options: [{action: "raise", big_blinds: 1.6, chips_in: "14", to: "14"},
    {action: "call", big_blinds: 0.4, chips_in: "4"}, {action: "fold", big_blinds: 0}]};
const riverGrade = {at: 1700000300, hand_id: "hand_12", street: "river", hero: ["4d", "4s"],
  board: ["6h", "8s", "Kd", "8h", "2d"], pot: "85", to_call: "28", stack: "160", dealer: 3,
  dealt: [0, 1, 2, 3, 4, 5, 6, 7], facing: {slot: 2, kind: "raise", amount: "28", raises: 1},
  action: {kind: "fold", amount: "0"}, chosen: "fold", frequency: 0.43, grade: "fine",
  advice: [{action: "call", frequency: 0.57}, {action: "fold", frequency: 0.43}]};
const grades = {schema_version: 1, hands: 87, graded: 2, best: 0, preflop_lost_big_blinds: 1.2,
  last: preflopGrade, rows: [riverGrade, preflopGrade]};
view = signalView(running(base({hero_controls_v1: {visible: false}, current_actor: 2, grade_v1: grades})), 0, {});
assert.equal(view.tone, "grade");
assert.equal(view.graded.word, "小失误"); assert.equal(view.graded.size, "−1.2");
assert.equal(view.graded.note, "这一步比最好的打法少赢 1.2 个大盲");
assert.deepEqual(view.graded.compare.map(item => [item.label, item.text, item.value, Boolean(item.best)]),
  [["你做了", "跟注 4", "+0.4 大盲", false], ["最好的打法", "加注到 14", "+1.6 大盲", true]]);
assert.deepEqual(view.tags, ["翻前", "你已行动 · 打分"]);
assert.match(view.price, /^\d\d:\d\d 这一步 · 下次轮到你之前一直显示$/);
assert.equal(view.context, "SB · 你，UTG 加注 4，底池 13，跟注要 4");
assert.deepEqual(view.cards.hero.map(card => card.rank + card.suit), ["Kc", "Tc"]);
assert.equal(view.potCap, "13"); assert.match(view.rule, /^怎么打分/);
// For the small window, which has no side panel: how the session is going.
assert.deepEqual(view.numbers.map(item => [item.label, item.value]), [["本场照着打", "0/2"], ["翻前少赢", "1.2"]]);
// The live table on the side and the session list stay current.
assert.equal(view.pot, "85"); assert.equal(view.header.session, "本场 87 手 · 照建议 0/2");
assert.deepEqual(view.session.stats.map(item => [item.label, item.value]),
  [["有建议的", "2"], ["照着打", "0"], ["翻前少赢", "1.2"]]);
assert.deepEqual(view.session.rows.map(item => [item.title, item.detail, item.grade, item.tone]), [
  ["河牌 · 4♦︎ 4♠︎", "你弃牌 · 求解器 43% 这样打", "可以", "fine"],
  ["翻前 · K♣︎ 10♣︎", "你跟注 4 · 最好加注到 14 · 少赢 1.2", "小失误", "slip"]]);
assert.match(view.session.rows[0].time, /^\d\d:\d\d$/);
// A solver grade: how often the solver does what you did, its mix, its most frequent action.
let graded = gradeView(riverGrade);
assert.deepEqual([graded.word, graded.size, graded.note], ["可以", "43%", "求解器 43% 的时候这样打"]);
assert.deepEqual(graded.compare.map(item => [item.label, item.text, item.value]),
  [["你做了", "弃牌", "求解器 43%"], ["求解器最常用", "跟注 28", "57%"]]);
assert.equal(gradeView({...riverGrade, chosen: "call", frequency: 0.57, grade: "best"}).compare[0].label,
  "你做了 · 就是求解器最常用的打法");
assert.deepEqual(graded.mix.map(item => item.percent), ["57%", "43%"]);
graded = gradeView({...riverGrade, action: {kind: "call", amount: "28"}, chosen: "call", frequency: 1, grade: "best",
  advice: [{action: "call", frequency: 1}]});
assert.deepEqual([graded.word, graded.note, graded.compare.length, graded.detail],
  ["最佳", "求解器每次都这样打", 1, "你跟注 28 · 求解器每次都这样打"]);
graded = gradeView({...riverGrade, street: "turn", to_call: "0", action: {kind: "raise", amount: "40"},
  chosen: "raise", frequency: 0.01, grade: "mistake", advice: [{action: "check", frequency: 0.99},
    {action: "bet", frequency: 0.01, chips: "30", to: "30"}]});
assert.deepEqual([graded.word, graded.note, graded.detail],
  ["错误", "求解器几乎从不这样打", "你下注 40 · 求解器几乎从不这样打"]);
// The best preflop option, or one worth about the same.
graded = gradeView({...preflopGrade, action: {kind: "raise", amount: "14"}, chosen: "raise",
  lost_big_blinds: 0, grade: "best"});
assert.deepEqual([graded.word, graded.size, graded.note, graded.detail, graded.compare.length],
  ["最佳", "", "就是最好的打法", "你加注 14 · 和建议一样", 1]);
assert.equal(graded.compare[0].label, "你做了 · 就是最好的打法");
graded = gradeView({...preflopGrade, lost_big_blinds: 0.02, grade: "best"});
assert.equal(graded.note, "和加注到 14 差不多，都可以");
// A value that rounds to zero has no sign.
graded = gradeView({...preflopGrade, options: [{action: "raise", big_blinds: 3.11, chips_in: "14", to: "14"},
  {action: "call", big_blinds: -0.04, chips_in: "4"}, {action: "fold", big_blinds: 0}], lost_big_blinds: 3.15});
assert.equal(graded.compare[0].value, "0.0 大盲");
// Your turn again: the advice, not the old grade.
view = signalView(running(base({...river, grade_v1: grades})), 0, {});
assert.equal(view.tone, "call"); assert.equal(view.verdict.word, "跟注");
// "行动后再看": on your turn the advice is held back until you act.
view = signalView(running(base({...river, grade_v1: grades})), 0, {}, {afterAct: true});
assert.equal(view.tone, "info"); assert.equal(view.title, "你先决定"); assert.equal(view.verdict, undefined);
assert.equal(view.numbers[0].value, "25%");
view = signalView(running(base({solver_advice_v1: states[0][0]})), 0, {}, {afterAct: true});
assert.equal(view.title, "你先决定");
view = signalView(running(base({solver_advice_v1: {status: "abstain", reason: "hand_incomplete"}})), 0, {},
  {afterAct: true});
assert.equal(view.title, "这一手不给建议");
// Equity against random hands overstates it against the hands still in: an upper bound.
view = signalView(running(base({solver_advice_v1: {status: "idle", reason: "more_than_one_opponent"}})), 0, {});
assert.match(view.note, /只当上限参考/);
// Nothing graded yet: an empty list that says when it fills.
const empty = sessionView({hands: 3, graded: 0, best: 0, preflop_lost_big_blinds: 0, last: null, rows: []});
assert.deepEqual([empty.pill, empty.rows, empty.empty],
  ["本场 3 手 · 照建议 0/0", [], "轮到你、有了建议、你做完以后，这里记一笔"]);
assert.equal(sessionView(undefined), null);
view = signalView(running(base({hero_controls_v1: {visible: false}})), 0, {});
assert.equal(view.session, null); assert.equal(view.header.session, null);
// The "录像" button: only while the capture card is being watched, with a running clock.
view = signalView(running(base()), 0, {});
assert.deepEqual(view.header.recording, {can: true, active: false, text: "录像", note: "", folder: ""});
view = signalView({...running(base()), source_kind: "video-replay"}, 0, {});
assert.equal(view.header.recording.can, false);
view = signalView({...running(base()), recording: {active: true, seconds: 65.4}}, 0, {});
assert.deepEqual([view.header.recording.active, view.header.recording.text], [true, "录制中 01:05"]);
view = signalView({...running(base()), recording: {active: true, seconds: 3725}}, 0, {});
assert.equal(view.header.recording.text, "录制中 1:02:05");
// After it stops (or after the service stops) it says what became of it.
const stopped = extra => signalView({status: "STOPPED", recording: {active: false, ...extra}}, 0, {}).header.recording;
assert.deepEqual(stopped({seconds: 1260, stopped_reason: "stopped", folder: "20261008-020000-live"}),
  {can: false, active: false, text: "录像", note: "已存好 · 21 分钟", folder: "20261008-020000-live"});
assert.equal(stopped({seconds: 12, stopped_reason: "source_stopped"}).note, "已存好 · 不到 1 分钟");
assert.equal(stopped({seconds: 7200, stopped_reason: "time_limit"}).note, "已存好 · 满 2 小时自动停");
assert.equal(stopped({seconds: 3, error: "the H.264 encoder did not open"}).note,
  "录像出错：the H.264 encoder did not open");
console.log("signal view cases passed");
