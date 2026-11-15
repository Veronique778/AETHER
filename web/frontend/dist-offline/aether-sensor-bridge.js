/* AETHER 1.4 (bridge introduced in 1.1.1) sensor-status bridge for the prebuilt offline React distribution.
 * This script only PRESENTS the existing real BLE HRS status returned from the
 * same-origin local API. It never fabricates readings, computes clinical scores,
 * or maps Earth wearable data onto simulated astronaut records.
 * Rebuilding with the updated React source renders equivalent cards natively.
 */
(() => {
  'use strict';
  const api = '/api/biosignals/sensor/status';
  function isLive(status) {
    return status && status.connection === 'connected' && status.quality === 'screened' &&
      Number.isFinite(status.heart_rate) && Boolean(status.last_sample_utc);
  }
  function view(status, error) {
    if (error) return 'Sensor status unavailable — open BIOSIGNALS for details';
    if (isLive(status)) return `${status.heart_rate} bpm · measured BLE HRS · ${status.last_sample_utc}`;
    if (status && status.connection === 'connected') return 'Bluetooth connected · awaiting valid fresh measurements';
    return 'No live measurement · Bluetooth disconnected';
  }
  function currentNodes() {
    const bodyCard = Array.from(document.querySelectorAll('li')).find(
      n => n.textContent?.includes('Chest-strap heart-rate monitor') && n.textContent?.includes('Heart rate')
    );
    const garden = document.querySelector('[data-testid="sensor-status"]:not([data-aether-live-rendered])');
    const settle = Array.from(document.querySelectorAll('.eyebrow')).find(e => e.textContent?.trim() === 'Settling breath');
    return { bodyCard, garden, settle };
  }
  function ensure(container, name, css) {
    let node = container.querySelector(`[data-aether-status="${name}"]`);
    if (!node) {
      node = document.createElement('p');
      node.setAttribute('data-aether-status', name);
      node.setAttribute('role', 'status');
      node.setAttribute('aria-live', 'polite');
      node.className = css || 'mt-2 text-xs text-ink-2';
      container.appendChild(node);
    }
    return node;
  }
  function render(status, error) {
    const {bodyCard, garden, settle} = currentNodes();
    const label = view(status, error);
    if (bodyCard && !bodyCard.querySelector('[data-aether-live-rendered]')) {
      ensure(bodyCard, 'body', 'mt-2 text-xs text-ink-2').textContent = 'Actual HRS: ' + label;
    }
    if (garden) {
      const strong = garden.querySelector('strong');
      if (strong) strong.textContent = isLive(status) ? `${status.heart_rate} bpm (BLE)` : 'not connected or no fresh HR';
    }
    if (settle) {
      const parent = settle.parentElement;
      if (parent && !parent.querySelector('[data-aether-live-rendered]')) {
        ensure(parent, 'recovery', 'mb-2 text-xs text-ink-2').textContent =
          'Actual heart rate: ' + label + '. Not used to calculate reaction-time scores.';
      }
    }
  }
  let loading = false;
  async function tick() {
    if (document.hidden || loading) return;
    const {bodyCard, garden, settle} = currentNodes();
    if (!bodyCard && !garden && !settle) return;
    loading = true;
    try {
      const token = document.querySelector('meta[name="aether-session-token"]')?.getAttribute('content');
      const response = await fetch(api, {cache: 'no-store', credentials: 'same-origin', headers: token ? {'X-AETHER-Token': token} : {}});
      if (!response.ok) throw new Error('sensor status request failed');
      render(await response.json(), false);
    } catch {
      render(null, true);
    } finally {
      loading = false;
    }
  }
  window.addEventListener('hashchange', () => { void tick(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) void tick(); });
  window.setInterval(() => { void tick(); }, 3000);
  window.setTimeout(() => { void tick(); }, 400);
})();
