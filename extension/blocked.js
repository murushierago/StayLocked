const api = typeof browser !== 'undefined' ? browser : chrome;
const raw = new URL(location.href).searchParams.get('host') || '';
const domain = raw.length <= 253 && /^[a-z0-9.-]+$/i.test(raw) && raw.includes('.') ? raw : '';
document.getElementById('domain').textContent = domain || 'This website';
let state = null;
function isBlocked() {
  return state?.active && state.domains.some(d => domain === d || domain.endsWith('.' + d));
}
async function update() {
  try {
    state = await api.runtime.sendMessage({type: 'status'});
    const blocked = isBlocked();
    const remaining = blocked ? Math.max(0, Math.ceil((state.until - Date.now()) / 1000)) : 0;
    const minutes = Math.floor(remaining / 60);
    document.getElementById('timer').textContent = blocked ? (state.mode === 'until_reboot' ? 'Until restart' : `${minutes}:${String(remaining % 60).padStart(2,'0')}`) : 'Ready';
    document.getElementById('heading').textContent = blocked ? 'FOCUS MODE' : state.connected ? 'WEBSITE AVAILABLE' : 'CONNECTION UNAVAILABLE';
    document.getElementById('description').textContent = blocked ? 'is blocked during your focus session.' : 'is not currently blocked by the extension.';
    document.getElementById('instruction').textContent = blocked ? (state.mode === 'until_reboot' ? 'Restart your PC to end Focus Mode.' : 'Wait for the timer or restart your PC to end Focus Mode.') : 'You can open the website again.';
    document.getElementById('connection').textContent = state.error || (state.connected ? '' : 'Desktop bridge disconnected. Last known session expires automatically.');
    document.getElementById('open').disabled = blocked || !domain;
  } catch {
    document.getElementById('connection').textContent = 'Extension unavailable. Reload this page.';
  }
}
document.getElementById('open').addEventListener('click', async () => {
  await update();
  if (domain && state && !isBlocked()) location.replace('https://' + domain + '/');
});
update();
setInterval(update, 1000);
