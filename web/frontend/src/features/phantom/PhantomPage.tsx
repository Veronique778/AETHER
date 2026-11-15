import { RecordingView, useBiosignal, usePersonalView } from '../biosignals/BiosignalPage';
import { useMemo, useState } from 'react';
import type { Analysis, Correlations, Measurement, MetricKey, PhantomHistory, Signal } from '../../api/types';
import { ChartFrame, divergingColor, Matrix, TimeSeriesChart, useSize } from '../../charts';
import { dayLabel, downloadText, fmt, METRIC_COLOR, METRICS } from '../../lib/format';
import { useResource } from '../../lib/useResource';
import { useApp, useAstronaut } from '../../state/AppState';
import { Async, Button, Card, cx, Disclosure, Empty, Icon, InfoTip, Notice, PhantomPill, Pill, Segmented, SourceBadge, TabPanel, Tabs, useTab, type TabDef } from '../../ui';
import { CrewSwitcher } from '../shared/CrewSwitcher';
import { ModuleHeader } from '../shared/ModuleHeader';
import { TrendPrediction } from '../shared/TrendPrediction';
import { useScenarioRun } from '../../state/scenario';
import { EngineCrewChart, EngineDetectorTable, EngineEvaluation, EngineRunCard, PhantomRegimeNote } from '../shared/EngineCards';
import { Phantom2Card, RadiationContextCard } from './Phantom2Card';
import { NasaReferenceCard } from '../research/NasaReferenceCard';
import { PersonalPhantomPage } from '../personal/PersonalMonitoring';

type PhTab = 'console' | 'explore' | 'relationships' | 'history';
const TABS: TabDef<PhTab>[] = [
  { id: 'console', label: 'Analytical console', icon: 'gauge' },
  { id: 'explore', label: 'Signal & event explorer', icon: 'activity' },
  { id: 'relationships', label: 'Relationships', icon: 'layers' },
  { id: 'history', label: 'Episodes & reports', icon: 'printer' },
];

/**
 * PHANTOM – analytical instrument. All numbers are API results (research prototype); the UI only
 * re-arranges them. Display normalisation (value − baseline) / spread uses the API's own baseline.
 */
export function PhantomPage() {
  const { source, sessionId } = useBiosignal();
  const { mode } = useApp();
  const personal = usePersonalView();
  if (personal) return <PersonalPhantomPage />;
  return <>
    {source === 'synthetic' ? <SimulationPhantomPage /> : <RecordingView key={sessionId} body={false} />}
    {mode === 'live' && <NasaReferenceCard />}
  </>;
}

function SimulationPhantomPage() {
  const { api, astronautId, day, dataVersion } = useApp();
  const astronaut = useAstronaut();
  const key = `${api.mode}-${astronautId}-${day}-${dataVersion}`;
  const analysis = useResource(`ph-${key}`, () => api.phantom(astronautId, day));
  const history = useResource(`phh-${key}`, () => api.phantomHistory(astronautId, day, 41));
  const timeline = useResource(`tl-${key}`, () => api.timeline(astronautId, day));
  const [corrWindow, setCorrWindow] = useState<'14' | '30' | '60'>('30');
  const corr = useResource(`corr-${key}-${corrWindow}`, () => api.correlations(astronautId, day, Number(corrWindow)));
  const [tab, setTab] = useTab(TABS);
  const [eventDay, setEventDay] = useState<number | null>(null);
  const [selected, setSelected] = useState<MetricKey | null>(null);
  const explore = (d: number, k?: MetricKey) => { setEventDay(d); if (k) setSelected(k); setTab('explore'); };

  return (
    <div>
      <Notice tone="attention" className="mb-4" title="Synthetic Mission Demo · PHANTOM research prototype">
        This result belongs to synthetic mission simulation data. It is not a personalized PHANTOM analysis and is not a diagnosis.
      </Notice>
      <ModuleHeader module="/phantom" title={`Analysis · ${astronaut?.name ?? ''}`}
        description="Deviation from this astronaut’s own baseline, as returned by the PHANTOM research service. Click any deviation to open its event explorer."
        actions={<CrewSwitcher />} />
      <Notice tone="analysis" className="mb-4" title="Research algorithm – not a diagnosis">PHANTOM is an experimental, explainable heuristic (owned by the Human Systems developer). Its index is not a probability and it cannot detect illness. Real decisions belong to qualified medical staff.</Notice>
      {analysis.data && <ScenarioAnalysis actual={analysis.data} />}
      <Phantom2Card />
      <RadiationContextCard />
      <div className="mb-4"><EngineRunCard eyebrow="Research evaluation · Mission Systems engine" title="PHANTOM on labelled synthetic events">{(r) => <div className="grid gap-5 xl:grid-cols-2"><div className="space-y-3"><EngineEvaluation run={r} />{r.phantom2 && <EngineDetectorTable cmp={r.phantom2.physiology} caption="All detectors on this run" />}<PhantomRegimeNote run={r} /></div><div><div className="mb-1 text-xs text-ink-3">Fatigue per engine crew member · dots = PHANTOM flags</div><EngineCrewChart run={r} metric="fatigue" height={180} /></div></div>}</EngineRunCard></div>
      <Tabs label="PHANTOM sections" tabs={TABS} value={tab} onChange={setTab} />
      <TabPanel label={TABS.find((t) => t.id === tab)!.label}>
        {tab === 'console' && (
          <Async res={analysis} loadingLabel="Loading analysis">
            {(a) => <AnalyticalConsole a={a} rows={timeline.data} selected={selected ?? a.signals.find((s) => s.flagged)?.key ?? a.signals[0].key} onSelect={setSelected} onExplore={explore} />}
          </Async>
        )}
        {tab === 'explore' && (
          <Async res={analysis} loadingLabel="Loading analysis">{(a) => (
            <Async res={timeline}>{(rows) => (
              <Async res={history}>{(h) => <SignalExplorer a={a} rows={rows} h={h} eventDay={eventDay} setEventDay={setEventDay} focus={selected} />}</Async>
            )}</Async>
          )}</Async>
        )}
        {tab === 'relationships' && (
          <Card eyebrow="Relationships" title="How signals moved together"
            actions={<Segmented size="sm" label="Correlation window" value={corrWindow} onChange={setCorrWindow} options={[{ value: '14', label: '14 d' }, { value: '30', label: '30 d' }, { value: '60', label: '60 d' }]} />}>
            <Async res={corr}>{(c) => <Async res={timeline}>{(rows) => <RelationshipPanel c={c} rows={rows} a={analysis.data} />}</Async>}</Async>
          </Card>
        )}
        {tab === 'history' && (
          <div className="grid gap-5 xl:grid-cols-2">
            <Card eyebrow="Predicted vs observed" title="Index: last 14 days and next 14 days" className="xl:col-span-2"><TrendPrediction horizon={14} height={230} /></Card>
            <Async res={history}>{(h) => <IndexHistory h={h} />}</Async>
            <Async res={history}>{(h) => <AlertHistory h={h} onExplore={(d) => explore(d)} />}</Async>
            <div className="xl:col-span-2">
              <Async res={analysis}>{(a) => <Async res={history}>{(h) => <ReportPanel name={astronaut?.name ?? astronautId} id={astronautId} a={a} h={h} c={corr.data} />}</Async>}</Async>
            </div>
          </div>
        )}
      </TabPanel>
    </div>
  );
}

