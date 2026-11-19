const api = typeof browser !== 'undefined' ? browser : chrome;
/* Also checks pages served from service-worker cache and back/forward cache. */
function checkFocus() {
  if (location.protocol !== 'http:' && location.protocol !== 'https:') return;
  api.runtime.sendMessage({type: 'check_page'}).then(response => {
    if (response?.blockedUrl) location.replace(response.blockedUrl);
  }).catch(() => {});
}
checkFocus();
addEventListener('pageshow', checkFocus);
addEventListener('popstate', checkFocus);
addEventListener('hashchange', checkFocus);
api.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && changes.policy) checkFocus();
});
