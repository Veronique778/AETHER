import { RecordingView, useBiosignal, usePersonalView } from '../biosignals/BiosignalPage';
import { useEffect, useMemo, useState } from 'react';
import { METRIC_KEYS, type Analysis, type Measurement, type MetricKey, type PhantomHistory } from '../../api/types';
import { ChartFrame, TimeSeriesChart } from '../../charts';
import { BODY_SYSTEMS, fmt, fmtMetric, METRICS, type BodySystem } from '../../lib/format';
import { navigate, useRoute } from '../../lib/router';
import { useResource } from '../../lib/useResource';
import { hexToRgb } from '../../scene3d/engine';
import { METRIC_ANCHORS, SYSTEM_FOCUS } from '../../scene3d/models';
import { Viewport } from '../../scene3d/Viewport';
import { API_BASE, useApp, useAstronaut } from '../../state/AppState';
import { Async, Button, Card, cx, Dialog, Disclosure, Icon, InfoTip, MissingValue, Notice, PhantomPill, Pill, Segmented, SourceBadge, TabPanel, Tabs, Tooltip, useTab, type TabDef } from '../../ui';
import { CrewSwitcher } from '../shared/CrewSwitcher';
import { ModuleHeader } from '../shared/ModuleHeader';
import { ManualEntryForm } from './ManualEntryForm';
import { SensorPanel } from './SensorPanel';
import { DEMO_CHANNEL_NOTE, demoVitals } from '../../mocks/demoChannels';
import { useScenarioRun } from '../../state/scenario';
import { HUMAN_ASSETS, type HumanAssetId } from '../../scene3d/humanAssets';
import { readBodyModel, useHumanModel, writeBodyModel } from '../../scene3d/useHumanModel';
import { EngineMetricsCard } from './EngineMetricsCard';
import { METRIC_SCIENCE } from '../../lib/metricScience';
import { PersonalBodyPage } from '../personal/PersonalMonitoring';

const SYSTEM_ORDER: BodySystem[] = ['cardiovascular', 'respiratory', 'nervous', 'musculoskeletal', 'metabolic'];
type BodyTab = 'twin' | 'history' | 'compare' | 'sensors';
const TABS: TabDef<BodyTab>[] = [
  { id: 'twin', label: 'Digital twin', icon: 'body' },
  { id: 'history', label: 'Measurement history', icon: 'table' },
  { id: 'compare', label: 'Compare time points', icon: 'layers' },
  { id: 'sensors', label: 'Sensors', icon: 'bluetooth' },
];
const SELECT = hexToRgb('#00e5ff');
const FLAG = hexToRgb('#ffbf69');

/** Flags per day as delivered by the PHANTOM history API – BODY only displays them. */
function flagsOn(h: PhantomHistory | undefined, day: number): MetricKey[] | null {
  const p = h?.points.find((x) => x.day === day);
  return p ? p.flagged : null;
}

export function BodyPage() {
  const { source, sessionId } = useBiosignal();
  const personal = usePersonalView();
  if (personal) return <PersonalBodyPage />;
  return source === 'synthetic' ? <SimulationBodyPage /> : <RecordingView key={sessionId} body={true} />;
}

function SimulationBodyPage() {
  const { api, astronautId, day, dataVersion, openWith, hour } = useApp();
  const astronaut = useAstronaut();
  const key = `${api.mode}-${astronautId}-${day}-${dataVersion}`;
  const timeline = useResource(`tl-${key}`, () => api.timeline(astronautId, day));
  const analysis = useResource(`ph-${key}`, () => api.phantom(astronautId, day));
  const history = useResource(`phh-${key}`, () => api.phantomHistory(astronautId, day, 41));
  const ship = useResource(`ship-${api.mode}-${day}-${hour}-${dataVersion}`, () => api.ship(day, hour));
  const [tab, setTab] = useTab(TABS);
  const [entry, setEntry] = useState<{ metric?: MetricKey } | null>(null);
  const where = ship.data?.crew.find((c) => c.id === astronautId);

  return (
    <div>
      <Notice tone="attention" className="mb-4" title="Synthetic Mission Demo · A01–A04">
        These mission-day values are synthetic simulation data, not Personal Monitoring records or wearable measurements.
      </Notice>
      <ModuleHeader module="/body" title={astronaut?.name ?? 'Astronaut'}
        description={<>{astronaut?.role} · mission day {day}. The twin displays measurements and the PHANTOM flags it receives; BODY performs no analysis of its own.</>}
        actions={<>
          <Button variant="primary" icon="plus" onClick={() => setEntry({})}>Record measurement</Button>
          <Button icon="brain" onClick={() => navigate('/phantom')}>Analyse in PHANTOM</Button>
          {where && <Button icon="waves" onClick={() => openWith('/symbiosis', { zoneId: where.zone })}>Environment here now</Button>}
        </>} />
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <CrewSwitcher />
        {analysis.data && <span className="flex items-center gap-2 text-sm text-ink-3">PHANTOM day {day}: <PhantomPill status={analysis.data.status} /></span>}
      </div>
      {api.mode === 'live' && <HumanSystemsQuality astronautId={astronautId} day={day} dataVersion={dataVersion} />}
      {api.mode === 'live' && <NasaResearchPanel />}
      <Tabs label="BODY sections" tabs={TABS} value={tab} onChange={setTab} />
      <TabPanel label={TABS.find((t) => t.id === tab)!.label}>
        {tab === 'twin' && (
          <Async res={timeline} loadingLabel="Loading physiological history">
            {(rows) => <div className="space-y-5"><ScenarioMetrics row={rows.find((r) => r.day === day)} /><EngineMetricsCard /><TwinStage rows={rows} analysis={analysis.data} history={history.data} onRecord={(m) => setEntry({ metric: m })} /></div>}
          </Async>
        )}
        {tab === 'history' && <Async res={timeline}>{(rows) => <HistoryTable rows={rows} />}</Async>}
        {tab === 'compare' && <Async res={timeline}>{(rows) => <><CompareTimePoints rows={rows} history={history.data} /><div className="mt-5"><PeriodComparison rows={rows} /></div></>}</Async>}
        {tab === 'sensors' && <SensorPanel />}
      </TabPanel>
      <Dialog open={!!entry} onClose={() => setEntry(null)} title={`Record measurement · ${astronaut?.name ?? ''}`} wide
        description="Enter only what you measured; other values for that day are kept. Stored with source “manual”.">
        <ManualEntryForm bare initialMetric={entry?.metric} onSaved={() => undefined} />
      </Dialog>
    </div>
  );
}

