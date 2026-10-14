"use strict";
// "录像自动上传" in the settings view: the switch and what the uploader is
// doing (/api/upload). Without rclone set up it only says so.
(function () {
  const HEADERS = {"Content-Type": "application/json", "X-AA-Live": "1"};
  const REFRESH_MS = 15000;

  function nodes() {
    return {
      box: document.getElementById("upload-on"),
      tag: document.getElementById("upload-state"),
      text: document.getElementById("upload-status"),
    };
  }

  function render(state) {
    const {box, tag, text} = nodes();
    if (!box || !tag || !text) return;
    if (!state) {
      box.disabled = true;
      tag.textContent = "读不到";
      text.textContent = "暂时读不到上传状态，稍后自动再试。";
      return;
    }
    text.textContent = state.message || "";
    if (!state.available) {
      box.disabled = true;
      box.checked = false;
      tag.textContent = "不录像";
      return;
    }
    box.disabled = false;
    box.checked = Boolean(state.enabled);
    if (!state.enabled) tag.textContent = "已关";
    else if (!state.configured) tag.textContent = "未配置上传";
    else if (state.uploading) tag.textContent = "正在上传";
    else if (state.last_error) tag.textContent = "稍后重试";
    else tag.textContent = "已开";
  }

  async function load() {
    try {
      const response = await fetch("/api/upload", {cache: "no-store"});
      render(response.ok ? await response.json() : null);
    } catch (error) {
      render(null);
    }
  }

  async function toggle(event) {
    const box = event.target;
    box.disabled = true;
    try {
      const response = await fetch("/api/upload", {
        method: "POST", headers: HEADERS, body: JSON.stringify({on: box.checked}),
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
    setInterval(load, REFRESH_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
