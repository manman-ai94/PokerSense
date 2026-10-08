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
// From the capture card it may be the wrong device (the Mac camera); the pill
// no longer says the reading is fine, and a small picture shows what comes in.
assert.match(view.note, /换一个设备编号/);
assert.equal(view.thumbnail, true);
assert.deepEqual(view.header.health, {tone: "warn", text: "采集卡 · 看不到牌桌"});
// A device the service picked because it shows the phone: no number to try.
const found = (check, seen) => ({...running({...base(), scene_supported: false}),
  source_options: {mode: "capture-card", device_index: 1, device_check: check, device_seen: seen}});
view = signalView(found("phone_between_black_bars", {"0": "other", "1": "phone"}), 9000, {});
assert.equal(view.title, "看不到牌桌");
view = signalView(found("phone_between_black_bars", {"1": "phone"}), 9000, blind);
assert.equal(view.title, "画面看不清"); assert.doesNotMatch(view.note, /设备编号/);
// No device showed the phone: said at once, in words that say what came in.
for (const [seen, pill, words] of [
  [{"0": "other", "1": null}, "只认到摄像头", /^Mac 只认到电脑自带的摄像头/],
  [{"0": "other", "1": "dark"}, "没有画面", /^采集卡接上了，但收不到手机画面/],
  [{"0": null, "1": null}, "没认到采集卡", /^Mac 没认到采集卡/]]) {
  view = signalView(found("no_phone_found", seen), 0, {});
  assert.equal(view.tone, "warn"); assert.equal(view.title, "没找到手机画面");
  assert.match(view.note, words); assert.equal(view.thumbnail, true);
  assert.deepEqual(view.header.health, {tone: "warn", text: `采集卡 · ${pill}`});
}
// The cameras macOS lists, when the service knows them.
view = signalView({...found("no_phone_found", {"0": "other"}), capture_available: true,
  capture_devices: ["FaceTime HD Camera"]}, 0, {});
assert.match(view.note, /（Mac 现在认到的摄像头：FaceTime HD Camera）$/);
view = signalView({status: "STOPPED", capture_available: true, capture_devices: ["FaceTime HD Camera", "USB Video"]}, 0, {});
assert.equal(view.note, "选好来源，点“开始”。Mac 现在认到的摄像头：FaceTime HD Camera、USB Video");
assert.equal(signalView({status: "STOPPED", capture_available: true, capture_devices: null}, 0, {}).note,
  "选好来源，点“开始”");
// While the table is read, the pill says so as before.
view = signalView({...found("no_phone_found", {"0": "other"}), payload: base()}, 0, {});
assert.match(view.header.health.text, /^采集卡 · 识别正常/); assert.equal(view.thumbnail, undefined);

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
// A new price is a new decision too, even when your action before it was not read.
view = signalView(running(base({hero_controls_v1: {visible: true, button: "call", call_amount: "28"}})), 6000, memory);
view = signalView(running(base({hero_controls_v1: {visible: true, button: "call", call_amount: "80"}})), 9000, memory);
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
assert.ok(!view.basis.some(line => line.includes("蘑菇池")));
// As the small blind the mushroom pool read on the table is counted.
view = signalView(running({...pre, solver_advice_v1: {...pre.solver_advice_v1, mushroom_pool: "48"}}), 0, {});
assert.ok(view.basis.includes("算上蘑菇池 48：你是小盲，赢下底池就一起拿走"));
assert.ok(!view.basis.some(line => line.includes("本场看到")));
view = signalView(running({...pre, solver_advice_v1: {...pre.solver_advice_v1, reads_hands: 37}}), 0, {});
assert.ok(view.basis.includes("各对手爱不爱入池、加注，按本场看到的 37 手调整"));
assert.ok(view.seats.every(seat => seat.read === null));
view = signalView(running({...pre, solver_advice_v1: {...pre.solver_advice_v1,
  seat_reads: {"3": {hands: 20, vpip: 0.7, pfr: 0.1, tag: "loose"}, "5": {hands: 20, vpip: 0.3, pfr: 0.1, tag: null}}}}), 0, {});
