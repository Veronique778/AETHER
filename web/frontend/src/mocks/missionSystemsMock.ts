/**
 * DEMO MODE MOCK SERVER – not part of the UI.
 * Reference port of web/backend/app/simulation.py (owned by Mission Systems) so Demo Mode
 * can run without a server. The UI never imports this file; only AppState selects it.
 * Parity with Python is enforced by backend/tests/test_parity.py.
 */
import { METRIC_KEYS, type Analysis, type Assignment, type CabinEnvironment, type CalendarBlock, type CrewCalendar, type CrewLocation,
  type CrewMember, type EnvStatus, type MetricKey, type Projection, type ProjectionDay, type ReferenceBands, type Scenario, type Schedule,
  type ShipState, type SimulationResult, type Task, type Zone, type ZoneEnvironment, type ZoneId } from '../api/types';
import { Mulberry32 } from '../lib/random';
import { analyze, computeBaselines, pyRound, scoreValues, BASELINE_END, type Row } from './phantomMock';
export { Mulberry32 };

export const CREW_SEED = [
  { id: 'A01', name: 'Alex Vega', role: 'Mission commander' },
  { id: 'A02', name: 'Mira Chen', role: 'Flight engineer' },
  { id: 'A03', name: 'Sam Okafor', role: 'Medical officer' },
  { id: 'A04', name: 'Noor Patel', role: 'Mission specialist' },
];
export const SEED_SHIFTS: [string, number][] = [['A01', 0], ['A02', -2], ['A03', 1], ['A04', -1]];
export const SEED_DAYS = 67;

export function seedRow(person: string, shift: number, day: number): Row & { astronaut_id: string } {
  const cyclic = Math.sin(day * 0.29 + shift) * 1.9;
  const strain = person === 'A01' ? Math.max(0, day - 56) : 0;
  return {
    astronaut_id: person, day,
    heart_rate_bpm: pyRound(66 + shift + cyclic + strain * 1.15, 1),
    sleep_hours: pyRound(Math.max(3.2, 7.6 + Math.sin(day * 0.21) * 0.25 - strain * 0.19), 2),
    fatigue_1_10: pyRound(Math.min(10, Math.max(1, 2.6 + Math.sin(day * 0.33) * 0.4 + strain * 0.37)), 1),
    reaction_ms: pyRound(242 + shift * 4 + Math.sin(day * 0.25) * 9 + strain * 10, 1),
    activity_minutes: pyRound(55 + Math.cos(day * 0.36) * 9 - strain * 1.2, 1),
    source: 'simulated',
  };
}

export const SCENARIOS: Scenario[] = [
  { id: 'baseline', title: 'Nominal mission', detail: 'Steady routine and healthy baseline', sleep_delta: 0, workload: 50, co2_ppm: 850, temperature_c: 22, crew_available: 4 },
  { id: 'day67', title: 'Day 67 · accumulated strain', detail: 'Shorter sleep and heavier workload', sleep_delta: -1.8, workload: 85, co2_ppm: 1450, temperature_c: 25, crew_available: 4 },
  { id: 'recovery', title: 'Recovery intervention', detail: 'Additional rest and redistributed tasks', sleep_delta: 0.8, workload: 35, co2_ppm: 850, temperature_c: 21, crew_available: 4 },
  { id: 'crew3', title: 'One crew member unavailable', detail: 'Same task list shared by three people', sleep_delta: -0.5, workload: 60, co2_ppm: 1000, temperature_c: 23, crew_available: 3 },
];
export const CREW: CrewMember[] = [
  { id: 'A01', name: 'Alex Vega', skills: ['command', 'science'], capacity: 6, home_zone: 'command' },
  { id: 'A02', name: 'Mira Chen', skills: ['engineering', 'science'], capacity: 7, home_zone: 'systems' },
  { id: 'A03', name: 'Sam Okafor', skills: ['medical', 'science'], capacity: 6, home_zone: 'medical' },
  { id: 'A04', name: 'Noor Patel', skills: ['engineering', 'command'], capacity: 7, home_zone: 'command' },
];
export const TASKS: Task[] = [
  { id: 'T1', title: 'Life-support check', skill: 'engineering', hours: 2, priority: 1, zone: 'systems' },
  { id: 'T2', title: 'Health assessment', skill: 'medical', hours: 2, priority: 1, zone: 'medical' },
  { id: 'T3', title: 'Navigation review', skill: 'command', hours: 2, priority: 2, zone: 'command' },
  { id: 'T4', title: 'Science experiment', skill: 'science', hours: 3, priority: 2, zone: 'habitat' },
  { id: 'T5', title: 'Equipment inspection', skill: 'engineering', hours: 2, priority: 3, zone: 'systems' },
];

