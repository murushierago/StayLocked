/* Real Chromium DNR engine checks. Requires npm install playwright.
   Optional FOCUSLOCK_CHROMIUM_PATH points at a Chrome for Testing executable.
   Uses a temporary profile, synthetic HTTP pages and an injected test session;
   does not use a personal profile or a Windows native bridge. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {chromium} = require('playwright');
(async () => {
  const extension = path.resolve(process.argv[2] || path.join(__dirname, '../extension'));
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'focuslock-browser-check-'));
  const options = {headless:true, args:[`--disable-extensions-except=${extension}`, `--load-extension=${extension}`, '--no-sandbox']};
  if (process.env.FOCUSLOCK_CHROMIUM_PATH) options.executablePath = process.env.FOCUSLOCK_CHROMIUM_PATH;
  else options.channel = 'chromium';
  let context;
  try {
    context = await chromium.launchPersistentContext(profile, options);
    let [worker] = context.serviceWorkers();
    if (!worker) worker = await context.waitForEvent('serviceworker', {timeout:15000});
    const id = worker.url().split('/')[2];
    assert.equal(id,'mmcnhdgobmfalggffgjfhbogfoblhheo');
    await worker.evaluate(async () => {
      await chain;
      globalThis.testLease = setInterval(() => enqueue(() => accept({protocol:2,state:'active',domains:['youtube.com'],remainingSeconds:15,mode:'until_reboot',sessionId:'engine-test'})), 1000);
      await enqueue(() => accept({protocol:2, state:'active', domains:['youtube.com'], remainingSeconds:15, mode:'until_reboot', sessionId:'engine-test'}));
    });
    assert.equal(await worker.evaluate(() => chrome.runtime.getManifest().name),'StayLocked');
    const installed = await worker.evaluate(() => chrome.declarativeNetRequest.getSessionRules());
    assert.equal(installed.length,3);
    const probes = [
      ['https://www.youtube.com/watch?v=test', 'main_frame', undefined, true],
      ['https://m.youtube.com/', 'main_frame', undefined, true],
      ['https://www.youtube.com/api', 'xmlhttprequest', 'https://www.youtube.com', true],
      ['https://video.example/videoplayback', 'media', 'https://www.youtube.com', true],
      ['https://www.google.com/search?q=youtube.com', 'main_frame', undefined, false],
      ['https://www.bing.com/search?q=youtube.com', 'main_frame', undefined, false],
      ['https://duckduckgo.com/?q=youtube.com', 'main_frame', undefined, false],
      ['https://www.google.com/search?q=test', 'main_frame', 'https://www.youtube.com', false],
      ['https://www.google.com/script.js', 'script', 'https://www.google.com', false],
      ['chrome://new-tab-page/', 'main_frame', undefined, false],
      ['chrome://newtab/', 'main_frame', undefined, false],
      ['opera://startpage/', 'main_frame', undefined, false],
      ['edge://newtab/', 'main_frame', undefined, false],
      ['about:blank', 'main_frame', undefined, false],
      ['browser://newtab/', 'main_frame', undefined, false],
      ['about:newtab', 'main_frame', undefined, false],
      ['https://yandex.ru/search/?text=youtube.com', 'main_frame', undefined, false],
      ['chrome://new-tab-page/', 'script', 'https://www.youtube.com', false],
    ];
    for (const [url,type,initiator,blocked] of probes) {
      const request = {url,type};
      if (initiator) request.initiator = initiator;
      const result = await worker.evaluate(request => chrome.declarativeNetRequest.testMatchOutcome(request), request);
      assert.equal(result.matchedRules.length>0, blocked, JSON.stringify({request,result}));
    }
    // Real tab navigation with synthetic search results avoids contacting providers.
    await context.route('https://www.google.com/**', route => route.fulfill({contentType:'text/html',body:'<title>Search test</title><h1>Search is available</h1>'}));
    const tab = await context.newPage();
    await tab.goto('https://www.google.com/search?q=youtube.com');
    assert.equal(await tab.title(),'Search test');
    assert.ok(tab.url().startsWith('https://www.google.com/search'));
    await tab.goto('chrome://newtab/');
    assert.ok(!tab.url().startsWith('chrome-extension://'));
    // Avoid remote access even if redirect regresses; the route only responds locally.
    await context.route('https://www.youtube.com/**', route => route.fulfill({contentType:'text/html',body:'<title>YouTube test</title>'}));
    await tab.goto('https://www.youtube.com/watch?v=test').catch(error => {
      if (!String(error).includes('ERR_ABORTED')) throw error;
    });
    await tab.waitForFunction(expected => location.href === expected, `chrome-extension://${id}/blocked.html?host=youtube.com`, {timeout:10000});
    await tab.locator('#heading').waitFor({state:'visible'});
    await tab.locator('.brand img').evaluate(img => img.decode());
    assert.equal(await tab.locator('.brand img').evaluate(img => img.naturalWidth),128);
    if(process.env.STAYLOCKED_SCREENSHOT) await tab.screenshot({path:process.env.STAYLOCKED_SCREENSHOT});
    await worker.evaluate(() => {clearInterval(globalThis.testLease); return enqueue(() => accept({protocol:1,state:'idle',domains:[],remainingSeconds:0}));});
    assert.equal((await worker.evaluate(() => chrome.declarativeNetRequest.getSessionRules())).length,0);
    await tab.goto('https://www.youtube.com/watch?v=test');
    assert.equal(await tab.title(),'YouTube test');
    await worker.evaluate(() => enqueue(() => accept({protocol:1, state:'active', domains:['youtube.com'],
      remainingSeconds:5, sessionId:'timer-test'})));
    await tab.waitForURL(`chrome-extension://${id}/blocked.html?host=youtube.com`, {timeout:10000});
    assert.equal(await worker.evaluate(() => current().mode), 'timed');
    await tab.waitForFunction(() => document.getElementById('timer').textContent === 'Ready', {timeout:15000});
    assert.equal((await worker.evaluate(() => chrome.declarativeNetRequest.getSessionRules())).length,0);
    await tab.goto('https://www.youtube.com/watch?v=after-timer');
    assert.equal(await tab.title(),'YouTube test');
    console.log(JSON.stringify({result:'PASS', browser:context.browser()?.version(), extension:id,
      probes:probes.length, checks:'real DNR engine, search tab, new tab, YouTube redirect, idle release, timed expiry'},null,2));
  } finally {
    if (context) await context.close();
    fs.rmSync(profile,{recursive:true,force:true});
  }
})().catch(error => {console.error(error);process.exitCode=1;});
