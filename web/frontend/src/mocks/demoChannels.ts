import type { ZoneId } from '../api/types';

/**
 * DEMO CHANNELS – values the AETHER API does not provide (SpO₂, respiration rate, cabin O₂, cabin pressure).
 * Used ONLY in Demo Mode, always rendered with the "Demo channel" label. Deterministic (same input ⇒ same
 * value) and deliberately flat: they illustrate layout, they carry no physiological or engineering model.
 * In Live Mode the UI shows "not provided by API" instead.
 */
export const DEMO_CHANNEL_NOTE = 'Demo channel – synthetic value generated in the browser; the AETHER API has no such measurement.';

function noise(seed: string, n: number): number {
  let h = 2166136261;
  for (const ch of `${seed}:${n}`) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619); }
  return ((h >>> 0) / 4294967295) * 2 - 1;
}
const r1 = (v: number) => Math.round(v * 10) / 10;

export function demoVitals(astronautId: string, day: number) {
  return { spo2_pct: r1(97.8 + 0.6 * noise(astronautId + 'spo2', day)), resp_rate_min: r1(14 + 1.4 * noise(astronautId + 'rr', day)) };
}
export function demoVitalsSeries(astronautId: string, day: number, n = 14) {
  return Array.from({ length: n }, (_, i) => ({ day: day - n + 1 + i, ...demoVitals(astronautId, day - n + 1 + i) }));
}
export function demoCabin(zone: ZoneId, day: number, hour: number) {
  const k = day * 24 + Math.floor(hour);
  return { o2_pct: r1(20.9 + 0.15 * noise(zone + 'o2', k)), pressure_kpa: r1(101.3 + 0.3 * noise(zone + 'p', k)) };
}
