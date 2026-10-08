"use strict";
// What the signal window shows, worked out from one /api/status reply.
// Pure functions, no DOM: signal.js draws the result, tests call it directly.
// Only data the service sends live is shown; anything missing gives an
// explicit state instead of a guessed number.
(function (root) {
  const STREETS = {preflop: "翻前", flop: "翻牌", turn: "转牌", river: "河牌"};
  // Clockwise from the dealer, as aa_rules_v2 names them.
  const POSITIONS = {
    5: ["BTN", "SB", "BB", "UTG", "CO"],
    6: ["BTN", "SB", "BB", "UTG", "HJ", "CO"],
    7: ["BTN", "SB", "BB", "UTG", "LJ", "HJ", "CO"],
    8: ["BTN", "SB", "BB", "UTG", "UTG+1", "LJ", "HJ", "CO"],
  };
  const HERO = 4;
  const BOARD = {preflop: 0, flop: 3, turn: 4, river: 5};
  // A missing read this soon after your buttons appear is usually the screen
  // settling (cards sliding in, a new street), so it waits before warning.
  const SETTLE_SECONDS = 1.5;
  // Between hands the phone shows animations the reader does not take as a
  // table; only a longer gap is worth a warning.
  const BLIND_SECONDS = 8;
  const DEALT = new Set(["active", "folded", "all_in"]);
  const IN_HAND = new Set(["active", "all_in"]);
  // Reasons the advice is held back because something on screen was not read.
  const READ_REASONS = new Set(["your_cards_not_read", "stack_unknown", "board_not_read",
    "raise_without_amount", "stacks_do_not_fit", "dealer_ambiguous", "no_dealer_fits",
    "not_this_seats_turn", "street_mismatch", "action_after_hand_end"]);
  const REASONS = {
    hand_incomplete: "这手牌是中途接上的，前面的动作不知道",
    starts_after_preflop: "没有翻前下注（多半是暴击局），规则模型不支持",
    not_this_seats_turn: "重放时轮到的人对不上，可能漏记了动作",
    street_mismatch: "重放时街道对不上",
    illegal_at_the_table: "有下注额在牌桌上不合法",
    raise_without_amount: "有一次加注没读到金额",
    stacks_do_not_fit: "筹码读数和下注对不上",
    stack_unknown: "你或对手的筹码没读到",
    board_not_read: "公共牌还没读全",
    your_cards_not_read: "还没读到你的两张牌",
    dealer_ambiguous: "庄位定不下来",
    no_dealer_fits: "找不到对得上的庄位",
    action_after_hand_end: "这手牌结束后还有动作",
    solver_not_installed: "这台电脑没装求解器",
    solver_error: "求解器出错了",
    own_hand_not_in_range: "你的牌不在推算的范围里",
    multiway_at_street_start: "这条街开始时不止两人",
    all_in: "已经全下，没有可选的动作",
    raise_not_in_solution: "对手的下注额不在求解树里",
    action_not_in_solution: "对手的动作不在求解树里",
  };

  const isNumber = value => value !== null && value !== undefined && value !== "" &&
    Number.isFinite(Number(value));
  const num = value => (isNumber(value) ? Number(value) : null);
  const chips = value => {
    const number = num(value);
    return number === null ? null : String(Math.round(number * 100) / 100);
  };
  const pct = value => `${Math.round(value * 100)}%`;
  const one = value => (Math.round(value * 10) / 10).toFixed(1);
  const signed = value => `${value > 0 ? "+" : value < 0 ? "−" : ""}${one(Math.abs(value))}`;

  function reasonText(reason) {
    if (typeof reason === "string" && reason.startsWith("players_"))
      return `${reason.slice(8)} 人桌，现在只支持 6–8 人`;
    return REASONS[reason] || "这一步的条件不够";
  }

  // seat -> position name, from the dealer and the seats dealt in.
  function positions(row, history) {
    const seats = row.seat_states_v1?.seats || {};
    const dealt = [];
    for (let seat = 0; seat < 8; seat++) if (DEALT.has(seats[seat]?.state)) dealt.push(seat);
    const dealer = Number.isInteger(history?.dealer) ? history.dealer : row.dealer_seat;
    const names = POSITIONS[dealt.length];
    const result = {};
    if (!names || !dealt.includes(dealer)) return result;
    const start = dealt.indexOf(dealer);
    dealt.slice(start).concat(dealt.slice(0, start)).forEach((seat, i) => { result[seat] = names[i]; });
    return result;
  }

  function seatName(seat, names) {
    if (seat === HERO) return names[seat] ? `${names[seat]} · 你` : "你";
    return names[seat] || `${seat} 号位`;
  }

  // A card, {unread: true} for one that should be there but was not read,
  // or null for a card not dealt (yet).
  function cardList(values, count, expected = 0) {
    const list = [];
    for (let i = 0; i < count; i++) {
      const value = Array.isArray(values) ? values[i] : null;
      const match = typeof value === "string" && /^([2-9TJQKA])([cdhs])$/i.exec(value);
      list.push(match ? {rank: match[1].toUpperCase(), suit: match[2].toLowerCase()}
        : i < expected ? {unread: true} : null);
    }
    return list;
  }

  function seatList(row, names, history) {
    const seats = row.seat_states_v1?.seats || {};
    const street = row.street_v1?.street;
    const bets = {};
    for (const action of history?.actions || []) {
      if (action.street !== street || !isNumber(action.amount)) continue;
      if (["call", "raise", "all_in"].includes(action.kind))
        bets[action.slot] = (bets[action.slot] || 0) + Number(action.amount);
    }
    const list = [];
    for (let seat = 0; seat < 8; seat++) {
      const state = seats[seat]?.state || "unknown";
      list.push({seat, name: seatName(seat, names), state, hero: seat === HERO,
        acting: row.current_actor === seat, dealer: row.dealer_seat === seat,
        stack: chips(row.stacks?.[seat]?.value), bet: bets[seat] ? chips(bets[seat]) : null,
        out: !IN_HAND.has(state)});
    }
    return list;
  }

  function actionText(action, names, opened) {
    const amount = chips(action.amount);
    const who = action.slot === HERO ? "你" : `${names[action.slot] || `${action.slot} 号位`} `;
    if (action.kind === "fold") return `${who}弃牌`;
    if (action.kind === "check") return `${who}过牌`;
    if (action.kind === "call") return `${who}跟注${amount ? ` ${amount}` : ""}`;
    if (action.kind === "all_in") return `${who}全下${amount ? ` ${amount}` : ""}`;
    const verb = opened ? "加注" : "下注";
    return `${who}${verb}${amount ? ` ${amount}` : ""}`;
  }

  function handLog(history, names, street, yourTurn) {
    const actions = Array.isArray(history?.actions) ? history.actions : [];
    const lines = [];
    for (const name of ["preflop", "flop", "turn", "river"]) {
      const here = actions.filter(action => action.street === name);
      if (!here.length && name !== street) continue;
      // Preflop the blinds are already a bet, so the first raise is a raise.
      let opened = name === "preflop";
      const parts = here.map(action => {
        const text = actionText(action, names, opened);
        if (action.kind === "raise" || action.kind === "all_in") opened = true;
        return text;
      });
      lines.push({street: STREETS[name], text: parts.join(" · "),
        yourTurn: yourTurn && name === street});
    }
    return lines;
  }

  // "CO 加注，跟注要 28": who you are facing and what calling costs.
  function priceText(history, names, street, price, stack) {
    const raises = (history?.actions || []).filter(action =>
      action.street === street && ["raise", "all_in"].includes(action.kind));
    const facing = raises[raises.length - 1];
    const verb = facing?.kind === "all_in" ? "全下"
      : street === "preflop" || raises.length > 1 ? "加注" : "下注";
    const who = facing ? `${names[facing.slot] || `${facing.slot} 号位`} ${verb}，` : "";
    const allIn = stack !== null && Number(price) >= stack;
    return `${who}跟注要 ${chips(allIn ? stack : price)}${allIn ? "（全下）" : ""}`;
  }

  function tone(action) {
    return {fold: "fold", check: "call", call: "call", bet: "raise", raise: "raise",
      all_in: "allin"}[action] || "info";
  }

  // The solver's row for a turn or river action, in words.
  function solverLabel(item, toCall, stack) {
    const size = chips(["bet", "raise"].includes(item.action) ? item.chips : null);
    if (size && stack !== null && Number(size) >= stack)
      return {action: "all_in", word: "全下", size, tone: "allin"};
    if (item.action === "check") return {action: "check", word: "过牌", size: null, tone: "call"};
    if (item.action === "fold") return {action: "fold", word: "弃牌", size: null, tone: "fold"};
    if (item.action === "call") {
      const price = num(toCall);
      const size = price !== null && stack !== null ? Math.min(price, stack) : price;
      return {action: "call", word: "跟注", tone: "call", size: size > 0 ? chips(size) : null};
    }
    if (item.action === "bet") return {action: "bet", word: "下注", size, tone: "raise"};
    return {action: "raise", word: "加注到", size: chips(item.to), tone: "raise"};
  }

  function preflopLabel(item, stack) {
    if (item.action === "fold") return {action: "fold", word: "弃牌", size: null, tone: "fold"};
    if (item.action === "check") return {action: "check", word: "过牌", size: null, tone: "call"};
    const put = num(item.chips_in);
    if (put !== null && stack !== null && put >= stack)
      return {action: "all_in", word: "全下", size: chips(stack), tone: "allin"};
    if (item.action === "call")
      return put ? {action: "call", word: "跟注", size: chips(put), tone: "call"}
        : {action: "check", word: "过牌", size: null, tone: "call"};
    return {action: "raise", word: "加注到", size: chips(item.to), tone: "raise"};
  }

  const short = label => `${label.word}${label.size ? ` ${label.size}` : ""}`;
  const verb = row => row.label.word.replace("到", "");

  function readyVerdict(advice, controls, stack) {
    if (Array.isArray(advice.options) && advice.options.length) {
      const options = advice.options.map(item => ({...item, label: preflopLabel(item, stack)}));
      const best = options[0], top = Math.max(...options.map(item => item.big_blinds), 0);
      const rest = options.slice(1).map(item => {
        const gap = best.big_blinds - item.big_blinds;
        const name = `${short(item.label)}${item.label.size ? " " : ""}`;
        return gap < 0.05 ? `和${name}差不多` : `比${name}多赢 ${one(gap)} 大盲`;
      });
      return {...best.label, kind: "preflop",
        note: rest.length ? rest.join("，") : "只有这一个选择",
        options: options.map((item, i) => ({text: short(item.label), tone: item.label.tone,
          value: `${signed(item.big_blinds)} 大盲`, best: i === 0,
          width: top > 0 && item.big_blinds > 0 ? Math.round(item.big_blinds / top * 100) : 0}))};
    }
    const toCall = advice.to_call ?? controls.call_amount;
    const rows = (advice.advice || []).map(item => ({...item, label: solverLabel(item, toCall, stack)}));
    if (!rows.length) return null;
    const top = rows[0], share = top.frequency;
    const note = share >= 0.95 ? "求解器每次都这样打"
      : share >= 0.8 ? "求解器几乎总是这样打"
        : rows.length < 2 ? "求解器这样打"
          : share >= 0.5 ? `混合打法：大多数时候${verb(top)}，有时${verb(rows[1])}`
            : `混合打法：${verb(top)}和${verb(rows[1])}都常用，${verb(top)}稍多`;
    return {...top.label, kind: "solver", note,
      mix: rows.filter((item, i) => i === 0 || item.frequency >= 0.01).map(item => ({
        text: short(item.label), tone: item.label.tone, share: item.frequency, percent: pct(item.frequency)}))};
  }

  function numbers(math, advice) {
    const list = [];
    const odds = math?.pot_odds;
    if (odds?.available) {
      list.push({label: "要赢多少才不亏", value: pct(odds.required_equity),
        note: `跟 ${chips(odds.call)}，底池会到 ${chips(Number(odds.pot) + Number(odds.call))}`});
    } else if (odds?.reason === "nothing_to_call") {
      list.push({label: "要赢多少才不亏", value: "0%", note: "现在不用跟注"});
    }
    const range = advice?.range_equity;
    const equity = math?.equity;
    if (range && isNumber(range.value)) {
      list.push({label: "你对他的范围能赢", value: pct(range.value), note: "按 AA 真人打法推算他的牌"});
    } else if (equity?.available) {
      list.push({label: "对随机牌能赢", value: pct(equity.value),
        note: `${equity.opponents} 个对手；真人的牌通常更强`});
    }
    const spr = math?.spr;
    if (spr?.available) {
      list.push({label: "有效筹码", value: chips(spr.effective_stack),
        note: `是底池的 ${one(spr.value)} 倍`});
    }
    return list;
  }

  // One decision: this hand, this street, and how often you already acted on it
  // (an opponent's action read late does not restart the count).
  function decisionKey(row, history) {
    const street = row.street_v1?.street ?? "?";
    const mine = (history?.actions || []).filter(action =>
      action.street === street && action.slot === HERO).length;
    return `${history?.hand_id ?? "?"}|${street}|${mine}`;
  }

  // memory keeps when the current decision and the current solve were first
  // seen, so "已等 N 秒" counts from the moment your buttons appeared.
  function since(memory, slot, key, now) {
    if (!key) { memory[slot] = null; return null; }
    if (!memory[slot] || memory[slot].key !== key) memory[slot] = {key, at: now};
    return Math.max(0, (now - memory[slot].at) / 1000);
  }

  function header(state) {
    const status = String(state?.status || "STOPPED").toUpperCase();
    const ms = num(state?.processing_ms);
    const running = status === "RUNNING" && state?.payload;
    const source = {"capture-card": "采集卡", "video-replay": "录像回放",
      "development-replay": "开发回放"}[state?.source_kind] || "";
    const health = running ? {tone: "good", text: `${source || "画面"} · 识别正常${ms !== null ? ` · ${Math.round(ms)} 毫秒` : ""}`}
      : status === "STALE" ? {tone: "bad", text: "画面断了"}
        : status === "ERROR" ? {tone: "bad", text: "出错了"}
          : status === "STARTING" ? {tone: "neutral", text: "正在启动"}
            : status === "ENDED" ? {tone: "neutral", text: "录像放完了"}
              : {tone: "neutral", text: "还没开始"};
    return {health, running: Boolean(running),
      active: ["STARTING", "RUNNING", "STALE", "STOPPING"].includes(status)};
  }

  function signalView(state, now, memory = {}) {
    const top = header(state);
    const row = top.running ? state.payload : null;
    const base = {header: top, street: null, tags: [], cards: {hero: cardList(null, 2), board: cardList(null, 5)},
      pot: null, seats: [], log: [], numbers: [], basis: [], price: null};
    if (!row) {
      since(memory, "turn", null, now); since(memory, "solve", null, now);
      const stale = String(state?.status).toUpperCase() === "STALE";
      return {...base, tone: stale ? "warn" : "wait",
        title: stale ? "画面断了" : top.active ? "等画面" : "还没开始",
        note: stale ? "超过 3 秒没有新画面，旧的牌面已经清掉" : top.active ? "第一帧马上就到"
          : "选好来源，点“开始”"};
    }
    if (row.scene_supported !== true) {
      since(memory, "turn", null, now); since(memory, "solve", null, now);
      const blind = since(memory, "blind", "scene", now);
      return blind < BLIND_SECONDS
        ? {...base, tone: "wait", title: "看不到牌桌", note: "多半是两手牌之间的动画，牌桌回来就接着读"}
        : {...base, tone: "warn", title: "画面看不清", note: `已经 ${Math.floor(blind)} 秒看不到牌桌：手机画面被挡住，或现在不是牌桌`};
    }
    since(memory, "blind", null, now);
    const history = row.action_history_v1;
    const names = positions(row, history);
    const controls = row.hero_controls_v1 || {};
    const advice = row.solver_advice_v1 || null;
    const math = row.table_math_v1 || {};
    const street = row.street_v1?.street || advice?.street || null;
    const yourTurn = controls.visible === true;
    const stack = num(row.stacks?.[HERO]?.value);
    const view = {...base, street: STREETS[street] || null,
      cards: {hero: cardList(row.cards?.hero, 2, IN_HAND.has(row.seat_states_v1?.seats?.[HERO]?.state) ? 2 : 0),
        board: cardList(row.cards?.board_slots, 5, BOARD[street] ?? 0)},
      pot: chips(row.pot?.value), seats: seatList(row, names, history),
      log: handLog(history, names, street, yourTurn)};
    const waited = since(memory, "turn", yourTurn ? decisionKey(row, history) : null, now);
    const computing = yourTurn && advice?.status === "computing";
    const solving = since(memory, "solve", computing ? `${advice.hand_id}|${advice.street}|${advice.decision}` : null, now);
    view.tags = [view.street, yourTurn ? "轮到你" : null,
      yourTurn && waited !== null ? `已等 ${Math.floor(waited)} 秒` : null].filter(Boolean);
    const price = isNumber(controls.call_amount) ? controls.call_amount : advice?.to_call;
    if (yourTurn && (controls.button === "check" || isNumber(price))) {
      view.price = controls.button === "check" ? "现在可以过牌" : priceText(history, names, street, price, stack);
    }
    if (!yourTurn) {
      const actor = Number.isInteger(row.current_actor) && row.current_actor !== HERO
        ? `${names[row.current_actor] || `${row.current_actor} 号位`} 在想` : null;
      return {...view, tone: "wait", tags: [view.street, actor].filter(Boolean),
        title: "还没轮到你", note: "轮到你时这里会整块亮起来",
        numbers: [{label: "底池", value: view.pot ?? "—", note: ""},
          {label: "还在局", value: `${view.seats.filter(seat => !seat.out).length} 人`, note: ""}]};
    }
    view.numbers = numbers(math, advice);
    if (advice?.status === "ready") {
      const verdict = readyVerdict(advice, controls, stack);
      if (verdict) {
        const basis = verdict.kind === "preflop" ? ["翻前算法", "后面的人按 AA 真人翻前打法推算"]
          : ["单挑求解器", "对手范围按 AA 真人打法推算"];
        if (isNumber(advice.seconds)) basis[0] += ` · ${advice.seconds} 秒算完`;
        if (isNumber(advice.pot_offset) && Number(advice.pot_offset) > 0)
          basis.push(`底池比规则多 ${chips(advice.pot_offset)}，已算进去`);
        if (Array.isArray(advice.stacks_assumed) && advice.stacks_assumed.length)
          basis.push("有人筹码没读到，按很深算");
        basis.push("只显示建议，不替你点");
        return {...view, tone: verdict.tone, verdict, basis};
      }
    }
    if (computing) {
      return {...view, tone: "busy", title: "正在算",
        note: `已算 ${Math.floor(solving ?? 0)} 秒，通常 1–4 秒。先看价格：`};
    }
    const reason = advice?.reason;
    if (READ_REASONS.has(reason) && waited < SETTLE_SECONDS) {
      return {...view, tone: "info", title: "稍等", note: "还在读画面，读清楚就开始算。"};
    }
    if (advice?.status === "abstain") {
      const read = READ_REASONS.has(reason);
      return {...view, tone: read ? "warn" : "info", title: read ? "识别不全" : "这一手不给建议",
        note: `${reasonText(reason)}，这一步不给建议。`};
    }
    if (reason === "waiting_for_last_action" || !advice) {
      return {...view, tone: "info", title: "稍等", note: "对手刚才的动作还没读出来，读到后马上开始算。"};
    }
    if (reason === "street_not_covered") {
      const flop = (advice.street || street) === "flop";
      return {...view, tone: "info", title: `${STREETS[advice.street] || view.street || "这条街"}不给打法`,
        note: flop ? "翻牌算一次要 40 秒左右，来不及。下面的数是实时的：" : "这条街现在不给建议。下面的数是实时的："};
    }
    if (reason === "more_than_one_opponent") {
      return {...view, tone: "info", title: "多人底池不给打法",
        note: "胜率是对随机牌算的，真人的牌通常更强，只当下限参考。"};
    }
    if (reason === "your_cards_not_read") {
      return {...view, tone: "warn", title: "识别不全", note: "还没读到你的两张牌，这一步不给建议。"};
    }
    return {...view, tone: "info", title: "这一步不给建议", note: `${reasonText(reason)}。`};
  }

  const api = {signalView, positions, reasonText};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SignalView = api;
})(typeof window !== "undefined" ? window : globalThis);
