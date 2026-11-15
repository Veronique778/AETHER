/**
 * Mind Pulse – brief go/no-go reaction test. Pure trial generation and scoring.
 * Not a validated clinical instrument (cf. PVT); results are for self-tracking.
 */
import { Mulberry32 } from '../../../lib/random';

export type Trial = { kind: 'go' | 'nogo'; delayMs: number };
export type Response =
  | { kind: 'go' | 'nogo'; rt: number | null; falseStart?: false }   // rt null = no press
  | { kind: 'go' | 'nogo'; rt: null; falseStart: true };

export const LAPSE_MS = 500;
export const RESPONSE_WINDOW_MS = 1500;
export const MIN_VALID_RT_MS = 100;

export function makeTrials(n: number, seed: number, nogoShare = 0.2): Trial[] {
  const rng = new Mulberry32(seed);
  const nogo = Math.round(n * nogoShare);
  const kinds: Trial['kind'][] = [...Array(n - nogo).fill('go'), ...Array(nogo).fill('nogo')];
  for (let i = kinds.length - 1; i > 0; i--) { const j = Math.floor(rng.next() * (i + 1)); [kinds[i], kinds[j]] = [kinds[j], kinds[i]]; }
  return kinds.map((kind) => ({ kind, delayMs: Math.round(1200 + rng.next() * 2300) }));
}

export type MindPulseStats = {
  trials: number; goTrials: number; validGo: number; medianRt: number | null; meanRt: number | null; sdRt: number | null;
  lapses: number; omissions: number; commissions: number; falseStarts: number; anticipations: number; accuracy: number;
};

export function score(responses: Response[]): MindPulseStats {
  const go = responses.filter((r) => r.kind === 'go');
  const nogo = responses.filter((r) => r.kind === 'nogo');
  const falseStarts = responses.filter((r) => r.falseStart).length;
  const goRts = go.filter((r) => !r.falseStart && r.rt != null).map((r) => r.rt as number);
  const anticipations = goRts.filter((t) => t < MIN_VALID_RT_MS).length;
  const valid = goRts.filter((t) => t >= MIN_VALID_RT_MS).sort((a, b) => a - b);
  const omissions = go.filter((r) => !r.falseStart && r.rt == null).length;
  const commissions = nogo.filter((r) => !r.falseStart && r.rt != null).length;
  const correct = valid.length + nogo.filter((r) => !r.falseStart && r.rt == null).length;
  const mean = valid.length ? valid.reduce((s, x) => s + x, 0) / valid.length : null;
  const median = valid.length ? (valid.length % 2 ? valid[(valid.length - 1) / 2] : (valid[valid.length / 2 - 1] + valid[valid.length / 2]) / 2) : null;
  const sd = valid.length > 1 && mean != null ? Math.sqrt(valid.reduce((s, x) => s + (x - mean) ** 2, 0) / (valid.length - 1)) : null;
  return {
    trials: responses.length, goTrials: go.length, validGo: valid.length, medianRt: median, meanRt: mean, sdRt: sd,
    lapses: valid.filter((t) => t > LAPSE_MS).length, omissions, commissions, falseStarts, anticipations,
    accuracy: responses.length ? correct / responses.length : 0,
  };
}
