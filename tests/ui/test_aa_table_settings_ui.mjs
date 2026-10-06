// Exercises the shipped controls.js with scheduled GET/POST responses.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import {createDom, click, fire} from "../js/dom_stub.mjs";

const source = readFileSync(new URL("../../ui/aa-live/controls.js", import.meta.url), "utf8");
const response = data => ({ok:true, json:async () => data});
const settle = async () => { for (let i=0;i<8;i++) await Promise.resolve(); };
// Keep the startup fetch resolver so tests drive actual loading, not ready flags.
function fresh(docFactory) {
  const dom=createDom(), calls=[], views=[], effects={invalidations:0,hand:0,clears:0,polls:0};
  const timers=new Map();let timerId=0;
  let resolveInitial, fetchImpl=()=>new Promise(resolve=>{resolveInitial=resolve;});
  const context=vm.createContext({document:dom.document,console,el:dom.el,AbortController,
    setTimeout:callback=>{timers.set(++timerId,callback);return timerId;},clearTimeout:id=>timers.delete(id),
    headers:{"X-AA-Live":"1"},text:value=>String(value),statusData:{status:"STOPPED"},setInterval(){},
    showDesk:view=>views.push(view),clearCurrent:()=>effects.clears++,
    invalidateAnalysis:()=>effects.invalidations++,handRulesChanged:()=>effects.hand++,poll:async()=>effects.polls++,
    fetch:(url,options={})=>{calls.push({url,...options});return fetchImpl(url,options);}});
  const run=code=>vm.runInContext(code,context);run(source);
  const empty=Object.fromEntries(run("Object.entries(ruleFields)").map(([key,[,type]])=>[key,
    key==="table_label" ? "" : typeof type==="object" && !Array.isArray(type) ? "unknown" : null]));
  const packet=(document=empty,revision="r1")=>({document,revision,pending_fields:["big_blind"],unsupported_effects:[],conditional_analysis_ready:false});
  return {dom,run,calls,views,effects,empty,packet,timers,
    setFetch:fn=>{fetchImpl=fn;},async ready(){resolveInitial(response(packet(docFactory ? docFactory(empty) : empty)));await settle();}};
}

