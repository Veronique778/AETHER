/**
 * Views of a Mission Systems engine run (web/backend/mission_systems via /api/engine/*), shared by
 * MISSION LAB, CO-ORBIT, SYMBIOSIS, PHANTOM and BODY. The run itself lives in AppState.engineRun, so every
 * module shows the SAME synthetic run. All values are synthetic and labelled as such.
 */
import { useMemo, type ReactNode } from 'react';
import type { Confusion, DetectorComparison, DetectorName, EngineEnvMetric, EngineMetric, EngineRun, EngineStrategy } from '../../api/types';
import { ChartFrame, TimeSeriesChart } from '../../charts';
import { navigate } from '../../lib/router';
import { useApp } from '../../state/AppState';
import { Button, Card, cx, Icon, Notice, Pill, SourceBadge } from '../../ui';

export const ENGINE_METRICS: { value: EngineMetric; label: string; unit: string; better: 'lower' | 'higher' }[] = [
  { value: 'heart_rate', label: 'Heart rate', unit: 'bpm', better: 'lower' },
  { value: 'fatigue', label: 'Fatigue', unit: '/10', better: 'lower' },
  { value: 'cognition', label: 'Cognition', unit: '/100', better: 'higher' },
  { value: 'sleep_hours', label: 'Sleep (rolling)', unit: 'h', better: 'higher' },
  { value: 'sleep_quality', label: 'Sleep quality', unit: '/100', better: 'higher' },
  { value: 'activity', label: 'Activity', unit: 'min/day', better: 'higher' },
  { value: 'workload', label: 'Workload', unit: 'h/day', better: 'lower' },
];
export const ENGINE_ENV: { value: EngineEnvMetric; label: string; unit: string }[] = [
  { value: 'co2', label: 'CO₂', unit: 'ppm' }, { value: 'temperature', label: 'Temperature', unit: '°C' },
  { value: 'humidity', label: 'Humidity', unit: '%' }, { value: 'light', label: 'Light', unit: 'lux' },
];
export const ENGINE_CREW_COLORS = ['var(--color-series-1)', 'var(--color-series-2)', 'var(--color-series-3)', 'var(--color-series-4)'];

export const clock = (minute: number) => {
  const d = Math.floor(minute / 1440), h = Math.floor((minute % 1440) / 60), m = Math.round(minute % 60);
  return `${d ? `D+${d} ` : ''}${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
};
const pct = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v * 100)}%`);

/** Header strip used when another module shows the engine run. Returns null when no run exists. */
export function EngineRunCard({ eyebrow, title, children, actions }: { eyebrow: string; title: ReactNode; children: (run: EngineRun) => ReactNode; actions?: ReactNode }) {
  const { engineRun } = useApp();
  if (!engineRun) return null;
  return (
    <Card eyebrow={<span className="text-violet">{eyebrow}</span>} title={title} className="border-violet/40"
      actions={<>{actions}<Pill tone="info" icon="flask">{engineRun.title}</Pill><SourceBadge source="simulated" /><Button size="sm" variant="ghost" icon="arrowRight" onClick={() => navigate('/mission-lab?tab=engine')}>Open in MISSION LAB</Button></>}>
      {children(engineRun)}
    </Card>
  );
}

/** Crew time series of one metric, with injected events and PHANTOM flags. */
export function EngineCrewChart({ run, metric, cursor, onCursor, height = 220, crewFilter }: { run: EngineRun; metric: EngineMetric; cursor?: number | null; onCursor?: (m: number | null) => void; height?: number; crewFilter?: number[] }) {
  const info = ENGINE_METRICS.find((m) => m.value === metric)!;
  const crew = run.crew.filter((c) => !crewFilter || crewFilter.includes(c.id));
  const series = crew.map((c) => ({
    id: String(c.id), label: c.name, color: ENGINE_CREW_COLORS[(c.id - 1) % 4],
    points: run.times.map((t, i) => ({ x: t, y: run.series[String(c.id)][metric][i], tag: run.phantom_flags[String(c.id)]?.includes(t) ? 'flag' : undefined })),
  }));
  const markers = run.events.map((e) => ({ x: e.minute, label: `${e.kind.replace('_', ' ')}${e.crew_id ? ` · crew ${e.crew_id}` : ''}` }));
  return (
    <ChartFrame caption={`${info.label} per crew member (engine, synthetic)`} table={{ columns: ['Time', ...crew.map((c) => c.name)], rows: run.times.map((t, i) => [clock(t), ...crew.map((c) => run.series[String(c.id)][metric][i] ?? '—')]) }}>
      <TimeSeriesChart height={height} ariaLabel={`${info.label} time series for ${crew.length} crew members`} series={series} markers={markers}
        cursorX={cursor ?? null} onCursor={onCursor} unit={info.unit} xFormat={clock} yFormat={(y) => (Math.abs(y) >= 100 ? y.toFixed(0) : y.toFixed(1))}
        tagLabel={{ flag: 'PHANTOM flag' }} />
    </ChartFrame>
  );
}

