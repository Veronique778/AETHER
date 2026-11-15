import { useCallback, useEffect, useRef, useState, type ComponentType } from 'react';
import type { RecoveryActivity, RecoverySession, SessionDetails } from '../../api/types';
import { BarRows, ChartFrame, TimeSeriesChart } from '../../charts';
import { navigate, useRoute } from '../../lib/router';
import { useResource } from '../../lib/useResource';
import { useApp, useAstronaut } from '../../state/AppState';
import { Async, Button, Card, cx, Empty, Icon, Notice, SourceBadge, TabPanel, Tabs, useTab, type IconName, type TabDef } from '../../ui';
import { ModuleHeader } from '../shared/ModuleHeader';
import { RecoveryRecommendations } from './Recommendations';

type RecTab = 'activities' | 'lab';
const TABS: TabDef<RecTab>[] = [{ id: 'activities', label: 'Activities', icon: 'leaf' }, { id: 'lab', label: 'Personal Recovery Lab', icon: 'activity' }];
import { EarthWindow } from './activities/EarthWindow';
import { MindPulse } from './activities/MindPulse';
import { OrbitFlow } from './activities/OrbitFlow';
import { ZeroGGarden } from './activities/ZeroGGarden';

type ActivityProps = { reducedMotion: boolean; onReport: (d: SessionDetails) => void };
export const ACTIVITIES: Record<RecoveryActivity, { name: string; icon: IconName; blurb: string; component: ComponentType<ActivityProps> }> = {
  'zero-g-garden': { name: 'Zero-G Garden', icon: 'leaf', blurb: 'Paced breathing grows a small garden. Pacing feedback, adjustable rhythm.', component: ZeroGGarden },
  'earth-window': { name: 'Earth Window', icon: 'mountain', blurb: 'Quiet Earth landscapes, generated ambient sound and a gentle rest timer.', component: EarthWindow },
  'orbit-flow': { name: 'Orbit Flow', icon: 'puzzle', blurb: 'Untimed connection puzzles that adapt their size to how you solve them.', component: OrbitFlow },
  'mind-pulse': { name: 'Mind Pulse', icon: 'timer', blurb: 'A one-minute go/no-go reaction test with reaction time and accuracy.', component: MindPulse },
};
const IDS = Object.keys(ACTIVITIES) as RecoveryActivity[];

export function RecoveryPage() {
  const { segments } = useRoute();
  const activity = IDS.includes(segments[1] as RecoveryActivity) ? (segments[1] as RecoveryActivity) : null;
  return (
    <div className="theme-recovery -mx-4 -my-6 min-h-[calc(100vh-57px)] bg-canvas px-4 py-6 lg:-mx-8 lg:px-8">
      {activity ? <Session activity={activity} /> : <Hub />}
    </div>
  );
}