/* ───────────────────────── Scenario comparison ───────────────────────── */

/** PHANTOM's analysis of the modelled scenario day next to its analysis of the recorded day. */
function ScenarioAnalysis({ actual }: { actual: Analysis }) {
  const { scenario } = useApp();
  const run = useScenarioRun();
  if (!scenario) return null;
  return (
    <section aria-label="Scenario comparison" className="card mb-4 border-violet/40 p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div><div className="mono-label text-violet">Scenario comparison · {scenario.title}</div><h2 className="text-base font-semibold text-ink">PHANTOM on recorded data vs on the modelled scenario day</h2></div>
        <SourceBadge source="simulated" />
      </div>
      <Async res={run} loadingLabel="Running scenario">{(r) => (
        <div className="grid gap-3 md:grid-cols-[220px_minmax(0,1fr)]">
          <div className="grid grid-cols-2 gap-2 text-center">
            <div className="rounded-xl border border-line bg-raised/40 p-2"><div className="mono-label">Recorded</div><div className="tabular text-2xl font-semibold text-ink">{actual.score ?? '—'}</div><PhantomPill status={actual.status} /></div>
            <div className="rounded-xl border border-violet/50 bg-violet/10 p-2"><div className="mono-label text-violet">Scenario</div><div className="tabular text-2xl font-semibold text-violet">{r.phantom.score ?? '—'}</div><PhantomPill status={r.phantom.status} /></div>
          </div>
          <ul className="space-y-1.5">
            {r.phantom.signals.map((s) => {
              const a = actual.signals.find((x) => x.key === s.key);
              return (
                <li key={s.key} className="grid grid-cols-[110px_minmax(0,1fr)_120px] items-center gap-2 text-xs">
                  <span className="text-ink-2">{METRICS[s.key].short}</span>
                  <span className="relative h-3 rounded bg-line" aria-hidden="true">
                    <span className="absolute inset-y-0 left-1/2 w-px bg-line-strong" />
                    {a && <span className="absolute top-1/2 h-3 w-1 -translate-y-1/2 rounded bg-ink" style={{ left: `${50 + Math.max(-48, Math.min(48, a.deviation * 6))}%` }} />}
                    <span className="absolute top-1/2 h-3 w-1 -translate-y-1/2 rounded bg-violet" style={{ left: `${50 + Math.max(-48, Math.min(48, s.deviation * 6))}%` }} />
                  </span>
                  <span className={cx('tabular text-right', s.flagged ? 'text-attention' : 'text-ink-2')}>{a ? `${a.deviation.toFixed(1)}σ → ` : ''}{s.deviation.toFixed(1)}σ{s.flagged ? ' · flag' : ''}</span>
                </li>
              );
            })}
            <li className="pt-1 text-[11px] text-ink-3"><span className="mr-2 inline-block h-2 w-1 rounded bg-ink align-middle" />recorded <span className="mx-2 inline-block h-2 w-1 rounded bg-violet align-middle" />scenario (model). {r.assumptions}</li>
          </ul>
        </div>
      )}</Async>
    </section>
  );
}

/* ───────────────────────── Analytical console ───────────────────────── */

const zOf = (s: Signal, v: number | null) => (v == null ? null : (v - s.baseline) / (s.scale || 1));