assert.equal(view.seats[3].read, "很松");
assert.equal(view.seats[5].read, null);
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
  [{status: "idle", reason: "more_than_one_opponent"}, "info", "多人底池只给数字"],
  [{status: "idle", reason: "heads_up_flop"}, "info", "单挑翻牌只给数字"],
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
// A report from before the session counts (no actions or chips yet): what there is.
assert.deepEqual(view.session.stats.map(item => [item.label, item.value, item.unit]),
  [["有建议", "2", undefined], ["照着打", "0/2", undefined], ["输赢 · 大盲", "—", undefined]]);
assert.equal(view.session.spread, "最佳 0 · 可以 0 · 小失误 0 · 错误 0 · 翻前少赢 1.2 大盲");
const counted = sessionView({...grades, decisions: 5, advised: 4, grades: {best: 0, fine: 1, slip: 1, mistake: 0},
  net_big_blinds: -12.5, rebuys: 1});
assert.deepEqual(counted.stats.map(item => [item.label, item.value, item.unit]),
  [["有建议", "4/5", undefined], ["照着打", "0/2", undefined], ["输赢 · 大盲", "−12.5", undefined]]);
assert.equal(counted.spread, "最佳 0 · 可以 1 · 小失误 1 · 错误 0 · 翻前少赢 1.2 大盲 · 补码 1 次不算输赢");
assert.equal(sessionView({...grades, net_big_blinds: 3}).stats[2].value, "+3.0");
assert.equal(sessionView({...grades, net_big_blinds: -234.5}).stats[2].value, "−235");
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
// With more than one opponent (or on the flop) the equity against their ranges arrives a moment later.
view = signalView(running(base({solver_advice_v1: {status: "idle", reason: "more_than_one_opponent",
  range_equity: {value: 0.42, opponents: 2, hands: null, hands_each: {"2": 315, "6": 103}}}})), 0, {});
assert.deepEqual([view.numbers[1].label, view.numbers[1].value, view.numbers[1].note],
  ["你对他们的牌能赢", "42%", "按 AA 真人打法推算 2 个对手可能拿的牌"]);
assert.match(view.note, /^你的筹码没读到/);
view = signalView(running(base({street_v1: {street: "flop"}, solver_advice_v1: {status: "idle",
  reason: "street_not_covered", street: "flop", range_equity: {value: 0.6, opponents: 1, hands: 240}}})), 0, {});
assert.equal(view.title, "翻牌不给打法");
assert.deepEqual([view.numbers[1].label, view.numbers[1].note], ["你对他的范围能赢", "按 AA 真人打法推算，他还可能有 240 种牌"]);
// Equity against random hands overstates it against the hands still in: an upper bound.
view = signalView(running(base({solver_advice_v1: {status: "idle", reason: "more_than_one_opponent"}})), 0, {});
assert.match(view.note, /只当上限参考/);
// With several opponents the range rule's action, its reason and its basis.
const multiway = (row, extra = {}) => base({solver_advice_v1: {status: "ready", kind: "multiway",
  advice: [row], cuts: {call: 0.248, raise: 0.6}, to_call: "28", pot: "85", seconds: 0.4, stacks_assumed: [],
  range_equity: {value: 0.31, opponents: 2, hands: null, hands_each: {"2": 300, "6": 120}}, ...extra}});
view = signalView(running(multiway({action: "call", frequency: 1.0})), 0, {});
assert.deepEqual([view.tone, view.verdict.word, view.verdict.size, view.verdict.kind], ["call", "跟注", "28", "multiway"]);
assert.equal(view.verdict.note, "你能赢 31%，跟注只要 25% 就够");
assert.deepEqual(view.basis, ["按胜率和价格定 · 0.4 秒算完", "没有多人求解器，对手范围按 AA 真人打法推算",
  "只显示建议，不替你点"]);
assert.equal(view.numbers[1].label, "你对他们的牌能赢");
// The heads-up flop by the same rule, and an action the table filled in.
view = signalView(running(multiway({action: "call", frequency: 1.0}, {heads_up: true, inferred_actions: 1,
  range_equity: {value: 0.31, opponents: 1, hands: 240}})), 0, {});