function Hub() {
  const astronaut = useAstronaut();
  const { api, astronautId, dataVersion } = useApp();
  const [tab, setTab] = useTab(TABS);
  const sessions = useResource(`rec-${api.mode}-${astronautId}-${dataVersion}`, () => api.recovery(astronautId));
  return (
    <div>
      <ModuleHeader module="/recovery" title={`Recovery space${astronaut ? ` · ${astronaut.name.split(' ')[0]}` : ''}`}
        description="Short, optional activities for decompression. Each session asks how you feel before and after, so you can see what tends to help you." />
      <RecoveryHero />
      <RecoveryRecommendations sessions={sessions.data} />
      <RecoveryTrends />
      <Tabs label="RECOVERY sections" tabs={TABS} value={tab} onChange={setTab} />
      <TabPanel label={TABS.find((t) => t.id === tab)!.label}>
      {tab === 'lab' ? <RecoveryLab /> : (
        <div className="space-y-5">
          <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {IDS.map((id) => {
              const mine = sessions.data?.filter((x) => x.activity === id) ?? [];
              const mean = mine.length ? mine.reduce((t, x) => t + x.after_mood - x.before_mood, 0) / mine.length : null;
              return (
                <li key={id}>
                  <button type="button" onClick={() => navigate(`/recovery/${id}`)} className="card interactive group flex h-full w-full flex-col items-start gap-2 overflow-hidden p-0 text-left hover:border-moss-500">
                    <span className="always-dark relative block h-32 w-full overflow-hidden bg-[#0d1612]"><ActivityArt id={id} /></span>
                    <span className="flex w-full flex-1 flex-col gap-2 px-5 pb-5 pt-2">
                      <span className="flex items-center gap-2 text-lg font-semibold text-calm"><Icon name={ACTIVITIES[id].icon} size={18} className="text-teal-300" />{ACTIVITIES[id].name}</span>
                      <span className="text-sm text-ink-2">{ACTIVITIES[id].blurb}</span>
                      <span className="text-xs text-ink-3">{mine.length ? `You: ${mine.length} session${mine.length === 1 ? '' : 's'} · mean change ${mean! >= 0 ? '+' : ''}${mean!.toFixed(1)}` : 'Not tried yet'}</span>
                      <span className="mt-auto inline-flex items-center gap-1 text-sm text-teal-300 transition-transform group-hover:translate-x-0.5">Begin <Icon name="arrowRight" size={15} /></span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <Async res={sessions}>{(all) => <OwnSummary sessions={all} />}</Async>
        </div>
      )}
      </TabPanel>
    </div>
  );
}

/** Sleep and self-reported fatigue (the only recovery-related signals the API provides). */
function RecoveryTrends() {
  const { api, astronautId, day, dataVersion } = useApp();
  const tl = useResource(`tl-${api.mode}-${astronautId}-${day}-${dataVersion}`, () => api.timeline(astronautId, day));
  return (
    <section aria-label="Sleep and fatigue trends" className="card mb-5 p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div><div className="mono-label text-teal-300">Recovery indicators · last 21 days</div><h2 className="text-base font-semibold text-calm">Sleep and how tired you felt</h2></div>
        <SourceBadge source={tl.data?.at(-1)?.source ?? 'simulated'} />
      </div>
      <Async res={tl}>{(rows) => {
        const r = rows.slice(-21);
        return (
          <div className="grid gap-4 md:grid-cols-2">
            <TimeSeriesChart height={150} ariaLabel="Sleep hours, last 21 days" series={[{ id: 's', label: 'Sleep', color: 'var(--color-series-2)', points: r.map((x) => ({ x: x.day, y: x.sleep_hours })) }]} xFormat={(x) => `D${x}`} yFormat={(y) => y.toFixed(1)} unit="h" />
            <TimeSeriesChart height={150} ariaLabel="Self-reported fatigue, last 21 days" yDomain={[1, 10]} series={[{ id: 'f', label: 'Fatigue', color: 'var(--color-series-3)', points: r.map((x) => ({ x: x.day, y: x.fatigue_1_10 })) }]} xFormat={(x) => `D${x}`} yFormat={(y) => y.toFixed(1)} unit="/10" />
          </div>
        );
      }}</Async>
      <p className="mt-2 text-xs text-ink-3">AETHER has no stress or HRV measurement; self-reported fatigue is shown as it was entered, not as a stress score.</p>
    </section>
  );
}

/** Calm hero: slow particle drift over an Earth limb, plus a breathing orb that paces the eye. */
function RecoveryHero() {
  const { reducedMotion } = useApp();
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let raf = 0;
    const t0 = performance.now();
    const frame = (t: number) => { paintHero(ref.current, reducedMotion ? 0 : (t - t0) / 1000); if (!reducedMotion) raf = requestAnimationFrame(frame); };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [reducedMotion]);
  return (
    <section aria-label="Recovery space" className="always-dark relative mb-5 overflow-hidden rounded-2xl border border-line">
      <canvas ref={ref} className="block h-56 w-full" aria-hidden="true" />
      <div className="absolute inset-0 flex items-center gap-6 px-6 sm:px-10">
        <div className="relative grid h-28 w-28 shrink-0 place-items-center" aria-hidden="true">
          <span className="breathe-orb absolute inset-0 rounded-full bg-[radial-gradient(circle,rgba(227,214,189,.45),rgba(156,201,173,.12)_60%,transparent_70%)]" />
          <span className="h-8 w-8 rounded-full bg-[#e3d6bd]/80 shadow-[0_0_30px_rgba(227,214,189,.6)]" />
        </div>
        <div className="max-w-xl">
          <div className="mono-label text-[#9cc9ad]">Take a few minutes</div>
          <p className="mt-1 text-xl font-semibold text-[#e3d6bd] sm:text-2xl">Breathe with the light. In as it grows, out as it fades.</p>
          <p className="mt-1 text-sm text-[#b9c7bd]">Nothing here is scored against you. Pick any activity below, or simply watch for a minute.</p>
        </div>
      </div>
    </section>
  );
}

function paintHero(canvas: HTMLCanvasElement | null, t: number) {
  if (!canvas) return;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return;
  const dpr = Math.min(2, devicePixelRatio || 1);
  if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
  const ctx = canvas.getContext('2d')!;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, '#0a1410'); g.addColorStop(1, '#13241c');
  ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
  for (let i = 0; i < 90; i++) {
    const x = ((((i * 7919) % 1000) / 1000) * w - t * (4 + (i % 5)) + w * 4) % w;
    const y = (((i * 3571) % 1000) / 1000) * h * 0.85;
    const a = 0.25 + 0.35 * (0.5 + 0.5 * Math.sin(t * 0.6 + i));
    ctx.fillStyle = `rgba(227,214,189,${a * 0.6})`;
    ctx.beginPath(); ctx.arc(x, y, i % 9 === 0 ? 1.6 : 0.9, 0, Math.PI * 2); ctx.fill();
  }
  const R = w * 1.2, cx = w * 0.62, cy = h + R - h * 0.28;
  const glow = ctx.createRadialGradient(cx, cy, R * 0.98, cx, cy, R * 1.05);
  glow.addColorStop(0, 'rgba(120,190,200,0.35)'); glow.addColorStop(1, 'rgba(120,190,200,0)');
  ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(cx, cy, R * 1.05, 0, Math.PI * 2); ctx.fill();
  const earth = ctx.createLinearGradient(0, h * 0.7, 0, h);
  earth.addColorStop(0, '#2d5a6b'); earth.addColorStop(1, '#183a33');
  ctx.fillStyle = earth; ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();
  ctx.save(); ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.clip();
  for (let k = 0; k < 5; k++) {
    ctx.fillStyle = 'rgba(255,255,255,0.07)';
    const x = ((k * 0.27 - t * 0.003) % 1.2 + 1.2) % 1.2 * w - w * 0.1;
    ctx.beginPath(); ctx.ellipse(x, h * (0.82 + k * 0.03), 120 + k * 20, 9, -0.05, 0, Math.PI * 2); ctx.fill();
  }
  ctx.restore();
}

function ActivityArt({ id }: { id: RecoveryActivity }) {
  if (id === 'zero-g-garden') return (
    <svg viewBox="0 0 200 100" className="h-full w-full" aria-hidden="true">
      <defs><radialGradient id="ag1" cx="50%" cy="100%" r="80%"><stop offset="0" stopColor="#2f5a43" /><stop offset="1" stopColor="#0d1612" /></radialGradient></defs>
      <rect width="200" height="100" fill="url(#ag1)" />
      {[40, 75, 110, 145, 170].map((x, i) => (
        <g key={x} className="breathe-orb" style={{ ['--breath' as string]: `${8 + i}s`, transformOrigin: `${x}px 100px` }}>
          <path d={`M${x} 100 C ${x - 6} ${80 - i * 4}, ${x + 8} ${60 - i * 3}, ${x + 2} ${40 + (i % 2) * 10}`} stroke="#9cc9ad" strokeWidth="2" fill="none" />
          <ellipse cx={x + 2} cy={40 + (i % 2) * 10} rx="7" ry="4" fill={i % 2 ? '#e3d6bd' : '#7fb08f'} />
        </g>
      ))}
    </svg>
  );
  if (id === 'earth-window') return (
    <svg viewBox="0 0 200 100" className="h-full w-full" aria-hidden="true">
      <rect width="200" height="100" fill="#070c12" />
      {Array.from({ length: 24 }, (_, i) => <circle key={i} cx={(i * 53) % 200} cy={(i * 29) % 60} r={i % 5 ? 0.6 : 1} fill="#e3d6bd" opacity=".6" />)}
      <circle cx="100" cy="150" r="96" fill="#7cc4d4" opacity=".18" />
      <circle cx="100" cy="150" r="90" fill="#24506a" />
      <path d="M40 90 q20 -16 40 -6 t40 -4 t40 8" stroke="#3f7a5a" strokeWidth="10" fill="none" opacity=".8" />
      <path d="M30 78 q50 -12 140 0" stroke="#fff" strokeWidth="3" fill="none" opacity=".25" />
    </svg>
  );
  if (id === 'orbit-flow') return (
    <svg viewBox="0 0 200 100" className="h-full w-full" aria-hidden="true">
      <rect width="200" height="100" fill="#0d1612" />
      {[18, 30, 42].map((r) => <ellipse key={r} cx="100" cy="50" rx={r * 1.8} ry={r} fill="none" stroke="#5f7268" strokeDasharray="2 4" />)}
      <path d="M46 50 H80 V30 H120 V70 H154" stroke="#9cc9ad" strokeWidth="5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M46 50 H80 V30 H120 V70 H154" className="flow-dash" stroke="#e3d6bd" strokeWidth="2" fill="none" strokeLinecap="round" />
      <circle cx="100" cy="50" r="9" fill="#e3d6bd" />
    </svg>
  );
  return (
    <svg viewBox="0 0 200 100" className="h-full w-full" aria-hidden="true">
      <rect width="200" height="100" fill="#0d1612" />
      <path d="M0 55 H60 L70 35 L80 75 L90 20 L100 60 L110 55 H200" stroke="#9cc9ad" strokeWidth="2.5" fill="none" strokeLinejoin="round" />
      <g className="breathe-orb" style={{ ['--breath' as string]: '6s', transformOrigin: '160px 50px' }}><circle cx="160" cy="50" r="22" fill="#e3d6bd" opacity=".18" /><circle cx="160" cy="50" r="10" fill="#e3d6bd" /></g>
    </svg>
  );
}

/** Descriptive summary of the user's own sessions. The API offers no recommendation service yet. */
function OwnSummary({ sessions }: { sessions: RecoverySession[] }) {
  if (!sessions.length) return null;
  const by = IDS.map((id) => { const s = sessions.filter((x) => x.activity === id); return { id, n: s.length, mean: s.length ? s.reduce((t, x) => t + x.after_mood - x.before_mood, 0) / s.length : null }; });
  const best = by.filter((b) => b.n >= 2 && b.mean != null).sort((a, b) => b.mean! - a.mean!)[0];
  const last = [...sessions].sort((a, b) => b.id - a.id)[0];
  return (
    <section aria-label="From your own sessions" className="card grid gap-4 p-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div>
        <div className="mono-label text-teal-300">From your own sessions</div>
        <p className="mt-1 text-ink-2">{sessions.length} session{sessions.length === 1 ? '' : 's'} recorded. Last: {ACTIVITIES[last.activity].name}, mood {last.before_mood} → {last.after_mood}.</p>
        {best ? <p className="mt-1 text-ink-2">Your largest average self-rated change so far: <strong className="text-calm">{ACTIVITIES[best.id].name}</strong> ({best.mean! >= 0 ? '+' : ''}{best.mean!.toFixed(1)}, n = {best.n}).</p>
          : <p className="mt-1 text-ink-3">Try an activity at least twice to compare averages.</p>}
        <Button size="sm" variant="ghost" iconRight="arrowRight" className="-ml-2 mt-1" onClick={() => navigate('/recovery?tab=lab')}>Open Personal Recovery Lab</Button>
      </div>
      <Notice tone="unknown" title="Descriptive, not a recommendation">This summarises your own ratings without a control condition. Personalised recommendations are a pending Human Systems service; until it exists AETHER does not suggest one activity over another.</Notice>
    </section>
  );
}

function MoodScale({ value, onChange, label }: { value: number | null; onChange: (v: number) => void; label: string }) {
  return (
    <fieldset>
      <legend className="mb-2 text-ink">{label}</legend>
      <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={label}>
        {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
          <button key={n} type="button" role="radio" aria-checked={value === n} onClick={() => onChange(n)}
            className={cx('tabular h-11 w-11 rounded-xl border text-sm font-medium', value === n ? 'border-sand bg-moss-500 text-white' : 'border-line-strong text-ink-2 hover:border-moss-300')}>{n}</button>
        ))}
      </div>
      <div className="mt-1 flex max-w-[520px] justify-between text-xs text-ink-3"><span>1 · very low</span><span>10 · very good</span></div>
    </fieldset>
  );
}

