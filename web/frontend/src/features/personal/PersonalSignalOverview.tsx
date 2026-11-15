import type { Measurement, PersonalSignalSnapshot } from '../../api/accountApi';
import { latestTwinReadings } from './personalTwinData';

const GROUPS = [
  { title: 'Heart & circulation', origin: 'BLE HRS can supply HR and sometimes RR', signals: [
    { keys: ['heart_rate', 'heart_rate_bpm'], label: 'Heart rate', unit: 'bpm' },
    { keys: ['rr_interval'], label: 'Cardiac RR interval', unit: 'ms' },
  ] },
  { title: 'Breathing & oxygenation', origin: 'Requires separate compatible sensors or recorded measurements', signals: [
    { keys: ['respiratory_rate'], label: 'Breathing rate', unit: 'breaths/min' },
    { keys: ['spo2'], label: 'Blood oxygen saturation', unit: '%' },
  ] },
  { title: 'Daily life & cognitive', origin: 'Manual or separately imported signals; not provided by Bluetooth HRS', signals: [
    { keys: ['sleep_hours', 'sleep_duration'], label: 'Sleep duration', unit: 'h' },
    { keys: ['activity_minutes'], label: 'Activity', unit: 'min' },
    { keys: ['fatigue_1_10'], label: 'Self-reported fatigue', unit: 'score' },
    { keys: ['reaction_ms'], label: 'Reaction time', unit: 'ms' },
  ] },
  { title: 'Cabin / environment', origin: 'Independent environmental sensors; never inferred from heart rate', signals: [
    { keys: ['temperature'], label: 'Temperature (source-specific)', unit: 'degC' },
    { keys: ['humidity'], label: 'Humidity', unit: '%' },
    { keys: ['co2'], label: 'Carbon dioxide', unit: 'ppm' },
    { keys: ['light'], label: 'Illuminance', unit: 'lux' },
  ] },
] as const;

const BAD = new Set(['corrupt', 'rejected', 'no_contact', 'connection_lost']);
export function snapshotValue(s: PersonalSignalSnapshot, keys: readonly string[]): Measurement | null {
  const readings = s.items.filter((m) => keys.includes(m.signal) && m.value !== null && !m.missing
    && !BAD.has(m.quality) && Number.isFinite(m.value) && !!m.measured_at);
  return readings.sort((a, b) => (Date.parse(b.measured_at ?? b.received_at) - Date.parse(a.measured_at ?? a.received_at)) || b.seq - a.seq)[0] ?? null;
}

function sourceLabel(m: Measurement): string {
  if (m.origin === 'simulated') return 'SYNTHETIC';
  if (m.origin === 'manual') return 'MANUAL';
  if (m.origin === 'research') return 'RESEARCH';
  if (m.origin === 'real' && m.metadata?.data_class === 'real_wearable' && m.written_via === 'device_manager') return 'REAL SENSOR';
  if (m.origin === 'real' && m.metadata?.data_class === 'real_wearable') return 'REAL / PROVENANCE CHECK NEEDED';
  return 'UNVERIFIED';
}

export function PersonalSignalOverview({ snapshot }: { snapshot: PersonalSignalSnapshot }) {
  const collected = latestTwinReadings(snapshot.items);
  return (
    <section className="card space-y-4 p-4 sm:p-5" aria-label="Actual sensor coverage across physiological and environment channels">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><p className="mono-label text-cyan">PERSONAL SIGNAL COVERAGE · SQLite</p>
          <h2 className="text-lg font-semibold">What AETHER actually received</h2>
          <p className="mt-1 text-sm text-ink-3">The app never invents a missing breath, sleep cycle, oxygen reading or cabin measurement.</p></div>
        <span className="rounded-lg border border-line px-3 py-2 text-xs text-ink-2">{collected.length} human signal types present · NOT a health score</span>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        {GROUPS.map((group) => <div key={group.title} className="rounded-xl border border-line p-3">
          <h3 className="text-sm font-semibold text-ink">{group.title}</h3><p className="mb-3 text-xs text-ink-3">{group.origin}</p>
          <div className="space-y-2">
            {group.signals.map(({ keys, label, unit }) => {
              const m = snapshotValue(snapshot, keys);
              const count = keys.reduce((sum, key) => sum + (snapshot.counts[key]?.usable ?? 0), 0);
              const value = m && m.value !== null
                ? m.signal === 'sleep_duration' && m.unit === 's' ? m.value / 3600 : m.value : null;
              return <div key={label} className="flex flex-wrap items-start justify-between gap-2 rounded-lg bg-raised/30 px-2 py-2 text-xs">
                <div><div className="font-medium text-ink">{label}</div>
                  <div className="text-ink-3">{m ? `${sourceLabel(m)} · ${m.quality} · ${count} usable` : 'Not measured / no usable records'}</div>
                  {m?.measured_at && <div className="text-ink-3">{new Date(m.measured_at).toLocaleString()} · historical sample</div>}
                </div>
                <span className={m ? 'font-semibold tabular text-cyan' : 'text-ink-3'}>{value !== null && Number.isFinite(value)
                  ? `${Number(value.toFixed(1))} ${unit}` : '—'}</span>
              </div>;
            })}
          </div>
        </div>)}
      </div>
      <p className="text-xs text-ink-3">BLE HRS measures heart rate and optionally cardiac beat-to-beat RR intervals. RR is not a breathing measurement or clinically verified NN/HRV. Displayed values are stored records, never inferred from other channels. PHANTOM 1.5 scientifically analyses heart-rate deviation, not all channels together.</p>
    </section>
  );
}
