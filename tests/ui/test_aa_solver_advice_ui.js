"use strict";
// The solver advice panel, rendered by the shipped app.js in a minimal DOM.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const nodes = new Map();
class Element {
  constructor() { this.textContent = ""; this.children = []; this.options = [{}, {}]; }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  setAttribute() {}
  removeAttribute() {}
  addEventListener() {}
}
const element = id => {
  if (!nodes.has(id)) nodes.set(id, new Element());
  return nodes.get(id);
};
const document = {hidden: true, getElementById: element,
  createElement: () => new Element(), addEventListener() {}};
const context = vm.createContext({document, console, AbortController,
  performance: {now: () => 0}, setTimeout() {}, clearTimeout() {}, setInterval() {},
  fetch() { throw Error("hidden page must not poll"); }, URL: {revokeObjectURL() {}}});
vm.runInContext(fs.readFileSync(path.resolve(__dirname, "../../ui/aa-live/app.js"), "utf8"), context);
const render = (advice, history) =>
  vm.runInContext(`renderSolverAdvice(${JSON.stringify(advice)}, ${JSON.stringify(history)});`, context);
const texts = id => element(id).children.map(child => child.textContent);
const history = {actions: [
  {street: "preflop", slot: 4, kind: "call", amount: "4"},
  {street: "turn", slot: 2, kind: "raise", amount: "10"}]};

render({status: "ready", street: "turn", pot: "33", to_call: "10", pot_offset: "2", seconds: 3.2,
        advice: [{action: "call", frequency: 0.7},
                 {action: "raise", frequency: 0.2, chips: "30", to: "30"},
                 {action: "fold", frequency: 0.1}]}, history);
assert.equal(element("advice-status").textContent, "转牌：求解器给你这手牌的打法比例");
assert.deepEqual(texts("advice-rows"), ["跟注 · 70%", "加注到 30 · 20%", "弃牌 · 10%"]);
assert.equal(element("advice-detail").textContent, "底池 35（比 AA 规则算出的多 2，已按画面修正） · 要跟 10 · 用时 3.2 秒");
assert.deepEqual(texts("advice-history"), ["翻前 · 座位 4 · 跟注 4", "转牌 · 座位 2 · 加注 10"]);

render({status: "abstain", reason: "starts_after_preflop", street: "river"}, history);
assert.equal(element("advice-status").textContent, "这手牌不给建议：没有读到翻牌前下注，底池也不像暴击局");
assert.deepEqual(texts("advice-rows"), []);
assert.equal(element("advice-detail").textContent, "");

render({status: "idle", reason: "players_5"}, null);
assert.equal(element("advice-status").textContent, "5 人桌，规则模型只支持 6–8 人");
assert.deepEqual(texts("advice-history"), ["还没有动作"]);

render({status: "computing", street: "river"}, history);
assert.equal(element("advice-status").textContent, "河牌：正在计算…");

render({status: "ready", street: "preflop", pot: "23", to_call: "4", pot_offset: null,
        stacks_assumed: [6], seconds: 0.004,
        advice: [{action: "raise", frequency: 1.0, chips: "17", to: "17"}],
        options: [{action: "raise", chips: 27.1, big_blinds: 13.53, to: "17", chips_in: "17"},
                  {action: "call", chips: 11.9, big_blinds: 5.95, chips_in: "4"},
                  {action: "fold", chips: 0, big_blinds: 0}]}, history);
assert.equal(element("advice-status").textContent, "翻前：建议加注到 17（下面是每个选择平均值多少，比弃牌多赚为正）");
assert.deepEqual(texts("advice-rows"), ["加注到 17 · +13.5 个大盲（+27.1 筹码）",
  "跟注 · +6.0 个大盲（+11.9 筹码）", "弃牌 · 0.0 个大盲（0.0 筹码）"]);
assert.equal(element("advice-detail").textContent, "底池 23 · 要跟 4 · 座位 6 的筹码没读到，按很深计算 · 用时 0.004 秒");
render({status: "ready", street: "preflop", pot: "23", to_call: "4",
        advice: [{action: "fold", frequency: 1.0}],
        options: [{action: "fold", chips: 0, big_blinds: 0},
                  {action: "call", chips: -2.4, big_blinds: -1.2, chips_in: "4"}]}, history);
assert.equal(element("advice-status").textContent, "翻前：建议弃牌（下面是每个选择平均值多少，比弃牌多赚为正）");
assert.deepEqual(texts("advice-rows"), ["弃牌 · 0.0 个大盲（0.0 筹码）", "跟注 · −1.2 个大盲（−2.4 筹码）"]);

render({status: "idle", reason: "street_not_covered", street: "flop"}, history);
assert.equal(element("advice-status").textContent, "翻牌不计算（求解要约一分钟，来不及）");

render(null, null);
assert.equal(element("advice-status").textContent, "暂无（等待画面）");
console.log("solver advice panel cases passed");