function Session({ activity }: { activity: RecoveryActivity }) {
  const { api, astronautId, reducedMotion, bumpData } = useApp();
  const A = ACTIVITIES[activity];
  const [step, setStep] = useState<'before' | 'activity' | 'after' | 'saved'>('before');
  const [before, setBefore] = useState<number | null>(null);
  const [after, setAfter] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const details = useRef<SessionDetails>({});
  const startedAt = useRef(0);
  const [duration, setDuration] = useState(0);
  const onReport = useCallback((d: SessionDetails) => { details.current = d; }, []);
  const stage = useRef<HTMLDivElement>(null);
  const [full, setFull] = useState(false);
  useEffect(() => { const on = () => setFull(document.fullscreenElement === stage.current && !!stage.current); document.addEventListener('fullscreenchange', on); return () => document.removeEventListener('fullscreenchange', on); }, []);
  const toggleFull = () => { if (document.fullscreenElement) void document.exitFullscreen(); else void stage.current?.requestFullscreen?.().catch(() => undefined); };
  useEffect(() => { setStep('before'); setBefore(null); setAfter(null); details.current = {}; }, [activity]);

  const save = async () => {
    if (before == null || after == null) return;
    setBusy(true); setError(null);
    try {
      await api.saveRecovery({ astronaut_id: astronautId, activity, before_mood: before, after_mood: after, duration_seconds: duration, details: details.current });
      bumpData();
      setStep('saved');
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const Comp = A.component;
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Button variant="ghost" icon="chevronLeft" onClick={() => navigate('/recovery')}>Recovery space</Button>
        <ol className="flex items-center gap-2 text-xs text-ink-3" aria-label="Session steps">
          {(['before', 'activity', 'after'] as const).map((s, i) => <li key={s} className={cx('rounded-full border px-2 py-0.5', step === s ? 'border-sand text-calm' : 'border-line')} aria-current={step === s ? 'step' : undefined}>{i + 1}. {s === 'before' ? 'Check in' : s === 'activity' ? A.name : 'Reflect'}</li>)}
        </ol>
      </div>
      <h1 className="mb-4 flex items-center gap-2 text-2xl font-semibold text-calm"><Icon name={A.icon} size={24} />{A.name}</h1>
      {step === 'before' && (
        <Card title="Before you start" eyebrow="Check-in">
          <MoodScale label="How do you feel right now?" value={before} onChange={setBefore} />
          <div className="mt-4"><Button variant="primary" icon="arrowRight" disabled={before == null} onClick={() => { startedAt.current = performance.now(); setStep('activity'); }}>Begin activity</Button></div>
        </Card>
      )}
      {step === 'activity' && (
        <div ref={stage} className={cx(full && 'overflow-auto bg-canvas p-6')}>
        <Card bodyClassName="pt-5">
          <Comp reducedMotion={reducedMotion} onReport={onReport} />
          <div className="mt-5 flex flex-wrap justify-between gap-2 border-t border-line pt-4">
            <Button variant="ghost" icon="expand" onClick={toggleFull} aria-pressed={full}>{full ? 'Exit full screen' : 'Full screen'}</Button>
            <Button variant="primary" icon="check" onClick={() => { if (document.fullscreenElement) void document.exitFullscreen(); setDuration(Math.round((performance.now() - startedAt.current) / 1000)); setStep('after'); }}>Finish activity</Button>
          </div>
        </Card>
        </div>
      )}
      {step === 'after' && (
        <Card title="After the activity" eyebrow="Reflect">
          <MoodScale label="How do you feel now?" value={after} onChange={setAfter} />
          <p className="mt-3 text-sm text-ink-3">Session length {Math.floor(duration / 60)} min {duration % 60} s. Recorded activity data: {Object.keys(details.current).length ? Object.entries(details.current).map(([k, v]) => `${k.replaceAll('_', ' ')}: ${v ?? '—'}`).join(' · ') : 'none'}.</p>
          {error && <Notice tone="high" className="mt-3">{error}</Notice>}
          <div className="mt-4 flex gap-2"><Button variant="primary" icon="check" disabled={after == null || busy} onClick={save}>{busy ? 'Saving…' : 'Save session'}</Button><Button variant="ghost" onClick={() => setStep('activity')}>Back to activity</Button></div>
        </Card>
      )}
      {step === 'saved' && (
        <Card title="Session saved" eyebrow="Thank you">
          <p className="text-ink-2">Before {before} → after {after}. Your Personal Recovery Lab below now includes this session.</p>
          <div className="mt-3 flex gap-2"><Button variant="primary" onClick={() => navigate('/recovery')}>Back to recovery space</Button><Button onClick={() => { setStep('before'); setBefore(null); setAfter(null); }}>Another round</Button></div>
        </Card>
      )}
      {step === 'saved' && <div className="mt-5"><RecoveryLab /></div>}
    </div>
  );
}

export function RecoveryLab() {
  const { api, astronautId, dataVersion } = useApp();
  const res = useResource(`rec-${api.mode}-${astronautId}-${dataVersion}`, () => api.recovery(astronautId));
  return (
    <Card eyebrow="Personal Recovery Lab" title="Your sessions" actions={<SourceBadge source="manual" />}>
      <Async res={res} loadingLabel="Loading sessions">{(sessions) => sessions.length === 0 ? (
        <Empty icon="leaf" title="No sessions yet">Complete any activity above; your before/after ratings and activity metrics will appear here.</Empty>
      ) : <LabContent sessions={sessions} />}</Async>
    </Card>
  );
}

function LabContent({ sessions }: { sessions: RecoverySession[] }) {
  const chrono = [...sessions].sort((a, b) => a.id - b.id);
  const byActivity = IDS.map((id) => {
    const s = sessions.filter((x) => x.activity === id);
    return { id, n: s.length, mean: s.length ? s.reduce((t, x) => t + x.after_mood - x.before_mood, 0) / s.length : 0 };
  });
  const mp = chrono.filter((s) => s.activity === 'mind-pulse' && typeof s.details?.median_rt_ms === 'number');
  return (
    <div className="space-y-5">
      <div className="grid gap-5 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-medium text-ink">Before vs after, by session</h3>
          <ChartFrame caption="Self-rated mood before and after each session" table={{ columns: ['#', 'Activity', 'Before', 'After'], rows: chrono.map((s, i) => [i + 1, ACTIVITIES[s.activity].name, s.before_mood, s.after_mood]) }}>
            <TimeSeriesChart ariaLabel="Mood before and after each session" height={200} yDomain={[1, 10]}
              series={[
                { id: 'before', label: 'Before', color: 'var(--color-series-1)', points: chrono.map((s, i) => ({ x: i + 1, y: s.before_mood })), dashed: true },
                { id: 'after', label: 'After', color: 'var(--color-series-2)', points: chrono.map((s, i) => ({ x: i + 1, y: s.after_mood })) },
              ]}
              xFormat={(x) => `Session ${x}`} />
          </ChartFrame>
        </div>
        <div>
          <h3 className="mb-2 text-sm font-medium text-ink">Mean change by activity (after − before)</h3>
          <BarRows max={Math.max(3, ...byActivity.map((a) => Math.abs(a.mean)))} format={(v) => (v > 0 ? '+' : '') + v.toFixed(1)}
            rows={byActivity.map((a) => ({ label: ACTIVITIES[a.id].name, value: Math.max(0, a.mean), note: `n=${a.n}${a.mean < 0 ? ` · ${a.mean.toFixed(1)}` : ''}`, color: 'var(--color-moss-300)' }))} />
          {mp.length > 0 && (
            <div className="mt-4">
              <h3 className="mb-2 text-sm font-medium text-ink">Mind Pulse median reaction time</h3>
              <TimeSeriesChart ariaLabel="Mind Pulse median reaction time per session" height={140} unit="ms"
                series={[{ id: 'rt', label: 'Median RT', color: 'var(--color-sand)', points: mp.map((s, i) => ({ x: i + 1, y: s.details.median_rt_ms as number })) }]} xFormat={(x) => `Test ${x}`} yFormat={(y) => String(Math.round(y))} />
            </div>
          )}
        </div>
      </div>
      <Notice tone="unknown" title="How to read this">Self-ratings without a control condition. A positive change can reflect the activity, time passing, or expectation – this lab shows patterns for you, it does not prove an effect.</Notice>
      <div>
        <h3 className="mb-2 text-sm font-medium text-ink">History</h3>
        <div className="max-h-80 overflow-auto rounded-xl border border-line">
          <table className="tabular w-full text-sm">
            <thead className="sticky top-0 bg-raised text-left text-xs text-ink-3"><tr><th className="px-3 py-2 font-medium">When (UTC)</th><th className="font-medium">Activity</th><th className="font-medium">Mood</th><th className="font-medium">Duration</th><th className="font-medium">Activity data</th></tr></thead>
            <tbody>{sessions.map((s) => (
              <tr key={s.id} className="border-t border-line align-top">
                <td className="px-3 py-2 text-ink-3">{s.created_at}</td>
                <td className="text-ink">{ACTIVITIES[s.activity].name}</td>
                <td className="text-ink-2">{s.before_mood} → {s.after_mood} <span className={s.after_mood >= s.before_mood ? 'text-good' : 'text-attention'}>({s.after_mood - s.before_mood >= 0 ? '+' : ''}{s.after_mood - s.before_mood})</span></td>
                <td className="text-ink-2">{Math.round(s.duration_seconds / 60)} min</td>
                <td className="max-w-xs py-2 pr-3 text-xs text-ink-3">{Object.entries(s.details ?? {}).map(([k, v]) => `${k.replaceAll('_', ' ')}: ${v ?? '—'}`).join(' · ') || '—'}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