function AnalyticalConsole({ a, rows, selected, onSelect, onExplore }: { a: Analysis; rows?: Measurement[]; selected: MetricKey; onSelect: (k: MetricKey) => void; onExplore: (d: number, k?: MetricKey) => void }) {
  const { day, openWith } = useApp();
  const sig = a.signals.find((s) => s.key === selected) ?? a.signals[0];
  const recent = (rows ?? []).slice(-30);
  return (
    <div className="always-dark stage rounded-2xl border border-line p-3">
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)_minmax(0,1fr)]">
        <section aria-label="Overall result" className="hud min-w-0 flex flex-col rounded-xl p-4">
          <div className="flex items-center justify-between"><span className="mono-label text-violet">{dayLabel(day)} · result</span><SourceBadge source="research_prototype" /></div>
          <IndexGauge score={a.score} />
          <div className="mt-1 flex flex-wrap items-center justify-center gap-2"><PhantomPill status={a.status} /><span className="text-xs text-ink-3">{a.flagged_count}/{a.signals.length} signals flagged{a.multi_signal_pattern ? ' · changing together' : ''}</span></div>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <div className="rounded-lg border border-line bg-raised/40 p-2.5">
              <div className="mono-label flex items-center gap-1 text-ink-3">Uncertainty<InfoTip text="How much to trust this result: depends on data quality, missing values and the number of baseline days." label="About uncertainty" /></div>
              <UncertaintyMeter u={a.uncertainty} />
            </div>
            <div className="rounded-lg border border-line bg-raised/40 p-2.5">
              <div className="mono-label text-ink-3">Data</div>
              <div className="mt-1 text-sm text-ink">{a.data_quality}</div>
              <div className="text-xs text-ink-3">{a.baseline_days ?? '—'} baseline days · {a.current_source ?? 'no data today'}</div>
            </div>
          </div>
          <div className="mt-4 rounded-lg border border-violet/30 bg-violet/5 p-3">
            <div className="mono-label mb-1 text-violet">Explanation</div>
            <p className="text-sm text-ink-2">{a.explanation}</p>
          </div>
        </section>

        <section aria-label="Deviation radar" className="hud min-w-0 flex flex-col rounded-xl p-4">
          <div className="flex items-center justify-between"><span className="mono-label text-ink-3">Deviation from personal baseline</span><span className="text-xs text-ink-3">select an axis</span></div>
          <DeviationRadar signals={a.signals} threshold={a.method.flag_threshold_z} selected={sig.key} onSelect={onSelect} />
          <div className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs text-ink-3">
            <span className="flex items-center gap-1"><span className="h-0.5 w-4 border-t-2 border-dashed border-attention" />flag threshold ±{a.method.flag_threshold_z}σ</span>
            <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-violet/40" />today’s |robust z|</span>
          </div>
        </section>

        <section aria-label={`Selected signal: ${METRICS[sig.key].label}`} className="hud min-w-0 flex flex-col rounded-xl p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="mono-label" style={{ color: METRIC_COLOR[sig.key] }}>{METRICS[sig.key].label}</span>
            {sig.flagged ? <Pill tone="attention">flagged</Pill> : <Pill tone="good">within threshold</Pill>}
          </div>
          <div className="mt-2 grid grid-cols-3 gap-2 text-center">
            <div className="rounded-lg border border-line bg-raised/40 p-2"><div className="mono-label text-ink-3">Today</div><div className="tabular text-lg font-semibold text-ink">{fmt(sig.value, METRICS[sig.key].decimals)}</div><div className="text-[11px] text-ink-3">{sig.unit}</div></div>
            <div className="rounded-lg border border-line bg-raised/40 p-2"><div className="mono-label text-ink-3">Baseline</div><div className="tabular text-lg font-semibold text-ink-2">{fmt(sig.baseline, METRICS[sig.key].decimals)}</div><div className="text-[11px] text-ink-3">± {fmt(sig.scale, 1)}</div></div>
            <div className="rounded-lg border border-line bg-raised/40 p-2"><div className="mono-label text-ink-3">Robust z</div><div className={cx('tabular text-lg font-semibold', sig.flagged ? 'text-attention' : 'text-ink')}>{sig.deviation > 0 ? '+' : ''}{sig.deviation.toFixed(1)}</div><div className="text-[11px] text-ink-3">from API</div></div>
          </div>
          <div className="mt-3">
            {recent.length ? (
              <TimeSeriesChart height={150} ariaLabel={`${METRICS[sig.key].label}, last 30 days, with personal baseline band`}
                series={[{ id: sig.key, label: METRICS[sig.key].short, color: METRIC_COLOR[sig.key], points: recent.map((r) => ({ x: r.day, y: r[sig.key] })) }]}
                refBand={{ lo: sig.baseline - 2 * sig.scale, hi: sig.baseline + 2 * sig.scale, label: 'baseline ± 2 spread' }} refLines={[{ y: sig.baseline, label: 'baseline' }]}
                xFormat={(x) => `D${x}`} yFormat={(y) => fmt(y, METRICS[sig.key].decimals)} unit={sig.unit} />
            ) : <div className="skeleton h-36 rounded-lg" />}
          </div>
          <div className="mt-3">
            <div className="mono-label mb-1 text-ink-3">Recommended next measurements</div>
            {a.next_measurements.length ? <ul className="space-y-1 text-sm">{a.next_measurements.map((m) => <li key={m} className="flex gap-2 text-ink-2"><Icon name="target" size={15} className="mt-0.5 shrink-0 text-violet" />{m}</li>)}</ul>
              : <p className="text-sm text-ink-3">None suggested for this day.</p>}
          </div>
          <div className="mt-auto flex flex-wrap gap-2 border-t border-line pt-3">
            <Button size="sm" variant="primary" icon="activity" onClick={() => onExplore(day, sig.key)}>Explore in timeline</Button>
            <Button size="sm" icon="body" onClick={() => openWith('/body', {})}>Record in BODY</Button>
            <Button size="sm" icon="timer" onClick={() => openWith('/recovery/mind-pulse', {})}>Reaction test</Button>
          </div>
        </section>
      </div>
      <div className="mt-3 grid gap-3 xl:grid-cols-2">
        <section aria-label="All signals" className="hud min-w-0 rounded-xl p-4">
          <div className="mono-label mb-2 text-ink-3">All signals · robust z (API)</div>
          <DeviationBars signals={a.signals} threshold={a.method.flag_threshold_z} />
        </section>
        <section aria-label="Method" className="hud min-w-0 rounded-xl p-4">
          <div className="mono-label mb-1 text-ink-3">How the result is produced</div>
          <p className="text-sm text-ink-2">{a.method.name}</p>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-ink-2">{a.method.steps.map((st) => <li key={st}>{st}</li>)}</ol>
          <div className="mt-3"><Disclosure summary="Limitations">{<ul className="list-disc space-y-1 pl-5">{a.method.limitations.map((l) => <li key={l}>{l}</li>)}</ul>}</Disclosure></div>
        </section>
      </div>
    </div>
  );
}

function IndexGauge({ score }: { score: number | null }) {
  const R = 86, cx0 = 110, cy0 = 104;
  const ang = (v: number) => Math.PI * (1 - v / 100);
  const pt = (v: number, r = R) => [cx0 + r * Math.cos(ang(v)), cy0 - r * Math.sin(ang(v))];
  const arc = (a: number, b: number) => { const [x0, y0] = pt(a); const [x1, y1] = pt(b); return `M${x0} ${y0} A${R} ${R} 0 0 1 ${x1} ${y1}`; };
  const v = score ?? 0;
  const [nx, ny] = pt(v, R - 20);
  return (
    <svg viewBox="0 0 220 130" className="mx-auto mt-2 w-full max-w-[300px]" role="img" aria-label={score == null ? 'Deviation index not available' : `Deviation index ${score} of 100. 50 marks the priority review level.`}>
      <path d={arc(0, 100)} stroke="var(--color-line)" strokeWidth={14} fill="none" strokeLinecap="round" />
      <path d={arc(50, 100)} stroke="var(--color-attention)" strokeOpacity={0.25} strokeWidth={14} fill="none" />
      {score != null && <path d={arc(0, Math.max(0.5, v))} stroke={v >= 50 ? 'var(--color-attention)' : 'var(--color-violet)'} strokeWidth={14} fill="none" strokeLinecap="round" />}
      {[0, 25, 50, 75, 100].map((t) => { const [x, y] = pt(t, R + 14); return <text key={t} x={x} y={y + 3} textAnchor="middle" fontSize="9" fill="var(--color-ink-3)">{t}</text>; })}
      {score != null && <line x1={cx0} y1={cy0} x2={nx} y2={ny} stroke="var(--color-ink)" strokeWidth={2} strokeLinecap="round" />}
      <circle cx={cx0} cy={cy0} r={5} fill="var(--color-ink)" />
      <text x={cx0} y={cy0 - 26} textAnchor="middle" fontSize="28" fontWeight="600" fill="var(--color-ink)" className="tabular">{score ?? '—'}</text>
      <text x={cx0} y={cy0 + 20} textAnchor="middle" fontSize="9" fill="var(--color-ink-3)">deviation index /100 · not a probability</text>
    </svg>
  );
}

function UncertaintyMeter({ u }: { u: Analysis['uncertainty'] }) {
  const bars = u === 'low' ? 1 : u === 'medium' ? 2 : 3;
  return (
    <div className="mt-1 flex items-center gap-2">
      <span aria-hidden className="flex items-end gap-0.5">{[1, 2, 3].map((i) => <span key={i} className={cx('w-2 rounded-sm', i <= bars ? (u === 'high' ? 'bg-attention' : 'bg-ink-2') : 'bg-line')} style={{ height: 6 + i * 5 }} />)}</span>
      <span className="text-sm font-medium capitalize text-ink">{u}</span>
    </div>
  );
}

