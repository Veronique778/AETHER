import assert from 'node:assert/strict';
import { test } from 'node:test';
import { analyze, pyRound, spearman } from '../src/mocks/phantomMock';
import { createDemoApi } from '../src/mocks/demoApi';
import { project, seedRow, schedules } from '../src/mocks/missionSystemsMock';
import { CoherenceMeter, pacerPhase } from '../src/features/recovery/logic/breathing';
import { makeTrials, score } from '../src/features/recovery/logic/mindPulse';
import { connected, generate, isSolved, minRotations, nextSize, rotateMask } from '../src/features/recovery/logic/orbitFlow';
import { validateMeasurement } from '../src/features/body/ManualEntryForm';

const history = (p = 'A01', shift = 0) => Array.from({ length: 67 }, (_, i) => seedRow(p, shift, i + 1));

test('pyRound matches Python banker rounding', () => {
  assert.equal(pyRound(2.5), 2);
  assert.equal(pyRound(3.5), 4);
  assert.equal(pyRound(1.234, 2), 1.23);
});

test('PHANTOM flags day-67 strain but not baseline days', () => {
  assert.equal(analyze(history(), 30).status, 'normal');
  const a = analyze(history(), 67);
  assert.equal(a.status, 'attention');
  assert.ok(a.flagged_count >= 2 && a.multi_signal_pattern);
  assert.equal(analyze(history('A02', -2), 67).status, 'normal');
  assert.equal(analyze([{ day: 5, sleep_hours: 7 }], 5).status, 'insufficient');
});

test('spearman handles ties and constants', () => {
  assert.ok(Math.abs(spearman([1, 2, 3, 4], [1, 3, 2, 4])! - 0.8) < 1e-9);
  assert.equal(spearman([1, 1, 1], [1, 2, 3]), null);
});

test('projection is reproducible and ordered', () => {
  const p = { start_day: 67, horizon_days: 10, sleep_delta: -1.8, workload: 85, co2_ppm: 1450, temperature_c: 25, crew_available: 4, runs: 40, seed: 5 };
  const a = project(history(), p), b = project(history(), p);
  assert.deepEqual(a, b);
  for (const d of a.days) assert.ok(d.score.p10 <= d.score.p50 && d.score.p50 <= d.score.p90);
});

test('scheduler respects skills, capacity and availability', () => {
  const s = schedules({ unavailable: ['A03'], capacity: { A01: 2 } });
  assert.equal(s.loads.A03, 0);
  assert.ok(s.loads.A01 <= 2);
  assert.equal(s.assignments.find((t) => t.skill === 'medical')!.astronaut_id, null);
  assert.ok((s.peak_utilisation ?? 0) <= (s.greedy_peak_utilisation ?? 0) + 1e-9);
});

test('Orbit Flow puzzles are always solvable and start unsolved', () => {
  for (let seed = 1; seed < 60; seed++) {
    for (const size of [3, 4, 6, 8]) {
      const g = generate(size, seed);
      assert.equal(isSolved({ ...g, tiles: g.solution }), true, `solution solves ${size}/${seed}`);
      assert.equal(connected({ ...g, tiles: g.solution }).size, size * size);
      assert.equal(isSolved(g), false, `scrambled ${size}/${seed}`);
      // Rotating each tile by its minimal rotation count reaches the solution.
      const fixed = g.tiles.map((m, i) => { for (let r = 0; r < 4; r++) if (rotateMask(m, r) === g.solution[i]) return rotateMask(m, r); return m; });
      assert.equal(isSolved({ ...g, tiles: fixed }), true);
      assert.ok(minRotations(g) > 0);
    }
  }
});

test('Orbit Flow difficulty adapts', () => {
  assert.equal(nextSize({ size: 4, seconds: 20, moves: 12, minMoves: 10 }).size, 5);
  assert.equal(nextSize({ size: 5, seconds: 400, moves: 80, minMoves: 12 }).size, 4);
  assert.equal(nextSize({ size: 8, seconds: 10, moves: 10, minMoves: 10 }).size, 8);
});