assert.deepEqual(view.basis, ["按胜率和价格定 · 0.4 秒算完", "翻牌求解要 40 秒左右，来不及；对手范围按 AA 真人打法推算",
  "有 1 个动作没读到，按牌桌补上", "只显示建议，不替你点"]);
assert.equal(view.numbers[1].label, "你对他的范围能赢");
// A bomb pot says so in the basis.
view = signalView(running(multiway({action: "call", frequency: 1.0}, {bomb_pot: "14"})), 0, {});
assert.ok(view.basis.includes("暴击局：每人先投 14，直接发翻牌"));
assert.ok(!view.basis.some(line => line.includes("本场看到")));
// The ranges follow each opponent's reads once there are some.
view = signalView(running(multiway({action: "call", frequency: 1.0}, {reads_hands: 37})), 0, {});
assert.ok(view.basis.includes("各对手的范围按本场看到的 37 手调整：爱加注的人下注时诈唬多算一些"));
view = signalView(running(multiway({action: "fold", frequency: 1.0},
  {range_equity: {value: 0.18, opponents: 3}})), 0, {});
assert.deepEqual([view.tone, view.verdict.word, view.verdict.note], ["fold", "弃牌", "你能赢 18%，跟注要 25% 才够，不跟"]);
view = signalView(running(multiway({action: "raise", frequency: 1.0, chips: "90", to: "90"},
  {range_equity: {value: 0.71, opponents: 2}})), 0, {});
assert.deepEqual([view.verdict.word, view.verdict.size, view.verdict.note], ["加注到", "90", "你能赢 71%，超过 60% 就加注"]);
view = signalView(running(multiway({action: "bet", frequency: 1.0, chips: "56", to: "56"},
  {cuts: {bet: 0.4}, to_call: "0", range_equity: {value: 0.47, opponents: 2}})), 0, {});
assert.deepEqual([view.tone, view.verdict.word, view.verdict.size, view.verdict.note],
  ["raise", "下注", "56", "你能赢 47%，超过 40% 就下注"]);
view = signalView(running(multiway({action: "bet", frequency: 1.0, chips: "160", to: "160"},
  {cuts: {bet: 0.4}, to_call: "0", range_equity: {value: 0.8, opponents: 2}})), 0, {});
assert.deepEqual([view.tone, view.verdict.word], ["allin", "全下"]);
view = signalView(running(multiway({action: "check", frequency: 1.0},
  {cuts: {bet: 0.4}, to_call: "0", range_equity: {value: 0.33, opponents: 2}})), 0, {});
assert.deepEqual([view.verdict.word, view.verdict.note], ["过牌", "你能赢 33%，不到 40% 就过牌"]);
// After you acted: graded by how far your share was from where your action starts.
const multiwayGrade = {kind: "multiway", street: "turn", hero: ["4d", "4s"], board: ["6h", "8s", "Kd", "8h"],
  stack: "160", to_call: "28", pot: "85", dealer: 3, dealt: [2, 4, 6], at: 1000,
  action: {kind: "fold", amount: null}, advice: [{action: "call", frequency: 1.0}],
  cuts: {call: 0.248, raise: 0.6}, chosen: "fold", share: 0.31, gap: 0.062, grade: "slip"};
graded = gradeView(multiwayGrade);
assert.deepEqual([graded.word, graded.size, graded.note], ["小失误", "", "你能赢 31%，跟注只要 25% 就够"]);
assert.equal(graded.detail, "你弃牌 · 建议跟注 28 · 能赢 31%");
assert.deepEqual(graded.compare.map(row => [row.label, row.text]), [["你做了", "弃牌"], ["按胜率该", "跟注 28"]]);
graded = gradeView({...multiwayGrade, action: {kind: "call", amount: "28"}, chosen: "call", gap: 0, grade: "best"});
assert.deepEqual([graded.word, graded.size, graded.note, graded.compare.length], ["最佳", "", "你能赢 31%，和建议一样", 1]);
view = signalView(running(base({hero_controls_v1: {visible: false}, current_actor: 2,
  grade_v1: {hands: 1, graded: 1, best: 0, preflop_lost_big_blinds: 0, last: multiwayGrade, rows: [multiwayGrade]}})), 0, {});
