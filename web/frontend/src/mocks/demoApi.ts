/**
 * In-browser DEMO ADAPTER. Implements the same `AetherApi` contract as the HTTP
 * client using a 1:1 port of the backend's synthetic generator and models.
 * Every response is synthetic; the UI shows a persistent "Demo adapter" label.
 * Manual entries and recovery sessions persist in localStorage when available.
 */
import { analyze, correlations, historyScores, spearman, type Row } from './phantomMock';
import { calendar, CREW, CREW_SEED, environment, project, runScenario, SCENARIOS, schedules, SEED_DAYS, SEED_SHIFTS,
  seedRow, shipState, TASKS, ZONES, zoneHistory } from './missionSystemsMock';
import { ApiError } from '../api/httpClient';
import { deleteExperiment, listExperiments, saveExperiment } from '../lib/experiments';
import { METRIC_KEYS, type AetherApi, type Measurement, type RecoverySession } from '../api/types';

const STORE_KEY = 'aether.demo.v2';
type Persisted = { manual: (Row & { astronaut_id: string })[]; sessions: RecoverySession[] };

function load(): Persisted {
  try {
    const raw = globalThis.localStorage?.getItem(STORE_KEY);
    if (raw) return JSON.parse(raw) as Persisted;
  } catch { /* storage unavailable */ }
  return { manual: [], sessions: [] };
}