/** SpO₂ / respiration: demo channels in Demo Mode, "not provided" in Live Mode. */
function ExtraVitals({ viewDay }: { viewDay: number }) {
  const { api, astronautId } = useApp();
  const v = demoVitals(astronautId, viewDay);
  return (
    <div className="mt-3 border-t border-line pt-2">
      <div className="mb-1 flex items-center justify-between"><span className="mono-label">Respiratory</span>{api.mode === 'demo' ? <Tooltip text={DEMO_CHANNEL_NOTE}>{(id) => <span aria-describedby={id} tabIndex={0} className="rounded border border-dashed border-attention/70 px-1.5 text-[10px] uppercase tracking-wide text-attention">demo channel</span>}</Tooltip> : <span className="text-[10px] text-ink-3">not in API</span>}</div>
      <div className="grid grid-cols-2 gap-1 text-xs">
        <span className="text-ink-2">SpO₂ <span className="tabular font-semibold text-ink">{api.mode === 'demo' ? `${v.spo2_pct} %` : '—'}</span></span>
        <span className="text-ink-2">Resp. rate <span className="tabular font-semibold text-ink">{api.mode === 'demo' ? `${v.resp_rate_min} /min` : '—'}</span></span>
      </div>
    </div>
  );
}

/** Modelled values for the applied MISSION LAB scenario next to the actual day values. */
export function ScenarioMetrics({ row }: { row?: Measurement }) {
  const { scenario, day } = useApp();
  const run = useScenarioRun();
  if (!scenario) return null;
  return (
    <section aria-label="Scenario effect on this astronaut" className="card border-violet/40 p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div><div className="mono-label text-violet">Scenario (model) · day {day}</div><h2 className="text-base font-semibold text-ink">{scenario.title}: modelled vs actual</h2></div>
        <SourceBadge source="simulated" />
      </div>
      <Async res={run} loadingLabel="Running scenario model">{(r) => (
        <>
          <div className="overflow-x-auto"><table className="tabular w-full min-w-[480px] text-sm">
            <caption className="sr-only">Actual and modelled values per metric</caption>
            <thead><tr className="text-left text-xs text-ink-3"><th className="py-1 font-medium">Metric</th><th className="font-medium">Actual (day {day})</th><th className="font-medium">Scenario (model)</th><th className="font-medium">Δ</th></tr></thead>
            <tbody>{METRIC_KEYS.map((k) => {
              const a = row?.[k] ?? null, m = r.metrics[k];
              const d = a == null || m == null ? null : m - a;
              const worse = d != null && (METRICS[k].better === 'lower' ? d > 0 : d < 0);
              return <tr key={k} className="border-t border-line"><td className="py-1.5 text-ink-2">{METRICS[k].label}</td><td className="text-ink">{fmtMetric(k, a)} {METRICS[k].unit}</td><td className="text-violet">{fmtMetric(k, m)} {METRICS[k].unit}</td>
                <td className={cx(d == null ? 'text-ink-3' : worse ? 'text-attention' : 'text-good')}>{d == null ? '—' : `${d > 0 ? '+' : ''}${fmt(d, METRICS[k].decimals)}`}</td></tr>;
            })}</tbody>
          </table></div>
          <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-3">Modelled PHANTOM status: <PhantomPill status={r.phantom.status} /> index {r.phantom.score ?? '—'}/100. {r.assumptions}</p>
        </>
      )}</Async>
    </section>
  );
}

