/**
 * DEMO MODE MOCK SERVER – not part of the UI and not a frontend algorithm.
 * Reference port of web/backend/app/analytics.py (PHANTOM, owned by Human Systems) so
 * Demo Mode can return realistic typed responses. Parity enforced by backend/tests/test_parity.py.
 */
import { METRIC_KEYS, type Analysis, type Correlations, type MetricKey, type PhantomAlert, type PhantomHistory, type PhantomPoint, type Signal } from '../api/types';

export type Row = { day: number; source?: string } & Partial<Record<MetricKey, number | null>>;

export const BASELINE_END = 40;
const MIN_BASELINE_POINTS = 10;
const FLAG_Z = 2.0;
export const LABELS: Record<MetricKey, [string, string, 1 | -1]> = {
  heart_rate_bpm: ['Resting heart rate', 'bpm', 1],
  sleep_hours: ['Sleep duration', 'h', -1],
  fatigue_1_10: ['Self-reported fatigue', '/10', 1],
  reaction_ms: ['Reaction time', 'ms', 1],
  activity_minutes: ['Physical activity', 'min', -1],
};
const SCALE_FLOOR: Record<MetricKey, number> = { heart_rate_bpm: 2.8, sleep_hours: 0.35, fatigue_1_10: 0.55, reaction_ms: 13, activity_minutes: 11 };
export const METHOD = {
  name: 'Robust personal-baseline deviation (median / MAD)',
  baseline_window: `mission days 1–${BASELINE_END}`,
  flag_threshold_z: FLAG_Z,
  steps: [
    `Personal baseline = median of days 1–${BASELINE_END} for each signal.`,
    'Spread = 1.4826 × median absolute deviation, with a per-signal minimum.',
    'Deviation = (today − baseline) / spread, signed so that positive means “less favourable”.',
    `A signal is flagged when its deviation is ≥ ${FLAG_Z}.`,
    'Index = Σ min(15, 3·|z|) over flagged signals, +20 if two or more change together, capped at 100.',
  ],
  limitations: [
    'Heuristic research index, not a probability and not a diagnosis.',
    'Assumes the baseline window was representative of the person.',
    'Co-occurring deviations do not establish a cause.',
  ],
};

/**
 * Python's round(): correctly rounded on the exact binary value, ties (only possible
 * when x·10ⁿ is exactly representable as k+0.5) go to the even neighbour.
 * toFixed() also works on the exact binary value but rounds exact ties away from zero.
 */
export function pyRound(x: number, n = 0): number {
  const m = x * 10 ** n;
  if (Number.isFinite(m) && Math.abs(m - Math.trunc(m)) === 0.5 && Number(m.toFixed(1)) === m) {
    const lo = Math.floor(m);
    return (lo % 2 === 0 ? lo : lo + 1) / 10 ** n;
  }
  return Number(x.toFixed(n));
}

export function median(values: number[]): number {
  const s = [...values].sort((a, b) => a - b);
  const n = s.length;
  if (n === 0) return NaN;
  return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
}

export type Baselines = Record<MetricKey, { median: number; scale: number; n: number } | null>;

export function computeBaselines(history: Row[]): Baselines {
  const earlier = history.filter((r) => (r.day ?? 0) <= BASELINE_END);
  const out = {} as Baselines;
  for (const key of METRIC_KEYS) {
    const valid = earlier.map((x) => x[key]).filter((v): v is number => v != null).map(Number);
    if (valid.length < MIN_BASELINE_POINTS) { out[key] = null; continue; }
    const base = median(valid);
    const mad = median(valid.map((v) => Math.abs(v - base)));
    out[key] = { median: base, scale: Math.max(1.4826 * mad, SCALE_FLOOR[key]), n: valid.length };
  }
  return out;
}

export function scoreValues(current: Row, baselines: Baselines, nBaselineDays: number) {
  const signals: Signal[] = [];
  const missing: MetricKey[] = [];
  for (const key of METRIC_KEYS) {
    const b = baselines[key];
    const now = current[key];
    if (now == null || b == null) { missing.push(key); continue; }
    const z = (Number(now) - b.median) / b.scale;
    const severity = Math.max(0, LABELS[key][2] * z);
    signals.push({
      key, label: LABELS[key][0], unit: LABELS[key][1], value: pyRound(Number(now), 2), baseline: pyRound(b.median, 2),
      scale: pyRound(b.scale, 3), deviation: pyRound(z, 2), adverse_deviation: pyRound(severity, 2), flagged: severity >= FLAG_Z,
    });
  }
  const flagged = signals.filter((x) => x.flagged);
  const coverage = signals.length / METRIC_KEYS.length;
  const multi = flagged.length >= 2;
  const score = Math.min(100, pyRound(flagged.reduce((s, x) => s + Math.min(15, Math.abs(x.deviation) * 3), 0) + (multi ? 20 : 0)));
  const quality = coverage === 1 ? 'complete' : coverage >= 0.6 ? 'partial' : 'insufficient';
  const uncertainty: Analysis['uncertainty'] = nBaselineDays < 15 || coverage < 0.6 ? 'high' : coverage < 1 ? 'medium' : 'low';
  const status: Analysis['status'] = !signals.length ? 'insufficient' : flagged.length ? 'attention' : 'normal';
  return { signals, missing, flagged, multi, score, quality, uncertainty, status };
}

const DISCLAIMER = 'Research-only heuristic on synthetic data; not a diagnosis or probability.';

