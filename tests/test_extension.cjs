const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const policy = require('../extension/policy.js');
const root = path.resolve(__dirname, process.env.STAYLOCKED_FIREFOX ? '../extension-firefox' : '../extension');
function event() { const callbacks=[]; return {addListener:f=>callbacks.push(f), emit:(...a)=>callbacks.forEach(f=>f(...a))}; }
(async () => {
  assert.deepEqual(policy.domains(['www.youtube.com', 'youtube.com']), ['youtube.com']);
  assert.equal(policy.match('https://m.youtube.com/watch?v=x',['youtube.com']), 'youtube.com');
  assert.equal(policy.match('https://notyoutube.com/',['youtube.com']), null);
  assert.equal(policy.match('https://youtube.com.evil.test/',['youtube.com']), null);
  assert.equal(policy.match('https://example.com/?next=youtube.com',['youtube.com']), null);
  for (const url of ['chrome://settings/', 'chrome://new-tab-page/', 'opera://startpage/',
    'opera://settings/', 'edge://newtab/', 'about:blank', 'chrome-search://local-ntp/',
    'chrome-extension://other/page.html', 'file:///C:/example.html',
    'https://www.google.com/search?q=youtube.com', 'https://www.bing.com/search?q=youtube.com',
    'https://duckduckgo.com/?q=youtube.com', 'browser://newtab/', 'about:newtab',
    'https://yandex.ru/search/?text=youtube.com']) {
    assert.equal(policy.match(url, ['youtube.com']), null, url);
  }
  const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));
  for (const key of ['chrome_url_overrides','chrome_settings_overrides','omnibox'])
    assert.equal(manifest[key], undefined, `Extension must not control ${key}`);
  for (const rule of policy.rules(['youtube.com'], 'chrome-extension://test/blocked.html')) {
    assert.ok(new RegExp(rule.condition.regexFilter).test('https://www.youtube.com/'));
    assert.ok(!new RegExp(rule.condition.regexFilter).test('chrome://new-tab-page/'));
    assert.ok(!new RegExp(rule.condition.regexFilter).test('opera://startpage/'));
  }
  assert.equal(policy.active({domains:['youtube.com'],until:100},101),false);
  assert.equal(policy.rules([], 'chrome-extension://test/blocked.html').length,0);
  let now = 100000, rules=[], saved={}, nextId=0;
  const protectedUrls = ['https://www.google.com/search?q=youtube.com', 'https://www.bing.com/search?q=youtube.com',
    'https://duckduckgo.com/?q=youtube.com', 'chrome://new-tab-page/', 'opera://startpage/', 'about:blank'];
  const tabs=[{id:1,url:'https://www.youtube.com/watch?v=1'}, {id:2,url:'https://example.com/'},
    ...protectedUrls.map((url, i) => ({id:i+3,url}))];
  const port={onMessage:event(),onDisconnect:event(),postMessage(){},disconnect(){this.onDisconnect.emit();}};
  const chrome={
    runtime:{id:'test',getURL:file=>'chrome-extension://test/'+file,connectNative:()=>port,
      onMessage:event(),onStartup:event(),onInstalled:event()},
    storage:{local:{get:async()=>saved,set:async value=>{saved={...saved,...value};}}},
    declarativeNetRequest:{getSessionRules:async()=>rules,updateSessionRules:async value=>{rules=value.addRules;}},
    tabs:{query:async()=>tabs, get:async id=>tabs.find(t=>t.id===id),
      update:async(id,value)=>Object.assign(tabs.find(t=>t.id===id),value),onUpdated:event()},
    webNavigation:{onBeforeNavigate:event(),onCommitted:event(),onHistoryStateUpdated:event(),onReferenceFragmentUpdated:event()},
    alarms:{create:async()=>{},onAlarm:event()},
    action:{setBadgeText:async()=>{},setBadgeBackgroundColor:async()=>{}}
  };
  class Clock extends Date {static now(){return now;}}
  const context=vm.createContext({[process.env.STAYLOCKED_FIREFOX ? 'browser' : 'chrome']:chrome,console,URL,Date:Clock,setInterval:()=>++nextId,setTimeout:()=>++nextId});
  if (process.env.STAYLOCKED_FIREFOX) {
    assert.equal(manifest.browser_specific_settings.gecko.id, 'staylocked@staylocked.local');
    assert.deepEqual(manifest.background.scripts, ['policy.js','background.js']);
    assert.equal(manifest.background.service_worker,undefined);
    vm.runInContext(fs.readFileSync(path.join(root,'policy.js'),'utf8'),context);
  } else context.importScripts=file=>vm.runInContext(fs.readFileSync(path.join(root,file),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(root,'background.js'),'utf8'),context);
  await vm.runInContext('chain',context);
  port.onMessage.emit({protocol:1,state:'active',domains:['www.youtube.com'],remainingSeconds:60,sessionId:'first'});
  await vm.runInContext('chain',context);
  assert.equal(rules.length,3);
  assert.ok(tabs[0].url.startsWith('chrome-extension://test/blocked.html'));
  assert.equal(tabs[1].url,'https://example.com/');
  for (let i=0;i<protectedUrls.length;i++) {
    const tab = tabs[i+2];
    chrome.tabs.onUpdated.emit(tab.id,{url:tab.url,status:'loading'},tab);
    chrome.webNavigation.onBeforeNavigate.emit({tabId:tab.id,frameId:0,url:tab.url});
    chrome.webNavigation.onCommitted.emit({tabId:tab.id,frameId:0,url:tab.url});
  }
  await vm.runInContext('chain',context);
  assert.deepEqual(tabs.slice(2).map(t=>t.url),protectedUrls);
  // Old YouTube event arrives while a new-tab or search navigation is pending.
  for (const next of protectedUrls) {
    tabs[0].url='https://youtube.com/watch?v=old';
    tabs[0].pendingUrl=next;
    chrome.webNavigation.onCommitted.emit({tabId:1,frameId:0,url:tabs[0].url});
    await vm.runInContext('chain',context);
    assert.equal(tabs[0].url,'https://youtube.com/watch?v=old');
    assert.equal(tabs[0].pendingUrl,next);
  }
  delete tabs[0].pendingUrl;
  // Simulate navigation served from service-worker cache (DNR may not run).
  tabs[0].url='https://www.youtube.com/@channel';
  chrome.webNavigation.onCommitted.emit({tabId:1,frameId:0,url:tabs[0].url});
  await vm.runInContext('chain',context);
  assert.ok(tabs[0].url.startsWith('chrome-extension://test/blocked.html'));
  port.disconnect();
  await vm.runInContext('chain',context);
  assert.equal(rules.length,3); // Do not unlock early on transient disconnect.
  now += 61000;
  chrome.alarms.onAlarm.emit({name:'focuslock-heartbeat'});
  await vm.runInContext('chain',context);
  assert.equal(rules.length,0); // No indefinite lock if bridge fails.
  port.onMessage.emit({protocol:1,state:'active',domains:['youtube.com'],remainingSeconds:60,sessionId:'second'});
  await vm.runInContext('chain',context);
  assert.equal(rules.length,3);
  port.onMessage.emit({protocol:1,state:'idle',domains:[],remainingSeconds:0});
  await vm.runInContext('chain',context);
  assert.equal(rules.length,0); // Worker ended or Windows rebooted.
  port.onMessage.emit({protocol:2,state:'active',domains:['youtube.com'],remainingSeconds:15,mode:'until_reboot',sessionId:'service'});
  await vm.runInContext('chain',context);
  assert.equal(rules.length,3);
  assert.equal(vm.runInContext('current().mode',context),'until_reboot');
  for(let i=0;i<4;i++) {
    now+=14000;
    port.onMessage.emit({protocol:2,state:'active',domains:['youtube.com'],remainingSeconds:15,mode:'until_reboot',sessionId:'service'});
    await vm.runInContext('chain',context);
    assert.equal(rules.length,3); // lease renews for the entire reboot session
  }
  now+=16000;
  chrome.alarms.onAlarm.emit({name:'focuslock-heartbeat'});
  await vm.runInContext('chain',context);
  assert.equal(rules.length,0); // stale browser cache cannot outlive a failed bridge indefinitely
  console.log('Extension policy, search/internal-page exclusions, navigation races and mocked lifecycle checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