/* ------------------------------------------------------------------ the twin stage */
function TwinStage({ rows, analysis, history, onRecord }: { rows: Measurement[]; analysis?: Analysis; history?: PhantomHistory; onRecord: (m: MetricKey) => void }) {
  const { reducedMotion, day } = useApp();
  const [xray, setXray] = useState(false);
  const [layers, setLayers] = useState<Record<BodySystem, boolean>>({ cardiovascular: true, respiratory: true, nervous: true, musculoskeletal: true, metabolic: true });
  const { query } = useRoute();
  const [system, setSystem] = useState<BodySystem>(() => (SYSTEM_ORDER.includes(query.get('system') as BodySystem) ? (query.get('system') as BodySystem) : 'cardiovascular'));
  const [metric, setMetric] = useState<MetricKey>(() => BODY_SYSTEMS[system].metrics[0] ?? 'heart_rate_bpm');
  const [viewDay, setViewDay] = useState(day);
  const [asset, setAssetState] = useState<HumanAssetId>(() => readBodyModel());
  const setAsset = (a: HumanAssetId) => { writeBodyModel(a); setAssetState(a); };
  const { model, status: modelStatus, error: modelError } = useHumanModel(asset, xray);
  const assetInfo = HUMAN_ASSETS.find((a) => a.id === asset)!;
  const row = rows.find((r) => r.day === viewDay) ?? rows.at(-1);
  const flags = flagsOn(history, viewDay);
  const flagged = (k: MetricKey) => !!flags?.includes(k);
  const sysFlag = (s: BodySystem) => BODY_SYSTEMS[s].metrics.some(flagged);
  const hidden = useMemo(() => new Set(SYSTEM_ORDER.filter((s) => !layers[s] || !xray)), [layers, xray]);
  const highlight = useMemo(() => {
    const h: Record<string, { color: [number, number, number]; amount: number }> = {};
    for (const s of SYSTEM_ORDER) if (sysFlag(s)) h[s] = { color: FLAG, amount: 0.45 };
    h[system] = { color: SELECT, amount: 0.35 };
    return h;
  }, [system, flags?.join()]); // eslint-disable-line react-hooks/exhaustive-deps
  // Surface retains the shell; unchecked systems dim approximate exterior regions.
  // X-ray still filters the corresponding schematic inner layers via hiddenLayers.
  const dim = useMemo(() => (id: string | null, layer?: string) =>
    layer === 'shell' && id && layers[id as BodySystem] === false ? 0.18
      : layer === 'shell' || !id || id === system ? 1 : 0.55, [system, layers]);
  const pick = (s: BodySystem) => { setSystem(s); const ms = BODY_SYSTEMS[s].metrics; if (ms.length && !ms.includes(metric)) setMetric(ms[0]); };
  const choose = (k: MetricKey) => { setMetric(k); setSystem(METRICS[k].system); };
  const signal = analysis?.signals.find((s) => s.key === metric);
  const info = METRICS[metric];
  const shown = rows.slice(-40);

  return (
    <div className="space-y-5">
      <div className="always-dark stage relative overflow-hidden rounded-2xl border border-line">
        <Viewport model={model} initialCamera={{ yaw: 0.35, pitch: 0.08, dist: 10.5, target: [0, 0.35, 0], fov: 0.72 }} focus={SYSTEM_FOCUS[system]}
          highlight={highlight} hiddenLayers={hidden} dim={dim} reducedMotion={reducedMotion} height={560}
          onPick={(id) => { if (id) pick(id as BodySystem); }}
          anchors={METRIC_KEYS.filter((k) => layers[METRICS[k].system]).map((k) => ({
            id: k, pos: METRIC_ANCHORS[k],
            render: ({ front }) => (
              <button type="button" onClick={() => choose(k)} aria-pressed={metric === k}
                aria-label={`${METRICS[k].label} on day ${viewDay}: ${row?.[k] == null ? 'no data' : fmtMetric(k, row[k]) + ' ' + METRICS[k].unit}${flagged(k) ? ', flagged by PHANTOM' : ''}`}
                className={cx('group flex min-h-8 items-center gap-1.5 rounded-full border py-1 pl-1.5 pr-2.5 text-[11px] font-medium text-white shadow-lg backdrop-blur transition-transform hover:scale-105',
                  metric === k ? 'border-[#4fd1e8] bg-[#1d6f8a]/90' : 'border-[#56708c]/70 bg-[#0c1422]/80', !front && 'opacity-50')}>
                <span className={cx('relative grid h-4 w-4 place-items-center rounded-full', flagged(k) ? 'bg-[#f2b45a]' : 'bg-[#4fd1e8]')}>
                  {flagged(k) && !reducedMotion && <span className="absolute inset-0 rounded-full bg-[#f2b45a]" style={{ animation: 'aether-ring 1.8s ease-out infinite' }} />}
                  <Icon name={flagged(k) ? 'info' : 'activity'} size={10} className="relative text-[#070b14]" />
                </span>
                <span className="tabular">{row?.[k] == null ? '—' : fmtMetric(k, row[k])}<span className="ml-0.5 text-[#a9b8ca]">{METRICS[k].unit}</span></span>
              </button>
            ),
          }))}
          ariaLabel="3D human digital twin. Drag or use arrow keys to rotate, plus and minus to zoom. Click a region or organ to select its system."
          instructions="Drag / arrows rotate · ± zoom · click organ or region · value tags open the metric" />

        {/* Layer controls */}
        <div className="hud absolute left-3 top-3 w-60 p-3">
          <div className="mono-label mb-2">View</div>
          <label className="mb-2 block text-xs text-ink-2">3D model
            <select className="field mt-1 !py-1 text-xs" value={asset} onChange={(e) => setAsset(e.target.value as HumanAssetId)} aria-describedby="body-model-note">
              {HUMAN_ASSETS.map((a) => <option key={a.id} value={a.id}>{a.label}{a.sizeMb ? ` · ${a.sizeMb} MB` : ''}</option>)}
            </select>
          </label>
          {modelStatus === 'loading' && <p className="mb-2 text-[11px] text-teal-300" role="status">Loading {assetInfo.file}…</p>}
          {modelStatus === 'error' && <p className="mb-2 rounded-md border border-attention/50 bg-attention/10 p-1.5 text-[11px] text-ink-2" role="alert">{modelError} Showing the schematic figure instead.</p>}
          <Segmented size="sm" label="Body view" value={xray ? 'xray' : 'surface'} onChange={(v) => setXray(v === 'xray')} options={[{ value: 'xray', label: 'X-ray layers', icon: 'layers' }, { value: 'surface', label: 'Surface', icon: 'body' }]} />
          <div className="mono-label mb-1.5 mt-3">Systems</div>
          <ul className="space-y-1">
            {SYSTEM_ORDER.map((s) => (
              <li key={s} className={cx('flex items-center gap-1 rounded-lg', system === s && 'bg-white/5')}>
                <label className="grid h-8 w-8 shrink-0 cursor-pointer place-items-center" title={`Show ${BODY_SYSTEMS[s].label} layer`}>
                  <input type="checkbox" checked={layers[s]} onChange={(e) => { const checked = e.target.checked; setLayers((previous) => ({ ...previous, [s]: checked })); }} aria-label={`Show ${BODY_SYSTEMS[s].label} layer`} />
                </label>
                <button type="button" onClick={() => pick(s)} aria-pressed={system === s} className="flex min-h-8 flex-1 items-center gap-2 text-left text-xs text-ink">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: BODY_SYSTEMS[s].color }} />
                  <span className="flex-1">{BODY_SYSTEMS[s].label}</span>
                  {sysFlag(s) && <Icon name="info" size={13} className="text-attention" title="PHANTOM flag on this day" />}
                </button>
              </li>
            ))}
          </ul>
          {BODY_SYSTEMS[system].note && <p className="mt-2 rounded-md border border-line bg-white/5 p-1.5 text-[11px] text-ink-2">{BODY_SYSTEMS[system].note}</p>}
          <p id="body-model-note" className="mt-2 text-[11px] text-ink-3">{assetInfo.description} {asset === 'procedural' ? 'Not anatomically accurate.' : 'Region-to-system mapping is approximate.'} {xray ? 'X-ray toggles control inner layers.' : 'Surface toggles dim approximate body regions and hide related metric tags; use X-ray for inner organ layers.'} Not a medical visualisation.</p>
        </div>

        {/* Current parameters */}
        <div className="hud absolute right-16 top-3 hidden w-72 p-3 md:block">
          <div className="mb-2 flex items-center justify-between"><span className="mono-label">Parameters · day {viewDay}</span><SourceBadge source={row?.source} /></div>
          <ul className="space-y-1">
            {METRIC_KEYS.map((k) => {
              const sig = analysis?.signals.find((x) => x.key === k);
              return (
                <li key={k}>
                  <button type="button" onClick={() => choose(k)} aria-pressed={metric === k}
                    className={cx('flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors', metric === k ? 'bg-teal-600/30' : 'hover:bg-white/5')}>
                    <span className="h-2 w-2 rounded-full" style={{ background: BODY_SYSTEMS[METRICS[k].system].color }} />
                    <span className="flex-1 text-xs text-ink-2">{METRICS[k].short}</span>
                    <span className="tabular text-sm font-semibold text-ink">{row?.[k] == null ? <MissingValue /> : fmtMetric(k, row[k])}</span>
                    <span className="w-7 text-[10px] text-ink-3">{METRICS[k].unit}</span>
                    {flagged(k) ? <Icon name="info" size={13} className="text-attention" title="Flagged by PHANTOM" /> : <span className="w-[13px]" />}
                  </button>
                  {metric === k && sig && viewDay === day && <DeviationStrip z={sig.deviation} better={METRICS[k].better} />}
                </li>
              );
            })}
          </ul>
          <Button size="sm" icon="plus" className="mt-2 w-full" onClick={() => onRecord(metric)}>Record {METRICS[metric].short.toLowerCase()}</Button>
          <ExtraVitals viewDay={viewDay} />
        </div>

        {/* Time scrubber */}
        <div className="hud absolute bottom-9 left-3 right-3 flex flex-wrap items-center gap-3 px-3 py-2 sm:right-16">
          <span className="mono-label">Time point</span>
          <input type="range" min={rows[0]?.day ?? 1} max={day} value={viewDay} onChange={(e) => setViewDay(Number(e.target.value))} className="min-w-40 flex-1" aria-label="Day shown on the twin" />
          <span className="tabular w-16 text-sm font-semibold text-ink">Day {viewDay}</span>
          {flags == null ? <Pill tone="unknown">baseline window</Pill> : flags.length ? <Pill tone="attention">{flags.length} PHANTOM flag{flags.length > 1 ? 's' : ''}</Pill> : <Pill tone="good">no flags</Pill>}
          {viewDay !== day && <Button size="sm" variant="ghost" icon="reset" onClick={() => setViewDay(day)}>Back to day {day}</Button>}
        </div>
      </div>

      {/* Selected metric: interactive history */}
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Card eyebrow={`${BODY_SYSTEMS[system].label} · interactive history`} title={`${info.label} (${info.unit})`} actions={<InfoTip text="Click or use ←/→ on the chart to move the time point shown on the twin." />}>
          <ChartFrame caption={`${info.label} by mission day`} table={{ columns: ['Day', `${info.short} (${info.unit})`, 'Source'], rows: shown.map((r) => [r.day, fmtMetric(metric, r[metric]), r.source]) }}>
            <TimeSeriesChart ariaLabel={`${info.label} over mission days; selecting a day moves the twin's time point`} height={220} cursorX={viewDay}
              onCursor={(x) => { if (x != null) setViewDay(x); }}
              series={[{ id: metric, label: info.short, color: 'var(--color-cyan)', points: shown.map((r) => ({ x: r.day, y: r[metric], tag: r.source === 'manual' ? 'manual' : flagsOn(history, r.day)?.includes(metric) ? 'flag' : undefined })) }]}
              refBand={signal ? { lo: signal.baseline - 2 * signal.scale, hi: signal.baseline + 2 * signal.scale, label: 'personal band' } : undefined}
              xFormat={(x) => `Day ${x}`} yFormat={(y) => fmt(y, info.decimals)} unit={info.unit} tagLabel={{ manual: 'manual entry', flag: 'PHANTOM flag' }} />
          </ChartFrame>
          <p className="mt-2 text-xs text-ink-3">Band: personal baseline ± 2 robust spreads (from PHANTOM). Diamonds: manual entries or days PHANTOM flagged this signal.</p>
          <Disclosure summary={`Why ${info.short.toLowerCase()} is tracked – scientific basis`}>
            <div className="space-y-1 text-xs text-ink-2">
              <p>{METRIC_SCIENCE[metric].why}</p>
              <p><span className="text-ink-3">NASA HRP risk: </span>{METRIC_SCIENCE[metric].risk}</p>
              <p><span className="text-ink-3">Sources (SCIENCE → evidence library): </span>{METRIC_SCIENCE[metric].sources.join(', ')}</p>
              <p className="text-ink-3">Limitation: {METRIC_SCIENCE[metric].limitation}</p>
            </div>
          </Disclosure>
        </Card>
        <Card eyebrow="PHANTOM result received" title="Status & deviations" actions={<SourceBadge source="research_prototype" />}>
          {analysis ? (
            <>
              <PhantomPill status={analysis.status} />
              <p className="mt-2 text-sm text-ink-2">{analysis.explanation}</p>
              <ul className="mt-3 space-y-1.5">
                {analysis.signals.map((s) => (
                  <li key={s.key} className="flex items-center gap-2 text-xs">
                    <span className="w-20 text-ink-3">{METRICS[s.key].short}</span>
                    <DeviationStrip z={s.deviation} better={METRICS[s.key].better} compact />
                    {s.flagged && <Icon name="info" size={13} className="text-attention" title="flagged" />}
                  </li>
                ))}
              </ul>
              <Button size="sm" className="mt-3" iconRight="arrowRight" onClick={() => navigate('/phantom')}>Explanation in PHANTOM</Button>
            </>
          ) : <MissingValue label="No PHANTOM result" />}
        </Card>
      </div>
    </div>
  );
}