type ZoneDef = Omit<Zone, 'environment'> & { offset: { co2: number; temp: number; hum: number } };
export const ZONES: ZoneDef[] = [
  { id: 'command', name: 'Command deck', module: 'co-orbit', volume_m3: 38, description: 'Flight control, navigation and communications.', offset: { co2: -40, temp: -0.3, hum: -3 } },
  { id: 'habitat', name: 'Habitat ring', module: 'body', volume_m3: 96, description: 'Crew quarters, galley and shared living space.', offset: { co2: 60, temp: 0.4, hum: 4 } },
  { id: 'medical', name: 'Medical bay', module: 'phantom', volume_m3: 24, description: 'Health checks, sensors and physiological measurements.', offset: { co2: -20, temp: -0.2, hum: 0 } },
  { id: 'exercise', name: 'Exercise & recovery', module: 'recovery', volume_m3: 30, description: 'Countermeasure exercise devices and recovery activities.', offset: { co2: 90, temp: 0.8, hum: 6 } },
  { id: 'systems', name: 'Life support (ECLSS)', module: 'symbiosis', volume_m3: 42, description: 'Air revitalisation, water recovery and thermal control.', offset: { co2: 20, temp: 0.6, hum: -2 } },
];
export const REFERENCE: ReferenceBands = {
  co2_ppm: { attention: 1200, high: 2500, unit: 'ppm' },
  temperature_c: { low: 19, high: 26, unit: '°C' },
  humidity_pct: { low: 30, high: 65, unit: '%' },
  light_lux: { unit: 'lux' },
  note: 'AETHER demo reference bands for visual grouping only; not spacecraft flight rules or exposure limits.',
};

export function environment(day = 67): CabinEnvironment {
  const strain = Math.max(0, day - 56);
  return {
    day, co2_ppm: pyRound(850 + strain * 46), temperature_c: pyRound(22 + strain * 0.2, 1), humidity_pct: 45,
    light_lux: day % 2 ? 380 : 280, source: 'simulated', note: 'Illustrative simulation; not a life-support recommendation.',
  };
}

function envStatus(co2: number, temp: number, hum: number): EnvStatus {
  if (co2 >= REFERENCE.co2_ppm.high) return 'high';
  if (co2 >= REFERENCE.co2_ppm.attention || temp < REFERENCE.temperature_c.low || temp > REFERENCE.temperature_c.high
    || hum < REFERENCE.humidity_pct.low || hum > REFERENCE.humidity_pct.high) return 'attention';
  return 'nominal';
}

