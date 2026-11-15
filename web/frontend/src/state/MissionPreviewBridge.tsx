import { useEffect, useMemo, useState, type ReactNode } from 'react';
import type { Astronaut } from '../api/types';
import { createDemoApi } from '../mocks/demoApi';
import { MissionPreviewProvider, useApp } from './AppState';
import { useAuth } from './AuthState';
import { navigate } from '../lib/router';
import { useBiosignal } from '../features/biosignals/BiosignalPage';
import { Button, Notice } from '../ui';
import { latestTwinReadings } from '../features/personal/personalTwinData';

/**
 * Render the existing interactive ship, games, cabin and mission simulator inside the
 * same authenticated desktop shell. Only this subtree receives the SYNTHETIC adapter;
 * BE2 personal records and authentication are never passed into synthetic crew APIs.
 */
export function MissionPreviewBridge({ children }: { children: ReactNode }) {
  const app = useApp();
  const { token, user, api: accountApi } = useAuth();
  const { choose } = useBiosignal();
  const demoApi = useMemo(() => createDemoApi(), []);
  const [crew, setCrew] = useState<Astronaut[]>([]);
  const [latest, setLatest] = useState<Array<{ label: string; value: number; unit: string; origin: string; timestamp: string }>>([]);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  useEffect(() => {
    let active = true;
    void demoApi.astronauts().then((list) => { if (active) setCrew(list); });
    return () => { active = false; };
  }, [demoApi]);
  useEffect(() => {
    if (!user || !token) { setLatest([]); setStatus('ready'); return; }
    let active = true;
    const controller = new AbortController();
    setStatus('loading');
    void accountApi.latestMeasurements(token, controller.signal)
      .then((snapshot) => {
        if (!active) return;
        setLatest(latestTwinReadings(snapshot.items).map((r) => ({
          label: r.signal.label, value: r.value, unit: r.signal.unit, origin: r.provenance, timestamp: r.timestamp,
        })));
        setStatus('ready');
      })
      .catch(() => { if (active) setStatus('error'); });
    return () => { active = false; controller.abort(); };
  }, [token, user?.id, accountApi]);

  if (app.mode !== 'live') return <>{children}</>;
  return (
    <>
      <section className="mb-4 space-y-3" aria-label="Unified AETHER research and personal context">
        <Notice tone="attention" title="MISSION SIMULATION · SYNTHETIC CREW A01–A04">
          This spacecraft, cabin, crew schedule and recovery simulation use modelled mission data. Your signed-in
          personal measurements remain separate; they are not silently assigned to simulated astronauts or used as environmental sensor readings.
        </Notice>
        <div className="card flex flex-wrap items-center justify-between gap-3 p-3" aria-label="Personal data alongside simulation">
          <div className="min-w-0 text-sm">
            <span className="font-semibold text-ink">Your actual signal snapshot alongside the simulated mission</span>
            <p className="text-ink-3">
              {!user ? 'Sign in to view your records without leaving Mission Control.'
                : status === 'loading' ? 'Loading your latest stored physiological signals…'
                : status === 'error' ? 'Personal data unavailable — simulation continues independently.'
                : latest.length ? latest.map((r) => `${r.label}: ${Number(r.value.toFixed(1))} ${r.unit} (${r.origin})`).join(' · ') + ' — historical personal records, not mission crew telemetry'
                : 'No usable personal physiological signals recorded yet.'}
            </p>
          </div>
          <Button variant="primary" onClick={() => { if (user) choose('personal'); navigate(user ? '/body' : '/login'); }}>
            {user ? 'Open my 3D personal twin' : 'Sign in'}
          </Button>
        </div>
      </section>
      <MissionPreviewProvider
        api={demoApi}
        astronauts={crew}
        astronautId={/^A0[1-4]$/.test(app.astronautId) ? app.astronautId : 'A01'}
      >
        {children}
      </MissionPreviewProvider>
    </>
  );
}