/** Robust z rendered as a centred bar; amber when in the less favourable direction beyond 2. */
function DeviationStrip({ z, better, compact }: { z: number; better: 'lower' | 'higher'; compact?: boolean }) {
  const max = 6;
  const c = Math.max(-max, Math.min(max, z));
  const adverse = better === 'lower' ? z >= 2 : z <= -2;
  return (
    <span className={cx('relative block flex-1', compact ? 'h-2' : 'mx-2 mb-1 mt-0.5 h-1.5')} role="img" aria-label={`robust deviation ${z.toFixed(1)}`}>
      <span className="absolute inset-0 rounded-full bg-white/5" />
      <span className="absolute inset-y-0 left-1/2 w-px bg-white/25" />
      <span className={cx('absolute inset-y-0 rounded-full', adverse ? 'bg-attention' : 'bg-teal-300/70')} style={{ left: `${50 + Math.min(0, c) / max * 50}%`, width: `${Math.abs(c) / max * 50}%` }} />
    </span>
  );
}

/* ------------------------------------------------------------------ two time points */
function CompareTimePoints({ rows, history }: { rows: Measurement[]; history?: PhantomHistory }) {
  const { day } = useApp();
  const first = rows[0]?.day ?? 1;
  const [a, setA] = useState(Math.max(first, 40));
  const [b, setB] = useState(day);
  const ra = rows.find((r) => r.day === a), rb = rows.find((r) => r.day === b);
  const fa = flagsOn(history, a), fb = flagsOn(history, b);
  return (
    <Card eyebrow="Compare two time points" title={`Day ${a} → day ${b}`} actions={<Tooltip text="Flags are PHANTOM results for each day; days 1–40 are its baseline window.">{(id) => <span aria-describedby={id} tabIndex={0} className="text-xs text-ink-3 underline decoration-dotted">About flags</span>}</Tooltip>}>
      <div className="mb-4 grid gap-4 sm:grid-cols-2">
        {([['A', a, setA, 'var(--color-series-1)'], ['B', b, setB, 'var(--color-series-3)']] as const).map(([lbl, v, set, col]) => (
          <label key={lbl} className="block rounded-xl border border-line p-3">
            <span className="mb-1 flex items-center justify-between text-sm"><span className="flex items-center gap-2 font-medium text-ink"><span className="h-2.5 w-2.5 rounded-full" style={{ background: col }} />Time point {lbl}</span><span className="tabular font-semibold text-ink">Day {v}</span></span>
            <input type="range" min={first} max={day} value={v} onChange={(e) => set(Number(e.target.value))} className="w-full" aria-label={`Time point ${lbl} day`} />
          </label>
        ))}
      </div>
      <ul className="space-y-3">
        {METRIC_KEYS.map((k) => {
          const va = ra?.[k] ?? null, vb = rb?.[k] ?? null;
          const vals = rows.map((r) => r[k]).filter((x): x is number => x != null);
          const lo = Math.min(...vals), hi = Math.max(...vals);
          const pos = (v: number) => `${((v - lo) / (hi - lo || 1)) * 100}%`;
          const d = va != null && vb != null ? vb - va : null;
          const worse = d != null && Math.abs(d) > 1e-9 && ((METRICS[k].better === 'lower') === d > 0);
          return (
            <li key={k} className="grid items-center gap-2 sm:grid-cols-[170px_minmax(0,1fr)_150px]">
              <span className="text-sm text-ink-2">{METRICS[k].label}</span>
              <div className="relative h-7" role="img" aria-label={`${METRICS[k].label}: day ${a} ${va ?? 'no data'}, day ${b} ${vb ?? 'no data'}`}>
                <div className="absolute inset-x-0 top-1/2 h-px bg-line-strong/50" />
                {va != null && vb != null && <div className={cx('absolute top-1/2 h-1 -translate-y-1/2 rounded-full', worse ? 'bg-attention/70' : 'bg-teal-300/50')} style={{ left: pos(Math.min(va, vb)), width: `calc(${pos(Math.max(va, vb))} - ${pos(Math.min(va, vb))})` }} />}
                {va != null && <span className={cx('absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-canvas', fa?.includes(k) && 'ring-2 ring-attention')} style={{ left: pos(va), background: 'var(--color-series-1)' }} />}
                {vb != null && <span className={cx('absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-canvas', fb?.includes(k) && 'ring-2 ring-attention')} style={{ left: pos(vb), background: 'var(--color-series-3)' }} />}
              </div>
              <span className="tabular text-right text-sm">
                <span className="text-ink-3">{fmtMetric(k, va)} → </span><span className="font-semibold text-ink">{fmtMetric(k, vb)}</span>
                {d != null && <span className={cx('ml-1.5 text-xs', worse ? 'text-attention' : 'text-ink-3')}>({d > 0 ? '+' : ''}{fmt(d, METRICS[k].decimals + 1)})</span>}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-xs text-ink-3">Dots: A = blue, B = violet, on each metric's mission range. Amber ring = PHANTOM flagged that signal on that day. Descriptive comparison only.</p>
    </Card>
  );
}

function HistoryTable({ rows }: { rows: Measurement[] }) {
  const [onlyManual, setOnlyManual] = useState(false);
  const shown = [...rows].reverse().filter((r) => !onlyManual || r.source === 'manual');
  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {METRIC_KEYS.map((k) => (
          <Card key={k} eyebrow={METRICS[k].unit} title={METRICS[k].label} bodyClassName="pt-1">
            <TimeSeriesChart ariaLabel={`${METRICS[k].label} over the mission`} height={140}
              series={[{ id: k, label: METRICS[k].short, color: 'var(--color-teal-300)', points: rows.map((r) => ({ x: r.day, y: r[k], tag: r.source === 'manual' ? 'manual' : undefined })) }]}
              xFormat={(x) => `Day ${x}`} yFormat={(y) => fmt(y, METRICS[k].decimals)} unit={METRICS[k].unit} tagLabel={{ manual: 'manual entry' }} />
          </Card>
        ))}
      </div>
      <Card title="All measurements" eyebrow={`${rows.length} days`} actions={<label className="flex items-center gap-2 text-sm text-ink-2"><input type="checkbox" checked={onlyManual} onChange={(e) => setOnlyManual(e.target.checked)} />Manual entries only</label>}>
        {shown.length === 0 ? <p className="text-sm text-ink-3">No manual entries yet – add one in the Manual entry tab.</p> : (
          <div className="max-h-[520px] overflow-auto rounded-xl border border-line">
            <table className="tabular w-full min-w-[640px] text-sm">
              <caption className="sr-only">Daily measurements, newest first</caption>
              <thead className="sticky top-0 bg-raised text-left text-xs text-ink-3"><tr><th className="px-3 py-2 font-medium">Day</th>{METRIC_KEYS.map((k) => <th key={k} className="font-medium">{METRICS[k].short} ({METRICS[k].unit})</th>)}<th className="font-medium">Source</th></tr></thead>
              <tbody>{shown.map((r) => (
                <tr key={r.day} className="border-t border-line">
                  <td className="px-3 py-1.5 text-ink">{r.day}</td>
                  {METRIC_KEYS.map((k) => <td key={k} className="text-ink-2">{r[k] == null ? <MissingValue /> : fmtMetric(k, r[k])}</td>)}
                  <td><SourceBadge source={r.source} /></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

function mean(rows: Measurement[], k: MetricKey) {
  const v = rows.map((r) => r[k]).filter((x): x is number => x != null);
  return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null;
}

function PeriodComparison({ rows }: { rows: Measurement[] }) {
  const last = rows.at(-1)?.day ?? 1;
  const [a, setA] = useState<[number, number]>([1, 40]);
  const [b, setB] = useState<[number, number]>([Math.max(1, last - 6), last]);
  const pa = rows.filter((r) => r.day >= a[0] && r.day <= a[1]);
  const pb = rows.filter((r) => r.day >= b[0] && r.day <= b[1]);
  const rangeInput = (v: [number, number], set: (x: [number, number]) => void, label: string) => (
    <fieldset className="flex items-center gap-1.5 text-sm text-ink-2">
      <legend className="sr-only">{label}</legend>
      <span className="w-20 font-medium text-ink">{label}</span>
      <span>day</span><input aria-label={`${label} start day`} type="number" min={1} max={v[1]} value={v[0]} onChange={(e) => set([Math.max(1, Math.min(Number(e.target.value), v[1])), v[1]])} className="field !w-16 !py-1" />
      <span>to</span><input aria-label={`${label} end day`} type="number" min={v[0]} max={last} value={v[1]} onChange={(e) => set([v[0], Math.min(last, Math.max(Number(e.target.value), v[0]))])} className="field !w-16 !py-1" />
    </fieldset>
  );
  return (
    <Card eyebrow="Compare periods" title="Period A vs period B">
      <div className="mb-3 space-y-2">{rangeInput(a, setA, 'Period A')}{rangeInput(b, setB, 'Period B')}</div>
      <table className="tabular w-full text-sm">
        <thead><tr className="text-left text-xs text-ink-3"><th className="py-1 font-medium">Metric</th><th className="font-medium">A mean</th><th className="font-medium">B mean</th><th className="font-medium">Change</th></tr></thead>
        <tbody>
          {METRIC_KEYS.map((k) => {
            const ma = mean(pa, k), mb = mean(pb, k);
            const d = ma != null && mb != null ? mb - ma : null;
            const worse = d != null && Math.abs(d) > 1e-9 && ((METRICS[k].better === 'lower') === d > 0);
            return (
              <tr key={k} className="border-t border-line">
                <td className="py-1.5 text-ink-2">{METRICS[k].label}</td>
                <td>{fmt(ma, METRICS[k].decimals + 1)}</td>
                <td>{fmt(mb, METRICS[k].decimals + 1)}</td>
                <td className={worse ? 'text-attention' : 'text-ink-2'}>
                  {d == null ? '—' : <span className="inline-flex items-center gap-1">{Math.abs(d) > 1e-9 && <Icon name={d > 0 ? 'arrowUp' : 'arrowDown'} size={13} />}{d > 0 ? '+' : ''}{fmt(d, METRICS[k].decimals + 1)} {METRICS[k].unit}{worse && <span className="sr-only"> (less favourable)</span>}</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-ink-3">n = {pa.length} vs {pb.length} days. Amber marks a change in the less favourable direction; this is descriptive, not a significance test.</p>
    </Card>
  );
}

/** Additional provenance-aware analytics from the shared Python backend. */
function HumanSystemsQuality({ astronautId, day, dataVersion }: { astronautId: string; day: number; dataVersion: number }) {
  const [result, setResult] = useState<{ completeness: number; record_count: number; sources: string[]; missing_latest: string[]; uncertainty: {data:string}; suggested_measurements: {metric:string;reason:string}[] } | null>(null);
  const [error, setError] = useState('');
  // The primary API client uses the same localhost backend in desktop mode.
  const { backendVersion } = useApp();
  const { API_BASE } = requireHumanSystemsApi();
  useEffect(() => {
    let cancelled = false;
    setResult(null);
    fetch(`${API_BASE}/api/human-systems/${encodeURIComponent(astronautId)}/quality?day=${day}&window=14`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(data => { if (!cancelled) { setResult(data); setError(''); } })
      .catch(() => { if (!cancelled) setError('Extended data-quality API unavailable on this backend.'); });
    return () => { cancelled = true; };
  }, [astronautId, day, dataVersion, API_BASE, backendVersion]);
  return <section className="mb-4 rounded-xl border border-white/10 p-4" aria-label="Human systems data quality">
    <div className="mb-2 text-sm font-semibold">BIOMETRIC · Data quality</div>
    {result ? <div className="text-sm text-ink-3">
      <span>14-day completeness: {Math.round(result.completeness*100)}% · {result.record_count} recorded days</span>
      <span className="ml-3">Source: {result.sources.join(', ') || 'none'} · Data uncertainty: {result.uncertainty.data}</span>
      {result.missing_latest.length>0 && <p className="mt-2">Missing latest: {result.missing_latest.join(', ')}</p>}
      <p className="mt-1 text-xs">Research demo only. Synthetic records are not astronaut telemetry.</p>
    </div> : <p className="text-xs text-ink-3">{error || 'Checking measurement completeness…'}</p>}
  </section>;
}
function requireHumanSystemsApi() { return { API_BASE }; }


/** Real NASA OSDR catalog metadata; deliberately NOT mixed into the mission telemetry. */
function NasaResearchPanel() {
  const [result, setResult] = useState<{ available?:boolean; cached?:boolean; warning?:string; studies?:{accession:string;title:string;organism?:string;evidence_label?:string;data_layer?:string}[];source?:string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [term, setTerm] = useState('human physiology');
  const load = async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API_BASE}/api/nasa/catalog?term=${encodeURIComponent(term)}&refresh=true`);
      if (!r.ok) throw new Error('NASA catalog request failed');
      setResult(await r.json());
    } catch { setResult({warning: 'NASA research catalog is unavailable.'}); }
    finally { setLoading(false); }
  };
  return <section className="mb-4 rounded-xl border border-white/10 p-4" aria-label="NASA OSDR research catalog">
    <div className="mb-2 text-sm font-semibold">NASA OSDR · Research data</div>
    <p className="mb-2 text-xs text-ink-3">Real NASA study metadata; not live astronaut vitals. Mission measurements above are synthetic.</p>
    <div className="flex flex-wrap gap-2">
      <input aria-label="NASA research search" className="rounded border border-white/20 bg-transparent px-2 py-1 text-sm" value={term} onChange={e=>setTerm(e.target.value)} />
      <button type="button" className="rounded border border-white/20 px-3 py-1 text-sm" onClick={load} disabled={loading}>{loading ? 'Loading…' : 'Search NASA'}</button>
    </div>
    {result?.warning && <p className="mt-2 text-xs text-ink-3">{result.warning}</p>}
    {result?.studies?.map((study,i)=><p key={i} className="mt-1 text-xs">{study.accession}: {study.title || 'Untitled NASA research record'}{study.organism ? ` · ${study.organism} · ${study.evidence_label} · ${study.data_layer?.replace(/_/g,' ')}` : ''}</p>)}
    {result?.source && <a href={result.source} target="_blank" rel="noreferrer" className="mt-2 inline-block text-xs underline">NASA source / API</a>}
  </section>;
}