export function zoneEnvironment(day: number, zoneId: ZoneId, hour: number, occupants: number): ZoneEnvironment {
  const base = environment(day);
  const z = ZONES.find((x) => x.id === zoneId)!;
  const cyc = Math.sin(((hour - 9) / 24) * 2 * Math.PI);
  const co2 = base.co2_ppm + z.offset.co2 + 55 * occupants + 25 * cyc;
  const temp = base.temperature_c + z.offset.temp + 0.15 * occupants + 0.3 * cyc;
  const hum = base.humidity_pct + z.offset.hum + 1.5 * occupants;
  let light: number;
  if (zoneId === 'habitat') light = hour < 7 || hour >= 23 ? 20 : hour >= 20 ? 150 : 420;
  else if (zoneId === 'exercise') light = hour >= 7 && hour < 22 ? 500 : 30;
  else light = hour >= 7 && hour < 22 ? base.light_lux : 60;
  return {
    zone: zoneId, day, hour: pyRound(hour, 2), co2_ppm: pyRound(co2), temperature_c: pyRound(temp, 1), humidity_pct: pyRound(hum, 1),
    light_lux: light, occupants, status: envStatus(co2, temp, hum), source: 'estimated',
  };
}

const SHIFTS: Record<string, number> = { A01: 0, A02: 1, A03: -0.5, A04: 0.5 };

export function calendar(day: number, latest: Record<string, Row>): CrewCalendar {
  const blocks: Record<string, CalendarBlock[]> = {};
  for (const c of CREW) {
    const s = SHIFTS[c.id];
    const sleep = Number(latest[c.id]?.sleep_hours ?? 7.5) || 7.5;
    const wake = (23 + s + sleep) % 24;
    const raw: CalendarBlock[] = [
      { start: 0, end: wake, kind: 'sleep', title: 'Sleep period', zone: 'habitat' },
      { start: wake, end: wake + 1, kind: 'personal', title: 'Hygiene & breakfast', zone: 'habitat' },
      { start: wake + 1, end: 12 + s, kind: 'work', title: 'Primary duties', zone: c.home_zone },
      { start: 12 + s, end: 13 + s, kind: 'meal', title: 'Crew meal', zone: 'habitat' },
      { start: 13 + s, end: 14.5 + s, kind: 'exercise', title: 'Exercise countermeasures', zone: 'exercise' },
      { start: 14.5 + s, end: 18.5 + s, kind: 'work', title: 'Assigned tasks', zone: c.home_zone },
      { start: 18.5 + s, end: 19.5 + s, kind: 'health', title: 'Daily check-in', zone: 'medical' },
      { start: 19.5 + s, end: 23 + s, kind: 'personal', title: 'Personal & recovery time', zone: 'habitat' },
      { start: 23 + s, end: 24, kind: 'sleep', title: 'Sleep period', zone: 'habitat' },
    ];
    blocks[c.id] = raw.filter((b) => b.end - b.start > 0.01).map((b) => ({ ...b, start: pyRound(b.start, 2), end: pyRound(b.end, 2) }));
  }
  return { day, blocks, source: 'simulated' };
}

export function blockAt(blocks: CalendarBlock[], hour: number): CalendarBlock {
  return blocks.find((b) => b.start <= hour && hour < b.end) ?? blocks[blocks.length - 1];
}

const AVAILABILITY: Record<CalendarBlock['kind'], CrewLocation['availability']> = {
  sleep: 'resting', work: 'on task', exercise: 'exercise', meal: 'available', personal: 'available', health: 'check-in',
};

export function shipState(day: number, hour: number, latest: Record<string, Row>, phantomStatus: Record<string, Analysis['status']>): ShipState {
  const cal = calendar(day, latest);
  const crew: CrewLocation[] = CREW.map((c) => {
    const b = blockAt(cal.blocks[c.id], hour);
    return { id: c.id, name: c.name, zone: b.zone, activity: b.title, availability: AVAILABILITY[b.kind],
      reduced_load_suggested: phantomStatus[c.id] === 'attention', location_source: 'schedule' };
  });
  const zones: Zone[] = ZONES.map(({ offset: _o, ...z }) => ({
    ...z, environment: zoneEnvironment(day, z.id, hour, crew.filter((p) => p.zone === z.id).length),
  }));
  return { day, hour, zones, crew, reference: REFERENCE, source: 'simulated', note: 'Crew positions are inferred from the synthetic schedule, not tracked.' };
}

