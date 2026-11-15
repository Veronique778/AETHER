import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import { AccountApiError, createAccountApi } from '../src/api/accountApi';
import {
  be2Analyses, be2Analysis, be2Devices, be2Login, be2Logout, be2Me, be2Measurements, be2Profile,
  be2Recovery, be2Registration, be2Signals,
} from './fixtures/be2-api-examples';

const originalFetch = globalThis.fetch;
const calls: { url: string; method: string; headers: Headers; body: string }[] = [];

function respond(body: unknown, status = 200) {
  globalThis.fetch = async (input, init) => {
    calls.push({
      url: String(input),
      method: init?.method ?? 'GET',
      headers: new Headers(init?.headers),
      body: typeof init?.body === 'string' ? init.body : '',
    });
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  };
}

afterEach(() => {
  globalThis.fetch = originalFetch;
  calls.length = 0;
});

test('register follows BE2 201 DTO and returns a one-time code, not an authenticated session', async () => {
  respond(be2Registration, 201);
  const result = await createAccountApi('https://aether.test').register({
    login: 'demo_user',
    password: 'test-password-not-a-credential',
    display_name: 'Demo User',
    language: 'uk',
  });

  assert.equal(calls[0].url, 'https://aether.test/api/auth/register');
  assert.deepEqual(JSON.parse(calls[0].body), {
    login: 'demo_user',
    password: 'test-password-not-a-credential',
    display_name: 'Demo User',
    language: 'uk',
  });
  assert.equal(calls[0].headers.has('Authorization'), false);
  assert.equal(result.user.login, 'demo_user');
  assert.equal(result.recovery_code, be2Registration.recovery_code);
  assert.equal('access_token' in result, false);
});

test('login sends login and validates BE2 Bearer response case-insensitively', async () => {
  respond({ ...be2Login, token_type: 'bEaReR' });
  const result = await createAccountApi('https://aether.test').login('demo_user', 'test-password-not-a-credential');
  assert.equal(calls[0].url, 'https://aether.test/api/auth/login');
  assert.deepEqual(JSON.parse(calls[0].body), { login: 'demo_user', password: 'test-password-not-a-credential' });
  assert.equal(result.token_type, 'Bearer');
  assert.equal(result.idle_timeout_seconds, 900);
});

test('me unwraps the nested identity while profile uses its own endpoint and DTO', async () => {
  const api = createAccountApi('https://aether.test');
  respond(be2Me);
  assert.deepEqual(await api.me('test-bearer'), be2Me.user);
  assert.equal(calls[0].url, 'https://aether.test/api/auth/me');
  assert.equal(calls[0].headers.get('Authorization'), 'Bearer test-bearer');

  respond(be2Profile);
  const profile = await api.profile('test-bearer');
  assert.deepEqual(profile, be2Profile);
  assert.equal(calls[1].url, 'https://aether.test/api/profile');
  assert.equal('email' in profile, false);
});

test('profile update, devices, measurements and analyses use actual BE2 paths and shapes', async () => {
  const api = createAccountApi('https://aether.test');
  respond(be2Profile);
  await api.updateProfile('test-bearer', { display_name: 'Updated', language: 'en' });
  assert.equal(calls[0].method, 'PATCH');
  assert.equal(calls[0].url, 'https://aether.test/api/profile');
  assert.deepEqual(JSON.parse(calls[0].body), { display_name: 'Updated', language: 'en' });

  respond(be2Devices);
  assert.deepEqual(await api.devices('test-bearer'), be2Devices.items);
  assert.equal(calls[1].url, 'https://aether.test/api/devices');
  assert.equal('status' in be2Devices.items[0], false);

  respond(be2Measurements);
  const measurements = await api.measurements('test-bearer', {
    start: '2026-11-15T00:00:00.000000Z',
    end: '2026-11-15T23:59:59.999999Z',
    signal: 'heart_rate',
    after: 12,
    limit: 50,
  });
  const url = new URL(calls[2].url);
  assert.equal(url.pathname, '/api/measurements');
  assert.equal(url.searchParams.get('start'), '2026-11-15T00:00:00.000000Z');
  assert.equal(url.searchParams.get('end'), '2026-11-15T23:59:59.999999Z');
  assert.equal(url.searchParams.get('signal'), 'heart_rate');
  assert.equal(url.searchParams.get('after'), '12');
  assert.equal(url.searchParams.get('limit'), '50');
  assert.equal(measurements.next_cursor, 1);
  assert.equal(measurements.items[0].value, null);
  assert.equal(measurements.items[0].missing, true);

  respond(be2Analyses);
  assert.deepEqual(await api.analyses('test-bearer', 4, 25), be2Analyses);
  assert.equal(new URL(calls[3].url).pathname, '/api/analyses');
  assert.equal(be2Analysis.model, 'summary-v1');
});