/** Radar of |robust z| per signal; axes are keyboard-operable buttons. */
function DeviationRadar({ signals, threshold, selected, onSelect }: { signals: Signal[]; threshold: number; selected: MetricKey; onSelect: (k: MetricKey) => void }) {
  const C = 170, R = 112;
  const MAXZ = Math.min(8, Math.max(4, Math.ceil(Math.max(...signals.map((s) => Math.abs(s.deviation))))));
  const n = signals.length;
  const ang = (i: number) => -Math.PI / 2 + (i * 2 * Math.PI) / n;
  const p = (i: number, z: number) => { const r = (Math.min(MAXZ, Math.abs(z)) / MAXZ) * R; return [C + r * Math.cos(ang(i)), C + r * Math.sin(ang(i))] as const; };
  const lab = (i: number) => [C + (R + 34) * Math.cos(ang(i)), C + (R + 26) * Math.sin(ang(i))] as const;
  const ring = (z: number) => signals.map((_, i) => p(i, z).join(',')).join(' ');
  const poly = signals.map((s, i) => p(i, s.deviation).join(',')).join(' ');
  return (
    <svg viewBox="0 0 340 340" className="mx-auto w-full max-w-[400px]" role="group" aria-label="Deviation radar: distance from centre is the absolute robust z-score per signal">
      {Array.from({ length: MAXZ }, (_, i) => i + 1).map((z) => <polygon key={z} points={ring(z)} fill="none" stroke="var(--color-line)" strokeDasharray={z === MAXZ ? undefined : '2 4'} />)}
      <polygon points={ring(threshold)} fill="none" stroke="var(--color-attention)" strokeDasharray="5 4" strokeWidth={1.5} />
      {signals.map((_, i) => { const [x, y] = p(i, MAXZ); return <line key={i} x1={C} y1={C} x2={x} y2={y} stroke="var(--color-line)" />; })}
      <polygon points={poly} fill="var(--color-violet)" fillOpacity={0.22} stroke="var(--color-violet)" strokeWidth={2} strokeLinejoin="round" />
      {signals.map((s, i) => {
        const [x, y] = p(i, s.deviation);
        const [lx, ly] = lab(i);
        const sel = s.key === selected;
        return (
          <g key={s.key} role="button" tabIndex={0} aria-pressed={sel} aria-label={`${s.label}: robust z ${s.deviation.toFixed(1)}${s.flagged ? ', flagged' : ''}`}
            onClick={() => onSelect(s.key)} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(s.key); } }}
            className="cursor-pointer outline-none [&:focus-visible>rect]:stroke-[var(--color-cyan)]">
            <rect x={lx - 42} y={ly - 13} width={84} height={26} rx={13} fill={sel ? 'var(--color-raised)' : 'transparent'} stroke={sel ? METRIC_COLOR[s.key] : 'transparent'} strokeWidth={1.5} />
            <text x={lx} y={ly + 4} textAnchor="middle" fontSize="11.5" fontWeight={sel ? 700 : 500} fill={s.flagged ? 'var(--color-attention)' : 'var(--color-ink-2)'}>{METRICS[s.key].short}</text>
            <circle cx={x} cy={y} r={sel ? 7 : 5} fill={s.flagged ? 'var(--color-attention)' : METRIC_COLOR[s.key]} stroke="var(--color-surface)" strokeWidth={2} />
            <circle cx={x} cy={y} r={16} fill="transparent" />
          </g>
        );
      })}
      <text x={C + 4} y={C - (R / MAXZ) * 2 + 3} fontSize="9" fill="var(--color-ink-3)">2σ</text>
      <text x={C + 4} y={C - R + 3} fontSize="9" fill="var(--color-ink-3)">{MAXZ}σ{MAXZ === 8 ? '+' : ''}</text>
    </svg>
  );
}

/* ───────────────────────── Signal & event explorer ───────────────────────── */