export function EngineEnvChart({ run, metrics = ['co2', 'temperature'], cursor, height = 170 }: { run: EngineRun; metrics?: EngineEnvMetric[]; cursor?: number | null; height?: number }) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {metrics.map((m, k) => {
        const info = ENGINE_ENV.find((x) => x.value === m)!;
        return (
          <div key={m}>
            <div className="mb-1 text-xs text-ink-3">{info.label} · habitat ({info.unit})</div>
            <TimeSeriesChart height={height} ariaLabel={`Modelled cabin ${info.label}`} cursorX={cursor ?? null}
              series={[{ id: m, label: info.label, color: k ? 'var(--color-series-5)' : 'var(--color-series-2)', points: run.times.map((t, i) => ({ x: t, y: run.environment[m][i] })) }]}
              refLines={m === 'co2' ? [{ y: 2500, label: 'attention (illustrative)' }] : []} xFormat={clock} unit={info.unit} yFormat={(y) => (m === 'temperature' ? y.toFixed(1) : y.toFixed(0))} />
          </div>
        );
      })}
    </div>
  );
}

function ConfusionRow({ label, c, accent }: { label: string; c: Confusion | null; accent?: boolean }) {
  if (!c) return <tr className="border-t border-line"><td className="py-1.5 text-ink-2">{label}</td><td colSpan={7} className="text-ink-3">not connected</td></tr>;
  return (
    <tr className={cx('border-t border-line', accent && 'text-ink')}>
      <td className="py-1.5 font-medium">{label}</td><td>{c.tp}</td><td>{c.fp}</td><td>{c.tn}</td><td>{c.fn}</td>
      <td>{pct(c.precision)}</td><td>{pct(c.recall)}</td><td className="font-semibold">{c.f1 == null ? '—' : c.f1.toFixed(2)}</td>
    </tr>
  );
}

/** Research evaluation: AETHER PHANTOM vs the engine's fixed-threshold comparator, against hidden injected labels. */
export function EngineEvaluation({ run }: { run: EngineRun }) {
  const e = run.evaluation;
  const thresholdSilent = (e.threshold.tp + e.threshold.fp) === 0;
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="tabular w-full min-w-[520px] text-sm">
          <caption className="sr-only">Detection of injected synthetic events per crew sample</caption>
          <thead><tr className="text-left text-xs text-ink-3"><th className="py-1 font-medium">Detector</th><th className="font-medium">TP</th><th className="font-medium">FP</th><th className="font-medium">TN</th><th className="font-medium">FN</th><th className="font-medium">Precision</th><th className="font-medium">Recall</th><th className="font-medium">F1</th></tr></thead>
          <tbody>
            <ConfusionRow label="AETHER PHANTOM (median / MAD)" c={e.phantom} accent />
            <ConfusionRow label="Fixed thresholds (comparator)" c={e.threshold} />
          </tbody>
        </table>
      </div>
      <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-3">
        {thresholdSilent && <Pill tone="unknown">Comparator raised no alert on this run – not a meaningful reference</Pill>}
        Coverage {pct(e.phantom?.coverage)} · abstained {e.phantom?.abstained ?? '—'} · seed {e.seed} · {e.model_version}.
      </p>
      <p className="mt-1 text-xs text-ink-3">{e.threshold.definition} {e.threshold.limitation}</p>
    </div>
  );
}

