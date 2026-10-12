"use strict";
// "A new version is out" strip in the corner of the window. Only the
// installed Windows program answers /api/update; anywhere else it stays hidden.
(function () {
  const CHECK_EVERY_MS = 6 * 60 * 60 * 1000;
  const HEADERS = {"Content-Type": "application/json", "X-AA-Live": "1"};
  let box = null;

  function element() {
    if (box) return box;
    box = document.createElement("div");
    box.id = "update-banner";
    box.setAttribute("role", "status");
    box.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:9999;" +
      "max-width:360px;padding:12px 14px;border-radius:10px;background:#10251a;" +
      "color:#e8fff1;border:1px solid #45D483;font:14px/1.5 sans-serif;" +
      "box-shadow:0 6px 24px rgba(0,0,0,.35)";
    document.body.appendChild(box);
    return box;
  }

  function hide() {
    if (box) box.hidden = true;
  }

  function show(text, button, onClick) {
    const node = element();
    node.hidden = false;
    node.textContent = "";
    const line = document.createElement("div");
    line.textContent = text;
    node.appendChild(line);
    if (button) {
      const action = document.createElement("button");
      action.type = "button";
      action.textContent = button;
      action.style.cssText = "margin-top:8px;padding:6px 14px;border:0;" +
        "border-radius:8px;background:#45D483;color:#05140B;font-weight:700;" +
        "cursor:pointer";
      action.addEventListener("click", onClick);
      node.appendChild(action);
    }
  }

  function render(state) {
    if (!state || !state.configured) return hide();
    if (state.status === "AVAILABLE") {
      if (state.can_install) {
        return show(`有新版本 ${state.latest}（现在是 ${state.current}）。` +
                    "点更新后程序会关掉、自动安装、再自己打开。", "立即更新", install);
      }
      return show(`有新版本 ${state.latest}，请找给你安装包的人要新安装包。`);
    }
    if (state.status === "DOWNLOADING") {
      const percent = state.total ? Math.floor(100 * state.received / state.total) : 0;
      return show(`正在下载新版本 ${state.latest || ""}…… ${percent}%`);
    }
    if (state.status === "INSTALLING") {
      return show("下载完成、校验通过，正在安装。装好后程序会自己打开，这个页面可以关掉。");
    }
    if (state.status === "ERROR" && state.installing === false && state.attempted) {
      return show(`这次没更新成功：${state.error}`, "再试一次", install);
    }
    return hide();
  }

  async function status() {
    try {
      const response = await fetch("/api/update", {cache: "no-store"});
      return response.ok ? await response.json() : null;
    } catch (error) {
      return null;
    }
  }

  async function poll() {
    const state = await status();
    if (state) render(state);
    return state;
  }

  async function install() {
    show("正在下载新版本……");
    const watch = setInterval(poll, 1000);
    try {
      const response = await fetch("/api/update/install", {
        method: "POST", headers: HEADERS, body: "{}"});
      const state = response.ok ? await response.json() :
        {status: "ERROR", error: await response.text(), configured: true};
      render({...state, attempted: true});
      if (state.status === "INSTALLING") clearInterval(watch);
    } catch (error) {
      // The program closes itself to be replaced; a lost connection then is expected.
    } finally {
      const state = await status();
      if (!state || state.status !== "DOWNLOADING") clearInterval(watch);
    }
  }

  async function check() {
    try {
      const response = await fetch("/api/update/check", {
        method: "POST", headers: HEADERS, body: "{}"});
      if (response.ok) render(await response.json());
    } catch (error) {
      // Offline or the program is closing: try again next time.
    }
  }

  async function start() {
    let state = await poll();
    if (!state || !state.configured) return;
    for (let tries = 0; state && state.status === "NOT_CHECKED" && tries < 10; tries++) {
      await new Promise((resolve) => setTimeout(resolve, 3000));
      state = await poll();
    }
    setInterval(check, CHECK_EVERY_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