function SignalExplorer({ a, rows, h, eventDay, setEventDay, focus }: { a: Analysis; rows: Measurement[]; h: PhantomHistory; eventDay: number | null; setEventDay: (d: number | null) => void; focus: MetricKey | null }) {
  const [on, setOn] = useState<Record<MetricKey, boolean>>(() => Object.fromEntries(a.signals.map((s) => [s.key, focus ? s.key === focus || s.flagged : true])) as Record<MetricKey, boolean>);
  const [win, setWin] = useState<'27' | '45' | 'all'>('27');
  const shown = win === 'all' ? rows : rows.slice(-Number(win));
  const thr = a.method.flag_threshold_z;
  const series = a.signals.filter((s) => on[s.key]).map((s) => ({
    id: s.key, label: METRICS[s.key].short, color: METRIC_COLOR[s.key],
    points: shown.map((r) => ({ x: r.day, y: zOf(s, r[s.key]) == null ? null : Math.round(zOf(s, r[s.key])! * 100) / 100 })),
  }));
  const xs = shown.map((r) => r.day);
  const x0 = xs[0] ?? 0, x1 = xs[xs.length - 1] ?? 1;
  const pct = (d: number) => ((d - x0) / (x1 - x0 || 1)) * 100;
  const flagged = h.points.filter((p) => p.flagged.length && p.day >= x0 && p.day <= x1);
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_400px]">
      <Card eyebrow="Multi-signal comparison" title="All signals on one scale" actions={<SourceBadge source="research_prototype" />}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <fieldset className="flex flex-wrap gap-1.5">
            <legend className="sr-only">Signals to compare</legend>
            {a.signals.map((s) => (
              <label key={s.key} className={cx('interactive flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs', on[s.key] ? 'border-line-strong bg-raised text-ink' : 'border-line text-ink-3')}>
                <input type="checkbox" className="sr-only" checked={on[s.key]} onChange={(e) => setOn({ ...on, [s.key]: e.target.checked })} />
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: on[s.key] ? METRIC_COLOR[s.key] : 'transparent', boxShadow: `inset 0 0 0 2px ${METRIC_COLOR[s.key]}` }} />
                {METRICS[s.key].short}{s.flagged && <Icon name="info" size={12} className="text-attention" />}
              </label>
            ))}
          </fieldset>
          <Segmented size="sm" label="Time window" value={win} onChange={setWin} options={[{ value: '27', label: '27 d' }, { value: '45', label: '45 d' }, { value: 'all', label: 'All' }]} />
        </div>
        {series.length ? (
          <ChartFrame caption="Signals normalised to the personal baseline" table={{ columns: ['Day', ...series.map((s) => s.label)], rows: shown.map((r, i) => [r.day, ...series.map((s) => s.points[i].y ?? '—')]) }}>
            <TimeSeriesChart height={280} ariaLabel="All selected signals expressed as distance from the personal baseline in spreads"
              series={series} refBand={{ lo: -thr, hi: thr, label: 'within flag threshold' }} refLines={[{ y: 0, label: 'personal baseline' }]}
              markers={eventDay != null && eventDay >= x0 ? [{ x: eventDay, label: `event · day ${eventDay}` }] : []}
              cursorX={eventDay} xFormat={(x) => `Day ${x}`} yFormat={(y) => `${y > 0 ? '+' : ''}${fmt(y, 1)}σ`} />
          </ChartFrame>
        ) : <Empty title="No signal selected">Turn on at least one signal above.</Empty>}
        <div className="mt-3" role="group" aria-label="Deviation markers: days with flagged signals. Select one to explore the event.">
          <div className="mono-label mb-1 text-ink-3">Deviation markers · select to explore</div>
          {a.signals.map((s) => {
            const days = flagged.filter((p) => p.flagged.includes(s.key));
            return (
              <div key={s.key} className="flex items-center gap-2">
                <span className="w-[38px] shrink-0 truncate text-right text-[10px] text-ink-3">{METRICS[s.key].short.slice(0, 5)}</span>
                <div className="relative h-6 flex-1" style={{ marginRight: 14 }}>
                  <div className="absolute inset-x-0 top-1/2 h-px bg-line" aria-hidden="true" />
                  {days.map((p) => (
                    <button key={p.day} type="button" onClick={() => setEventDay(p.day)} aria-pressed={eventDay === p.day}
                      aria-label={`${METRICS[s.key].short} flagged on day ${p.day}. Explore`} title={`Day ${p.day} · ${METRICS[s.key].short}`}
                      className={cx('interactive absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rotate-45 rounded-[3px] border-2', eventDay === p.day ? 'scale-125 border-white' : 'border-surface')}
                      style={{ left: `${pct(p.day)}%`, background: METRIC_COLOR[s.key] }} />
                  ))}
                </div>
              </div>
            );
          })}
          {!flagged.length && <p className="text-sm text-ink-3">No flagged days in this window.</p>}
        </div>
        <p className="mt-3 text-xs text-ink-3">Display normalisation: (value − baseline) ÷ spread, using the baseline the API returns for {dayLabel(a.day)}. PHANTOM’s own robust z per day is shown in the event panel.</p>
      </Card>
      <EventPanel day={eventDay} rows={rows} onClose={() => setEventDay(null)} />
      <div className="xl:col-span-2"><BaselineTable a={a} /></div>
    </div>
  );
}

function EventPanel({ day, rows, onClose }: { day: number | null; rows: Measurement[]; onClose: () => void }) {
  const { api, astronautId, dataVersion, setDay, openWith } = useApp();
  const ev = useResource(day != null ? `phev-${api.mode}-${astronautId}-${day}-${dataVersion}` : null, () => api.phantom(astronautId, day!));
  if (day == null) {
    return (
      <Card eyebrow="Event explorer" title="Select a deviation">
        <Empty title="No event selected" icon="target">Choose a diamond marker under the chart, an episode in “Episodes & reports”, or “Explore in timeline” in the console. The panel shows PHANTOM’s result for that day, related charts and next actions.</Empty>
      </Card>
    );
  }
  return (
    <Card eyebrow={`Event explorer · ${dayLabel(day)}`} title="What happened that day" actions={<Button size="sm" variant="ghost" icon="x" onClick={onClose}>Close</Button>}>
      <Async res={ev} loadingLabel="Loading event">{(e) => {
        const related = e.signals.filter((s) => s.flagged);
        const around = rows.filter((r) => r.day >= day - 10 && r.day <= day + 5);
        return (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2"><PhantomPill status={e.status} /><span className="tabular text-sm text-ink-2">index {e.score ?? '—'}/100</span><span className="text-xs text-ink-3">· uncertainty {e.uncertainty}</span></div>
            <p className="text-sm text-ink-2">{e.explanation}</p>
            <ul className="space-y-1">
              {e.signals.map((s) => (
                <li key={s.key} className="flex items-center gap-2 text-xs">
                  <span className="h-2 w-2 rounded-full" style={{ background: METRIC_COLOR[s.key] }} />
                  <span className="w-24 text-ink-2">{METRICS[s.key].short}</span>
                  <span className="tabular text-ink">{fmt(s.value, METRICS[s.key].decimals)} {s.unit}</span>
                  <span className={cx('tabular ml-auto', s.flagged ? 'font-semibold text-attention' : 'text-ink-3')}>{s.deviation > 0 ? '+' : ''}{s.deviation.toFixed(1)}σ</span>
                </li>
              ))}
            </ul>
            {related.length > 0 && (
              <div className="space-y-3">
                <div className="mono-label text-ink-3">Related charts · days {day - 10}–{Math.min(day + 5, rows[rows.length - 1]?.day ?? day)}</div>
                {related.map((s) => (
                  <div key={s.key}>
                    <div className="mb-0.5 text-xs text-ink-2">{METRICS[s.key].label}</div>
                    <TimeSeriesChart height={110} ariaLabel={`${METRICS[s.key].label} around day ${day}`}
                      series={[{ id: s.key, label: METRICS[s.key].short, color: METRIC_COLOR[s.key], points: around.map((r) => ({ x: r.day, y: r[s.key] })) }]}
                      refBand={{ lo: s.baseline - 2 * s.scale, hi: s.baseline + 2 * s.scale, label: 'baseline ± 2' }} markers={[{ x: day, label: '' }]}
                      xFormat={(x) => `D${x}`} yFormat={(y) => fmt(y, METRICS[s.key].decimals)} unit={s.unit} />
                  </div>
                ))}
              </div>
            )}
            <div>
              <div className="mono-label mb-1 text-ink-3">Suggested measurements (API)</div>
              {e.next_measurements.length ? <ul className="list-disc space-y-0.5 pl-5 text-sm text-ink-2">{e.next_measurements.map((m) => <li key={m}>{m}</li>)}</ul> : <p className="text-sm text-ink-3">None for this day.</p>}
            </div>
            <div className="flex flex-wrap gap-2 border-t border-line pt-3">
              <Button size="sm" variant="primary" icon="calendar" onClick={() => setDay(day)}>Set mission day {day}</Button>
              <Button size="sm" icon="body" onClick={() => openWith('/body', { day })}>BODY at day {day}</Button>
              <Button size="sm" icon="waves" onClick={() => openWith('/symbiosis', { day })}>Environment that day</Button>
              <Button size="sm" icon="flask" onClick={() => openWith('/mission-lab', { day })}>Try a scenario</Button>
            </div>
          </div>
        );
      }}</Async>
    </Card>
  );
}

