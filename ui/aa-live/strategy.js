"use strict";
// "建议用哪套打法" in the settings view: the switch between the old advice
// (classic) and the one page of 《一页纸打法》 (plain), /api/strategy.
(function () {
  const HEADERS = {"Content-Type": "application/json", "X-AA-Live": "1"};

  function nodes() {
    return {
      box: document.getElementById("strategy-plain"),
      tag: document.getElementById("strategy-state"),
      text: document.getElementById("strategy-status"),
    };
  }

  function render(state) {
    const {box, tag, text} = nodes();
    if (!box || !tag || !text) return;
    if (!state) {
      box.disabled = true;
      tag.textContent = "读不到";
      text.textContent = "暂时读不到开关，稍后再试。";
      return;
    }
    const plain = state.strategy === "plain";
    box.disabled = false;
    box.checked = plain;
    tag.textContent = plain ? "一页纸" : "原来的打法";
    text.textContent = (plain
      ? "现在按一页纸打法给建议：每条建议带定生死的那一条规则、三个数和翻转条件。"
      : "现在按原来的打法给建议（翻前算法、单挑求解器、按胜率和价格）。")
      + (state.saved ? "" : "这个窗口不保存开关，重开回到"
         + (state.default === "plain" ? "一页纸打法。" : "原来的打法。"));
  }

  async function load() {
    try {
      const response = await fetch("/api/strategy", {cache: "no-store"});
      render(response.ok ? await response.json() : null);
    } catch (error) {
      render(null);
    }
  }

  async function toggle(event) {
    const box = event.target;
    box.disabled = true;
    try {
      const response = await fetch("/api/strategy", {
        method: "POST", headers: HEADERS,
        body: JSON.stringify({strategy: box.checked ? "plain" : "classic"}),
      });
      if (response.ok) return render(await response.json());
    } catch (error) {
      // fall through: show what the service has
    }
    await load();
  }

  function init() {
    const {box} = nodes();
    if (!box) return;
    box.addEventListener("change", toggle);
    load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
