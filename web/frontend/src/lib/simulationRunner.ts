import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Agreed control interface for MISSION LAB simulations (start / pause / reset / seek).
 * v0.2 implementation: `start` requests the full projection from the API once, then plays it
 * back day by day. A future streaming simulator (SSE/WebSocket) can implement the same
 * interface without changing the page – see docs/FRONTEND_INTEGRATION.md §MISSION LAB.
 */
export type RunnerStatus = 'idle' | 'requesting' | 'ready' | 'playing' | 'paused' | 'finished' | 'error';
export type SimulationRunner<R> = {
  status: RunnerStatus; result: R | null; error: string | null; cursor: number; length: number;
  start: () => void; pause: () => void; reset: () => void; seek: (t: number) => void; invalidate: () => void;
};

export function useSimulationRunner<R>(request: () => Promise<R>, lengthOf: (r: R) => number, stepMs: number): SimulationRunner<R> {
  const [status, setStatus] = useState<RunnerStatus>('idle');
  const [result, setResult] = useState<R | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cursor, setCursor] = useState(0);
  const req = useRef(request);
  req.current = request;
  const length = result ? lengthOf(result) : 0;

  const start = useCallback(() => {
    if (result && status !== 'error') {
      if (cursor >= length) setCursor(0);
      setStatus('playing');
      return;
    }
    setStatus('requesting');
    setError(null);
    req.current().then((r) => { setResult(r); setCursor(0); setStatus('playing'); }, (e: Error) => { setError(e.message); setStatus('error'); });
  }, [result, status, cursor, length]);

  useEffect(() => {
    if (status !== 'playing') return;
    const id = setInterval(() => setCursor((c) => {
      if (c >= length) { setStatus('finished'); return c; }
      return c + 1;
    }), stepMs);
    return () => clearInterval(id);
  }, [status, length, stepMs]);

  return {
    status, result, error, cursor, length, start,
    pause: () => { if (status === 'playing') setStatus('paused'); },
    reset: () => { setCursor(0); setStatus(result ? 'ready' : 'idle'); },
    seek: (t) => { setCursor(Math.max(0, Math.min(length, t))); if (status === 'playing' || status === 'finished') setStatus('paused'); },
    invalidate: () => { setResult(null); setCursor(0); setStatus('idle'); },
  };
}