/** MILP crew schedule as a Gantt chart (one row per crew member). */
export function EngineSchedule({ run, strategyIndex = 1, strategy, label }: { run: EngineRun; strategyIndex?: number; strategy?: EngineStrategy; label?: string }) {
  const strat = strategy ?? run.schedules.strategies[strategyIndex] ?? run.schedules.strategies[0];
  const titles = useMemo(() => Object.fromEntries(run.schedules.tasks.map((t) => [t.id, t])), [run]);
  if (!strat) return <Notice tone="unknown">No schedule in this run.</Notice>;
  const all = strat.assignments;
  const t0 = Math.min(...all.map((a) => a.start), 480), t1 = Math.max(...all.map((a) => a.end), 1200);
  const span = Math.max(60, t1 - t0);
  const hours: number[] = [];
  for (let h = Math.ceil(t0 / 60); h <= Math.floor(t1 / 60); h += 2) hours.push(h);
  return (
    <div>
      <div className="relative ml-28 h-5 text-[10px] text-ink-3" aria-hidden="true">
        {hours.map((h) => <span key={h} className="absolute -translate-x-1/2" style={{ left: `${((h * 60 - t0) / span) * 100}%` }}>{String(h % 24).padStart(2, '0')}:00</span>)}
      </div>
      <ul className="space-y-1.5" aria-label={label ?? `Schedule (${strat.strategy})`}>
        {run.crew.map((c) => (
          <li key={c.id} className="flex items-center gap-2">
            <span className="w-26 shrink-0 truncate text-xs text-ink-2" style={{ width: '6.5rem' }}><span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: ENGINE_CREW_COLORS[(c.id - 1) % 4] }} />{c.name} · {c.role}</span>
            <div className="relative h-8 flex-1 rounded-md border border-line bg-raised/40">
              {all.filter((a) => a.crew_ids.includes(c.id)).map((a) => (
                <span key={a.task_id} title={`${titles[a.task_id]?.title ?? a.task_id} · ${clock(a.start)}–${clock(a.end)} · priority ${titles[a.task_id]?.priority ?? '?'}${a.crew_ids.length > 1 ? ' · team task' : ''}`}
                  className="absolute top-1 bottom-1 flex items-center overflow-hidden rounded px-1.5 text-[10px] font-medium text-white"
                  style={{ left: `${((a.start - t0) / span) * 100}%`, width: `${((a.end - a.start) / span) * 100}%`, background: a.crew_ids.length > 1 ? 'var(--color-violet)' : ENGINE_CREW_COLORS[(c.id - 1) % 4] }}>
                  <span className="truncate">{titles[a.task_id]?.title ?? a.task_id}</span>
                </span>
              ))}
            </div>
          </li>
        ))}
      </ul>
      <dl className="tabular mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <div className="rounded-lg border border-line p-2"><dt className="text-ink-3">Solver</dt><dd className={solverLabel(strat).tone === 'high' ? 'text-high' : 'text-ink'} data-solver-status={strat.solver_status ?? strat.status}>{solverLabel(strat).text}</dd></div>
        <div className="rounded-lg border border-line p-2"><dt className="text-ink-3">Tasks scheduled</dt><dd className="text-ink">{strat.metrics.scheduled_tasks}/{run.schedules.tasks.length}{strat.unscheduled.length ? ` · ${strat.unscheduled.length} unscheduled` : ''}</dd></div>
        <div className="rounded-lg border border-line p-2"><dt className="text-ink-3">Max load</dt><dd className="text-ink">{strat.metrics.max_load.toFixed(2)} h-eq</dd></div>
        <div className="rounded-lg border border-line p-2"><dt className="text-ink-3">Constraint check</dt><dd className={strat.valid === false || strat.metrics.conflicts || strat.metrics.violations.length ? 'text-high' : 'text-good'}>{strat.valid === false ? 'not valid' : strat.metrics.conflicts || strat.metrics.violations.length ? `${strat.metrics.violations.length} violations` : 'valid · rest met'}</dd></div>
      </dl>
      {strat.reason && strat.valid === false && <Notice tone="high" className="mt-2">{strat.reason}</Notice>}
      {strat.unscheduled.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs text-ink-2" aria-label="Tasks that are not scheduled">
          {strat.unscheduled.map((u) => <li key={u.task_id}><Pill tone={u.required === false ? 'unknown' : 'high'}>{u.required === false ? 'optional' : 'required'}</Pill> <span className="text-ink">{u.title ?? titles[u.task_id]?.title ?? u.task_id}</span> – {u.reason}</li>)}
        </ul>
      )}
      {strat.criteria && <p className="mt-2 text-xs text-ink-3"><Icon name="info" size={12} className="mr-1 inline" />Objective: {strat.criteria}. {run.schedules.explanation}</p>}
    </div>
  );
}

