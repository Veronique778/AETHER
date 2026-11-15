import { useEffect, useState } from 'react';
import { bioApi } from './BiosignalPage';

type Status = {
  connection: string;
  quality: string;
  heart_rate: number | null;
  last_sample_utc: string | null;
};

export function useLiveHeartRate() {
  const [status, setStatus] = useState<Status | null>(null);
  useEffect(() => {
    let active = true;
    const tick = () => bioApi<Status>('/sensor/status').then(
      data => { if (active) setStatus(data); },
      () => { if (active) setStatus(null); },
    );
    void tick();
    const interval = setInterval(tick, 3000);
    return () => { active = false; clearInterval(interval); };
  }, []);
  const fresh = status?.connection === 'connected' && status?.quality === 'screened' &&
    typeof status?.heart_rate === 'number';
  return {
    fresh: Boolean(fresh),
    label: fresh ? `${status!.heart_rate} bpm · measured via BLE HRS` : 'No live heart-rate measurement',
    timestamp: fresh ? status!.last_sample_utc : null,
  };
}
