// Dependency-free verification for the 1.1.1 prebuilt BLE UI status bridge.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '..', 'public', 'aether-sensor-bridge.js'), 'utf8');

function element(tag, text = '') {
  const node = { tag, textContent: text, attrs: {}, children: [], className: '', parentElement: null };
  node.setAttribute = (key, value) => { node.attrs[key] = value; };
  node.appendChild = child => { child.parentElement = node; node.children.push(child); return child; };
  node.querySelector = sel => {
    const match = sel.match(/^\[data-aether-(?:status|live-rendered)(?:="([^"]+)")?\]$/);
    if (match) return node.children.find(c => match[1] ? c.attrs['data-aether-status'] === match[1] : c.attrs['data-aether-live-rendered'] === 'true') || null;
    if (sel === 'strong') return node.children.find(c => c.tag === 'strong') || null;
    return null;
  };
  return node;
}
async function probe(apiResponse) {
  const sensorCard = element('li', 'Chest-strap heart-rate monitor · Heart rate');
  const garden = element('p'); garden.appendChild(element('strong', 'not connected'));
  const setting = element('div'); const settling = element('h4', 'Settling breath'); setting.appendChild(settling);
  const document = {
    hidden: false,
    querySelectorAll: selector => selector === 'li' ? [sensorCard] : selector === '.eyebrow' ? [settling] : [],
    querySelector: selector => selector.startsWith('[data-testid="sensor-status"]') ? garden : null,
    createElement: tag => element(tag),
    addEventListener: () => {},
  };
  let scheduled;
  let requestCount = 0;
  const window = {
    addEventListener: () => {},
    setInterval: () => {},
    setTimeout: callback => { scheduled = callback; },
  };
  const sandbox = { document, window, fetch: async (endpoint, options) => {
    requestCount++;
    assert.equal(endpoint, '/api/biosignals/sensor/status');
    assert.equal(options.credentials, 'same-origin');
    return {ok:true, json:async() => apiResponse};
  }};
  vm.runInNewContext(source, sandbox, { filename:'aether-sensor-bridge.js' });
  scheduled();
  await new Promise(resolve => setImmediate(resolve));
  return {sensorCard, garden, setting, requestCount};
}
(async () => {
  const live = await probe({connection:'connected',quality:'screened',heart_rate:76,last_sample_utc:'2026-11-14T18:00:00Z'});
  assert.match(live.sensorCard.children[0].textContent, /76 bpm/);
  assert.match(live.garden.children[0].textContent, /76 bpm/);
  assert.match(live.setting.children.at(-1).textContent, /76 bpm/);
  assert.equal(live.requestCount, 1);
  const stale = await probe({connection:'connected',quality:'stale',heart_rate:76,last_sample_utc:'2026-11-14T18:00:00Z'});
  assert.doesNotMatch(stale.sensorCard.children[0].textContent, /76 bpm/);
  const disconnected = await probe({connection:'disconnected',quality:'unavailable',heart_rate:null,last_sample_utc:null});
  assert.match(disconnected.garden.children[0].textContent, /not connected/);
  console.log('3 BLE status bridge cases passed: live, stale, disconnected');
})().catch(error => { console.error(error); process.exitCode = 1; });
