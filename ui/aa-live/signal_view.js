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
  const SUITS = {c: "♣︎", d: "♦︎", h: "♥︎", s: "♠︎"};
  const GRADES = {best: "最佳", fine: "可以", slip: "小失误", mistake: "错误"};
  const RULE = "怎么打分：翻前看比最好的选择少赢几个大盲；转牌、河牌看求解器多常这样打：" +
    "最常用或一半以上是“最佳”，两成以上“可以”，更少是“小失误”，几乎从不这样打是“错误”。";
  const MULTIWAY_RULE = "怎么打分：几个人的底池和单挑翻牌，按你对对手的牌能赢几成来定该怎么打。和建议一样是“最佳”；" +
    "不一样时看你能赢的离你那样打的线差多远：5 个点以内“可以”，15 个点以内“小失误”，更远是“错误”。";
  const one = value => (Math.round(value * 10) / 10).toFixed(1);
  // "+1.6", "−0.3", and "0.0" for anything that rounds to zero.
  const signed = value => {
    const text = one(Math.abs(value));
    return `${text === "0.0" ? "" : value > 0 ? "+" : "−"}${text}`;
  };

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
    return positionsOf(Number.isInteger(history?.dealer) ? history.dealer : row.dealer_seat, dealt);
  }

  function positionsOf(dealer, dealt) {
    const names = POSITIONS[dealt?.length];
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
  // A label followed straight by more words: "和跟注 2 差不多".
  const spaced = label => `${short(label)}${label.size ? " " : ""}`;
  const verb = row => row.label.word.replace("到", "");

  // Several opponents: why the share of the pot calls for this action.
  function multiwayReason(action, value, cut = {}) {
    const share = isNumber(value) ? pct(Number(value)) : "—";
    const line = name => (isNumber(cut[name]) ? pct(Number(cut[name])) : "—");
    return {
      bet: `你能赢 ${share}，超过 ${line("bet")} 就下注`,
      check: `你能赢 ${share}，不到 ${line("bet")} 就过牌`,
      raise: `你能赢 ${share}，超过 ${line("raise")} 就加注`,
      call: `你能赢 ${share}，跟注只要 ${line("call")} 就够`,
      fold: `你能赢 ${share}，跟注要 ${line("call")} 才够，不跟`,
    }[action] || `你能赢 ${share}`;
  }

  // One action from your share of the pot against the price, with the share
  // and the line it crossed as the reason.
  function multiwayVerdict(advice, controls, stack) {
    const row = (advice.advice || [])[0];
    if (!row) return null;
    const label = solverLabel(row, advice.to_call ?? controls.call_amount, stack);
    return {...label, kind: "multiway",
      note: multiwayReason(row.action, advice.range_equity?.value, advice.cuts)};
  }

  function readyVerdict(advice, controls, stack) {
    if (advice.kind === "multiway") return multiwayVerdict(advice, controls, stack);
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

  // -- after you acted: the grade of that step and this session's list -------

  // What you did, in words: "跟注 4", "下注 30", "全下 80".
  function didText(item) {
    const kind = item.action?.kind;
    const amount = chips(item.action?.amount);
    if (kind === "fold") return "弃牌";
    if (kind === "check") return "过牌";
    const word = kind === "call" ? "跟注" : kind === "all_in" ? "全下"
      : kind === "raise" ? (item.street !== "preflop" && !(Number(item.to_call) > 0) ? "下注" : "加注")
        : "动作没读清";
    return `${word}${amount && Number(amount) > 0 ? ` ${amount}` : ""}`;
  }

  const group = action => (["bet", "raise", "all_in"].includes(action) ? "raise" : action);

  function handText(cards) {
    return cardList(cards, 2).map(card => (card && !card.unread
      ? `${card.rank === "T" ? "10" : card.rank}${SUITS[card.suit]}` : "?")).join(" ");
  }

  function clockText(at) {
    if (!isNumber(at)) return "";
    const date = new Date(Number(at) * 1000);
    return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  }

  // One graded step: the grade word, how far off it was, and you vs the best.
  function gradeView(item) {
    const stack = num(item.stack);
    const did = didText(item);
    if (item.kind === "multiway") {
      const top = (item.advice || []).map(row => ({...row, label: solverLabel(row, item.to_call, stack)}))[0];
      const same = !top || group(top.label.action) === item.chosen;
      const share = isNumber(item.share) ? pct(Number(item.share)) : "—";
      const compare = [{label: same ? "你做了 · 就是建议的打法" : "你做了", text: did, value: "", best: same}];
      if (!same) compare.push({label: "按胜率该", text: short(top.label), value: "", best: true});
      return {word: GRADES[item.grade] || "", grade: item.grade, size: "",
        note: same ? `你能赢 ${share}，和建议一样` : multiwayReason(top.action, item.share, item.cuts),
        detail: same ? `你${did} · 和建议一样` : `你${did} · 建议${short(top.label)} · 能赢 ${share}`,
        compare, mix: []};
    }
    if (Array.isArray(item.options) && item.options.length) {
      const options = item.options.map(option => ({...option, label: preflopLabel(option, stack)}));
      const best = options[0], chosen = options.find(option => option.action === item.chosen);
      const lost = num(item.lost_big_blinds) ?? 0;
      const same = chosen === best;
      const compare = [{label: same ? "你做了 · 就是最好的打法" : "你做了", text: did, best: same,
        value: chosen ? `${signed(chosen.big_blinds)} 大盲` : ""}];
      if (!same) compare.push({label: "最好的打法", text: short(best.label), best: true,
        value: `${signed(best.big_blinds)} 大盲`});
      return {word: GRADES[item.grade] || "", grade: item.grade, size: lost >= 0.05 ? `−${one(lost)}` : "",
        note: lost >= 0.05 ? `这一步比最好的打法少赢 ${one(lost)} 个大盲`
          : same ? "就是最好的打法" : `和${spaced(best.label)}差不多，都可以`,
        detail: same ? `你${did} · 和建议一样` : lost < 0.05 ? `你${did} · 和${spaced(best.label)}差不多`
          : `你${did} · 最好${short(best.label)} · 少赢 ${one(lost)}`,
        compare, mix: []};
    }
    const rows = (item.advice || []).map(row => ({...row, label: solverLabel(row, item.to_call, stack)}));
    const share = num(item.frequency) ?? 0;
    const how = share >= 0.95 ? "求解器每次都这样打" : share < 0.02 ? "求解器几乎从不这样打"
      : `求解器 ${pct(share)} 的时候这样打`;
    const top = rows[0];
    const same = !top || group(top.label.action) === item.chosen;
    const compare = [{label: same ? "你做了 · 就是求解器最常用的打法" : "你做了", text: did,
      value: `求解器 ${pct(share)}`, best: same}];
    if (top && group(top.label.action) !== item.chosen)
      compare.push({label: "求解器最常用", text: short(top.label), value: pct(top.frequency), best: true});
    return {word: GRADES[item.grade] || "", grade: item.grade, size: pct(share), note: how,
      detail: `你${did} · ${share >= 0.95 || share < 0.02 ? how : `求解器 ${pct(share)} 这样打`}`, compare,
      mix: rows.filter((row, i) => i === 0 || row.frequency >= 0.01).map(row => ({
        text: short(row.label), tone: row.label.tone, share: row.frequency, percent: pct(row.frequency)}))};
  }

  // "CO，UTG 加注 4，底池 13，跟注要 4": the spot as it was.
  function gradeContext(item) {
    const names = positionsOf(item.dealer, item.dealt);
    const parts = [names[HERO] ? `${names[HERO]} · 你` : "你"];
    const facing = item.facing;
    if (facing) {
      const verb = facing.kind === "all_in" ? "全下"
        : item.street === "preflop" || facing.raises > 1 ? "加注" : "下注";
      parts.push(`${names[facing.slot] || `${facing.slot} 号位`} ${verb}${isNumber(facing.amount) &&
        Number(facing.amount) > 0 ? ` ${chips(facing.amount)}` : ""}`);
    }
    if (isNumber(item.pot)) parts.push(`底池 ${chips(item.pot)}`);
    parts.push(Number(item.to_call) > 0 ? `跟注要 ${chips(item.to_call)}` : "可以过牌");
    return parts.join("，");
  }

  // The grade, and (for the small window, which has no side panel) how this
  // session is going.
  function gradeScreen(item, grades) {
    const graded = gradeView(item);
    const lost = num(grades?.preflop_lost_big_blinds);
    return {tone: "grade", graded, title: graded.word, note: graded.note,
      rule: item.kind === "multiway" ? MULTIWAY_RULE : RULE,
      tags: [STREETS[item.street], "你已行动 · 打分"].filter(Boolean),
      price: `${clockText(item.at)} 这一步 · 下次轮到你之前一直显示`.trim(),
      cards: {hero: cardList(item.hero, 2, 2), board: cardList(item.board, 5, BOARD[item.street] ?? 0)},
      potCap: chips(item.pot), context: gradeContext(item), basis: ["只显示建议和打分，不替你点"],
      numbers: isNumber(grades?.graded) ? [{label: "本场照着打", value: `${grades.best}/${grades.graded}`, note: ""},
        {label: "翻前少赢", value: one(lost ?? 0), note: "大盲"}] : []};
  }

  // Betting is over with someone all in (one player may cover the rest) and cards still to come:
  // AA offers the player ahead insurance on the turn or river card, with up to 3 players in the pot.
  // Board cards flicker while they are dealt and at the showdown, so once all five were read with
  // the same seats, a board read as shorter again is not a new runout.
  function runout(row, street, memory) {
    const seats = row.seat_states_v1?.seats || {};
    const states = Object.values(seats).map(seat => seat?.state);
    const inHand = states.filter(state => IN_HAND.has(state));
    const key = Object.keys(seats).sort().map(seat => `${seat}:${seats[seat]?.state}`).join(",");
    const dealt = Math.max(BOARD[street] ?? 0, memory.runout?.key === key ? memory.runout.dealt : 0);
    memory.runout = {key, dealt};
    if (dealt >= 5 || !IN_HAND.has(seats[HERO]?.state) || inHand.length < 2 || !inHand.includes("all_in")
        || inHand.filter(state => state === "active").length > 1 || Number.isInteger(row.current_actor)
        || !(street in BOARD)) return null;
    return {players: inHand.length};
  }

  function runoutScreen(view, run) {
    const insurable = run.players <= 3;
    return {...view, tone: "info", tags: ["全下了", "等发牌"],
      title: insurable ? "保险别买" : "全下了，等发牌",
      note: insurable ? "如果弹出买保险，一般别买：AA 给的赔率比公平赔率低，买了通常亏掉保费的 2 到 5 成。"
        : "超过 3 个人，这一手不能买保险。",
      numbers: [{label: "底池", value: view.pot ?? "—", note: ""},
        {label: "还在局", value: `${run.players} 人`, note: ""}],
      basis: insurable ? ["按牌桌“保险说明”的赔率表算：每张补牌的赔率都低于公平赔率", "只显示建议，不替你点"]
        : ["只显示建议，不替你点"]};
  }

  function sessionView(grades) {
    if (!grades || !isNumber(grades.graded)) return null;
    return {pill: `本场 ${grades.hands} 手 · 照建议 ${grades.best}/${grades.graded}`,
      stats: [{label: "有建议的", value: String(grades.graded)},
        {label: "照着打", value: String(grades.best)},
        {label: "翻前少赢", value: one(num(grades.preflop_lost_big_blinds) ?? 0), unit: "大盲"}],
      rows: (grades.rows || []).slice(0, 6).map(item => ({time: clockText(item.at),
        title: `${STREETS[item.street] || ""} · ${handText(item.hero)}`, detail: gradeView(item).detail,
        grade: GRADES[item.grade] || "", tone: item.grade})),
      empty: "轮到你、有了建议、你做完以后，这里记一笔"};
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
    if (range && isNumber(range.value) && num(range.opponents) > 1) {
      list.push({label: "你对他们的牌能赢", value: pct(range.value),
        note: `按 AA 真人打法推算 ${range.opponents} 个对手可能拿的牌`});
    } else if (range && isNumber(range.value)) {
      list.push({label: "你对他的范围能赢", value: pct(range.value),
        note: isNumber(range.hands) ? `按 AA 真人打法推算，他还可能有 ${range.hands} 种牌` : "按 AA 真人打法推算他的牌"});
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

  function duration(seconds) {
    const total = Math.max(0, Math.floor(num(seconds) ?? 0));
    const h = Math.floor(total / 3600), m = Math.floor(total / 60) % 60, s = total % 60;
    const two = value => String(value).padStart(2, "0");
    return h ? `${h}:${two(m)}:${two(s)}` : `${two(m)}:${two(s)}`;
  }

  // The "录像" button: recording what the capture card shows, from the service.
  function recordingView(state, running) {
    const rec = state?.recording;
    const can = running && state?.source_kind === "capture-card";
    if (rec?.active) return {can: true, active: true, text: `录制中 ${duration(rec.seconds)}`, note: ""};
    const minutes = Math.round((num(rec?.seconds) ?? 0) / 60);
    const mb = num(rec?.megabytes);
    const size = mb === null || mb <= 0 ? "" : mb >= 1000 ? ` · ${one(mb / 1000)} GB` : ` · ${Math.max(1, Math.round(mb))} MB`;
    const note = !rec ? "" : rec.error ? `录像出错：${rec.error}`
      : rec.stopped_reason === "time_limit" ? `已存好 · 满 2 小时自动停${size}`
        : rec.stopped_reason === "low_disk_space" ? `已存好 · 磁盘快满了，自动停${size}`
          : `已存好 · ${minutes < 1 ? "不到 1" : minutes} 分钟${size}`;
    return {can, active: false, text: "录像", note, folder: rec?.folder || ""};
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
    const session = running ? sessionView(state.payload.grade_v1) : null;
    return {health, running: Boolean(running), session: session?.pill || null,
      recording: recordingView(state, Boolean(running)),
      active: ["STARTING", "RUNNING", "STALE", "STOPPING"].includes(status)};
  }

  // settings.afterAct: hold the advice back on your turn and only grade
  // what you did ("行动后再看").
  function signalView(state, now, memory = {}, settings = {}) {
    const top = header(state);
    const row = top.running ? state.payload : null;
    const base = {header: top, street: null, tags: [], cards: {hero: cardList(null, 2), board: cardList(null, 5)},
      pot: null, seats: [], log: [], numbers: [], basis: [], price: null, session: null};
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
        : {...base, tone: "warn", title: "画面看不清", note: `已经 ${Math.floor(blind)} 秒看不到牌桌：手机画面被挡住，或现在不是牌桌${
          state?.source_kind === "capture-card" ? "。一直这样的话，停止后换一个设备编号再开始" : ""}`};
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
      log: handLog(history, names, street, yourTurn), session: sessionView(row.grade_v1)};
    const waited = since(memory, "turn", yourTurn ? decisionKey(row, history) : null, now);
    const computing = yourTurn && advice?.status === "computing";
    const solving = since(memory, "solve", computing ? `${advice.hand_id}|${advice.street}|${advice.decision}` : null, now);
    view.tags = [view.street, yourTurn ? "轮到你" : null,
      yourTurn && waited !== null ? `已等 ${Math.floor(waited)} 秒` : null].filter(Boolean);
    const price = isNumber(controls.call_amount) ? controls.call_amount : advice?.to_call;
    if (yourTurn && (controls.button === "check" || isNumber(price))) {
      view.price = controls.button === "check" ? "现在可以过牌" : priceText(history, names, street, price, stack);
    }
    const run = runout(row, street, memory);
    if (run && !yourTurn) return runoutScreen(view, run);
    if (!yourTurn && row.grade_v1?.last) return {...view, ...gradeScreen(row.grade_v1.last, row.grade_v1)};
    if (!yourTurn) {
      const actor = Number.isInteger(row.current_actor) && row.current_actor !== HERO
        ? `${names[row.current_actor] || `${row.current_actor} 号位`} 在想` : null;
      return {...view, tone: "wait", tags: [view.street, actor].filter(Boolean),
        title: "还没轮到你", note: "轮到你时这里会整块亮起来",
        numbers: [{label: "底池", value: view.pot ?? "—", note: ""},
          {label: "还在局", value: `${view.seats.filter(seat => !seat.out).length} 人`, note: ""}]};
    }
    view.numbers = numbers(math, advice);
    if (settings.afterAct && (advice?.status === "ready" || computing)) {
      return {...view, tone: "info", title: "你先决定",
        note: "点完以后这里给这一步打分。想先看建议，点上面的“实时建议”。"};
    }
    if (advice?.status === "ready") {
      const verdict = readyVerdict(advice, controls, stack);
      if (verdict) {
        const basis = verdict.kind === "preflop" ? ["翻前算法", "后面的人按 AA 真人翻前打法推算"]
          : verdict.kind === "multiway" ? ["按胜率和价格定", advice.heads_up
            ? "翻牌求解要 40 秒左右，来不及；对手范围按 AA 真人打法推算"
            : "没有多人求解器，对手范围按 AA 真人打法推算"]
            : ["单挑求解器", "对手范围按 AA 真人打法推算"];
        if (isNumber(advice.seconds))
          basis[0] += Number(advice.seconds) < 0.01 ? " · 不到 0.01 秒算完" : ` · ${advice.seconds} 秒算完`;
        if (isNumber(advice.pot_offset) && Number(advice.pot_offset) > 0)
          basis.push(`底池比规则多 ${chips(advice.pot_offset)}，已算进去`);
        if (verdict.kind === "preflop" && isNumber(advice.mushroom_pool) && Number(advice.mushroom_pool) > 0)
          basis.push(`算上蘑菇池 ${chips(advice.mushroom_pool)}：你是小盲，赢下底池就一起拿走`);
        if (Array.isArray(advice.stacks_assumed) && advice.stacks_assumed.length)
          basis.push("有人筹码没读到，按很深算");
        if (num(advice.inferred_actions) > 0)
          basis.push(`有 ${advice.inferred_actions} 个动作没读到，按牌桌补上`);
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
    if (reason === "more_than_one_opponent" || reason === "heads_up_flop") {
      const many = reason === "more_than_one_opponent";
      return {...view, tone: "info", title: many ? "多人底池只给数字" : "单挑翻牌只给数字",
        note: isNumber(advice.range_equity?.value)
          ? `你的筹码没读到，定不了下多少。胜率按 AA 真人打法推算${many ? "每个对手" : "对手"}可能拿的牌，只当参考。`
          : "对手可能拿的牌推算不出来。胜率是对随机牌算的，真人的牌通常更强，你实际能赢的多半更少，只当上限参考。"};
    }
    if (reason === "your_cards_not_read") {
      return {...view, tone: "warn", title: "识别不全", note: "还没读到你的两张牌，这一步不给建议。"};
    }
    return {...view, tone: "info", title: "这一步不给建议", note: `${reasonText(reason)}。`};
  }

  const api = {signalView, positions, reasonText, gradeView, sessionView};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SignalView = api;
})(typeof window !== "undefined" ? window : globalThis);
