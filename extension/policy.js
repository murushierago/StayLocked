/* Pure domain matching shared by the service worker and tests. */
(function (scope) {
  function domains(values) {
    if (!Array.isArray(values) || values.length > 20) throw new Error('Invalid domain list');
    return [...new Set(values.map(value => {
      if (typeof value !== 'string') throw new Error('Invalid domain');
      let host = value.toLowerCase().replace(/\.$/, '');
      if (host.startsWith('www.')) host = host.slice(4);
      if (host.length > 253 || !host.includes('.') || !host.split('.').every(label =>
        /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label))) throw new Error('Invalid domain');
      return host;
    }))];
  }
  function webUrl(url) {
    try {
      const parsed = new URL(url);
      return ['http:', 'https:'].includes(parsed.protocol) ? parsed : null;
    } catch { return null; }
  }
  function match(url, selected) {
    try {
      const parsed = webUrl(url);
      if (!parsed) return null;
      const host = parsed.hostname.toLowerCase().replace(/\.$/, '');
      return selected.find(domain => host === domain || host.endsWith('.' + domain)) || null;
    } catch { return null; }
  }
  function active(policy, now = Date.now()) {
    return !!policy && Array.isArray(policy.domains) && policy.domains.length > 0 && policy.until > now;
  }
  function rules(selected, base) {
    const result = selected.map((domain, i) => ({id: i + 1, priority: 2,
      action: {type: 'redirect', redirect: {url: base + '?host=' + encodeURIComponent(domain)}},
      condition: {regexFilter: '^https?://', requestDomains: [domain], resourceTypes: ['main_frame']}}));
    if (selected.length) {
      result.push({id: 100, priority: 1, action: {type: 'block'},
        condition: {regexFilter: '^https?://', requestDomains: selected, excludedResourceTypes: ['main_frame']}});
      result.push({id: 101, priority: 1, action: {type: 'block'},
        condition: {regexFilter: '^https?://', initiatorDomains: selected, excludedResourceTypes: ['main_frame']}});
    }
    return result;
  }
  scope.FocusPolicy = {domains, webUrl, match, active, rules};
  if (typeof module !== 'undefined') module.exports = scope.FocusPolicy;
})(globalThis);