const ZONE_OCC: Record<ZoneId, number> = { command: 1.4, habitat: 1.6, medical: 0.3, exercise: 0.4, systems: 0.6 };
export function zoneHistory(start: number, end: number, zoneId: ZoneId): ZoneEnvironment[] {
  const out: ZoneEnvironment[] = [];
  for (let d = Math.max(1, start); d <= end; d++) {
    const e = zoneEnvironment(d, zoneId, 9, 0);
    e.co2_ppm = pyRound(e.co2_ppm + 55 * ZONE_OCC[zoneId]);
    e.occupants = ZONE_OCC[zoneId];
    e.status = envStatus(e.co2_ppm, e.temperature_c, e.humidity_pct);
    out.push(e);
  }
  return out;
}

function utilisation(loads: Record<string, number>, limits: Record<string, number>): number {
  return Math.max(...Object.keys(loads).map((k) => (limits[k] ? loads[k] / limits[k] : loads[k] ? 1e9 : 0)));
}

const taskOrder = (a: Task, b: Task) => a.priority - b.priority || b.hours - a.hours || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);

export function schedules(opts: { reduceA01?: boolean; tasks?: Task[]; capacity?: Record<string, number>; unavailable?: string[]; optimise?: boolean } = {}): Schedule {
  const tasks = opts.tasks ?? TASKS;
  const optimise = opts.optimise ?? true;
  const limits: Record<string, number> = Object.fromEntries(CREW.map((c) => [c.id, c.capacity]));
  if (opts.reduceA01) limits.A01 = 2;
  for (const [k, v] of Object.entries(opts.capacity ?? {})) if (k in limits) limits[k] = v;
  for (const k of opts.unavailable ?? []) if (k in limits) limits[k] = 0;
  const skills = Object.fromEntries(CREW.map((c) => [c.id, c.skills as string[]]));
  let loads: Record<string, number> = Object.fromEntries(Object.keys(limits).map((k) => [k, 0]));
  const who: Record<string, string | null> = {};
  const ids = Object.keys(limits).sort();
  for (const task of [...tasks].sort(taskOrder)) {
    const q = Object.keys(limits).filter((c) => skills[c].includes(task.skill) && loads[c] + task.hours <= limits[c]);
    if (q.length) {
      const best = q.sort((a, b) => loads[a] / Math.max(1, limits[a]) - loads[b] / Math.max(1, limits[b]) || (a < b ? -1 : 1))[0];
      loads[best] += task.hours;
      who[task.id] = best;
    } else who[task.id] = null;
  }
  const greedyPeak = utilisation(loads, limits);
  let moves = 0;
  if (optimise) {
    let improved = true;
    while (improved && moves < 50) {
      improved = false;
      for (const task of [...tasks].sort((a, b) => (a.id < b.id ? -1 : 1))) {
        const cur = who[task.id];
        if (cur == null) continue;
        for (const c of ids) {
          if (c === cur || !skills[c].includes(task.skill) || loads[c] + task.hours > limits[c]) continue;
          const trial = { ...loads, [cur]: loads[cur] - task.hours, [c]: loads[c] + task.hours };
          if (utilisation(trial, limits) < utilisation(loads, limits) - 1e-9) {
            loads = trial; who[task.id] = c; moves++; improved = true; break;
          }
        }
      }
    }
  }
  const assignments: Assignment[] = [...tasks].sort(taskOrder).map((t) => ({ ...t, astronaut_id: who[t.id] }));
  return {
    assignments, loads: Object.fromEntries(Object.entries(loads).map(([k, v]) => [k, pyRound(v, 2)])), capacity: limits,
    unassigned: assignments.filter((x) => x.astronaut_id == null).length, peak_utilisation: pyRound(utilisation(loads, limits), 3),
    greedy_peak_utilisation: pyRound(greedyPeak, 3), local_search_moves: moves,
    method: optimise ? 'greedy_heuristic+local_search' : 'greedy_heuristic', source: 'simulated',
  };
}