test('signal catalog uses the authenticated BE2-05 route and validates its registry response', async () => {
  const api = createAccountApi('https://aether.test');
  respond(be2Signals);
  assert.deepEqual(await api.signals('test-bearer'), be2Signals);
  assert.equal(calls[0].url, 'https://aether.test/api/signals');
  assert.equal(calls[0].headers.get('Authorization'), 'Bearer test-bearer');

  respond({ contract_status: 'integration_candidate', catalog_source: 'be2_measurement_validation', items: [{ signal: 'rr_interval', unit: 'ms', minimum: 5000, maximum: 100 }] });
  await assert.rejects(() => api.signals('test-bearer'), /invalid signal catalog response/i);
});

test('logout, recovery and password change follow the BE2 one-time-code responses', async () => {
  const api = createAccountApi('https://aether.test');
  respond(be2Logout);
  assert.deepEqual(await api.logout('test-bearer'), be2Logout);
  assert.equal(calls[0].url, 'https://aether.test/api/auth/logout');
  assert.equal(calls[0].headers.get('Authorization'), 'Bearer test-bearer');

  respond(be2Recovery);
  assert.deepEqual(await api.recover({
    login: 'demo_user',
    recovery_code: 'test-only-recovery-code-with-more-than-32-characters',
    new_password: 'another-test-password-not-real',
  }), be2Recovery);
  assert.equal(calls[1].url, 'https://aether.test/api/auth/recover');
  assert.equal(calls[1].headers.has('Authorization'), false);

  respond(be2Recovery);
  assert.deepEqual(await api.changePassword('test-bearer', 'old-test-password', 'new-test-password-not-real'), be2Recovery);
  assert.equal(calls[2].url, 'https://aether.test/api/auth/change-password');
  assert.equal(calls[2].headers.get('Authorization'), 'Bearer test-bearer');
});

test('personal API requests refuse an absent Bearer and never fall back to demo data', async () => {
  const api = createAccountApi('https://aether.test');
  await assert.rejects(() => api.devices(''), (error: unknown) => {
    assert.ok(error instanceof AccountApiError);
    assert.equal(error.status, 401);
    return true;
  });
  assert.equal(calls.length, 0);

  globalThis.fetch = async () => { throw new Error('offline'); };
  await assert.rejects(() => api.measurements('test-bearer'), (error: unknown) => {
    assert.ok(error instanceof AccountApiError);
    assert.equal(error.status, 0);
    assert.doesNotMatch(error.message, /aether\.test|test-bearer/i);
    return true;
  });
});

test('error mapping supports BE2 and legacy transport envelopes without showing their details', async (t) => {
  const cases: [number, unknown, string][] = [
    [401, { error: { code: 'invalid_credentials', detail: 'password must never be shown' } }, 'incorrect'],
    [401, { error: { code: 'unauthenticated', detail: 'session' } }, 'expired'],
    [401, { detail: 'Missing or invalid AETHER session token' }, 'launch check'],
    [403, { error: { code: 'forbidden', detail: 'hidden resource information' } }, 'denied'],
    [404, { error: { code: 'not_found', detail: 'hidden resource information' } }, 'unavailable'],
    [409, { error: { code: 'conflict', detail: 'hidden conflict' } }, 'conflicts'],
    [422, { error: { code: 'validation_error', detail: 'invalid password content' } }, 'invalid'],
    [429, { error: { code: 'rate_limited', detail: 'slow down' } }, 'Too many'],
    [503, { error: { code: 'storage_unavailable', detail: 'database internals' } }, 'temporarily unavailable'],
  ];
  for (const [status, body, expected] of cases) {
    await t.test(`HTTP ${status}`, async () => {
      respond(body, status);
      await assert.rejects(() => createAccountApi('https://aether.test').login('demo_user', 'test-password'), (error: unknown) => {
        assert.ok(error instanceof AccountApiError);
        assert.equal(error.status, status);
        assert.match(error.message, new RegExp(expected, 'i'));
        assert.doesNotMatch(error.message, /hidden|password content|database internals/);
        return true;
      });
    });
  }
});

test('rejects legacy registration responses that pretend to create a signed-in session', async () => {
  respond(be2Login);
  await assert.rejects(
    () => createAccountApi('https://aether.test').register({
      login: 'demo_user', password: 'test-password-not-real', display_name: 'Demo User',
    }),
    /invalid registration response/i,
  );
});

test('remote account APIs require HTTPS; only loopback development may use HTTP', async () => {
  const remote = createAccountApi('http://aether.test');
  await assert.rejects(() => remote.login('demo_user', 'test-password'), /requires HTTPS/i);
  assert.equal(calls.length, 0);

  respond(be2Login);
  await createAccountApi('http://127.0.0.1:8000').login('demo_user', 'test-password');
  assert.equal(calls[0].url, 'http://127.0.0.1:8000/api/auth/login');
});