export function createDemoApi(opts: { latencyMs?: number; persist?: boolean } = {}): AetherApi {
  const latency = opts.latencyMs ?? 60;
  const persist = opts.persist ?? true;
  const state: Persisted = persist ? load() : { manual: [], sessions: [] };
  const save = () => { if (!persist) return; try { globalThis.localStorage?.setItem(STORE_KEY, JSON.stringify(state)); } catch { /* ignore */ } };

  const seeded = new Map<string, Row[]>();
  for (const [p, s] of SEED_SHIFTS) seeded.set(p, Array.from({ length: SEED_DAYS }, (_, i) => seedRow(p, s, i + 1)));

  function rows(id: string, day: number): Row[] {
    const base = new Map((seeded.get(id) ?? []).map((r) => [r.day, { ...r }]));
    for (const m of state.manual.filter((x) => x.astronaut_id === id)) {
      const prev = base.get(m.day) ?? { day: m.day };
      const merged: Row = { ...prev, day: m.day, source: 'manual' };
      for (const k of METRIC_KEYS) merged[k] = m[k] ?? prev[k] ?? null;
      base.set(m.day, merged);
    }
    return [...base.values()].filter((r) => r.day <= day).sort((a, b) => a.day - b.day);
  }
  const rows_ = (id: string, day: number) => rows(id, day);
  const requireAstronaut = (id: string) => { if (!CREW.some((c) => c.id === id)) throw new ApiError(404, 'Unknown astronaut', id); };
  const latest = (day: number) => Object.fromEntries(CREW.map((c) => [c.id, rows(c.id, day).at(-1) ?? { day }]));
  const wait = <T,>(fn: () => T): Promise<T> => new Promise((resolve, reject) => {
    setTimeout(() => { try { resolve(structuredClone(fn())); } catch (e) { reject(e instanceof ApiError ? e : new ApiError(404, (e as Error).message, 'demo')); } }, latency);
  });

  return {
    mode: 'demo',
    health: () => wait(() => ({ status: 'ok', project: 'AETHER', version: '0.2.0-demo', data: 'synthetic demo only (in-browser adapter)', capabilities: ['all'] })),
    astronauts: () => wait(() => CREW_SEED),
    timeline: (id, day) => wait(() => { requireAstronaut(id); return rows(id, day).map((r) => ({ astronaut_id: id, ...r }) as Measurement); }),
    saveMeasurement: (id, m) => wait(() => {
      requireAstronaut(id);
      const values = METRIC_KEYS.map((k) => m[k]).filter((v) => v != null);
      if (!values.length) throw new ApiError(400, 'At least one metric is required', 'measurements');
      state.manual = state.manual.filter((x) => !(x.astronaut_id === id && x.day === m.day));
      const prev = rows(id, m.day).find((r) => r.day === m.day);
      const merged: Row & { astronaut_id: string } = { astronaut_id: id, day: m.day, source: 'manual' };
      for (const k of METRIC_KEYS) merged[k] = m[k] ?? prev?.[k] ?? null;
      state.manual.push(merged);
      save();
      return { saved: true, astronaut_id: id, day: m.day };
    }),
    phantom: (id, day) => wait(() => { requireAstronaut(id); return analyze(rows(id, day), day); }),
    phantomHistory: (id, day, start = 41) => wait(() => { requireAstronaut(id); return historyScores(rows(id, day), start, day); }),
    correlations: (id, day, window = 30) => wait(() => { requireAstronaut(id); return correlations(rows(id, day), day, window); }),
    symbiosis: (day) => wait(() => environment(day)),
    zoneHistory: (zone, start, end) => wait(() => {
      if (!ZONES.some((z) => z.id === zone)) throw new ApiError(404, 'Unknown compartment', zone);
      return { zone, points: zoneHistory(start, end, zone), source: 'estimated' as const };
    }),
    ship: (day, hour) => wait(() => {
      const status = Object.fromEntries(CREW.map((c) => [c.id, analyze(rows(c.id, day), day).status]));
      return shipState(day, hour, latest(day), status);
    }),
    crew: (reduce = false) => wait(() => ({ crew: CREW, schedule: schedules({ reduceA01: reduce, optimise: false }) })),
    calendar: (day) => wait(() => calendar(day, latest(day))),
    plan: (req) => wait(() => {
      const tasks = req.tasks ?? TASKS;
      if (new Set(tasks.map((t) => t.id)).size !== tasks.length) throw new ApiError(400, 'Task ids must be unique', 'plan');
      return schedules({ tasks, capacity: req.capacity, unavailable: req.unavailable, optimise: req.optimise ?? true });
    }),
    scenarios: () => wait(() => SCENARIOS),
    simulate: (req) => wait(() => { requireAstronaut(req.astronaut_id); return runScenario(rows(req.astronaut_id, req.day), req); }),
    project: (req) => wait(() => {
      requireAstronaut(req.astronaut_id);
      return project(rows(req.astronaut_id, req.start_day), { ...req, runs: req.runs ?? 200, seed: req.seed ?? 67 });
    }),
    recovery: (id) => wait(() => { requireAstronaut(id); return state.sessions.filter((s) => s.astronaut_id === id).sort((a, b) => b.id - a.id).slice(0, 100); }),
    environmentAssociation: (day, zone) => wait(() => {
      const co2 = new Map(zoneHistory(41, day, zone).map((p) => [p.day, p.co2_ppm]));
      const rows = CREW.map((c) => {
        const pairs = rows_(c.id, day).filter((r) => r.day >= 41 && co2.has(r.day) && r.fatigue_1_10 != null).map((r) => [co2.get(r.day)!, Number(r.fatigue_1_10)] as const);
        const rho = pairs.length >= 8 ? spearman(pairs.map((p) => p[0]), pairs.map((p) => p[1])) : null;
        return { astronaut_id: c.id, rho: rho == null ? null : Math.round(rho * 1000) / 1000, n: pairs.length };
      });
      return { day, zone, environment_metric: 'co2_ppm' as const, outcome_metric: 'fatigue_1_10' as const, method: 'Spearman rank correlation, days 41+', rows,
        note: 'In the synthetic dataset both CO₂ and A01 strain rise after day 56 by construction; a high ρ reflects the generator, not causation.', source: 'simulated' as const };
    }),
    biofeedback: (id) => wait(() => {
      requireAstronaut(id);
      const t = Date.now() / 1000;
      return { astronaut_id: id, t: new Date().toISOString(), breathing_rate_bpm: Math.round((6 + Math.sin(t / 20)) * 10) / 10,
        heart_rate_bpm: Math.round(66 + 4 * Math.sin(t / 5)), coherence_0_1: Math.round((0.55 + 0.25 * Math.sin(t / 15)) * 100) / 100,
        quality: 'good' as const, source: 'simulated' as const };
    }),
    saveRecovery: (s) => wait(() => {
      requireAstronaut(s.astronaut_id);
      const id = (state.sessions.reduce((m, x) => Math.max(m, x.id), 0) || 0) + 1;
      state.sessions.push({ ...s, id, details: s.details ?? {}, created_at: new Date().toISOString().slice(0, 19).replace('T', ' ') });
      save();
      return { id, saved: true };
    }),
    // Experiments: Demo Mode keeps them in this browser (same store as older builds).
    experiments: () => wait(() => listExperiments()),
    saveExperiment: (e) => wait(() => ({ saved: saveExperiment(e), id: e.id })),
    deleteExperiment: (id) => wait(() => { deleteExperiment(id); return { deleted: true, id }; }),
    // The Mission Systems engine is Python (numpy + scipy MILP). It runs with the backend, never in the browser.
    engineTemplates: () => Promise.reject(engineOffline()),
    engineRun: () => Promise.reject(engineOffline()),
    engineGet: () => Promise.reject(engineOffline()),
    engineControl: () => Promise.reject(engineOffline()),
    engineCompare: () => Promise.reject(engineOffline()),
    engineCoorbit: () => Promise.reject(engineOffline()),
    engineCoorbitApply: () => Promise.reject(engineOffline()),
    // PHANTOM 2.0 (robust covariance, CUSUM, bootstrap) is Python/numpy code in the backend; no browser port.
    scienceEvidence: () => Promise.reject(scienceOffline()),
    scienceHazards: () => Promise.reject(scienceOffline()),
    scienceGraph: () => Promise.reject(scienceOffline()),
    radiationPresets: () => Promise.reject(scienceOffline()),
    radiation: () => Promise.reject(scienceOffline()),
    engineSymbiosis: () => Promise.reject(engineOffline()),
    compareConditions: () => Promise.reject(engineOffline()),
    engineReplan: () => Promise.reject(engineOffline()),
    engineCoorbitReject: () => Promise.reject(engineOffline()),
    engineEnvironment: () => Promise.reject(engineOffline()),
    phantom2: () => Promise.reject(new ApiError(503, 'PHANTOM 2.0 runs in the AETHER backend (desktop app or Live Mode).', '/api/phantom2')),
  };
}

const engineOffline = () => new ApiError(503, 'The Mission Systems engine runs in the AETHER backend (desktop app or Live Mode). Demo Mode has no engine.', '/api/engine');
const scienceOffline = () => new ApiError(503, 'The scientific core runs in the AETHER backend (desktop app or Live Mode).', '/api/science');