assert.equal(view.tone, "grade"); assert.match(view.rule, /几个人的底池/);
// Nothing graded yet: an empty list that says when it fills.
const empty = sessionView({hands: 3, graded: 0, best: 0, preflop_lost_big_blinds: 0, last: null, rows: []});
assert.deepEqual([empty.pill, empty.rows, empty.empty],
  ["本场 3 手 · 照建议 0/0", [], "轮到你、有了建议、你做完以后，这里记一笔"]);
assert.equal(sessionView(undefined), null);
view = signalView(running(base({hero_controls_v1: {visible: false}})), 0, {});
assert.equal(view.session, null); assert.equal(view.header.session, null);
// All in with cards to come: AA may offer insurance, which the table prices below fair.
const allIn = (states, extra = {}) => running(base({current_actor: null, hero_controls_v1: {visible: false},
  seat_states_v1: seats(states), street_v1: {street: "turn"}, ...extra}));
const headsUp = ["folded", "folded", "all_in", "folded", "all_in", "folded", "folded", "folded"];
view = signalView(allIn(headsUp), 0, {});
assert.deepEqual([view.tone, view.title, view.tags], ["info", "保险别买", ["全下了", "等发牌"]]);
assert.match(view.note, /^如果弹出买保险，一般别买.*2 到 5 成。$/);
assert.deepEqual(view.numbers.map(item => [item.label, item.value]), [["底池", "85"], ["还在局", "2 人"]]);
assert.match(view.basis[0], /赔率都低于公平赔率/);
// You cover the player all in: the betting is over too.
view = signalView(allIn(["folded", "folded", "all_in", "folded", "active", "folded", "folded", "folded"]), 0, {});
assert.equal(view.title, "保险别买");
// Four players in the pot cannot buy insurance.
view = signalView(allIn(["all_in", "folded", "all_in", "folded", "all_in", "active", "folded", "folded"]), 0, {});
assert.deepEqual([view.title, view.note], ["全下了，等发牌", "超过 3 个人，这一手不能买保险。"]);
// Someone still to act, two players still betting, the river out, or you folded: not this screen.
assert.equal(signalView(allIn(headsUp, {current_actor: 6}), 0, {}).title, "还没轮到你");
assert.equal(signalView(allIn(["folded", "folded", "active", "folded", "all_in", "active", "folded", "folded"]),
  0, {}).title, "还没轮到你");
assert.equal(signalView(allIn(headsUp, {street_v1: {street: "river"}}), 0, {}).title, "还没轮到你");
assert.equal(signalView(allIn(["folded", "all_in", "all_in", "folded", "folded", "folded", "folded", "folded"]),
  0, {}).title, "还没轮到你");
// Once all five cards were read with the same seats, a board read short again (dealing, showdown) is not a new runout.
const flicker = {};
signalView(allIn(headsUp, {street_v1: {street: "river"}}), 0, flicker);
assert.equal(signalView(allIn(headsUp, {street_v1: {street: "preflop"}}), 100, flicker).title, "还没轮到你");
// It comes before the grade of the all in, which stays in this session's list.
view = signalView(allIn(headsUp, {grade_v1: grades}), 0, {});
assert.equal(view.title, "保险别买"); assert.equal(view.session.rows.length, grades.rows.length);
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
assert.equal(stopped({seconds: 1260, stopped_reason: "stopped", megabytes: 52.96}).note, "已存好 · 21 分钟 · 53 MB");
assert.equal(stopped({seconds: 3600, stopped_reason: "low_disk_space", megabytes: 1530}).note,
  "已存好 · 磁盘快满了，自动停 · 1.5 GB");
assert.equal(stopped({seconds: 3, error: "the H.264 encoder did not open"}).note,
  "录像出错：the H.264 encoder did not open");
console.log("signal view cases passed");
