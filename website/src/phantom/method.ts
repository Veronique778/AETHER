/**
 * Browser ILLUSTRATION of the published PHANTOM personal-HR formulas (FORMULA_AUDIT F-3 … F-9).
 *
 * This is NOT the validated implementation (`phantom_hr_univariate_1_4` in the Windows app). It re-implements the
 * documented steps on fixed synthetic control scenarios so visitors can see how a frozen personal baseline,
 * a robust scale and a robust z threshold produce flag / no_flag / insufficient_data. Every output is SYNTHETIC DEMO.
 */
export type Sample = { t: number; hr: number | null; contact: boolean };          // t = seconds from start
export type Window = {
  index: number; start: number; mean: number | null; usable: boolean; reason?: string;
  z: number | null; flag: boolean; baseline: boolean;
};
export type Outcome = 'flag' | 'no_flag' | 'insufficient_data';
export type Result = {
  outcome: Outcome; windows: Window[]; median: number | null; mad: number | null; scale: number | null;
  baselineWindows: number; testWindows: number; flaggedWindows: number; maxZ: number | null; reason: string;
};

export const WINDOW_S = 300;
export const BASELINE_S = 3600;
export const MIN_BASELINE_WINDOWS = 10;
export const MIN_WINDOW_VALID = 20;
export const MIN_VALID_SPAN_S = 240;
export const MAX_VALID_GAP_S = 60;
export const MIN_VALID_FRACTION = 0.8;
export const SCALE_FLOOR = 3;
export const THRESHOLD = 3.5;

const median = (xs: number[]) => {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};
const round3 = (x: number) => Math.round(x * 1000) / 1000;

function windowStats(samples: Sample[], start: number): { mean: number | null; usable: boolean; reason?: string } {
  const inside = samples.filter((s) => s.t >= start && s.t < start + WINDOW_S);
  const valid = inside.filter((s) => s.hr !== null && s.contact && s.hr >= 25 && s.hr <= 240);
  if (!inside.length) return { mean: null, usable: false, reason: 'no measurements' };
  if (valid.length < MIN_WINDOW_VALID) return { mean: null, usable: false, reason: 'too few valid samples' };
  if (valid.length / inside.length < MIN_VALID_FRACTION) return { mean: null, usable: false, reason: 'low valid fraction' };
  const ts = valid.map((s) => s.t);
  const edges = [ts[0] - start, ...ts.slice(1).map((t, i) => t - ts[i]), start + WINDOW_S - ts[ts.length - 1]];
  if (ts[ts.length - 1] - ts[0] < MIN_VALID_SPAN_S || Math.max(...edges) > MAX_VALID_GAP_S) {
    return { mean: null, usable: false, reason: 'gap inside the window' };
  }
  return { mean: round3(valid.reduce((a, s) => a + (s.hr as number), 0) / valid.length), usable: true };
}

export function analyse(samples: Sample[], durationS: number): Result {
  const n = Math.floor(durationS / WINDOW_S);
  const windows: Window[] = [];
  for (let k = 0; k < n; k++) {
    const start = k * WINDOW_S;
    const st = windowStats(samples, start);
    windows.push({ index: k, start, ...st, z: null, flag: false, baseline: start < BASELINE_S });
  }
  const base = windows.filter((w) => w.baseline && w.usable).map((w) => w.mean as number);
  const test = windows.filter((w) => !w.baseline);
  const empty = { median: null, mad: null, scale: null, baselineWindows: base.length, maxZ: null, flaggedWindows: 0 };
  if (durationS < BASELINE_S + WINDOW_S || base.length < MIN_BASELINE_WINDOWS) {
    return { ...empty, outcome: 'insufficient_data', windows, testWindows: test.filter((w) => w.usable).length,
      reason: `The frozen personal baseline needs ≥ ${MIN_BASELINE_WINDOWS} usable 5-minute windows in the first 60 minutes, followed by data to analyse. Found ${base.length} usable baseline window(s).` };
  }
  const M = median(base);
  const mad = median(base.map((x) => Math.abs(x - M)));
  const s = Math.max(SCALE_FLOOR, 1.4826 * mad);
  for (const w of test) {
    if (!w.usable || w.mean === null) continue;
    w.z = round3(Math.abs(w.mean - M) / s);
    w.flag = w.z >= THRESHOLD;
  }
  const scored = test.filter((w) => w.z !== null);
  if (!scored.length) {
    return { ...empty, median: M, mad, scale: s, outcome: 'insufficient_data', windows, testWindows: 0,
      reason: 'No usable window after the baseline hour: nothing can be compared.' };
  }
  const flagged = scored.filter((w) => w.flag).length;
  const maxZ = Math.max(...scored.map((w) => w.z as number));
  return {
    outcome: flagged ? 'flag' : 'no_flag', windows, median: M, mad, scale: s, baselineWindows: base.length,
    testWindows: scored.length, flaggedWindows: flagged, maxZ,
    reason: flagged
      ? `${flagged} of ${scored.length} analysed windows differ from the frozen baseline by ≥ ${THRESHOLD} robust spreads (largest z = ${maxZ.toFixed(2)}).`
      : `All ${scored.length} analysed windows stay within ${THRESHOLD} robust spreads of the baseline (largest z = ${maxZ.toFixed(2)}). This does not mean “healthy”.`,
  };
}