/* ───────────────────────── Relationships ───────────────────────── */

function RelationshipPanel({ c, rows, a }: { c: Correlations; rows: Measurement[]; a?: Analysis }) {
  const [sel, setSel] = useState<[MetricKey, MetricKey]>(['sleep_hours', 'fatigue_1_10']);
  const [node, setNode] = useState<MetricKey | null>(null);
  const [minRho, setMinRho] = useState(0.3);
  const cell = (x: string, y: string) => { const m = c.matrix.find((q) => q.a === x && q.b === y)!; return { v: m.rho, n: m.n }; };
  const win = rows.filter((r) => c.day - c.window_days < r.day && r.day <= c.day);
  const selCell = cell(sel[0], sel[1]);
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
      <div>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
          <div className="mono-label text-ink-3">Relationship graph · {c.method}</div>
          <label className="flex items-center gap-2 text-xs text-ink-2">Show |ρ| ≥ <span className="tabular w-7 text-ink">{minRho.toFixed(1)}</span>
            <input type="range" min={0} max={0.9} step={0.1} value={minRho} onChange={(e) => setMinRho(Number(e.target.value))} aria-label="Minimum absolute correlation to draw" className="w-28 accent-[var(--color-violet)]" />
          </label>
        </div>
        <RelationshipGraph c={c} a={a} node={node} setNode={setNode} pair={sel} onPair={(x, y) => setSel([x, y])} minRho={minRho} />
        <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-ink-3">
          <span className="flex items-center gap-1"><span className="h-1 w-6 rounded" style={{ background: divergingColor(-0.9) }} />negative</span>
          <span className="flex items-center gap-1"><span className="h-1 w-6 rounded" style={{ background: divergingColor(0.9) }} />positive</span>
          <span>line width = |ρ| · amber ring = flagged today</span>
        </div>
      </div>
      <div className="space-y-4">
        <Matrix ariaLabel={`Spearman correlations over ${c.window_days} days`} labels={c.metrics.map((k) => ({ key: k, short: METRICS[k].short }))} value={cell} selected={sel} onSelect={(x, y) => setSel([x as MetricKey, y as MetricKey])} />
        <div>
          <h3 className="mb-1 text-sm font-medium text-ink">{METRICS[sel[0]].short} vs {METRICS[sel[1]].short} · ρ = {selCell.v == null ? '—' : selCell.v.toFixed(2)} <span className="text-xs font-normal text-ink-3">· n = {selCell.n}</span></h3>
          <Scatter points={win.map((r) => ({ x: r[sel[0]], y: r[sel[1]], day: r.day }))} xl={`${METRICS[sel[0]].short} (${METRICS[sel[0]].unit})`} yl={`${METRICS[sel[1]].short} (${METRICS[sel[1]].unit})`} />
        </div>
        <p className="text-xs text-ink-3">{c.note} Association is not causation.</p>
      </div>
    </div>
  );
}

function RelationshipGraph({ c, a, node, setNode, pair, onPair, minRho }: { c: Correlations; a?: Analysis; node: MetricKey | null; setNode: (k: MetricKey | null) => void; pair: [MetricKey, MetricKey]; onPair: (x: MetricKey, y: MetricKey) => void; minRho: number }) {
  const W = 420, H = 360, C = [W / 2, H / 2 + 6], R = 132;
  const pos = useMemo(() => Object.fromEntries(c.metrics.map((k, i) => {
    const t = -Math.PI / 2 + (i * 2 * Math.PI) / c.metrics.length;
    return [k, [C[0] + R * Math.cos(t), C[1] + R * Math.sin(t)]];
  })) as Record<MetricKey, number[]>, [c.metrics]);
  const edges = c.matrix.filter((m) => c.metrics.indexOf(m.a) < c.metrics.indexOf(m.b) && m.rho != null && Math.abs(m.rho) >= minRho);
  const flagged = new Set(a?.signals.filter((s) => s.flagged).map((s) => s.key));
  const isPair = (x: MetricKey, y: MetricKey) => (pair[0] === x && pair[1] === y) || (pair[0] === y && pair[1] === x);
  const key = (fn: () => void) => (e: { key: string; preventDefault: () => void }) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn(); } };
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded-xl border border-line bg-canvas" role="group" aria-label="Relationship graph: nodes are signals, lines are correlations above the chosen strength">
      {edges.map((m) => {
        const [x0, y0] = pos[m.a]; const [x1, y1] = pos[m.b];
        const touches = !node || m.a === node || m.b === node;
        const on = isPair(m.a, m.b);
        return (
          <g key={m.a + m.b} role="button" tabIndex={0} aria-pressed={on} aria-label={`${METRICS[m.a].short} and ${METRICS[m.b].short}: rho ${m.rho!.toFixed(2)}, n ${m.n}`}
            onClick={() => onPair(m.a, m.b)} onKeyDown={key(() => onPair(m.a, m.b))} className="cursor-pointer outline-none [&:focus-visible>line:nth-child(2)]:stroke-[var(--color-cyan)]">
            <line x1={x0} y1={y0} x2={x1} y2={y1} stroke="transparent" strokeWidth={16} />
            <line x1={x0} y1={y0} x2={x1} y2={y1} stroke={divergingColor(m.rho!)} strokeWidth={1.5 + Math.abs(m.rho!) * 7} strokeLinecap="round" opacity={touches ? (on ? 1 : 0.85) : 0.15} />
            {(on || (node && touches)) && <text x={(x0 + x1) / 2} y={(y0 + y1) / 2 - 6} textAnchor="middle" fontSize="12" fontWeight="600" fill="var(--color-ink)" className="tabular" paintOrder="stroke" stroke="var(--color-canvas)" strokeWidth={4}>ρ {m.rho!.toFixed(2)}</text>}
          </g>
        );
      })}
      {c.metrics.map((k) => {
        const [x, y] = pos[k];
        const sel = node === k;
        return (
          <g key={k} role="button" tabIndex={0} aria-pressed={sel} aria-label={`${METRICS[k].label}${flagged.has(k) ? ', flagged today' : ''}. Highlight its relationships`}
            onClick={() => setNode(sel ? null : k)} onKeyDown={key(() => setNode(sel ? null : k))} className="cursor-pointer outline-none [&:focus-visible>circle:first-child]:stroke-[var(--color-cyan)]">
            <circle cx={x} cy={y} r={30} fill="var(--color-surface)" stroke={flagged.has(k) ? 'var(--color-attention)' : 'var(--color-line-strong)'} strokeWidth={flagged.has(k) ? 3 : 1.5} />
            <circle cx={x} cy={y} r={22} fill={METRIC_COLOR[k]} opacity={!node || sel ? 1 : 0.45} />
            {sel && <circle cx={x} cy={y} r={36} fill="none" stroke="var(--color-ink)" strokeWidth={1.5} strokeDasharray="3 3" />}
            <text x={x} y={y + (y > C[1] ? 50 : -40)} textAnchor="middle" fontSize="13" fontWeight="600" fill="var(--color-ink)">{METRICS[k].short}</text>
          </g>
        );
      })}
      {!edges.length && <text x={W / 2} y={H / 2} textAnchor="middle" fontSize="13" fill="var(--color-ink-3)">No relationships at this strength</text>}
    </svg>
  );
}

