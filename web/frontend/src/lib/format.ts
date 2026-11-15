import type { MetricKey } from '../api/types';

export const METRICS: Record<MetricKey, { label: string; short: string; unit: string; decimals: number; better: 'lower' | 'higher'; system: BodySystem }> = {
  heart_rate_bpm: { label: 'Resting heart rate', short: 'Heart rate', unit: 'bpm', decimals: 0, better: 'lower', system: 'cardiovascular' },
  sleep_hours: { label: 'Sleep duration', short: 'Sleep', unit: 'h', decimals: 1, better: 'higher', system: 'nervous' },
  fatigue_1_10: { label: 'Perceived fatigue', short: 'Fatigue', unit: '/10', decimals: 1, better: 'lower', system: 'nervous' },
  reaction_ms: { label: 'Reaction time', short: 'Reaction', unit: 'ms', decimals: 0, better: 'lower', system: 'nervous' },
  activity_minutes: { label: 'Physical activity', short: 'Activity', unit: 'min', decimals: 0, better: 'higher', system: 'musculoskeletal' },
};

export type BodySystem = 'cardiovascular' | 'respiratory' | 'nervous' | 'musculoskeletal' | 'metabolic';
/** Visual layers of the BODY twin. Metric → layer mapping only; no clinical meaning is implied. */
export const BODY_SYSTEMS: Record<BodySystem, { label: string; description: string; metrics: MetricKey[]; color: string; note?: string }> = {
  cardiovascular: { label: 'Cardiovascular', description: 'Heart, arteries and veins. Resting heart rate as a coarse load indicator.', metrics: ['heart_rate_bpm'], color: '#ff6b81' },
  respiratory: { label: 'Respiratory', description: 'Trachea and lungs. The AETHER API has no respiratory measurement yet.', metrics: [], color: '#6fe7ff', note: 'No respiratory metric in the API (pending sensor contract). Demo Mode shows labelled demo channels.' },
  nervous: { label: 'Neurological', description: 'Brain, spinal cord and nerves. Reaction time, sleep duration and self-reported fatigue.', metrics: ['reaction_ms', 'sleep_hours', 'fatigue_1_10'], color: '#a875ff' },
  musculoskeletal: { label: 'Musculoskeletal', description: 'Skeleton and limbs. Daily countermeasure exercise minutes.', metrics: ['activity_minutes'], color: '#e8e0cc' },
  metabolic: { label: 'Metabolic', description: 'Liver, stomach and intestine shown for orientation.', metrics: [], color: '#ffbf69', note: 'No metabolic metric in the API – visual layer only.' },
};

export function fmt(v: number | null | undefined, decimals = 0): string {
  if (v == null || Number.isNaN(v)) return '—';
  return v.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export const fmtMetric = (k: MetricKey, v: number | null | undefined) => fmt(v, METRICS[k].decimals);

export function hourLabel(h: number): string {
  const hh = Math.floor(((h % 24) + 24) % 24);
  const mm = Math.round((h - Math.floor(h)) * 60) % 60;
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
}

export const dayLabel = (d: number) => `Day ${String(d).padStart(3, '0')}`;

export function initials(name: string) {
  return name.split(/\s+/).map((p) => p[0]).join('').slice(0, 2).toUpperCase();
}

export const CREW_COLORS: Record<string, string> = {
  A01: 'var(--color-series-1)', A02: 'var(--color-series-2)', A03: 'var(--color-series-3)', A04: 'var(--color-series-4)',
};
export const CREW_HEX: Record<string, string> = { A01: '#3987e5', A02: '#199e70', A03: '#9a7ae0', A04: '#d55181' };

export function downloadText(filename: string, text: string, type = 'text/markdown') {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Fixed categorical colour per metric (CVD-validated series order 1–5; never cycled). */
export const METRIC_COLOR: Record<MetricKey, string> = {
  heart_rate_bpm: 'var(--color-series-1)', sleep_hours: 'var(--color-series-2)', fatigue_1_10: 'var(--color-series-3)',
  reaction_ms: 'var(--color-series-4)', activity_minutes: 'var(--color-series-5)',
};
