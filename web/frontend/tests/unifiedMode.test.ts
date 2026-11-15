import assert from 'node:assert/strict';
import { test } from 'node:test';
import { missionNeedsSyntheticAdapter } from '../src/state/personalAccess';
import { latestTwinReadings } from '../src/features/personal/personalTwinData';
import type { Measurement } from '../src/api/accountApi';

test('all research/spacecraft/recovery modules remain navigable in authenticated live shell', () => {
  for (const route of ['', 'symbiosis', 'co-orbit', 'recovery', 'mission-lab', 'science']) {
    assert.equal(missionNeedsSyntheticAdapter(route, true), true, route);
  }
  assert.equal(missionNeedsSyntheticAdapter('body', false), true);
  assert.equal(missionNeedsSyntheticAdapter('phantom', false), true);
  assert.equal(missionNeedsSyntheticAdapter('body', true), false);
  assert.equal(missionNeedsSyntheticAdapter('phantom', true), false);
  for (const route of ['biosignals', 'profile', 'settings', 'login']) {
    assert.equal(missionNeedsSyntheticAdapter(route, false), false, route);
  }
});

function reading(signal: string, value: number | null, props: Partial<Measurement> = {}): Measurement {
  return {
    seq: 1, id: crypto.randomUUID(), astronaut_id: 'test-uuid', mission_id: null, device_id: null, session_id: null,
    source: 'test', signal, value, unit: 'bpm', measured_at: '2026-11-15T12:00:00Z',
    received_at: '2026-11-15T12:00:01Z', origin: 'real', quality: 'screened',
    confidence: null, missing: false, processing_version: 'test', metadata: {}, supersedes_id: null,
    ...props,
  };
}

test('personal 3D markers are sourced only from usable authenticated records', () => {
  const rows = [
    reading('heart_rate', 74, { metadata: { data_class: 'real_wearable' }, written_via: 'device_manager' }),
    reading('heart_rate', 150, { measured_at: '2026-11-15T13:00:00Z', quality: 'no_contact' }),
    reading('heart_rate', null, { measured_at: '2026-11-15T14:00:00Z', missing: true }),
    reading('sleep_duration', 28800, { unit: 's' }),
    reading('activity_minutes', 32, { unit: 'min', origin: 'manual' }),
  ];
  const view = latestTwinReadings(rows);
  assert.equal(view.find((x) => x.signal.key === 'heart_rate_bpm')?.value, 74);
  assert.equal(view.find((x) => x.signal.key === 'heart_rate_bpm')?.provenance, 'REAL SENSOR (SERVER-ATTESTED)');
  assert.equal(view.find((x) => x.signal.key === 'sleep_hours')?.value, 8);
  assert.equal(view.find((x) => x.signal.key === 'activity_minutes')?.origin, 'manual');
  assert.equal(view.some((x) => x.signal.system === 'respiratory'), false);
});

test('unverified REAL input is not misrepresented as a verified wearable', () => {
  const [view] = latestTwinReadings([reading('heart_rate', 72, { metadata: {} })]);
  assert.equal(view.provenance, 'UNVERIFIED REAL INPUT');
});

test('synthetic records remain explicitly labelled and are never projected to missing organs', () => {
  const result = latestTwinReadings([reading('heart_rate', 64, { origin: 'simulated' })]);
  assert.equal(result[0].provenance, 'SYNTHETIC');
  assert.equal(result.length, 1);
});


test('physical sensors are not silently inferred from HR: respiratory rate and oxygen require their own rows', () => {
  const view = latestTwinReadings([reading('heart_rate', 73)]);
  assert.deepEqual(view.map((x) => x.signal.key), ['heart_rate_bpm']);
  const enriched = latestTwinReadings([
    reading('heart_rate', 73),
    reading('rr_interval', 892, { unit: 'ms', measured_at: '2026-11-15T14:00:00Z' }),
    reading('respiratory_rate', 16, { unit: 'breaths/min' }),
    reading('spo2', 98, { unit: '%' }),
  ]);
  assert.deepEqual(enriched.map((x) => x.signal.key), ['heart_rate_bpm', 'rr_interval', 'respiratory_rate', 'spo2']);
});

test('wrong units and user-authored provenance do not become verified wearable readings', () => {
  assert.equal(latestTwinReadings([reading('spo2', 98, { unit: 'bpm' })]).length, 0);
  const result = latestTwinReadings([reading('heart_rate', 72, { metadata: { data_class: 'real_wearable' } })]);
  assert.equal(result[0].provenance, 'UNVERIFIED REAL INPUT');
});

test('latest valid sequence is selected after rejecting lost contact and later missing rows', () => {
  const result = latestTwinReadings([
    reading('heart_rate', 67, { seq: 1 }),
    reading('heart_rate', 75, { seq: 2 }),
    reading('heart_rate', 160, { seq: 3, quality: 'no_contact' }),
    reading('heart_rate', null, { seq: 4, missing: true }),
  ]);
  assert.equal(result[0].value, 75);
});