export const DETECTOR_LABELS: Record<DetectorName, string> = {
  zscore: 'PHANTOM 1.0 · robust z (fixed baseline)', ewma: 'EWMA chart (prewhitened)', adaptive: 'Adaptive-baseline z',
  cusum: 'CUSUM (prewhitened)', mahalanobis: 'Robust Mahalanobis (multivariate)',
  phantom2: 'PHANTOM 2.0 · noise-adaptive (1.0)', phantom2_v09: 'PHANTOM 2.0 · legacy 0.9 rule (Mahalanobis OR CUSUM)',
};

/** Plain-language solver outcome (API 1.0). `feasible` is valid but NOT proven optimal. */
export function solverLabel(s: EngineStrategy): { text: string; tone: 'good' | 'attention' | 'high' } {
  const st = s.solver_status;
  if (s.valid === false) return { text: `No valid schedule · ${(st ?? s.status).replace(/_/g, ' ')}`, tone: 'high' };
  if (st === 'optimal' || (!st && s.status === 'optimal_on_grid')) return { text: 'Valid · optimal on the planning grid', tone: 'good' };
  if (st === 'feasible' || s.status === 'feasible_time_limit') return { text: 'Valid · feasible, optimality not proven (time limit)', tone: 'attention' };
  return { text: (st ?? s.status).replace(/_/g, ' '), tone: 'attention' };
}

/** Noise regime chosen by PHANTOM 2.0 for each crew member (engine runs, API 1.0). */
export function PhantomRegimeNote({ run }: { run: EngineRun }) {
  const reg = run.phantom2.regimes;
  const st = run.phantom2.states;
  if (!reg && !st) return null;
  return (
    <div className="mt-2 space-y-1 text-xs text-ink-3" aria-label="PHANTOM 2.0 decision rule per crew member">
      {reg && <p>{run.crew.map((c) => {
        const r = reg[String(c.id)];
        return r ? `${c.name}: ${r.regime === 'clean' ? 'clean baseline → Mahalanobis OR CUSUM' : 'noisy baseline → calibrated EWMA'} (noise index ν = ${r.nu ?? 'n/a'}, switch at ${r.nu_star})` : null;
      }).filter(Boolean).join(' · ')}</p>}
      {st && <p className="flex flex-wrap gap-2"><Pill tone="attention">flag {st.flag}</Pill><Pill tone="good">no flag {st.no_flag}</Pill>
        <Pill tone="unknown" icon="info">insufficient data {st.insufficient_data}</Pill><span>“Insufficient data” is not a normal result – too few signals were measured to decide.</span></p>}
    </div>
  );
}

/** Same samples, same labels, every detector – the honest comparison table. */
export function EngineDetectorTable({ cmp, caption }: { cmp: DetectorComparison; caption: string }) {
  const rows = (Object.keys(DETECTOR_LABELS) as DetectorName[]).flatMap((d) => { const c = cmp.detectors[d]; return c ? [[d, c] as const] : []; });
  return (
    <div className="overflow-x-auto">
      <table className="tabular w-full min-w-[560px] text-sm">
        <caption className="mb-1 text-left text-xs text-ink-3">{caption} · {cmp.samples_scored} crew samples · baseline: {cmp.baseline}</caption>
        <thead><tr className="text-left text-xs text-ink-3"><th className="py-1 font-medium">Detector</th><th className="font-medium">TP</th><th className="font-medium">FP</th><th className="font-medium">FN</th><th className="font-medium">Precision</th><th className="font-medium">Recall</th><th className="font-medium">F1</th><th className="font-medium">False-alarm rate</th></tr></thead>
        <tbody>{rows.map(([d, c]) => (
          <tr key={d} className={cx('border-t border-line', d === 'phantom2' && 'text-ink font-medium', d === 'zscore' && 'text-ink-2')}>
            <td className="py-1.5">{DETECTOR_LABELS[d]}</td><td>{c.tp}</td><td>{c.fp}</td><td>{c.fn}</td><td>{pct(c.precision)}</td><td>{pct(c.recall)}</td>
            <td>{c.f1 == null ? '—' : c.f1.toFixed(2)}</td><td>{c.fpr == null ? '—' : `${(c.fpr * 100).toFixed(1)} %`}</td>
          </tr>))}</tbody>
      </table>
    </div>
  );
}
