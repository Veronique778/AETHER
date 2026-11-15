import assert from 'node:assert/strict';
import { test } from 'node:test';
import { personalRouteState } from '../src/state/personalAccess';

test('synthetic demo and legacy backends never force a personal login', () => {
  assert.equal(personalRouteState('demo', false, 'signed-out'), 'demo');
  assert.equal(personalRouteState('live', false, 'signed-out'), 'pending');
});

test('personal profile requires a BE2-capable live backend and a current in-memory session', () => {
  assert.equal(personalRouteState('live', true, 'checking'), 'checking');
  assert.equal(personalRouteState('live', true, 'signed-out'), 'sign-in');
  assert.equal(personalRouteState('live', true, 'signed-in'), 'authorized');
  assert.equal(personalRouteState('demo', true, 'signed-in'), 'demo');
});
