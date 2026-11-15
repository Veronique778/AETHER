import assert from 'node:assert/strict';
import { test } from 'node:test';
import { resolveApiBase } from '../src/state/runtimeConfig';

test('mobile builds do not mistake the WebView localhost origin for Mission Hub', () => {
  assert.equal(resolveApiBase({
    mobileBuild: true,
    browserOrigin: 'http://localhost',
  }), '');
});

test('mobile builds use an explicitly configured Mission Hub endpoint', () => {
  assert.equal(resolveApiBase({
    mobileBuild: true,
    configuredApiBase: ' https://mission-hub.example ',
    browserOrigin: 'http://localhost',
  }), 'https://mission-hub.example');
});

test('desktop runtime API and browser same-origin behavior remain supported', () => {
  assert.equal(resolveApiBase({
    mobileBuild: false,
    desktopApiBase: 'http://127.0.0.1:8123',
    configuredApiBase: 'https://mission-hub.example',
    browserOrigin: 'https://web.example',
  }), 'http://127.0.0.1:8123');
  assert.equal(resolveApiBase({
    mobileBuild: false,
    browserOrigin: 'https://web.example',
  }), 'https://web.example');
});