export function analyze(history: Row[], day = 67): Analysis {
  const current = history.find((r) => r.day === day);
  if (!current) {
    return {
      day, status: 'insufficient', score: null, data_quality: 'no current reading', uncertainty: 'high', signals: [],
      flagged_count: 0, multi_signal_pattern: false, explanation: 'No reading for selected day.',
      next_measurements: ['Record current measurements'], source: 'research_prototype', current_source: null, method: METHOD, disclaimer: DISCLAIMER,
    };
  }
  const nBase = history.filter((r) => (r.day ?? 0) <= BASELINE_END).length;
  const s = scoreValues(current, computeBaselines(history), nBase);
  let explanation: string;
  if (s.flagged.length) {
    explanation = `Changes relative to this astronaut's historical baseline: ${s.flagged.map((x) => x.label.toLowerCase()).join(', ')}.`;
    if (s.multi) explanation += ' Multiple metrics changed together; this does not establish a cause.';
  } else {
    explanation = 'No large deviations from the available personal baseline were found.';
  }
  let next = s.missing.map((k) => LABELS[k][0]);
  if (!next.length && s.flagged.length) {
    next = ['Repeat resting heart-rate measurement', 'Confirm sleep and workload log'];
    if (s.flagged.some((x) => x.key === 'reaction_ms')) next.push('Repeat a Mind Pulse reaction test at a consistent time of day');
  }
  return {
    day, status: s.status, score: s.signals.length ? s.score : null, data_quality: s.quality, uncertainty: s.uncertainty,
    signals: s.signals, flagged_count: s.flagged.length, multi_signal_pattern: s.multi, explanation,
    next_measurements: next.slice(0, 3), source: 'research_prototype', current_source: (current.source as Analysis['current_source']) ?? null,
    baseline_days: nBase, method: METHOD, disclaimer: DISCLAIMER,
  };
}

export function historyScores(history: Row[], start: number, end: number): PhantomHistory {
  const baselines = computeBaselines(history);
  const nBase = history.filter((r) => (r.day ?? 0) <= BASELINE_END).length;
  const byDay = new Map(history.map((r) => [r.day, r]));
  const points: PhantomPoint[] = [];
  type Ep = { start_day: number; end_day: number; peak_score: number; signals: Set<MetricKey>; ongoing?: boolean };
  const episodes: Ep[] = [];
  let open: Ep | null = null;
  for (let day = Math.max(1, start); day <= end; day++) {
    const row = byDay.get(day);
    if (!row) { points.push({ day, status: 'insufficient', score: null, flagged: [] }); continue; }
    const s = scoreValues(row, baselines, nBase);
    const keys = s.flagged.map((x) => x.key);
    points.push({ day, status: s.status, score: s.score, flagged: keys, source: row.source as PhantomPoint['source'] });
    if (s.status === 'attention') {
      if (!open) open = { start_day: day, end_day: day, peak_score: s.score, signals: new Set(keys) };
      else { open.end_day = day; open.peak_score = Math.max(open.peak_score, s.score); keys.forEach((k) => open!.signals.add(k)); }
    } else if (open) { episodes.push(open); open = null; }
  }
  if (open) { open.ongoing = true; episodes.push(open); }
  const alerts: PhantomAlert[] = episodes.map((e) => ({
    start_day: e.start_day, end_day: e.end_day, peak_score: e.peak_score, signals: [...e.signals].sort(),
    ongoing: e.ongoing ?? false, label: e.peak_score < 50 ? 'Review suggested' : 'Priority review suggested',
  }));
  return { points, alerts: alerts.reverse(), source: 'research_prototype' };
}

function ranks(values: number[]): number[] {
  const order = values.map((_, i) => i).sort((a, b) => values[a] - values[b]);
  const r = new Array<number>(values.length).fill(0);
  let i = 0;
  while (i < order.length) {
    let j = i;
    while (j + 1 < order.length && values[order[j + 1]] === values[order[i]]) j++;
    const avg = (i + j) / 2 + 1;
    for (let k = i; k <= j; k++) r[order[k]] = avg;
    i = j + 1;
  }
  return r;
}

function pearson(a: number[], b: number[]): number | null {
  const n = a.length;
  if (n < 3) return null;
  const ma = a.reduce((s, x) => s + x, 0) / n;
  const mb = b.reduce((s, x) => s + x, 0) / n;
  const sa = Math.sqrt(a.reduce((s, x) => s + (x - ma) ** 2, 0));
  const sb = Math.sqrt(b.reduce((s, x) => s + (x - mb) ** 2, 0));
  if (sa === 0 || sb === 0) return null;
  return a.reduce((s, x, i) => s + (x - ma) * (b[i] - mb), 0) / (sa * sb);
}

export const spearman = (a: number[], b: number[]) => pearson(ranks(a), ranks(b));

export function correlations(history: Row[], day: number, window = 30): Correlations {
  const rows = history.filter((r) => day - window < r.day && r.day <= day);
  const matrix = [];
  for (const a of METRIC_KEYS) {
    for (const b of METRIC_KEYS) {
      const pairs = rows.filter((r) => r[a] != null && r[b] != null).map((r) => [Number(r[a]), Number(r[b])] as const);
      const rho = pairs.length >= 8 ? spearman(pairs.map((p) => p[0]), pairs.map((p) => p[1])) : null;
      matrix.push({ a, b, rho: rho == null ? null : pyRound(rho, 3), n: pairs.length });
    }
  }
  return {
    day, window_days: window, method: 'Spearman rank correlation', metrics: [...METRIC_KEYS], matrix,
    note: 'Association within one person’s recent history; not evidence of causation. Pairs with fewer than 8 days are not computed.',
    source: 'research_prototype',
  };
}
