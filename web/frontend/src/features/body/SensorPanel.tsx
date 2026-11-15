import { useEffect, useState } from 'react';
import { navigate } from '../../lib/router';
import { Button, Card, Pill } from '../../ui';
import { bioApi } from '../biosignals/BiosignalPage';

type LiveSensor = {
  connection: string;
  heart_rate: number | null;
  quality: string;
  last_sample_utc: string | null;
  error: string | null;
};

/** Show the real standard BLE HRS adapter, not the obsolete Web Bluetooth placeholder.
 * A connected device is NOT claimed to be medically validated. Simulated mission
 * measurements are never silently replaced by the readings from this adapter.
 */
export function SensorPanel() {
  const [sensor, setSensor] = useState<LiveSensor | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    const refresh = () => bioApi<LiveSensor>('/sensor/status').then(
      s => { if (alive) { setSensor(s); setError(''); } },
      e => { if (alive) { setSensor(null); setError((e as Error).message); } },
    );
    void refresh();
    const timer = setInterval(refresh, 3000);
    return () => { alive = false; clearInterval(timer); };
  }, []);
  const valid = sensor?.connection === 'connected' && sensor?.quality === 'screened' &&
    typeof sensor?.heart_rate === 'number';
  return <Card eyebrow="Data sources" title="Sensor connections">
    <ul className="grid gap-3 md:grid-cols-3">
      <li className="rounded-xl border border-line p-3 space-y-2" data-aether-live-rendered="true">
        <div className="font-medium text-sm">Bluetooth Heart Rate Service</div>
        <Pill tone={valid ? 'good' : 'info'} icon="bluetooth">{valid ? 'Live HRS' : 'Ready to connect'}</Pill>
        <p className="text-sm text-ink-2">{valid ? `${sensor!.heart_rate} bpm · screened signal · ${sensor!.last_sample_utc ?? 'time unknown'}` : 'No current measured HR. Open BIOSIGNALS to scan, connect and save.'}</p>
        {sensor?.error && <p role="status" className="text-xs text-attention">{sensor.error}</p>}
        {error && <p role="status" className="text-xs text-attention">Sensor API unavailable: {error}</p>}
        <p className="text-xs text-ink-3">Standard HRS-compatible monitors only; physical hardware compatibility remains unverified. Real readings are separate from synthetic mission data.</p>
        <Button size="sm" onClick={() => navigate('/biosignals')}>Open Live Sensors</Button>
      </li>
      <li className="rounded-xl border border-line p-3 space-y-2">
        <div className="font-medium text-sm">Research wristband recordings</div>
        <Pill tone="info">Local import</Pill>
        <p className="text-sm text-ink-2">Import published MMASH activity, sleep and RR files. No live actigraphy watch integration is claimed.</p>
        <Button size="sm" onClick={() => navigate('/biosignals')}>Import MMASH</Button>
      </li>
      <li className="rounded-xl border border-line p-3 space-y-2">
        <div className="font-medium text-sm">Mind Pulse reaction test</div>
        <Pill tone="good" icon="checkCircle">Available in app</Pill>
        <p className="text-sm text-ink-2">Behavioural reaction-time measurement in RECOVERY; not a Bluetooth physiological signal.</p>
        <Button size="sm" onClick={() => navigate('/recovery/mind-pulse')}>Open Mind Pulse</Button>
      </li>
    </ul>
  </Card>;
}
