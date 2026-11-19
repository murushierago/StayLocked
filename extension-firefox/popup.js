const api = typeof browser !== 'undefined' ? browser : chrome;
async function update() {
  try {
    const state = await api.runtime.sendMessage({type: 'status'});
    document.getElementById('status').textContent = state.active ? `FOCUS MODE ACTIVE · ${state.domains.length} website(s)` : state.connected ? 'Connected to desktop · no website block' : 'Desktop bridge not connected';
    const seconds = Math.max(0, Math.ceil((state.until - Date.now()) / 1000));
    document.getElementById('timer').textContent = state.active ? (state.mode === 'until_reboot' ? 'Until Windows restarts' : `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`) : '';
    document.getElementById('error').textContent = state.error || '';
  } catch (error) { document.getElementById('error').textContent = String(error); }
}
update(); setInterval(update,1000);