/* ───────────────────────── Shared pieces ───────────────────────── */

function BaselineTable({ a }: { a: Analysis }) {
  return (
    <Card eyebrow="Individual baselines" title="Personal reference values" actions={<SourceBadge source="research_prototype" />}>
      <table className="tabular w-full text-sm">
        <caption className="sr-only">Personal baseline per signal</caption>
        <thead><tr className="text-left text-xs text-ink-3"><th className="py-1 font-medium">Signal</th><th className="font-medium">Baseline (median)</th><th className="font-medium">Spread</th><th className="font-medium">Today</th><th className="font-medium">Robust z</th></tr></thead>
        <tbody>{a.signals.map((sg) => (
          <tr key={sg.key} className="border-t border-line">
            <td className="py-1.5 text-ink-2">{sg.label}</td><td>{fmt(sg.baseline, 2)} {sg.unit}</td><td className="text-ink-3">± {fmt(sg.scale, 2)}</td><td className="text-ink">{fmt(sg.value, 2)}</td>
            <td className={sg.flagged ? 'text-attention' : 'text-ink-2'}>{sg.deviation > 0 ? '+' : ''}{sg.deviation.toFixed(2)}{sg.flagged && ' · flagged'}</td>
          </tr>
        ))}</tbody>
      </table>
      <p className="mt-2 text-xs text-ink-3">Baseline window: {a.method.baseline_window}. Values are provided by the API.</p>
    </Card>
  );
}

function ReportPanel({ name, id, a, h, c }: { name: string; id: string; a: Analysis; h: PhantomHistory; c?: Correlations }) {
  const { day } = useApp();
  const [withCorr, setWithCorr] = useState(true);
  const [copied, setCopied] = useState(false);
  const text = buildReport(name, a, h, withCorr ? c : undefined);
  return (
    <Card eyebrow="Reports" title="Analytical report" actions={<SourceBadge source="research_prototype" />}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="mr-2 flex items-center gap-2 text-sm text-ink-2"><input type="checkbox" checked={withCorr} onChange={(e) => setWithCorr(e.target.checked)} />Include relationships</label>
        <Button size="sm" icon="download" onClick={() => downloadText(`AETHER_PHANTOM_${id}_day${day}.md`, text)}>Download report (.md)</Button>
        <Button size="sm" icon="printer" onClick={() => globalThis.print()}>Print</Button>
        <Button size="sm" icon="check" onClick={() => { navigator.clipboard?.writeText(text).then(() => setCopied(true), () => setCopied(false)); }}>{copied ? 'Copied' : 'Copy text'}</Button>
      </div>
      <pre aria-label="Report preview" className="max-h-[460px] overflow-auto whitespace-pre-wrap rounded-xl border border-line bg-canvas p-3 font-mono text-xs leading-relaxed text-ink-2">{text}</pre>
      <p className="mt-2 text-xs text-ink-3">Generated in the browser from API results. A server-side PDF report is a pending backend contract.</p>
    </Card>
  );
}

function DeviationBars({ signals, threshold }: { signals: Signal[]; threshold: number }) {
  const max = Math.max(4, ...signals.map((s) => Math.abs(s.deviation)));
  const pos = (z: number) => 50 + (z / max) * 50;
  return (
    <div>
      <div className="mb-1 grid grid-cols-[92px_minmax(0,1fr)_78px] sm:grid-cols-[150px_minmax(0,1fr)_110px] gap-3 text-[11px] text-ink-3"><span /><span className="flex justify-between"><span>−{max.toFixed(0)}</span><span>0 = baseline</span><span>+{max.toFixed(0)}</span></span><span className="text-right">value · baseline</span></div>
      <ul className="space-y-2">
        {signals.map((s) => {
          const adverseSign = s.adverse_deviation > 0 ? Math.sign(s.deviation) : METRICS[s.key].better === 'lower' ? 1 : -1;
          const thr = pos(adverseSign * threshold);
          return (
            <li key={s.key} className="grid grid-cols-[92px_minmax(0,1fr)_78px] sm:grid-cols-[150px_minmax(0,1fr)_110px] items-center gap-3 text-sm">
              <span className="flex items-center gap-1.5 text-ink-2">{s.flagged && <Icon name="info" size={14} className="text-attention" />}{s.label}</span>
              <div className="relative h-6 rounded bg-canvas" role="img" aria-label={`${s.label}: robust deviation ${s.deviation}, ${s.flagged ? 'flagged' : 'not flagged'}`}>
                <div className="absolute inset-y-0 left-1/2 w-px bg-line-strong" />
                <div className="absolute inset-y-1 w-px border-l border-dashed border-attention" style={{ left: `${thr}%` }} title={`flag threshold ${threshold}`} />
                <div className={cx('absolute inset-y-1.5 rounded', s.flagged ? 'bg-attention' : 'bg-teal-300/70')}
                  style={{ left: `${Math.min(50, pos(s.deviation))}%`, width: `${Math.abs(pos(s.deviation) - 50)}%` }} />
              </div>
              <span className="tabular text-right text-ink-2">{fmt(s.value, METRICS[s.key].decimals)} · <span className="text-ink-3">{fmt(s.baseline, METRICS[s.key].decimals)}</span></span>
            </li>
          );
        })}
      </ul>
      <p className="mt-2 text-xs text-ink-3">Bars show the robust z-score. Dashed lines mark the ±{threshold} flag threshold on the less favourable side of each signal.</p>
    </div>
  );
}

function IndexHistory({ h, onCursor }: { h: PhantomHistory; onCursor?: (d: number | null) => void }) {
  const pts = h.points;
  return (
    <Card eyebrow="Time series" title="Deviation index by day" actions={<SourceBadge source="research_prototype" />}>
      <ChartFrame caption="PHANTOM deviation index by day" table={{ columns: ['Day', 'Index', 'Status', 'Flagged'], rows: pts.map((p) => [p.day, p.score ?? '—', p.status, p.flagged.map((k) => METRICS[k].short).join(', ') || '—']) }}>
        <TimeSeriesChart ariaLabel="PHANTOM deviation index per mission day" yDomain={[0, 100]}
          series={[{ id: 'score', label: 'Index', color: 'var(--color-violet)', points: pts.map((p) => ({ x: p.day, y: p.score })) }]}
          refLines={[{ y: 50, label: 'priority review level' }]} onCursor={onCursor}
          markers={h.alerts.map((e) => ({ x: e.start_day, label: `episode ${e.start_day}` }))}
          xFormat={(x) => `Day ${x}`} unit="/100" />
      </ChartFrame>
      <p className="mt-2 text-xs text-ink-3">Days 41+ only – days 1–40 form the baseline itself.</p>
    </Card>
  );
}