export const effectiveWorkload = (w: number, crew: number) => Math.min(100, (w * 4) / Math.max(1, crew));

export function runScenario(history: Row[], p: { sleep_delta: number; workload: number; co2_ppm: number; temperature_c: number; day: number; crew_available: number }): SimulationResult {
  const original = history.find((x) => x.day === p.day);
  if (!original) throw new Error('No measurement for this mission day');
  const o = original as Record<MetricKey, number>;
  const eff = effectiveWorkload(p.workload, p.crew_available);
  const load = (eff - 50) / 35;
  const adjusted: Row = {
    ...original,
    sleep_hours: pyRound(Math.max(2, Math.min(12, o.sleep_hours + p.sleep_delta)), 2),
    heart_rate_bpm: pyRound(o.heart_rate_bpm + load * 3 + ((p.co2_ppm - 850) / 600) * 1.8, 1),
    fatigue_1_10: pyRound(Math.max(1, Math.min(10, o.fatigue_1_10 + load * 0.6 - p.sleep_delta * 0.3)), 1),
    reaction_ms: pyRound(o.reaction_ms + load * 12 - p.sleep_delta * 5, 1),
    activity_minutes: pyRound(Math.max(0, o.activity_minutes + load * 15), 1),
    source: 'simulated',
  };
  const copied = [...history.filter((r) => r.day !== p.day), adjusted];
  const unavailable = p.crew_available < 4 ? CREW.slice(p.crew_available).map((c) => c.id) : [];
  return {
    day: p.day, input: { sleep_delta: p.sleep_delta, workload: p.workload, co2_ppm: p.co2_ppm, temperature_c: p.temperature_c, crew_available: p.crew_available },
    metrics: Object.fromEntries(METRIC_KEYS.map((k) => [k, adjusted[k] as number])) as Record<MetricKey, number>,
    phantom: analyze(copied, p.day), environment: { co2_ppm: p.co2_ppm, temperature_c: p.temperature_c },
    crew: schedules({ reduceA01: eff > 70, unavailable }), source: 'simulated',
    assumptions: 'Illustrative coefficients, not validated biological effects or causation.',
  };
}

const COEF: Partial<Record<MetricKey, [number, number, number]>> = {
  heart_rate_bpm: [1.2, 3.0, 1.8], fatigue_1_10: [0.45, 0.6, 0.3], reaction_ms: [9.0, 12.0, 6.0], activity_minutes: [0, -15.0, 0],
};
const NOISE: Record<MetricKey, number> = { heart_rate_bpm: 1.5, fatigue_1_10: 0.4, reaction_ms: 8, activity_minutes: 6, sleep_hours: 0.25 };
const CLAMP: Record<MetricKey, [number, number]> = { heart_rate_bpm: [30, 200], fatigue_1_10: [1, 10], reaction_ms: [120, 1500], activity_minutes: [0, 240], sleep_hours: [2, 12] };
export const PROJECTION_ASSUMPTIONS = [
  'Sleep debt accumulates from the gap between planned sleep and personal baseline, recovering 40 % per day.',
  'Workload is divided among available crew; one index unit = 35 points above a workload of 50.',
  'Environment index = (CO₂ − 850 ppm)/600 + max(0, temperature − 24 °C)/3.',
  'The starting day’s deviation from baseline fades with a time constant of 4–10 days.',
  'Each run samples effect sizes (log-normal, σ = 0.3) and daily noise; bands show the 10th–90th percentile of runs.',
  'All coefficients are illustrative assumptions, not validated physiology.',
];

