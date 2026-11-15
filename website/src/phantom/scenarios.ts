/** Fixed, seeded SYNTHETIC control scenarios (deterministic: the same chart for every visitor). Not measurements. */
import type { Sample } from './method';

export type ScenarioId = 'stable' | 'step' | 'drift' | 'bursts' | 'contact' | 'short';
export type Scenario = { id: ScenarioId; label: string; short: string; description: string; expected: string; durationS: number; generate: () => Sample[] };

function rng(seed: number) {
  let s = seed >>> 0;
  return () => { s = (s + 0x6d2b79f5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
function gauss(r: () => number) { return Math.sqrt(-2 * Math.log(1 - r())) * Math.cos(2 * Math.PI * r()); }

function series(seed: number, durationS: number, shape: (t: number) => number, opts: { contactLost?: [number, number]; gap?: [number, number] } = {}): Sample[] {
  const r = rng(seed);
  const out: Sample[] = [];
  let slow = 0;
  for (let t = 0; t < durationS; t += 2) {
    slow = 0.995 * slow + 0.08 * gauss(r);
    if (opts.gap && t >= opts.gap[0] && t < opts.gap[1]) continue;
    const contact = !(opts.contactLost && t >= opts.contactLost[0] && t < opts.contactLost[1]);
    const hr = 64 + slow + 1.2 * gauss(r) + shape(t);
    out.push({ t, hr: Math.round(hr * 10) / 10, contact });
  }
  return out;
}

const H3 = 3 * 3600;
export const SCENARIOS: Scenario[] = [
  { id: 'stable', label: 'Stable resting rhythm', short: 'Stable', durationS: H3, expected: 'no_flag',
    description: '3 h of steady heart rate with normal beat-to-beat noise.', generate: () => series(11, H3, () => 0) },
  { id: 'step', label: 'Sustained +15 bpm change', short: '+15 bpm step', durationS: H3, expected: 'flag',
    description: 'Heart rate rises by 15 bpm after 110 minutes and stays elevated.', generate: () => series(12, H3, (t) => (t >= 110 * 60 ? 15 : 0)) },
  { id: 'drift', label: 'Slow drift +20 bpm', short: 'Slow drift', durationS: H3, expected: 'flag',
    description: 'A gradual rise of 20 bpm over the last two hours.', generate: () => series(13, H3, (t) => (t > 3600 ? 20 * (t - 3600) / (H3 - 3600) : 0)) },
  { id: 'bursts', label: 'Short bursts (e.g. stairs)', short: 'Short bursts', durationS: H3, expected: 'flag',
    description: 'Three 6-minute bursts of +20 bpm. A known weakness: brief activity also triggers a flag.', generate: () => series(14, H3, (t) => ([80, 120, 150].some((m) => t >= m * 60 && t < (m + 6) * 60) ? 20 : 0)) },
  { id: 'contact', label: 'Contact loss + data gap', short: 'Contact loss', durationS: H3, expected: 'flag',
    description: '+15 bpm after 110 min, with 15 min of no skin contact and a 20 min Bluetooth gap: unusable windows stay empty.',
    generate: () => series(15, H3, (t) => (t >= 110 * 60 ? 15 : 0), { contactLost: [80 * 60, 95 * 60], gap: [130 * 60, 150 * 60] }) },
  { id: 'short', label: 'Too short to judge (50 min)', short: '50 min only', durationS: 50 * 60, expected: 'insufficient_data',
    description: 'Only 50 minutes recorded — not enough for a 60-minute personal baseline.', generate: () => series(16, 50 * 60, () => 0) },
];
