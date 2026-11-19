const api = typeof browser !== 'undefined' ? browser : chrome;
if (typeof importScripts === 'function') importScripts('policy.js');
const HOST = 'com.focuslock.bridge';
const BLOCKED = api.runtime.getURL('blocked.html');
let policy = {domains: [], until: 0, sessionId: ''};
let connected = false;
let nativeError = 'Connecting to desktop…';
let ruleError = '';
let port = null;
let applied = null;
let chain = Promise.resolve();
let ready = false;
let lastHeartbeat = 0;

function enqueue(work) {
  chain = chain.then(work).catch(error => {
    ruleError = String(error);
    api.action.setBadgeText({text: 'ERR'}).catch(() => {});
    console.error(error);
  });
  return chain;
}
function current() {
  const enabled = FocusPolicy.active(policy);
  return {active: enabled, connected, error: ruleError || nativeError,
    domains: enabled ? policy.domains : [], until: enabled ? policy.until : 0,
    sessionId: policy.sessionId, mode: policy.mode};
}
function blockUrl(domain) { return BLOCKED + '?host=' + encodeURIComponent(domain); }
async function protectTab(tabId, url) {
  if (!ready || !FocusPolicy.active(policy) || !FocusPolicy.webUrl(url)) return;
  const domain = FocusPolicy.match(url, policy.domains);
  if (!domain || tabId < 0) return;
  // Re-read to avoid replacing an unrelated page after a fast navigation.
  try {
    const tab = await api.tabs.get(tabId);
    const live = FocusPolicy.match(tab.pendingUrl || tab.url || '', policy.domains);
    if (live && FocusPolicy.active(policy)) await api.tabs.update(tabId, {url: blockUrl(live)});
  } catch { /* tab closed during navigation */ }
}
async function reconcile() {
  const selected = FocusPolicy.active(policy) ? policy.domains : [];
  const signature = JSON.stringify(selected);
  if (signature !== applied) {
    const old = await api.declarativeNetRequest.getSessionRules();
    await api.declarativeNetRequest.updateSessionRules({
      removeRuleIds: old.map(rule => rule.id), addRules: FocusPolicy.rules(selected, BLOCKED)});
    applied = signature;
    ruleError = '';
    const tabs = await api.tabs.query({});
    await Promise.all(tabs.map(tab => protectTab(tab.id, tab.pendingUrl || tab.url || '')));
  }
  await api.action.setBadgeText({text: ruleError ? 'ERR' : selected.length ? 'ON' : connected ? '' : '!'});
  await api.action.setBadgeBackgroundColor({color: connected ? '#6c63ff' : '#bd652a'});
}
async function accept(message) {
  if (![1, 2].includes(message?.protocol)) throw new Error('Incompatible desktop bridge');
  connected = true;
  lastHeartbeat = Date.now();
  if (message.state === 'active') {
    if (!Number.isInteger(message.remainingSeconds) || message.remainingSeconds < 0 || message.remainingSeconds > 43200)
      throw new Error('Invalid desktop lifetime');
    if (message.protocol === 2 && (message.mode !== 'until_reboot' || message.remainingSeconds > 15))
      throw new Error('Invalid service status lease');
    policy = {domains: FocusPolicy.domains(message.domains),
      until: Date.now() + message.remainingSeconds * 1000, sessionId: String(message.sessionId), mode: message.protocol === 2 ? 'until_reboot' : 'timed'};
    nativeError = '';
  } else if (message.state === 'idle') {
    policy = {domains: [], until: 0, sessionId: ''};
    nativeError = '';
  } else if (message.state === 'error') {
    nativeError = message.message || 'Cannot read desktop session';
  } else if (message.state === 'preparing') {
    nativeError = 'Desktop is preparing or finishing the session.';
  } else throw new Error('Invalid desktop status');
  await api.storage.local.set({policy});
  await reconcile();
}
function connect() {
  if (port || !ready) return;
  try {
    const candidate = api.runtime.connectNative(HOST);
    port = candidate;
    candidate.onMessage.addListener(message => enqueue(() => accept(message)));
    candidate.onDisconnect.addListener(() => {
      nativeError = api.runtime.lastError?.message || 'Desktop bridge disconnected';
      connected = false;
      if (port === candidate) port = null;
      enqueue(reconcile);
      setTimeout(connect, 3000);
    });
    candidate.postMessage({type: 'get_state'});
  } catch (error) {
    nativeError = String(error);
    connected = false;
    port = null;
    setTimeout(connect, 3000);
  }
}
function heartbeat() {
  if (!ready) return;
  if (port && lastHeartbeat && Date.now() - lastHeartbeat > 10000) {
    port.disconnect();
    port = null;
    connected = false;
    nativeError = 'Desktop bridge stopped responding.';
  }
  if (port) {
    try { port.postMessage({type: 'get_state'}); } catch { port = null; connected = false; }
  } else connect();
  enqueue(reconcile);  // Also clears expired rules when the bridge is unavailable.
}
api.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.id !== api.runtime.id) return false;
  if (message?.type === 'status') {
    chain.then(() => reply(current()));
    return true;
  }
  if (message?.type === 'check_page') {
    chain.then(async () => {
      const domain = FocusPolicy.active(policy) ? FocusPolicy.match(sender.url || '', policy.domains) : null;
      if (domain && sender.tab) await protectTab(sender.tab.id, sender.url);
      reply({blockedUrl: domain ? blockUrl(domain) : null});
    }).catch(() => reply({blockedUrl: null}));
    return true;
  }
  return false;  // No disable/start/stop endpoint.
});
api.tabs.onUpdated.addListener((id, change, tab) => {
  if (change.url || change.status === 'loading') enqueue(() => protectTab(id, change.url || tab.url || ''));
});
for (const event of [api.webNavigation.onBeforeNavigate, api.webNavigation.onCommitted,
                     api.webNavigation.onHistoryStateUpdated, api.webNavigation.onReferenceFragmentUpdated]) {
  event.addListener(details => {
    if (details.frameId === 0 && FocusPolicy.webUrl(details.url))
      enqueue(() => protectTab(details.tabId, details.url));
  }, {url: [{schemes: ['http', 'https']}]});
}
api.alarms.onAlarm.addListener(heartbeat);
api.runtime.onStartup.addListener(heartbeat);
api.runtime.onInstalled.addListener(heartbeat);
enqueue(async () => {
  const saved = (await api.storage.local.get('policy')).policy;
  if (saved && Number.isFinite(saved.until) && saved.until <= Date.now() + (saved.mode === 'until_reboot' ? 15000 : 43201000)) {
    try { policy = {...saved, domains: FocusPolicy.domains(saved.domains)}; } catch { /* discard invalid cache */ }
  }
  ready = true;
  await api.alarms.create('focuslock-heartbeat', {periodInMinutes: 0.5});
  await reconcile();
  connect();
});
setInterval(heartbeat, 1000);
