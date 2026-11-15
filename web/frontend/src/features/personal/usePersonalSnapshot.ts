import { useEffect, useState } from 'react';
import type { PersonalSignalSnapshot } from '../../api/accountApi';
import { useAuth } from '../../state/AuthState';

type SnapshotState = { status: 'loading' | 'ready' | 'error'; data: PersonalSignalSnapshot | null; error?: string };

/** Single authenticated source for all recent sensor channels (not simulated mission crew). */
export function usePersonalSnapshot(refreshKey = 0): SnapshotState {
  const { token, user, api } = useAuth();
  const [state, setState] = useState<SnapshotState>({ status: 'loading', data: null });
  useEffect(() => {
    if (!token || !user) { setState({ status: 'error', data: null, error: 'Sign in to see your own measurements.' }); return; }
    let alive = true;
    let current: AbortController | null = null;
    const load = async () => {
      current?.abort();
      const controller = new AbortController();
      current = controller;
      try {
        const data = await api.latestMeasurements(token, controller.signal);
        if (alive && !controller.signal.aborted) setState({ status: 'ready', data });
      } catch (error) {
        if (alive && !controller.signal.aborted) setState({ status: 'error', data: null,
          error: error instanceof Error ? error.message : 'Recent measurements unavailable.' });
      }
    };
    setState({ status: 'loading', data: null });
    void load();
    const timer = setInterval(() => { if (document.visibilityState === 'visible') void load(); }, 15000);
    const focus = () => void load();
    window.addEventListener('focus', focus);
    return () => { alive = false; clearInterval(timer); window.removeEventListener('focus', focus); current?.abort(); };
  }, [api, token, user?.id, refreshKey]);
  return state;
}
