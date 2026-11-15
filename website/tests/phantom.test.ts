import assert from 'node:assert/strict';
import { test } from 'node:test';
import { analyse, THRESHOLD } from '../src/phantom/method';
import { SCENARIOS } from '../src/phantom/scenarios';
import { downloadAvailable } from '../src/config/download';

for (const s of SCENARIOS) {
  test(`scenario ${s.id} → ${s.expected}`, () => {
    const r = analyse(s.generate(), s.durationS);
    assert.equal(r.outcome, s.expected, r.reason);
    if (r.outcome === 'insufficient_data') assert.equal(r.flaggedWindows, 0);
    if (r.outcome !== 'insufficient_data') assert.ok((r.scale ?? 0) >= 3);
  });
}

test('scenarios are deterministic (same chart for every visitor)', () => {
  for (const s of SCENARIOS) assert.deepEqual(s.generate().slice(0, 50), s.generate().slice(0, 50));
});

test('unusable windows are never filled and never flagged', () => {
  const s = SCENARIOS.find((x) => x.id === 'contact')!;
  const r = analyse(s.generate(), s.durationS);
  const empty = r.windows.filter((w) => !w.usable);
  assert.ok(empty.length >= 6);
  assert.ok(empty.every((w) => w.mean === null && w.z === null && !w.flag));
});

test('flag rule is z ≥ 3.5 on robust z against a frozen first-hour baseline', () => {
  const s = SCENARIOS.find((x) => x.id === 'step')!;
  const r = analyse(s.generate(), s.durationS);
  assert.ok(r.windows.filter((w) => w.baseline).every((w) => !w.flag));
  assert.ok(r.windows.filter((w) => w.flag).every((w) => (w.z as number) >= THRESHOLD));
});

test('download link: only https URLs count; empty means "coming soon"', () => {
  assert.equal(downloadAvailable(''), false);
  assert.equal(downloadAvailable('javascript:alert(1)'), false);
  assert.equal(downloadAvailable('http://example.com/a.zip'), false);
  assert.equal(downloadAvailable('https://user.itch.io/aether'), true);
});