function pct(sorted: number[], q: number): number {
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

export function project(history: Row[], p: { start_day: number; horizon_days: number; sleep_delta: number; workload: number; co2_ppm: number; temperature_c: number; crew_available: number; runs: number; seed: number }): Projection {
  const start = history.find((x) => x.day === p.start_day) as (Row & Record<MetricKey, number>) | undefined;
  if (!start) throw new Error('No measurement for this mission day');
  const baselines = computeBaselines(history);
  if (METRIC_KEYS.some((k) => baselines[k] == null)) throw new Error('Insufficient baseline history for projection');
  const nBase = history.filter((r) => r.day <= BASELINE_END).length;
  const base = Object.fromEntries(METRIC_KEYS.map((k) => [k, baselines[k]!.median])) as Record<MetricKey, number>;
  const planned = Math.max(2, Math.min(12, base.sleep_hours + p.sleep_delta));
  const deficit = Math.max(0, base.sleep_hours - planned);
  const load = (effectiveWorkload(p.workload, p.crew_available) - 50) / 35;
  const env = (p.co2_ppm - 850) / 600 + Math.max(0, p.temperature_c - 24) / 3;
  const rng = new Mulberry32(p.seed);
  const keys = [...METRIC_KEYS, 'score'] as const;
  const samples: Record<string, number[][]> = Object.fromEntries(keys.map((k) => [k, Array.from({ length: p.horizon_days + 1 }, () => [] as number[])]));
  const attention = new Array<number>(p.horizon_days + 1).fill(0);
  for (let run = 0; run < p.runs; run++) {
    const mult = [0, 1, 2].map(() => Math.exp(0.3 * rng.normal()));
    const tau = 4 + 6 * rng.next();
    let debt = 0;
    for (let t = 0; t <= p.horizon_days; t++) {
      if (t > 0) debt = debt * 0.6 + deficit;
      const fade = Math.exp(-t / tau);
      const vals = {} as Record<MetricKey, number>;
      for (const k of METRIC_KEYS) {
        const startOffset = Number(start[k]) - base[k];
        let v: number;
        if (k === 'sleep_hours') v = t === 0 ? Number(start[k]) : planned + NOISE[k] * rng.normal();
        else {
          const [a, b, c] = COEF[k]!;
          const effect = mult[0] * a * debt + mult[1] * b * load + mult[2] * c * env;
          v = base[k] + startOffset * fade + (t > 0 ? effect : 0);
          if (t > 0) v += NOISE[k] * rng.normal();
        }
        const [lo, hi] = CLAMP[k];
        vals[k] = Math.min(hi, Math.max(lo, v));
        samples[k][t].push(vals[k]);
      }
      const s = scoreValues({ day: p.start_day + t, ...vals }, baselines, nBase);
      samples.score[t].push(s.score);
      if (s.status === 'attention') attention[t]++;
    }
  }
  const days: ProjectionDay[] = [];
  for (let t = 0; t <= p.horizon_days; t++) {
    const row = { day: p.start_day + t, attention_share: pyRound(attention[t] / p.runs, 3) } as ProjectionDay;
    for (const k of keys) {
      const vs = [...samples[k][t]].sort((x, y) => x - y);
      (row as Record<string, unknown>)[k] = { p10: pyRound(pct(vs, 0.1), 2), p50: pyRound(pct(vs, 0.5), 2), p90: pyRound(pct(vs, 0.9), 2) };
    }
    days.push(row);
  }
  return {
    start_day: p.start_day, horizon_days: p.horizon_days, runs: p.runs, seed: p.seed,
    input: { sleep_delta: p.sleep_delta, workload: p.workload, co2_ppm: p.co2_ppm, temperature_c: p.temperature_c, crew_available: p.crew_available },
    derived: {
      planned_sleep_h: pyRound(planned, 2), sleep_deficit_h: pyRound(deficit, 2), workload_index: pyRound(load, 3), environment_index: pyRound(env, 3),
      baseline: Object.fromEntries(METRIC_KEYS.map((k) => [k, pyRound(base[k], 2)])) as Record<MetricKey, number>,
    },
    days, assumptions: PROJECTION_ASSUMPTIONS, source: 'simulated',
    note: '“attention_share” is the fraction of simulated runs that crossed the PHANTOM flag threshold – a property of this model, not a probability of a real health event.',
  };
}
