"use strict";
// Signal window: polls /api/status and draws what SignalView works out.
(function () {
  // While the colour field floats in the always-on-top small window its
  // elements live in that window's document.
  let pip = null;
  const el = id => pip?.document.getElementById(id) || document.getElementById(id);
  const headers = {"X-AA-Live": "1"};
  const SUITS = {c: "♣", d: "♦", h: "♥", s: "♠"};
  const now = () => globalThis.performance?.now?.() ?? Date.now();
  let memory = {}, generation = null, instance = null, sequence = null, progressAt = 0;
  let status = {}, pending = false, modeTouched = false;
  // The capture card's device number on this Mac (it can swap with the
  // built-in camera), remembered in this browser.
  const DEVICE_KEY = "pokersense.signal.device";
  try { const saved = localStorage.getItem(DEVICE_KEY); if (saved !== null) el("device").value = saved; }
  catch (ignored) { /* storage can be unavailable */ }
  // "行动后再看": hold the advice back on your turn, grade what you did.
  const ADVICE_KEY = "pokersense.signal.advice";
  let afterAct = false;
  try { afterAct = localStorage.getItem(ADVICE_KEY) === "after"; }
  catch (ignored) { /* storage can be unavailable */ }

  function node(tag, className, text) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined && text !== null) item.textContent = text;
    return item;
  }

  function cards(id, list) {
    el(id).replaceChildren(...list.map(card => {
      if (!card || card.unread) {
        const empty = node("span", card ? "card empty unread" : "card empty", card ? "?" : "");
        empty.setAttribute("aria-label", card ? "没读到" : "还没发");
        return empty;
      }
      const item = node("span", `card ${card.suit}`);
      item.append(node("span", null, card.rank === "T" ? "10" : card.rank), node("span", null, `${SUITS[card.suit]}︎`));
      item.setAttribute("aria-label", `${card.rank}${card.suit}`);
      return item;
    }));
  }

  function renderSignal(view) {
    el("signal").className = `signal tone-${view.tone}`;
    el("tags").replaceChildren(...view.tags.map(tag => node("span", "tag", tag)));
    el("price").textContent = view.price || "";
    cards("hero-cards", view.cards.hero);
    cards("board-cards", view.cards.board);
    const pot = view.potCap ?? view.pot;
    el("board-cap").textContent = pot ? `公共牌 · 底池 ${pot}` : "公共牌";
    el("context").hidden = !view.context;
    el("context").textContent = view.context || "";
    const verdict = view.verdict || view.graded;
    el("word").textContent = verdict ? verdict.word : view.title;
    el("word").className = verdict ? "word" : "word status";
    el("size").textContent = verdict?.size || "";
    el("note").textContent = verdict ? verdict.note : view.note || "";
    const mix = verdict?.mix || [];
    el("mix").hidden = !mix.length;
    el("mix").setAttribute("aria-label", `求解器打法：${mix.map(item => `${item.text} ${item.percent}`).join("，")}`);
    el("mix").replaceChildren(...mix.map(item => {
      const seg = node("div", `seg ${item.tone}${item.share < 0.12 ? " thin" : ""}`);
      seg.style.flex = `${Math.max(item.share, 0.001)} 1 0`;
      if (item.share >= 0.12) seg.append(node("span", null, item.text), node("b", null, item.percent));
      else if (item.share >= 0.05) seg.append(node("b", null, item.percent));
      return seg;
    }));
    const options = verdict?.options || [];
    el("options").hidden = !options.length;
    el("options").replaceChildren(...options.map(item => {
      const row = node("div", `opt${item.best ? " best" : ""}`);
      const bar = node("span", `opt-bar ${item.tone}`);
      bar.style.width = item.width > 0 ? `${item.width}%` : "4px";
      row.append(node("span", null, item.text), bar, node("span", "opt-value", item.value));
      return row;
    }));
    const compare = view.graded?.compare || [];
    el("compare").hidden = !compare.length;
    el("compare").replaceChildren(...compare.map(item => {
      const box = node("div", `cmp${item.best ? " best" : ""}`);
      box.append(node("span", null, item.label), node("b", null, item.text));
      if (item.value) box.append(node("small", null, item.value));
      return box;
    }));
    el("rule").hidden = !view.rule;
    el("rule").textContent = view.rule || "";
    el("numbers").replaceChildren(...view.numbers.map(item => {
      const box = node("div");
      box.append(node("span", null, item.label), node("b", null, item.value));
      if (item.note) box.append(node("small", null, item.note));
      return box;
    }));
  }

  function renderSide(view) {
    const felt = node("div", "felt");
    felt.append(node("span", null, "底池"), node("b", null, view.pot ?? "—"));
    el("table").replaceChildren(felt, ...view.seats.map(seat => {
      const classes = ["seat", `s${seat.seat}`];
      if (seat.out && !seat.hero) classes.push("out");
      if (seat.hero) classes.push("hero"); else if (seat.bet) classes.push("bet");
      if (seat.acting && !seat.hero) classes.push("acting");
      const box = node("div", classes.join(" "));
      box.append(node("span", null, `${seat.name}${seat.dealer ? " · 庄" : ""}`));
      if (seat.state === "empty") box.append(node("span", null, "空位"));
      else if (seat.state === "folded") box.append(node("span", null, "弃牌"));
      else {
        if (seat.bet) box.append(node("b", null, `本轮 ${seat.bet}`));
        const stack = node("span", null, "剩 ");
        stack.append(node("span", "num", seat.stack ?? "?"));
        box.append(stack);
      }
      return box;
    }));
    const log = view.log.flatMap(line => {
      const text = node("span", null, line.text || (line.yourTurn ? "" : "还没有动作"));
      if (line.yourTurn) text.append(node("span", "now", `${line.text ? " · " : ""}轮到你`));
      return [node("span", "st", line.street), text];
    });
    if (!log.length) log.push(node("span", "st", ""), node("span", null, "还没有这一手的动作"));
    el("log").replaceChildren(...log);
    el("basis").replaceChildren(...view.basis.map(text => node("span", "pill", text)));
    const session = view.session;
    el("session-block").hidden = !session;
    if (!session) return;
    el("session-stats").replaceChildren(...session.stats.map(item => {
      const box = node("div");
      const value = node("b", null, item.value);
      if (item.unit) value.append(node("small", null, ` ${item.unit}`));
      box.append(node("span", "label", item.label), value);
      return box;
    }));
    const rows = session.rows.map(item => {
      const line = node("div", "srow");
      const text = node("div");
      text.append(node("strong", null, item.title), node("small", null, item.detail));
      line.append(node("span", "num", item.time), text, node("span", `grade ${item.tone}`, item.grade));
      return line;
    });
    el("session-rows").replaceChildren(...(rows.length ? rows : [node("p", "muted", session.empty)]));
  }

  function renderHeader(view) {
    el("health").className = `pill ${view.header.health.tone}`;
    el("health-text").textContent = view.header.health.text;
    const available = {"capture-card": status.capture_available === true,
      "video-replay": status.video_available === true,
      "development-replay": status.replay_available === true};
    for (const option of el("mode").options) option.hidden = option.disabled = !available[option.value];
    const running = status.source_options?.mode;
    if (view.header.active && available[running]) el("mode").value = running;
    else if (!modeTouched && !available[el("mode").value])
      el("mode").value = Object.keys(available).find(mode => available[mode]) || "capture-card";
    el("mode").disabled = view.header.active || pending;
    const device = status.source_options?.device_index;
    if (view.header.active && Number.isInteger(device) && device >= 0 && device <= 2) el("device").value = String(device);
    el("device").hidden = el("mode").value !== "capture-card";
    el("device").disabled = view.header.active || pending;
    el("start").disabled = view.header.active || pending || !available[el("mode").value] ||
      status.profile?.ready === false;
    el("stop").disabled = !view.header.active && !pending;
    el("session").hidden = !view.header.session;
    el("session").textContent = view.header.session || "";
    el("advice-live").setAttribute("aria-pressed", String(!afterAct));
    el("advice-after").setAttribute("aria-pressed", String(afterAct));
    el("float").hidden = !("documentPictureInPicture" in window) || Boolean(pip);
    const mini = pip?.document.getElementById("mini-state");
    if (mini) mini.textContent = view.street ? `· ${view.street}` : `· ${view.header.health.text}`;
  }

  function draw(state) {
    const view = SignalView.signalView(state, now(), memory, {afterAct});
    renderHeader(view); renderSignal(view); renderSide(view);
  }

  function error(message) { el("error").textContent = message || ""; el("error").hidden = !message; }

  async function poll() {
    if (pending || (document.hidden && !pip)) return;
    const abort = new AbortController(), timeout = setTimeout(() => abort.abort(), 2500);
    try {
      const response = await fetch("/api/status", {headers, cache: "no-store", signal: abort.signal});
      if (!response.ok) throw Error(`HTTP ${response.status}`);
      const state = await response.json();
      if (state.instance_id !== instance || state.generation !== generation) {
        instance = state.instance_id; generation = state.generation; memory = {}; sequence = null;
      }
      if (state.sequence !== sequence) { sequence = state.sequence; progressAt = now(); }
      status = state; error(state.error ? String(state.error) : "");
      const frozen = String(state.status).toUpperCase() === "RUNNING" && state.payload &&
        now() - progressAt > 3000;
      draw(frozen ? {...state, status: "STALE", payload: null} : state);
      el("speed").textContent = Number.isFinite(state.processing_ms)
        ? `每帧 ${(state.processing_ms / 1000).toFixed(2)} 秒` : "";
    } catch (failure) {
      status = {...status, status: "ERROR", payload: null};
      draw({status: "ERROR"}); error(`连不上本机服务：${failure.message}`);
    } finally { clearTimeout(timeout); }
  }

  async function command(action) {
    pending = true; error(""); draw({...status, payload: null});
    const abort = new AbortController(), timeout = setTimeout(() => abort.abort(), 15000);
    try {
      const body = action === "start" ? {mode: el("mode").value, device_index: Number(el("device").value),
        api: status.capture_api_default || "AVFOUNDATION", fps: 30} : {};
      const response = await fetch(`/api/${action}`, {method: "POST",
        headers: {...headers, "Content-Type": "application/json"}, body: JSON.stringify(body), signal: abort.signal});
      const result = await response.json();
      if (!response.ok) {
        const detail = result.detail?.message || result.detail || result.error || `HTTP ${response.status}`;
        throw Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }
    } catch (failure) { error(`没有${action === "start" ? "开始" : "停止"}：${failure.message}`); }
    finally { clearTimeout(timeout); pending = false; memory = {}; await poll(); }
  }

  el("source-form").addEventListener("submit", event => {
    event.preventDefault(); if (!el("start").disabled) command("start");
  });
  el("stop").addEventListener("click", () => command("stop"));
  el("mode").addEventListener("change", () => { modeTouched = true; draw({...status, payload: null}); });
  for (const [id, value] of [["advice-live", false], ["advice-after", true]]) {
    el(id).addEventListener("click", () => {
      afterAct = value;
      try { localStorage.setItem(ADVICE_KEY, value ? "after" : "live"); } catch (ignored) { /* not kept */ }
      draw(status);
    });
  }
  el("device").addEventListener("change", () => {
    try { localStorage.setItem(DEVICE_KEY, el("device").value); } catch (ignored) { /* not kept */ }
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
  // Hidden (another tab, minimised) the page stops polling but says it is
  // still open, so the service keeps the source running for it.
  setInterval(() => {
    if (document.hidden) fetch("/api/heartbeat", {headers, cache: "no-store"}).catch(() => {});
  }, 20000);
  // The small window: Chrome's document picture-in-picture keeps it above
  // every other window. The colour field moves into it, and back when it
  // closes. Polling runs on the small window's timers while it is open,
  // since a hidden tab's timers are slowed down.
  let loop = 0;
  function run(host) {
    const mine = ++loop;
    (async function tick() {
      if (mine !== loop) return;
      await poll();
      if (mine === loop) host.setTimeout(tick, 250);
    })();
  }

  function dock() {
    if (!pip) return;
    const section = pip.document.getElementById("signal");
    pip = null;
    if (section) el("floating").before(section);
    el("floating").hidden = true;
    draw(status); run(window);
  }

  async function float() {
    if (pip || !("documentPictureInPicture" in window)) return;
    let small;
    try { small = await documentPictureInPicture.requestWindow({width: 380, height: 600}); }
    catch (failure) { error(`没有打开置顶小窗：${failure.message}`); return; }
    const head = small.document.head;
    for (const link of document.querySelectorAll('link[rel="stylesheet"], link[rel="preconnect"]')) {
      const copy = small.document.createElement("link");
      copy.rel = link.rel; copy.href = link.href;
      head.append(copy);
    }
    small.document.title = "PokerSense";
    small.document.documentElement.lang = "zh-CN";
    small.document.body.className = "mini";
    const bar = small.document.createElement("div");
    bar.className = "mini-bar";
    const name = small.document.createElement("strong");
    name.textContent = "PokerSense";
    const state = small.document.createElement("span");
    state.id = "mini-state";
    const back = small.document.createElement("button");
    back.type = "button"; back.textContent = "回到大窗口";
    back.addEventListener("click", () => small.close());
    bar.append(name, state, back);
    const shell = small.document.createElement("main");
    shell.className = "layout";
    shell.append(el("signal"));
    small.document.body.append(bar, shell);
    el("floating").hidden = false;
    pip = small;
    small.addEventListener("pagehide", dock);
    draw(status); run(small);
  }

  el("float").addEventListener("click", float);
  el("unfloat").addEventListener("click", () => pip?.close());
  draw({status: "STOPPED"});
  run(window);
})();
