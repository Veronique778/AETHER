import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { test } from 'node:test';
import { createAccountApi } from '../src/api/accountApi';
import { isExpiredPersonalResponse, isInvalidLaunchToken, installSecureFetch, setAuthToken } from '../src/lib/secureFetch';
import { be2Login, be2Profile } from './fixtures/be2-api-examples';

test('invalid launch-token 401 is distinct from an expired personal Bearer session', () => {
  const launchFailure = { detail: 'Missing or invalid AETHER session token' };
  assert.equal(isInvalidLaunchToken(401, launchFailure), true);
  assert.equal(isExpiredPersonalResponse(401, launchFailure, true, '/api/profile'), false);

  const personalExpiry = { error: { code: 'unauthenticated', detail: 'A valid personal session is required' } };
  assert.equal(isInvalidLaunchToken(401, personalExpiry), false);
  assert.equal(isExpiredPersonalResponse(401, personalExpiry, true, '/api/profile'), true);
});

test('only protected 401 unauthenticated responses expire a personal session', () => {
  const expired = { error: { code: 'unauthenticated', detail: 'session' } };
  assert.equal(isExpiredPersonalResponse(401, expired, false, '/api/profile'), false);
  assert.equal(isExpiredPersonalResponse(401, expired, true, '/api/auth/login'), false);
  assert.equal(isExpiredPersonalResponse(401, { error: { code: 'invalid_credentials' } }, true, '/api/profile'), false);
  assert.equal(isExpiredPersonalResponse(403, expired, true, '/api/profile'), false);
  assert.equal(isExpiredPersonalResponse(404, expired, true, '/api/profile'), false);
  assert.equal(isInvalidLaunchToken(403, { detail: 'Missing or invalid AETHER session token' }), false);
});

test('accountApi uses launch and personal tokens only on its real HTTP origin', async () => {
  const requests: { path: string; authorization: string | undefined; launch: string | undefined }[] = [];
  const backend = createServer((request, response) => {
    requests.push({
      path: request.url ?? '',
      authorization: request.headers.authorization,
      launch: request.headers['x-aether-token'],
    });
    response.setHeader('content-type', 'application/json');
    if (request.url === '/api/session') {
      response.end(JSON.stringify({ token: 'TEST_ONLY_LAUNCH_HEADER' }));
    } else if (request.url === '/api/auth/login') {
      response.end(JSON.stringify(be2Login));
    } else if (request.url === '/api/profile') {
      response.end(JSON.stringify(be2Profile));
    } else {
      response.statusCode = 404;
      response.end(JSON.stringify({ error: { code: 'not_found', detail: 'Not found' } }));
    }
  });
  const thirdPartyRequests: { authorization: string | undefined; launch: string | undefined }[] = [];
  const thirdParty = createServer((request, response) => {
    thirdPartyRequests.push({
      authorization: request.headers.authorization,
      launch: request.headers['x-aether-token'],
    });
    response.end('ok');
  });

  await Promise.all([
    new Promise<void>((resolve) => backend.listen(0, '127.0.0.1', resolve)),
    new Promise<void>((resolve) => thirdParty.listen(0, '127.0.0.1', resolve)),
  ]);
  const backendAddress = backend.address();
  const thirdPartyAddress = thirdParty.address();
  assert.ok(backendAddress && typeof backendAddress === 'object');
  assert.ok(thirdPartyAddress && typeof thirdPartyAddress === 'object');

  const originalFetch = globalThis.fetch;
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  const originalDocument = Object.getOwnPropertyDescriptor(globalThis, 'document');
  const originalLocation = Object.getOwnPropertyDescriptor(globalThis, 'location');
  const fakeWindow = Object.assign(new EventTarget(), {
    fetch: (input: RequestInfo | URL, init?: RequestInit) => originalFetch(input, init),
    __aetherFetch: false,
  });
  Object.defineProperty(globalThis, 'window', { configurable: true, value: fakeWindow });
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { querySelector: () => null } });
  Object.defineProperty(globalThis, 'location', { configurable: true, value: new URL('http://127.0.0.1:5173/') });

  try {
    const base = `http://127.0.0.1:${backendAddress.port}`;
    installSecureFetch(base);
    globalThis.fetch = fakeWindow.fetch as typeof fetch;
    const api = createAccountApi(base);
    const login = await api.login('demo_user', 'test-password-not-real');
    setAuthToken(login.access_token);
    assert.deepEqual(await api.profile(login.access_token), be2Profile);
    await globalThis.fetch(`http://127.0.0.1:${thirdPartyAddress.port}/api/external`, {
      headers: {
        Authorization: 'Bearer TEST_ONLY_PERSONAL_HEADER',
        'X-AETHER-Token': 'TEST_ONLY_LAUNCH_HEADER',
      },
    });

    assert.equal(requests.some((request) => request.path === '/api/session'), true);
    const loginRequest = requests.find((request) => request.path === '/api/auth/login');
    const profileRequest = requests.find((request) => request.path === '/api/profile');
    assert.equal(loginRequest?.launch, 'TEST_ONLY_LAUNCH_HEADER');
    assert.equal(loginRequest?.authorization, undefined);
    assert.equal(profileRequest?.launch, 'TEST_ONLY_LAUNCH_HEADER');
    assert.equal(profileRequest?.authorization, `Bearer ${be2Login.access_token}`);
    assert.deepEqual(thirdPartyRequests, [{ authorization: undefined, launch: undefined }]);
  } finally {
    setAuthToken(null);
    globalThis.fetch = originalFetch;
    for (const [key, descriptor] of [['window', originalWindow], ['document', originalDocument], ['location', originalLocation]] as const) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else Reflect.deleteProperty(globalThis, key);
    }
    await Promise.all([
      new Promise<void>((resolve, reject) => backend.close((error) => error ? reject(error) : resolve())),
      new Promise<void>((resolve, reject) => thirdParty.close((error) => error ? reject(error) : resolve())),
    ]);
  }
});