let cases=0;
{
  const h=fresh();
  assert.equal(h.dom.el("rules-save").disabled,true);
  await h.run("saveRules(false)");assert.equal(h.calls.length,1);
  await h.ready();
  assert.equal(h.dom.el("rule-small_blind").value,"");
  assert.equal(h.dom.el("rule-rake_percent").value,"");
  assert.equal(h.dom.el("rule-common_effective_stack_min_bb").value,"");
  assert.equal(h.dom.el("rules-details").open,true);
  assert.equal(h.dom.el("rules-more").open,false);
  assert.deepEqual(h.views,["settings"]);
  assert.match(h.dom.el("rules-summary").textContent,/盲注 未知\/未知/);
  assert.equal(h.dom.el("rule-rake_percent").parentNode.textContent,"%");
  assert.equal(h.dom.el("rule-rake_cap_bb").parentNode.textContent,"BB");
  cases++;
}
{
  const h=fresh(empty=>({...empty,table_label:"<img onerror=alert(1)>",dealt_players:7,ante:"0",rake_percent:"0"}));
  await h.ready();assert.deepEqual(h.views,[]);
  assert.match(h.dom.el("rules-summary").textContent,/前注 0.*抽水 0%/);
  assert.equal(h.dom.el("rules-summary-title").textContent,"<img onerror=alert(1)>");
  assert.equal(h.dom.state.innerHTMLWrites,0);
  h.dom.el("rule-small_blind").value="2";
  await click(h.dom.el("rules-edit"));
  assert.equal(h.dom.el("rule-small_blind").value,"2");assert.equal(h.calls.length,1);
  assert.equal(h.dom.el("rules-details").open,true);cases++;
}
{
  const h=fresh();await h.ready();
  h.dom.el("rule-table_label").value="未保存修改";
  h.setFetch(()=>response(h.packet({...h.empty,table_label:"另一页面的新配置",ante:"0"},"r2")));
  await click(h.dom.el("rules-cancel"));
  assert.equal(h.dom.el("rule-table_label").value,"另一页面的新配置");
  assert.equal(h.run("rulesRevision"),"r2");
  assert.equal(h.effects.hand,1);assert.equal(h.effects.invalidations,1);
  assert.ok(h.calls.every(call=>!call.method));cases++;
}
{
  const h=fresh();await h.ready();let finish;
  for(const [key,value] of Object.entries({ante:"0",rake_percent:"3",rake_cap_bb:"2",common_effective_stack_min_bb:"50",common_effective_stack_max_bb:"200"}))h.dom.el(`rule-${key}`).value=value;
  h.setFetch(()=>new Promise(resolve=>{finish=resolve;}));
  const saving=fire(h.dom.el("rules-form"),"submit",{preventDefault(){}});
  const posted=JSON.parse(h.calls.at(-1).body);
  assert.equal(posted.document.ante,"0");assert.equal(posted.document.small_blind,null);
  assert.equal(posted.document.rake_percent,"3");assert.equal(posted.document.rake_cap_bb,"2");
  assert.equal(posted.document.common_effective_stack_max_bb,"200");
  assert.equal(h.effects.hand,1);assert.equal(h.effects.invalidations,1);
  assert.equal(h.dom.el("rules-cancel").disabled,true);
  await h.run("saveRules(false)");await h.run("loadRules()");assert.equal(h.calls.length,2);
  finish(response(h.packet(posted.document,"r2")));await saving;
  assert.equal(h.run("rulesRevision"),"r2");
  assert.equal(h.dom.el("rules-status").textContent,"已保存 · 手动填写");
  assert.match(h.dom.el("rules-feedback").textContent,/观察已停止/);
  assert.match(h.dom.el("rules-summary").textContent,/50–200 BB/);
  assert.equal(h.effects.polls,1);assert.equal(h.dom.el("rules-save").disabled,false);cases++;
}
for(const failure of [
  {ok:false,json:async()=>({detail:"规则已被其他页面修改，请刷新后重试"})},
  {ok:false,json:async()=>{throw Error("HTTP 500 non-JSON");}},
  {ok:false,json:async()=>({detail:"常见有效筹码下限不能大于上限"})}
]){
  const h=fresh();await h.ready();h.dom.el("rule-common_effective_stack_min_bb").value="250";
  h.setFetch(()=>Promise.resolve(failure));await h.run("saveRules(false)");
  assert.equal(h.run("rulesRevision"),"r1");assert.equal(h.dom.el("rule-common_effective_stack_min_bb").value,"250");
  assert.match(h.dom.el("rules-feedback").textContent,/保存失败/);
  assert.equal(h.dom.el("rules-details").open,true);assert.equal(h.effects.polls,0);
  assert.equal(h.effects.hand,1);assert.equal(h.dom.el("rules-save").disabled,false);cases++;
}
{
  const h=fresh(empty=>({...empty,table_label:"测试桌",common_effective_stack_min_bb:"50",common_effective_stack_max_bb:"200"}));await h.ready();
  h.setFetch((url,options)=>response(h.packet(JSON.parse(options.body).document,"r2")));
  await click(h.dom.el("rules-reset"));
  const doc=JSON.parse(h.calls.at(-1).body).document;
  assert.deepEqual(doc,h.empty);assert.equal(h.dom.el("rules-status").textContent,"未配置");
  assert.equal(h.dom.el("rules-details").open,true);assert.match(h.dom.el("rules-feedback").textContent,/已清空/);cases++;
}
{
  const h=fresh();await h.ready();h.dom.el("rule-table_label").value="保留输入";
  h.setFetch(()=>Promise.reject(Error("network")));await click(h.dom.el("rules-cancel"));
  assert.equal(h.dom.el("rule-table_label").value,"保留输入");assert.equal(h.run("rulesRevision"),"r1");
  assert.match(h.dom.el("rules-feedback").textContent,/读取失败/);
  h.setFetch(()=>response(h.packet({...h.empty,table_label:"最新"},"r3")));
  await click(h.dom.el("rules-cancel"));assert.equal(h.dom.el("rule-table_label").value,"最新");cases++;
}
{
  const h=fresh();await h.ready();h.dom.el("rule-table_label").value="请求迟到";
  h.setFetch((url,options)=>new Promise((resolve,reject)=>options.signal.addEventListener("abort",()=>reject(Error("aborted")))));
  const saving=h.run("saveRules(false)");
  for(const timeout of [...h.timers.values()]) timeout();
  await saving;
  assert.match(h.dom.el("rules-feedback").textContent,/请求超时/);
  assert.equal(h.dom.el("rule-table_label").value,"请求迟到");
  assert.equal(h.dom.el("rules-cancel").disabled,false);assert.equal(h.run("rulesRevision"),"r1");
  assert.equal(h.timers.size,0);cases++;
}
console.log(`PASS: ${cases} AA table settings startup, units, cancel, save, failure and reset scenarios`);
