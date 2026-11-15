import type { Measurement } from '../../api/accountApi';
import type { BodySystem } from '../../lib/format';

export type DisplaySignal = { key: string; aliases: string[]; unit: string; label: string; system: BodySystem; scale?: number };
const DISPLAY: DisplaySignal[] = [
  { key: 'heart_rate_bpm', aliases: ['heart_rate', 'heart_rate_bpm'], unit: 'bpm', label: 'Heart rate', system: 'cardiovascular' },
  { key: 'rr_interval', aliases: ['rr_interval'], unit: 'ms', label: 'Cardiac RR interval', system: 'cardiovascular' },
  { key: 'respiratory_rate', aliases: ['respiratory_rate'], unit: 'breaths/min', label: 'Respiration rate', system: 'respiratory' },
  { key: 'spo2', aliases: ['spo2'], unit: '%', label: 'Oxygen saturation', system: 'respiratory' },
  { key: 'sleep_hours', aliases: ['sleep_hours', 'sleep_duration'], unit: 'h', label: 'Sleep duration', system: 'nervous' },
  { key: 'fatigue_1_10', aliases: ['fatigue_1_10'], unit: 'score', label: 'Fatigue (reported)', system: 'nervous' },
  { key: 'reaction_ms', aliases: ['reaction_ms'], unit: 'ms', label: 'Reaction time', system: 'nervous' },
  { key: 'activity_minutes', aliases: ['activity_minutes'], unit: 'min', label: 'Activity', system: 'musculoskeletal' },
];
const BAD_QUALITY = new Set(['corrupt', 'rejected', 'no_contact', 'connection_lost']);

export type PersonalTwinReading = { signal: DisplaySignal; value: number; origin: string; quality: string; timestamp: string; source: string; provenance: string };

/** No interpolation or mixing of data origins; an absent signal stays absent. */
export function latestTwinReadings(rows: Measurement[]): PersonalTwinReading[] {
  return DISPLAY.flatMap((signal) => {
    const matched = rows.filter((row) => signal.aliases.includes(row.signal)
      && !row.missing && typeof row.value === 'number' && Number.isFinite(row.value)
      && !BAD_QUALITY.has(row.quality) && (row.measured_at || row.received_at)
      && (row.unit === signal.unit || (signal.key === 'sleep_hours' && row.signal === 'sleep_duration' && row.unit === 's')));
    const row = matched.sort((a, b) => (Date.parse(b.measured_at ?? b.received_at) - Date.parse(a.measured_at ?? a.received_at)) || b.seq - a.seq)[0];
    if (!row || row.value === null) return [];
    const value = signal.key === 'sleep_hours' && row.signal === 'sleep_duration'
      ? row.value / 3600 : row.value;
    return [{ signal, value, origin: row.origin, quality: row.quality,
      timestamp: row.measured_at ?? row.received_at, source: row.source,
      provenance: row.origin === 'real' && row.metadata?.data_class === 'real_wearable' && row.written_via === 'device_manager' ? 'REAL SENSOR (SERVER-ATTESTED)'
        : row.origin === 'simulated' ? 'SYNTHETIC'
        : row.origin === 'manual' ? 'MANUAL / UNVERIFIED'
        : row.origin === 'research' ? 'TERRESTRIAL RESEARCH' : 'UNVERIFIED REAL INPUT' }];
  });
}

