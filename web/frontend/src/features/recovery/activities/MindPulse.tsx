import { useCallback, useEffect, useRef, useState } from 'react';
import type { SessionDetails } from '../../../api/types';
import { TimeSeriesChart } from '../../../charts';
import { CAPABILITIES, type DataSource } from '../../../api/types';
import { useApp } from '../../../state/AppState';
import { Button, cx, Notice, Segmented, SourceBadge, Stat } from '../../../ui';
import { useLiveHeartRate } from '../../biosignals/useLiveHeartRate';
import { LAPSE_MS, makeTrials, RESPONSE_WINDOW_MS, score, type MindPulseStats, type Response, type Trial } from '../logic/mindPulse';

type Phase = 'idle' | 'wait' | 'stimulus' | 'feedback' | 'done';

export function MindPulse({ onReport }: { reducedMotion: boolean; onReport: (d: SessionDetails) => void }) {
  const { api, astronautId, day, bumpData, hasCapability } = useApp();
  const [breath, setBreath] = useState<{ seconds: number; source: 'fixed' | 'service'; note?: string; data?: DataSource }>({ seconds: 10, source: 'fixed' });
  const [sync, setSync] = useState(false);
  const canSync = hasCapability(CAPABILITIES.biofeedback);
  const liveHeart = useLiveHeartRate();
  const [count, setCount] = useState<'12' | '20' | '30'>('20');
  const [phase, setPhase] = useState<Phase>('idle');
  const [index, setIndex] = useState(0);
  const [feedback, setFeedback] = useState('');
  const [responses, setResponses] = useState<Response[]>([]);
  const [stats, setStats] = useState<MindPulseStats | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const trials = useRef<Trial[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const shownAt = useRef(0);
  const phaseRef = useRef<Phase>('idle');
  const idxRef = useRef(0);
  const acc = useRef<Response[]>([]);
  const startedAt = useRef(0);
  const [elapsed, setElapsed] = useState(0);
  phaseRef.current = phase;

  // Optional: pace the settling breath from the biofeedback service (breathing rate), clearly labelled.
  useEffect(() => {
    if (!sync || !canSync || phase !== 'idle') return;
    let alive = true;
    const poll = () => api.biofeedback(astronautId).then((f) => {
      if (!alive) return;
      if (f.breathing_rate_bpm && f.quality !== 'none') setBreath({ seconds: Math.max(4, Math.min(15, 60 / f.breathing_rate_bpm)), source: 'service', note: `${f.breathing_rate_bpm} /min · signal ${f.quality}`, data: f.source });
      else setBreath({ seconds: 10, source: 'fixed', note: 'no usable frame' });
    }, () => alive && setBreath({ seconds: 10, source: 'fixed', note: 'service unavailable' }));
    poll();
    const id = setInterval(poll, 4000);
    return () => { alive = false; clearInterval(id); };
  }, [sync, canSync, phase, api, astronautId]);
  useEffect(() => { if (!sync) setBreath({ seconds: 10, source: 'fixed' }); }, [sync]);

  const clear = () => { if (timer.current) clearTimeout(timer.current); timer.current = null; };
  useEffect(() => clear, []);
  useEffect(() => {
    if (phase === 'idle' || phase === 'done') return;
    const id = setInterval(() => setElapsed((performance.now() - startedAt.current) / 1000), 250);
    return () => clearInterval(id);
  }, [phase]);

  const finish = useCallback(() => {
    const s = score(acc.current);
    setStats(s);
    setResponses([...acc.current]);
    setPhase('done');
    onReport({ trials: s.trials, median_rt_ms: s.medianRt == null ? null : Math.round(s.medianRt), mean_rt_ms: s.meanRt == null ? null : Math.round(s.meanRt),
      lapses: s.lapses, omissions: s.omissions, commission_errors: s.commissions, false_starts: s.falseStarts, accuracy_pct: Math.round(s.accuracy * 100) });
  }, [onReport]);

  const next = useCallback((i: number) => {
    if (i >= trials.current.length) { finish(); return; }
    idxRef.current = i;
    setIndex(i);
    setPhase('wait');
    timer.current = setTimeout(() => {
      shownAt.current = performance.now();
      setPhase('stimulus');
      timer.current = setTimeout(() => record(null), RESPONSE_WINDOW_MS);
    }, trials.current[i].delayMs);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finish]);

  const record = (rt: number | null, falseStart = false) => {
    clear();
    const t = trials.current[idxRef.current];
    acc.current.push(falseStart ? { kind: t.kind, rt: null, falseStart: true } : { kind: t.kind, rt });
    let msg: string;
    if (falseStart) msg = 'Too early – wait for the shape';
    else if (t.kind === 'go') msg = rt == null ? 'Missed' : `${Math.round(rt)} ms`;
    else msg = rt == null ? 'Correctly withheld' : 'Square – no press needed';
    setFeedback(msg);
    setPhase('feedback');
    timer.current = setTimeout(() => next(idxRef.current + 1), 650);
  };

  const press = useCallback(() => {
    const p = phaseRef.current;
    if (p === 'wait') record(null, true);
    else if (p === 'stimulus') record(performance.now() - shownAt.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const on = (e: KeyboardEvent) => { if (e.code === 'Space' && (phaseRef.current === 'wait' || phaseRef.current === 'stimulus')) { e.preventDefault(); if (!e.repeat) press(); } };
    addEventListener('keydown', on);
    return () => removeEventListener('keydown', on);
  }, [press]);

  const begin = () => {
    trials.current = makeTrials(Number(count), Math.floor(Math.random() * 1e9));
    acc.current = [];
    startedAt.current = performance.now();
    setElapsed(0);
    setStats(null); setSaved(null); setResponses([]);
    next(0);
  };

  const saveToBody = async () => {
    if (!stats?.medianRt) return;
    try {
      await api.saveMeasurement(astronautId, { day, reaction_ms: Math.round(stats.medianRt) });
      bumpData();
      setSaved(`Median ${Math.round(stats.medianRt)} ms saved to BODY for day ${day} (source: manual).`);
    } catch (e) { setSaved(`Could not save: ${(e as Error).message}`); }
  };

  const t = trials.current[index];
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
      <div>
        <button type="button" onPointerDown={(e) => { e.preventDefault(); press(); }} disabled={phase === 'idle' || phase === 'done'}
          aria-label="Response area: press when the circle appears"
          className="grid h-[320px] w-full place-items-center rounded-2xl border border-line bg-moss-900 text-sand disabled:cursor-default">
          {phase === 'idle' && (
            <span className="flex flex-col items-center gap-4">
              <span className="relative grid h-28 w-28 place-items-center" aria-hidden="true">
                <span className="breathe-orb absolute inset-0 rounded-full bg-[radial-gradient(circle,rgba(227,214,189,.5),rgba(156,201,173,.15)_60%,transparent_70%)]" style={{ ['--breath' as string]: `${breath.seconds}s` }} />
                <span className="h-6 w-6 rounded-full bg-sand" />
              </span>
              <span className="max-w-sm text-center text-ink-2">Settle with two or three breaths – in as the light grows, out as it fades. Then press <kbd className="rounded border border-line-strong px-1">Space</kbd> or tap here as soon as a <strong>circle</strong> appears. Do <strong>not</strong> respond to a <strong>square</strong>.</span>
            </span>
          )}
          {phase === 'wait' && <span className="text-4xl text-ink-3" aria-hidden>+</span>}
          {phase === 'stimulus' && t && (t.kind === 'go'
            ? <span className="flex flex-col items-center gap-2"><span className="h-28 w-28 rounded-full bg-sand" /><span className="text-sm">circle – press</span></span>
            : <span className="flex flex-col items-center gap-2"><span className="h-24 w-24 rounded-md bg-dusk" /><span className="text-sm">square – wait</span></span>)}
          {phase === 'feedback' && <span className="text-xl" role="status">{feedback}</span>}
          {phase === 'done' && <span className="text-xl">Test complete</span>}
        </button>
        {(phase !== 'idle') && acc.current.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1" aria-label="Response rhythm: one mark per trial" role="img">
            {acc.current.map((r, i) => {
              const ok = r.falseStart ? false : r.kind === 'go' ? r.rt != null : r.rt == null;
              const slow = r.kind === 'go' && r.rt != null && r.rt > LAPSE_MS;
              return <span key={i} title={`Trial ${i + 1}`} className={cx('h-3 rounded-full transition-all', r.kind === 'go' ? 'w-3' : 'w-3 rounded-sm', !ok ? 'bg-attention' : slow ? 'bg-sand/50' : 'bg-teal-300')} style={r.kind === 'go' && r.rt != null ? { width: Math.max(8, Math.min(28, r.rt / 20)) } : undefined} />;
            })}
          </div>
        )}
        {phase !== 'idle' && phase !== 'done' && (
          <div className="mt-2" aria-hidden>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-raised"><div className="h-full bg-teal-300" style={{ width: `${((index + (phase === 'feedback' ? 1 : 0)) / trials.current.length) * 100}%` }} /></div>
          </div>
        )}
        <div className="mt-2 flex items-center justify-between text-sm text-ink-3">
          <span className="tabular">{phase !== 'idle' && phase !== 'done' ? `Trial ${index + 1} of ${trials.current.length} · ${Math.floor(elapsed)} s · response window ${RESPONSE_WINDOW_MS / 1000} s` : stats ? `Completed in ${Math.round(elapsed)} s` : ''}</span>
          {(phase === 'idle' || phase === 'done') && <Button variant="primary" icon="play" onClick={begin}>{phase === 'done' ? 'Run again' : 'Start test'}</Button>}
        </div>
        {stats && responses.length > 0 && (
          <div className="mt-4">
            <TimeSeriesChart ariaLabel="Reaction time per trial" height={160} unit="ms"
              series={[{ id: 'rt', label: 'Reaction time', color: 'var(--color-sand)', points: responses.map((r, i) => ({ x: i + 1, y: r.kind === 'go' && !r.falseStart ? r.rt : null })) }]}
              refLines={[{ y: LAPSE_MS, label: `lapse > ${LAPSE_MS} ms` }]} xFormat={(x) => `Trial ${x}`} yFormat={(y) => String(Math.round(y))} />
          </div>
        )}
      </div>
      <div className="space-y-3">
        <div className="rounded-xl border border-line p-3">
          <div className="eyebrow mb-1">Settling breath</div>
          <p className="text-xs text-ink-3" data-aether-live-rendered="true" data-testid="live-sensor-status">Live sensor: {liveHeart.label}. Heart rate is not used to calculate reaction-time scores.</p>
          <div className="flex items-center justify-between text-sm text-ink-2"><span className="tabular">{breath.seconds.toFixed(1)} s per breath</span>{breath.source === 'service' ? <SourceBadge source={breath.data} /> : <span className="text-xs text-ink-3">fixed pace</span>}</div>
          <label className={cx('mt-2 flex items-center gap-2 text-sm', canSync ? 'text-ink-2' : 'text-ink-3')}>
            <input type="checkbox" checked={sync} disabled={!canSync} onChange={(e) => setSync(e.target.checked)} />Sync with biofeedback breathing rate (simulated – no sensor)
          </label>
          <p className="mt-1 text-xs text-ink-3">{!canSync ? 'Biofeedback service not available in this API (pending, Human Systems).' : breath.note ? `Service: ${breath.note}` : 'Off: a fixed, non-personalised 10 s rhythm.'}</p>
        </div>
        <div><div className="eyebrow mb-1.5">Length</div><Segmented size="sm" label="Number of trials" value={count} onChange={(v) => phase === 'idle' || phase === 'done' ? setCount(v) : undefined} options={[{ value: '12', label: '12' }, { value: '20', label: '20' }, { value: '30', label: '30' }]} /></div>
        {stats ? (
          <>
            <div className="grid grid-cols-2 gap-2">
              <Stat label="Median RT" value={stats.medianRt == null ? '—' : Math.round(stats.medianRt)} unit="ms" />
              <Stat label="Accuracy" value={Math.round(stats.accuracy * 100)} unit="%" />
              <Stat label="Lapses" value={stats.lapses} sub={`> ${LAPSE_MS} ms`} />
              <Stat label="Errors" value={stats.commissions + stats.omissions + stats.falseStarts} sub={`${stats.commissions} square · ${stats.omissions} missed · ${stats.falseStarts} early`} />
            </div>
            {stats.medianRt != null && <Button size="sm" icon="body" onClick={saveToBody}>Save median to BODY (day {day})</Button>}
            {saved && <Notice tone={saved.startsWith('Could') ? 'high' : 'good'}>{saved}</Notice>}
          </>
        ) : <p className="text-sm text-ink-3">Takes about {Math.round(Number(count) * 3.4 / 10) * 10} seconds. Timing uses your device clock; results vary with hardware and are for personal tracking only.</p>}
      </div>
    </div>
  );
}
