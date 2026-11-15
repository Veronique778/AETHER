import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import { AccountApiError, createAccountApi } from '../src/api/accountApi';
import { liveRouteAllowed } from '../src/state/personalAccess';
import { bleErrorText } from '../src/features/sensors/bleErrors';

const originalFetch = globalThis.fetch;
const calls: { url: string; method: string; headers: Headers; body: string }[] = [];
const TOKEN = 'p'.repeat(43);

function respond(body: unknown, status = 200) {
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), method: init?.method ?? 'GET', headers: new Headers(init?.headers),
      body: typeof init?.body === 'string' ? init.body : '' });
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  };
}
afterEach(() => { globalThis.fetch = originalFetch; calls.length = 0; });

test('Live Mode guard: BIOSIGNALS is personal (not gated); BODY/PHANTOM only in a personal view; demo screens gated', () => {
  assert.equal(liveRouteAllowed('biosignals', false), true);
  assert.equal(liveRouteAllowed('biosignals', true), true);
  assert.equal(liveRouteAllowed('body', true), true);
  assert.equal(liveRouteAllowed('phantom', true), true);
  assert.equal(liveRouteAllowed('body', false), false);
  assert.equal(liveRouteAllowed('phantom', false), false);
  for (const r of ['', 'symbiosis', 'co-orbit', 'recovery', 'mission-lab', 'science']) {
    assert.equal(liveRouteAllowed(r, true), false, r);
  }
  for (const r of ['login', 'profile', 'about', 'settings']) assert.equal(liveRouteAllowed(r, false), true, r);
});

test('BLE scan goes to the authenticated Device Manager route with the personal Bearer, never /api/biosignals', async () => {
  respond({ found: [{ hardware_address: 'C4:7A', name: 'Strap', advertised_hrs: true, rssi: -50, compatibility: 'hrs_advertised', registered_device_id: null }],
    scanned_at: '2026-11-15T10:00:00Z', ble_available: true, note: '' });
  const api = createAccountApi('http://127.0.0.1:8123');
  const r = await api.bleScan(TOKEN, true, 7);
  assert.equal(r.found.length, 1);
  assert.equal(calls[0].url, 'http://127.0.0.1:8123/api/devices/scan');
  assert.equal(calls[0].method, 'POST');
  assert.equal(calls[0].headers.get('authorization'), `Bearer ${TOKEN}`);
  assert.deepEqual(JSON.parse(calls[0].body), { include_unadvertised: true, timeout_seconds: 7 });
  assert.ok(!calls.some((c) => c.url.includes('/api/biosignals')));
});

test('BLE calls without a personal session fail locally (no request is sent)', async () => {
  respond({});
  const api = createAccountApi('http://127.0.0.1:8123');
  await assert.rejects(() => api.bleScan('', false), (e: unknown) => e instanceof AccountApiError && e.status === 401);
  await assert.rejects(() => api.bleStatus(TOKEN, '../../admin'), /Invalid device identifier/);
  assert.equal(calls.length, 0);
});

test('server BLE error codes are preserved (serverCode) and shown with a friendly hint + the code', async () => {
  respond({ error: { code: 'device_busy', detail: 'busy (session 123)' } }, 409);
  const api = createAccountApi('http://127.0.0.1:8123');
  try {
    await api.bleConnect(TOKEN, 'abc123', 'astro-1');
    assert.fail('expected rejection');
  } catch (e) {
    assert.ok(e instanceof AccountApiError);
    assert.equal(e.serverCode, 'device_busy');
    const shown = bleErrorText(e);
    assert.equal(shown.code, 'device_busy');
    assert.match(shown.text, /already in use/);
    assert.doesNotMatch(shown.text, /session 123/);          // server detail / identifiers are not echoed
  }
  respond({ error: { code: 'bluetooth_off', detail: 'x' } }, 503);
  await assert.rejects(() => api.bleScan(TOKEN, false), (e: unknown) => bleErrorText(e).text.includes('turned off'));
  respond({ error: { code: '<script>', detail: 'x' } }, 500);
  await assert.rejects(() => api.bleScan(TOKEN, false), (e: unknown) => e instanceof AccountApiError && e.serverCode === '');
});

test('simulated strap must come back labelled synthetic; diagnostics must keep hardware_verified=false', async () => {
  const api = createAccountApi('http://127.0.0.1:8123');
  respond({ device_id: 'd1', name: 'AETHER simulated HRS · SYNTHETIC', data_class: 'real_wearable' }, 201);
  await assert.rejects(() => api.simulatedDevice(TOKEN), /invalid simulated-device/);
  respond({ scan_available: true, hardware_verified: true });
  await assert.rejects(() => api.bleDiagnostics(TOKEN), /invalid diagnostics/);
});

test('personal science client only reaches whitelisted PHANTOM / measurement resources', async () => {
  respond({ items: [], next_cursor: null });
  const api = createAccountApi('http://127.0.0.1:8123');
  await api.science(TOKEN, '/phantom-analyses');
  assert.equal(calls[0].url, 'http://127.0.0.1:8123/api/phantom-analyses');
  await assert.rejects(() => api.science(TOKEN, '/admin/users'), /Unsupported personal science resource/);
  await assert.rejects(() => api.science(TOKEN, '/biosignals/sensor/scan'), /Unsupported/);
});