function Scatter({ points, xl, yl }: { points: { x: number | null; y: number | null; day: number }[]; xl: string; yl: string }) {
  const [ref, { width }] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const p = points.filter((q): q is { x: number; y: number; day: number } => q.x != null && q.y != null);
  const H = 200, M = 34;
  const [x0, x1] = [Math.min(...p.map((q) => q.x)), Math.max(...p.map((q) => q.x))];
  const [y0, y1] = [Math.min(...p.map((q) => q.y)), Math.max(...p.map((q) => q.y))];
  const sx = (x: number) => M + ((x - x0) / (x1 - x0 || 1)) * (width - M - 10);
  const sy = (y: number) => 20 + (1 - (y - y0) / (y1 - y0 || 1)) * (H - M - 20);
  const lastDay = Math.max(...p.map((q) => q.day));
  const h = p.find((q) => q.day === hover);
  return (
    <div ref={ref} className="relative w-full" style={{ height: H }}>
      {width > 0 && p.length > 0 && (
        <svg width={width} height={H} role="img" aria-label={`Scatter of ${xl} against ${yl}`}>
          <line x1={M} x2={width - 10} y1={H - M} y2={H - M} stroke="var(--color-line-strong)" />
          <line x1={M} x2={M} y1={8} y2={H - M} stroke="var(--color-line-strong)" />
          <text x={(width + M) / 2} y={H - 8} textAnchor="middle" fontSize="11" fill="var(--color-ink-3)">{xl}</text>
          <text x={10} y={(H - M) / 2} fontSize="11" fill="var(--color-ink-3)" transform={`rotate(-90 10 ${(H - M) / 2})`} textAnchor="middle">{yl}</text>
          {p.map((q) => (
            <circle key={q.day} cx={sx(q.x)} cy={sy(q.y)} r={q.day === lastDay ? 6 : 4.5} fill={q.day === lastDay ? 'var(--color-attention)' : 'var(--color-teal-300)'}
              fillOpacity={0.75} stroke="var(--color-surface)" strokeWidth={2} onPointerEnter={() => setHover(q.day)} onPointerLeave={() => setHover(null)} />
          ))}
        </svg>
      )}
      {h && <div className="pointer-events-none absolute right-2 top-1 rounded-md border border-line-strong bg-overlay px-2 py-1 text-xs text-ink-2">Day {h.day}: {fmt(h.x, 1)} · {fmt(h.y, 1)}</div>}
      <span className="absolute left-10 top-0 flex items-center gap-1 text-[11px] text-ink-3"><span className="h-2.5 w-2.5 rounded-full bg-attention" />selected day</span>
    </div>
  );
}

function AlertHistory({ h, onExplore }: { h: PhantomHistory; onExplore: (day: number) => void }) {
  return (
    <Card eyebrow="History" title="Review episodes">
      {h.alerts.length === 0 ? <p className="text-sm text-ink-3">No days above the flag threshold since day 41.</p> : (
        <ol className="space-y-2">
          {h.alerts.map((e) => (
            <li key={e.start_day} className="rounded-xl border border-line p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium text-ink">Days {e.start_day}–{e.end_day} {e.ongoing && <Pill tone="info" className="ml-1">ongoing</Pill>}</span>
                <Pill tone="attention">{e.label}</Pill>
              </div>
              <p className="mt-1 text-sm text-ink-2">Peak index {e.peak_score}. Signals: {e.signals.map((k) => METRICS[k].short.toLowerCase()).join(', ')}.</p>
              <Button size="sm" variant="ghost" iconRight="arrowRight" className="-ml-2 mt-1" onClick={() => onExplore(e.end_day)}>Explore this event</Button>
            </li>
          ))}
        </ol>
      )}
      <p className="mt-3 text-xs text-ink-3">An episode is a run of consecutive days with at least one flagged signal. Wording is intentionally calm: a review is a prompt to look, not an alarm.</p>
    </Card>
  );
}

export function buildReport(name: string, a: Analysis, h: PhantomHistory, c?: Correlations): string {
  const lines = [
    `# AETHER · PHANTOM analytical report`,
    ``,
    `- Astronaut: ${name}`,
    `- Mission day: ${a.day}`,
    `- Generated: ${new Date().toISOString()}`,
    `- Data: synthetic / research prototype. **Not a medical record or diagnosis.**`,
    ``,
    `## Result`,
    ``,
    `- Status: ${a.status}`,
    `- Deviation index: ${a.score ?? 'n/a'} / 100 (heuristic, not a probability)`,
    `- Uncertainty: ${a.uncertainty} · data quality: ${a.data_quality}`,
    ``,
    a.explanation,
    ``,
    `## Signals`,
    ``,
    `| Signal | Value | Baseline | Robust z | Flagged |`,
    `|---|---|---|---|---|`,
    ...a.signals.map((s) => `| ${s.label} | ${s.value} ${s.unit} | ${s.baseline} | ${s.deviation} | ${s.flagged ? 'yes' : 'no'} |`),
    ``,
    `## Review episodes (since day 41)`,
    ``,
    ...(h.alerts.length ? h.alerts.map((e) => `- Days ${e.start_day}–${e.end_day}${e.ongoing ? ' (ongoing)' : ''}: peak ${e.peak_score}; ${e.signals.join(', ')}`) : ['- none']),
    ``,
    `## Suggested additional measurements`,
    ``,
    ...(a.next_measurements.length ? a.next_measurements.map((m) => `- ${m}`) : ['- none']),
    ``,
  ];
  if (c) {
    const strong = c.matrix.filter((m) => m.a < m.b && m.rho != null && Math.abs(m.rho) >= 0.5);
    lines.push(`## Notable associations (${c.method}, ${c.window_days} days)`, '', ...(strong.length ? strong.map((m) => `- ${m.a} ~ ${m.b}: ρ = ${m.rho} (n=${m.n})`) : ['- none with |ρ| ≥ 0.5']), '', `_${c.note}_`, '');
  }
  lines.push('## Method', '', ...a.method.steps.map((s, i) => `${i + 1}. ${s}`), '', '## Limitations', '', ...a.method.limitations.map((l) => `- ${l}`), '');
  return lines.join('\n');
}
