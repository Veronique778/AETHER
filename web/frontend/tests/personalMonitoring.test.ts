import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Measurement } from '../src/api/accountApi';
import { chartSeriesForSignal, latestValidMeasurement, personalMeasurementQuery } from '../src/features/personal/measurementView';

function measurement(overrides: Partial<Measurement> = {}): Measurement {
  return {
    seq: 1,
    id: 'm-1',
    astronaut_id: 'a-1',
    mission_id: null,
    device_id: null,
    session_id: null,
    source: 'manual check-in',
    signal: 'heart_rate',
    value: 70,
    unit: 'bpm',
    measured_at: '2026-11-15T10:00:00.000Z',
    received_at: '2026-11-15T10:00:01.000Z',
    origin: 'manual',
    quality: 'validated',
    confidence: null,
    missing: false,
    processing_version: 'raw-1.5',
    metadata: {},
    supersedes_id: null,
    ...overrides,
  };
}

test('personal history query uses an inclusive UTC end and keeps unbounded ranges unbounded', () => {
  assert.deepEqual(personalMeasurementQuery('2026-11-14', '2026-11-15'), {
    start: '2026-11-14T00:00:00.000000Z',
    end: '2026-11-15T23:59:59.999999Z',
    limit: 100,
  });
  assert.deepEqual(personalMeasurementQuery('', ''), { limit: 100 });
});

test('personal charts keep null/poor-quality gaps and never combine units', () => {
  const rows = [
    measurement({ id: 'valid', value: 72, measured_at: '2026-11-15T12:00:00.000Z' }),
    measurement({ id: 'missing', seq: 2, value: null, missing: true, measured_at: '2026-11-15T12:01:00.000Z' }),
    measurement({ id: 'rejected', seq: 3, value: 240, quality: 'rejected', measured_at: '2026-11-15T12:02:00.000Z' }),
    measurement({ id: 'other-unit', seq: 4, unit: 'beats/s', value: 1.2, measured_at: '2026-11-15T12:03:00.000Z' }),
    measurement({ id: 'no-time', seq: 5, measured_at: null }),
  ];

  const series = chartSeriesForSignal(rows, 'heart_rate');
  assert.deepEqual(series.map((group) => group.unit).sort(), ['beats/s', 'bpm']);
  const bpm = series.find((group) => group.unit === 'bpm')!;
  assert.deepEqual(bpm.points.map((point) => point.y), [72, null, null]);
  assert.deepEqual(bpm.qualities, ['rejected', 'validated']);
  assert.equal(latestValidMeasurement(rows, 'heart_rate')?.id, 'other-unit');
});
