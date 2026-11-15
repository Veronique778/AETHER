import assert from 'node:assert/strict';
import { test } from 'node:test';
import { p2Drivers } from '../src/features/recovery/Recommendations';
import { METRIC_SCIENCE } from '../src/lib/metricScience';

const base = { status: 'ok', today: { phantom2: true } as Record<string, boolean | null>, multivariate: { attribution: { sleep_hours: 0.6, heart_rate_bpm: 0.3, fatigue_1_10: 0.1 } as Record<string, number> | null }, z: { sleep_hours: 3.1, heart_rate_bpm: -1.5, fatigue_1_10: 2 } as Record<string, number> | null };

test('PHANTOM 2.0 → RECOVERY: only unfavourable, material contributors of a flagged day', () => {
  const d = p2Drivers(base);
  assert.deepEqual(d.map((x) => x.key), ['sleep_hours']);      // heart rate is lower (favourable), fatigue share < 15 %
  assert.equal(p2Drivers({ ...base, today: { phantom2: false } }).length, 0);
  assert.equal(p2Drivers({ ...base, status: 'insufficient_baseline' }).length, 0);
  assert.equal(p2Drivers(undefined).length, 0);
});

test('every BODY metric has a scientific explanation with sources and a limitation', () => {
  for (const [k, v] of Object.entries(METRIC_SCIENCE)) {
    assert.ok(v.why.length > 40 && v.sources.length > 0 && v.limitation.length > 10 && v.risk.startsWith('Risk of'), k);
  }
});