test('Mind Pulse trials and scoring', () => {
  const t = makeTrials(20, 1);
  assert.equal(t.length, 20);
  assert.equal(t.filter((x) => x.kind === 'nogo').length, 4);
  assert.ok(t.every((x) => x.delayMs >= 1200 && x.delayMs <= 3500));
  const s = score([
    { kind: 'go', rt: 250 }, { kind: 'go', rt: 350 }, { kind: 'go', rt: 600 }, { kind: 'go', rt: null },
    { kind: 'nogo', rt: null }, { kind: 'nogo', rt: 300 }, { kind: 'go', rt: null, falseStart: true }, { kind: 'go', rt: 80 },
  ]);
  assert.equal(s.medianRt, 350);
  assert.equal(s.lapses, 1);
  assert.equal(s.omissions, 1);
  assert.equal(s.commissions, 1);
  assert.equal(s.falseStarts, 1);
  assert.equal(s.anticipations, 1);
  assert.equal(s.accuracy, 4 / 8);
});

test('breathing pacer and coherence', () => {
  const pace = { breathsPerMin: 6, inhaleShare: 0.4 };
  assert.equal(pacerPhase(1, pace).inhale, true);
  assert.equal(pacerPhase(5, pace).inhale, false);
  const m = new CoherenceMeter();
  for (let t = 0; t < 30; t += 0.05) { const ph = pacerPhase(t, pace); m.sample(ph.inhale, ph, 10, 0.4); }
  assert.equal(m.overall, 1);
  const n = new CoherenceMeter();
  for (let t = 0; t < 30; t += 0.05) { const ph = pacerPhase(t, pace); n.sample(!ph.inhale, ph, 10, 0.4); }
  assert.equal(n.overall, 0);
});

test('manual entry validation mirrors backend limits', () => {
  const empty = { heart_rate_bpm: '', sleep_hours: '', fatigue_1_10: '', reaction_ms: '', activity_minutes: '' };
  assert.ok(validateMeasurement('67', empty).errors.form);
  assert.ok(validateMeasurement('67', { ...empty, heart_rate_bpm: '500' }).errors.heart_rate_bpm);
  assert.ok(validateMeasurement('0', { ...empty, sleep_hours: '7' }).errors.day);
  assert.deepEqual(validateMeasurement('67', { ...empty, sleep_hours: '7.5' }).payload, { day: 67, sleep_hours: 7.5 });
});

test('demo adapter: partial manual entry merges, recovery persists in memory', async () => {
  const api = createDemoApi({ latencyMs: 0, persist: false });
  const before = (await api.timeline('A01', 67)).at(-1)!;
  await api.saveMeasurement('A01', { day: 67, reaction_ms: 300 });
  const after = (await api.timeline('A01', 67)).at(-1)!;
  assert.equal(after.reaction_ms, 300);
  assert.equal(after.heart_rate_bpm, before.heart_rate_bpm);
  assert.equal(after.source, 'manual');
  await assert.rejects(api.saveMeasurement('A01', { day: 67 }), /At least one metric/);
  await assert.rejects(api.phantom('nobody', 67), /Unknown astronaut/);
  await api.saveRecovery({ astronaut_id: 'A02', activity: 'orbit-flow', before_mood: 3, after_mood: 5, duration_seconds: 60, details: { puzzles_solved: 2 } });
  const rec = await api.recovery('A02');
  assert.equal(rec.length, 1);
  assert.equal(rec[0].details.puzzles_solved, 2);
  await assert.rejects(api.plan({ tasks: [{ id: 'X', title: 'a', skill: 'science', hours: 1, priority: 1 }, { id: 'X', title: 'b', skill: 'science', hours: 1, priority: 1 }] }), /unique/);
});
