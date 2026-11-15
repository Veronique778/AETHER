import { ResearchComparison } from '../biosignals/ResearchComparison';
import { useEffect, useMemo, useState } from 'react';
import { CAPABILITIES, type MetricKey, type Projection, type Scenario, type ScenarioParams, type SimulationResult } from '../../api/types';
import { ChartFrame, TimeSeriesChart } from '../../charts';
import { downloadText, fmt, METRICS } from '../../lib/format';
import { useResource } from '../../lib/useResource';
import { experimentStore, listExperiments, type SavedExperiment } from '../../lib/experiments';
import { EnginePanel } from './EnginePanel';
import { RadiationPanel } from './RadiationPanel';
import { useSimulationRunner } from '../../lib/simulationRunner';
import { useApp, useAstronaut } from '../../state/AppState';
import { Async, Button, Card, cx, Disclosure, Icon, Notice, PhantomPill, Pill, Segmented, SliderField, SourceBadge, TabPanel, Tabs, useTab, useToast, type TabDef } from '../../ui';
import { ModuleHeader } from '../shared/ModuleHeader';
import { paramSummary } from '../../state/scenario';
import { CrewSwitcher } from '../shared/CrewSwitcher';

type LabTab = 'setup' | 'results' | 'engine' | 'radiation' | 'experiments';
const TABS: TabDef<LabTab>[] = [
  { id: 'setup', label: 'Experiment setup', icon: 'sliders' },
  { id: 'results', label: 'Timeline & results', icon: 'activity' },
  { id: 'engine', label: 'Mission Systems engine', icon: 'orbit' },
  { id: 'radiation', label: 'Radiation', icon: 'zap' },
  { id: 'experiments', label: 'Saved experiments', icon: 'database' },
];
type RunOut = { slot: Slot; proj: Projection; single: SimulationResult }[];

/**
 * Illustrative scenario library (v0.5 brief). Each one is expressed ONLY through the simulator's existing
 * inputs; anything the model cannot represent is stated, never faked.
 */
const LIBRARY: { id: string; title: string; detail: string; params?: ScenarioParams; horizon?: number; unsupported?: string }[] = [
  { id: 'sleep-deprivation', title: 'Sleep deprivation', detail: '3 h less sleep than personal baseline, normal workload.', params: { sleep_delta: -3, workload: 60, co2_ppm: 900, temperature_c: 22.5, crew_available: 4 } },
  { id: 'elevated-co2', title: 'Elevated CO₂', detail: 'Cabin CO₂ 2,500 ppm (e.g. degraded scrubber), otherwise nominal.', params: { sleep_delta: 0, workload: 50, co2_ppm: 2500, temperature_c: 23, crew_available: 4 } },
  { id: 'heavy-workload', title: 'Heavy crew workload', detail: 'Workload 95/100 shared by 3 available crew.', params: { sleep_delta: -1, workload: 95, co2_ppm: 1000, temperature_c: 23, crew_available: 3 } },
  { id: 'emergency-eva', title: 'Emergency EVA (approx.)', detail: 'Approximated as maximal workload, −2 h sleep, 3 crew inside. The model has no EVA-specific physiology.', params: { sleep_delta: -2, workload: 100, co2_ppm: 1100, temperature_c: 24, crew_available: 3 } },
  { id: 'extended-mission', title: 'Extended mission duration', detail: 'Nominal inputs projected over a 60-day horizon.', params: { sleep_delta: -0.5, workload: 60, co2_ppm: 1000, temperature_c: 23, crew_available: 4 }, horizon: 60 },
  { id: 'radiation', title: 'Increased radiation exposure', detail: 'Not modelled.', unsupported: 'The simulator has no radiation input or dose–response model, so this scenario cannot be run honestly.' },
];

type Slot = { key: 'A' | 'B' | 'C'; title: string; params: ScenarioParams; color: string };
const SLOT_COLORS = { A: 'var(--color-series-1)', B: 'var(--color-series-2)', C: 'var(--color-series-3)' } as const;
type ChartKey = MetricKey | 'score' | 'attention_share';
const CHART_OPTS: { value: ChartKey; label: string }[] = [
  { value: 'score', label: 'PHANTOM index' }, { value: 'attention_share', label: 'Runs flagged' }, { value: 'fatigue_1_10', label: 'Fatigue' },
  { value: 'heart_rate_bpm', label: 'Heart rate' }, { value: 'reaction_ms', label: 'Reaction' }, { value: 'sleep_hours', label: 'Sleep' },
];

export function MissionLabPage() {
  const { api, astronautId, day, reducedMotion, applyScenario, scenario: applied, hasCapability, dataVersion } = useApp();
  const toast = useToast();
  const [reveal, setReveal] = useState(true);
  const apply = (id: string, t: string, p: ScenarioParams) => {
    applyScenario({ id, title: t, params: p });
    toast({ tone: 'info', title: `Scenario applied: ${t}`, body: 'SYMBIOSIS, PHANTOM, BODY and CO-ORBIT now show its modelled effect beside actual data.' });
  };
  const astronaut = useAstronaut();
  const presets = useResource(`scen-${api.mode}`, () => api.scenarios());
  const [params, setParams] = useState<ScenarioParams>({ sleep_delta: -1.8, workload: 85, co2_ppm: 1450, temperature_c: 25, crew_available: 4 });
  const [title, setTitle] = useState('Day 67 · accumulated strain');
  const [slots, setSlots] = useState<Slot[]>([]);
  const [horizon, setHorizon] = useState(21);
  const [runs, setRuns] = useState(200);
  const [seed, setSeed] = useState(67);
  const [chart, setChart] = useState<ChartKey>('score');
  const [tab, setTab] = useTab(TABS);
  const store = useMemo(() => experimentStore(api, hasCapability(CAPABILITIES.experiments)), [api, hasCapability]);
  const [saved, setSaved] = useState<SavedExperiment[]>([]);
  const reloadSaved = () => store.list().then(setSaved, () => setSaved(listExperiments()));
  useEffect(() => { void reloadSaved(); }, [store, dataVersion]); // eslint-disable-line react-hooks/exhaustive-deps
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  const runner = useSimulationRunner<RunOut>(
    () => Promise.all(slots.map(async (slot) => {
      const [proj, single] = await Promise.all([
        api.project({ astronaut_id: astronautId, start_day: day, horizon_days: horizon, runs, seed, ...slot.params }),
        api.simulate({ astronaut_id: astronautId, day, ...slot.params }),
      ]);
      return { slot, proj, single };
    })),
    () => horizon, reducedMotion ? 900 : 550,
  );
  // Any change to the experiment definition invalidates the previous result.
  useEffect(() => { runner.invalidate(); setSaveMsg(null); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [slots, horizon, runs, seed, astronautId, day, api]);

  useEffect(() => {
    if (!presets.data || slots.length) return;
    const pick = (id: string) => presets.data!.find((s) => s.id === id);
    setSlots((['baseline', 'day67', 'recovery'] as const).map((id) => pick(id)).filter((s): s is Scenario => !!s)
      .map((s, i) => ({ key: (['A', 'B', 'C'] as const)[i], title: s.title, params: toParams(s), color: SLOT_COLORS[(['A', 'B', 'C'] as const)[i]] })));
  }, [presets.data, slots.length]);

  const addSlot = () => {
    const used = new Set(slots.map((s) => s.key));
    const key = (['A', 'B', 'C'] as const).find((k) => !used.has(k));
    if (!key) return;
    setSlots([...slots, { key, title: title || `Scenario ${key}`, params: { ...params }, color: SLOT_COLORS[key] }]);
  };
  const series = useMemo(() => runner.result ?? [], [runner.result]);
  const cursorDay = day + runner.cursor;
  const startRun = () => { runner.start(); setTab('results'); };
  const save = () => {
    if (!runner.result) return;
    const e: SavedExperiment = {
      id: `${Date.now()}`, name: `${astronaut?.name ?? astronautId} · day ${day} · ${slots.map((s) => s.key).join('/')}`, created_at: new Date().toISOString().slice(0, 16).replace('T', ' '),
      astronaut_id: astronautId, start_day: day, horizon_days: horizon, runs, seed,
      scenarios: runner.result.map(({ slot, proj }) => { const d = proj.days[proj.days.length - 1]; return { key: slot.key, title: slot.title, params: slot.params, end: { score_p50: d.score.p50, score_p10: d.score.p10, score_p90: d.score.p90, attention_share: d.attention_share, fatigue_p50: d.fatigue_1_10.p50 } }; }),
    };
    const where = store.where === 'server' ? 'in the local AETHER database' : 'in this browser';
    store.save(e).then((ok) => {
      if (!ok) { setSaveMsg('Could not save – storage unavailable.'); return; }
      void reloadSaved(); setSaveMsg(`Saved ${where}.`); toast({ tone: 'good', title: 'Experiment saved', body: `Stored ${where}.` });
    }, (err: Error) => setSaveMsg(`Could not save – ${err.message}`));
  };
  const statusLabel: Record<typeof runner.status, string> = { idle: 'Not run', requesting: 'Requesting simulation…', ready: 'Ready', playing: 'Playing', paused: 'Paused', finished: 'Finished', error: 'Error' };

  return (
    <div>
      <ResearchComparison />
      <ModuleHeader module="/mission-lab" title={`Scenario explorer · day ${day}${day === 67 ? ' of the Mars transit' : ''}`}
        description={<>Configure alternative plans, run them through the Mission Systems simulator and compare the projected outcomes with their uncertainty. Illustrative model – bands show model spread, not a validated prediction.</>} />
      <LabConsole status={runner.status} cursor={runner.cursor} horizon={horizon} hasResult={!!runner.result} slots={slots.length} />
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <CrewSwitcher />
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Simulation controls">
          <Pill tone={runner.status === 'error' ? 'high' : runner.status === 'playing' ? 'info' : 'unknown'} icon="clock">{statusLabel[runner.status]}{runner.result ? ` · day ${cursorDay}` : ''}</Pill>
          <Button variant="primary" icon={runner.status === 'playing' ? 'pause' : 'play'} disabled={!slots.length || runner.status === 'requesting'} onClick={() => (runner.status === 'playing' ? runner.pause() : startRun())}>
            {runner.status === 'playing' ? 'Pause' : runner.result ? 'Play' : 'Start simulation'}
          </Button>
          <Button icon="reset" disabled={!runner.result} onClick={runner.reset}>Reset</Button>
        </div>
      </div>
      {runner.error && <Notice tone="high" className="mb-4" title="Simulation failed">{runner.error}</Notice>}
      <Tabs label="MISSION LAB sections" tabs={TABS} value={tab} onChange={setTab} />
      <TabPanel label={TABS.find((t) => t.id === tab)!.label}>
        {tab === 'setup' && (
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <Card eyebrow="Mission settings" title="Scenario parameters">
              <div className="mb-4">
                <div className="eyebrow mb-1.5">Scenario library (illustrative)</div>
                <ul className="grid gap-1.5 sm:grid-cols-2">
                  {LIBRARY.map((l) => (
                    <li key={l.id}>
                      <button type="button" disabled={!!l.unsupported} onClick={() => { if (l.params) { setParams(l.params); setTitle(l.title); if (l.horizon) setHorizon(l.horizon); } }}
                        title={l.unsupported ?? l.detail} aria-describedby={`lib-${l.id}`}
                        className={cx('interactive w-full rounded-lg border p-2 text-left text-sm disabled:cursor-not-allowed disabled:opacity-60', title === l.title ? 'border-teal-300 bg-teal-600/20' : 'border-line bg-raised/40 hover:border-line-strong')}>
                        <span className="flex items-center gap-1.5 font-medium text-ink">{l.unsupported && <Icon name="lock" size={13} className="text-ink-3" />}{l.title}</span>
                        <span id={`lib-${l.id}`} className="block text-xs text-ink-3">{l.unsupported ?? l.detail}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
              <Async res={presets}>{(ps) => (
                <div className="mb-4">
                  <div className="eyebrow mb-1.5">Simulator presets (API)</div>
                  <div className="flex flex-wrap gap-1.5">{ps.map((s) => <Button key={s.id} size="sm" variant={title === s.title ? 'primary' : 'secondary'} onClick={() => { setParams(toParams(s)); setTitle(s.title); }} title={s.detail}>{s.title}</Button>)}</div>
                </div>
              )}</Async>
              <div className="space-y-3">
                <label className="block text-sm text-ink-2">Name<input className="field mt-1" value={title} onChange={(e) => setTitle(e.target.value.slice(0, 50))} /></label>
                <SliderField label="Sleep duration vs personal baseline" value={params.sleep_delta} min={-4} max={2} step={0.1} unit=" h" format={(v) => (v > 0 ? '+' : '') + v.toFixed(1)} onChange={(v) => setParams({ ...params, sleep_delta: v })} />
                <SliderField label="Workload" value={params.workload} min={0} max={100} step={5} unit="/100" onChange={(v) => setParams({ ...params, workload: v })} />
                <SliderField label="Cabin CO₂" value={params.co2_ppm} min={400} max={3000} step={50} unit=" ppm" onChange={(v) => setParams({ ...params, co2_ppm: v })} />
                <SliderField label="Cabin temperature" value={params.temperature_c} min={16} max={30} step={0.5} unit=" °C" format={(v) => v.toFixed(1)} onChange={(v) => setParams({ ...params, temperature_c: v })} />
                <SliderField label="Crew availability" value={params.crew_available} min={1} max={4} step={1} unit=" of 4" onChange={(v) => setParams({ ...params, crew_available: v })} hint="Workload is shared among available crew." />
                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <Button icon="plus" onClick={addSlot} disabled={slots.length >= 3}>Add to comparison</Button>
                  <Button variant="primary" icon="orbit" onClick={() => apply(`custom-${Date.now()}`, title || 'Custom scenario', { ...params })}>Apply to mission</Button>
                  {slots.length >= 3 && <span className="text-xs text-ink-3">Max 3 – remove one first</span>}
                </div>
              </div>
            </Card>
            <Card eyebrow="Experiment panel" title="Scenarios in this experiment">
              {slots.length === 0 ? <p className="text-sm text-ink-3">Add up to three scenarios.</p> : (
                <ul className="space-y-2">{slots.map((s) => (
                  <li key={s.key} className="flex items-start gap-2 rounded-xl border border-line p-2.5 text-sm">
                    <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-md text-xs font-bold text-white" style={{ background: s.color }}>{s.key}</span>
                    <span className="min-w-0 flex-1"><span className="block font-medium text-ink">{s.title}</span><span className="tabular block text-xs text-ink-3">sleep {s.params.sleep_delta > 0 ? '+' : ''}{s.params.sleep_delta} h · load {s.params.workload} · CO₂ {s.params.co2_ppm} · {s.params.temperature_c} °C · crew {s.params.crew_available}</span></span>
                    <button type="button" aria-label={`Remove scenario ${s.key}`} onClick={() => setSlots(slots.filter((x) => x.key !== s.key))} className="grid h-7 w-7 place-items-center rounded-md text-ink-3 hover:text-high"><Icon name="x" size={16} /></button>
                  </li>
                ))}</ul>
              )}
              <div className="mt-4 space-y-3 border-t border-line pt-3">
                <SliderField label="Time horizon" value={horizon} min={7} max={60} step={1} unit=" days" onChange={setHorizon} />
                <div className="grid grid-cols-2 gap-2">
                  <label className="text-sm text-ink-2">Monte-Carlo runs<select className="field mt-1" value={runs} onChange={(e) => setRuns(Number(e.target.value))}>{[50, 100, 200, 500].map((r) => <option key={r} value={r}>{r}</option>)}</select></label>
                  <label className="text-sm text-ink-2">Random seed<input className="field mt-1" type="number" min={0} value={seed} onChange={(e) => setSeed(Math.max(0, Math.floor(Number(e.target.value) || 0)))} /></label>
                </div>
                <Button variant="primary" icon="play" className="w-full" onClick={startRun} disabled={runner.status === 'requesting' || !slots.length}>{runner.status === 'requesting' ? 'Simulating…' : `Start simulation (${slots.length} scenario${slots.length === 1 ? '' : 's'})`}</Button>
              </div>
            </Card>
          </div>
        )}
        {tab === 'results' && (!runner.result ? (
          <Card title="Results" eyebrow="Projection"><div className="flex min-h-64 flex-col items-center justify-center gap-3 text-center text-sm text-ink-3"><Icon name="flask" size={26} />{runner.status === 'requesting' ? 'Waiting for the simulator…' : `Start the simulation to project ${horizon} days from day ${day}.`}{runner.status !== 'requesting' && <Button variant="primary" icon="play" onClick={startRun} disabled={!slots.length}>Start simulation</Button>}</div></Card>
        ) : (
          <div className="space-y-5">
            <Card eyebrow={`Projection · day ${day}–${day + horizon}`} title="Timeline" actions={<><Button size="sm" icon="database" onClick={save}>Save experiment</Button><Button size="sm" icon="download" onClick={() => exportJson(series, { astronautId, day, horizon, runs, seed })}>JSON</Button><Button size="sm" icon="download" onClick={() => exportCsv(series, day)}>CSV</Button><SourceBadge source="simulated" /></>}>
              {saveMsg && <p className="mb-2 text-sm text-good" role="status">{saveMsg}</p>}
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <input type="range" aria-label="Timeline day" min={0} max={horizon} value={runner.cursor} onChange={(e) => runner.seek(Number(e.target.value))} className="min-w-40 flex-1" />
                <span className="tabular w-20 text-right text-sm font-semibold text-ink">Day {cursorDay}</span>
              </div>
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><Segmented size="sm" label="Metric" value={chart} onChange={setChart} options={CHART_OPTS} />
                <label className="flex items-center gap-2 text-xs text-ink-2"><input type="checkbox" checked={reveal} onChange={(e) => setReveal(e.target.checked)} />Reveal with playback</label></div>
              <ProjectionChart results={series} metric={chart} cursorDay={cursorDay} onCursor={(d) => runner.seek(d - day)} revealTo={reveal && runner.status !== 'finished' ? cursorDay : null} />
              <CursorTable results={series} t={runner.cursor} />
            </Card>
            {series.length >= 2 && <DifferenceCard results={series} metric={chart} />}
            <SideBySide results={series} metric={chart} cursorDay={cursorDay} />
            <Card eyebrow={`Single-day counterfactual · day ${day}`} title="PHANTOM and crew plan under each scenario" actions={<Button size="sm" icon="download" onClick={() => downloadText(`AETHER_MissionLab_day${day}.md`, buildLabReport(series, { astronaut: astronaut?.name ?? astronautId, day, horizon, runs, seed }))}>Summary report (.md)</Button>}>
              <div className="grid gap-3 md:grid-cols-3">
                {series.map(({ slot, single }) => (
                  <div key={slot.key} className="rounded-xl border border-line p-3">
                    <div className="mb-2 flex items-center gap-2"><span className="grid h-5 w-5 place-items-center rounded text-[11px] font-bold text-white" style={{ background: slot.color }}>{slot.key}</span><span className="truncate text-sm font-medium text-ink">{slot.title}</span></div>
                    <PhantomPill status={single.phantom.status} />
                    <div className="tabular mt-2 text-sm text-ink-2">Index {single.phantom.score ?? '—'}/100 · {single.phantom.flagged_count} flagged</div>
                    <div className="tabular text-sm text-ink-2">Unassigned tasks {single.crew.unassigned} · peak load {Math.round((single.crew.peak_utilisation ?? 0) * 100)}%</div>
                    <div className="tabular text-xs text-ink-3">Environment input: CO₂ {single.environment.co2_ppm} ppm · {single.environment.temperature_c} °C</div>
                    <Button size="sm" variant={applied?.title === slot.title ? 'primary' : 'secondary'} icon="orbit" className="mt-2" onClick={() => apply(`slot-${slot.key}-${slot.title}`, slot.title, slot.params)}>{applied?.title === slot.title ? 'Applied to mission' : 'Apply to mission'}</Button>
                  </div>
                ))}
              </div>
              <p className="mt-2 text-xs text-ink-3">{series[0]?.single.assumptions}</p>
            </Card>
            <Card eyebrow="Model transparency" title="Assumptions & uncertainty">
              <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">{series[0].proj.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
              <p className="mt-3 text-sm text-ink-3">{series[0].proj.note}</p>
              <div className="mt-3"><Disclosure summary="Derived model inputs per scenario">
                <table className="tabular w-full text-xs"><thead><tr className="text-left text-ink-3"><th>Scenario</th><th>Planned sleep</th><th>Sleep deficit</th><th>Workload index</th><th>Environment index</th></tr></thead>
                  <tbody>{series.map(({ slot, proj }) => <tr key={slot.key} className="border-t border-line"><td className="py-1">{slot.key}</td><td>{proj.derived.planned_sleep_h} h</td><td>{proj.derived.sleep_deficit_h} h</td><td>{proj.derived.workload_index}</td><td>{proj.derived.environment_index}</td></tr>)}</tbody></table>
                <p className="mt-2">Runs {series[0].proj.runs} · seed {series[0].proj.seed}. Same seed ⇒ identical results.</p>
              </Disclosure></div>
            </Card>
          </div>
        ))}
        {tab === 'engine' && <EnginePanel />}
        {tab === 'radiation' && <RadiationPanel />}
        {tab === 'experiments' && <ExperimentsPanel saved={saved} where={store.where} onDelete={(id) => { void store.remove(id).then(reloadSaved); }} />}
      </TabPanel>
    </div>
  );
}

function ExperimentsPanel({ saved, onDelete, where }: { saved: SavedExperiment[]; onDelete: (id: string) => void; where: 'server' | 'browser' }) {
  const [pick, setPick] = useState<string[]>([]);
  const chosen = saved.filter((e) => pick.includes(e.id));
  return (
    <div className="space-y-5">
      <Notice tone="unknown" title={where === 'server' ? 'Stored in the local AETHER database' : 'Stored in this browser'}>Saved experiments keep their parameters, seed and end-of-horizon summary. {where === 'server' ? 'They live in the SQLite database of the bundled backend (GET/POST/DELETE /api/mission-lab/experiments) and survive restarts.' : 'Demo Mode or an older backend: kept in this browser (localStorage).'}</Notice>
      <Card eyebrow="Experiments" title={`${saved.length} saved`}>
        {saved.length === 0 ? <p className="text-sm text-ink-3">Run a simulation and choose “Save experiment” on the Timeline tab.</p> : (
          <ul className="space-y-2">{saved.map((e) => (
            <li key={e.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-line p-3 text-sm">
              <label className="flex items-center gap-2"><input type="checkbox" checked={pick.includes(e.id)} disabled={!pick.includes(e.id) && pick.length >= 2} onChange={(ev) => setPick(ev.target.checked ? [...pick, e.id] : pick.filter((x) => x !== e.id))} aria-label={`Compare ${e.name}`} /></label>
              <span className="min-w-0 flex-1"><span className="block font-medium text-ink">{e.name}</span><span className="tabular text-xs text-ink-3">{e.created_at} · {e.horizon_days} days · {e.runs} runs · seed {e.seed}</span></span>
              <Button size="sm" variant="ghost" icon="x" onClick={() => onDelete(e.id)} aria-label={`Delete ${e.name}`}>Delete</Button>
            </li>
          ))}</ul>
        )}
      </Card>
      {chosen.length > 0 && (
        <Card eyebrow="Compare experiments" title={chosen.length === 2 ? 'Side by side' : 'Select one more to compare'}>
          <div className="grid gap-4 md:grid-cols-2">
            {chosen.map((e) => (
              <div key={e.id} className="rounded-xl border border-line p-3">
                <div className="mb-2 text-sm font-medium text-ink">{e.name}</div>
                <table className="tabular w-full text-sm">
                  <thead><tr className="text-left text-xs text-ink-3"><th className="py-1 font-medium">Scenario</th><th className="font-medium">Index at day {e.start_day + e.horizon_days}</th><th className="font-medium">Runs flagged</th></tr></thead>
                  <tbody>{e.scenarios.map((s) => (
                    <tr key={s.key} className="border-t border-line"><td className="py-1.5 text-ink-2">{s.key} · {s.title}</td><td className="text-ink">{fmt(s.end.score_p50, 0)} <span className="text-xs text-ink-3">{fmt(s.end.score_p10, 0)}–{fmt(s.end.score_p90, 0)}</span></td><td className={cx(s.end.attention_share >= 0.5 ? 'text-attention' : 'text-ink-2')}>{Math.round(s.end.attention_share * 100)}%</td></tr>
                  ))}</tbody>
                </table>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function toParams(s: Scenario): ScenarioParams {
  return { sleep_delta: s.sleep_delta, workload: s.workload, co2_ppm: s.co2_ppm, temperature_c: s.temperature_c, crew_available: s.crew_available ?? 4 };
}

function ProjectionChart({ results, metric, cursorDay, onCursor, revealTo = null }: { results: { slot: Slot; proj: Projection }[]; metric: ChartKey; cursorDay: number; onCursor: (d: number) => void; revealTo?: number | null }) {
  const shownDay = (d: number) => revealTo == null || d <= revealTo;
  const isShare = metric === 'attention_share';
  const label = metric === 'score' ? 'PHANTOM index' : isShare ? 'Share of runs flagged' : METRICS[metric as MetricKey].label;
  const unit = metric === 'score' ? '/100' : isShare ? '%' : METRICS[metric as MetricKey].unit;
  const dec = metric === 'score' || isShare ? 0 : METRICS[metric as MetricKey].decimals;
  const value = (d: Projection['days'][number]) => (isShare ? { p10: d.attention_share * 100, p50: d.attention_share * 100, p90: d.attention_share * 100 } : d[metric as MetricKey | 'score']);
  return (
    <ChartFrame caption={`${label} projection`} table={{ columns: ['Day', ...results.map((r) => `${r.slot.key} median (p10–p90)`)], rows: results[0].proj.days.map((d, i) => [d.day, ...results.map((r) => { const v = value(r.proj.days[i]); return isShare ? `${fmt(v.p50, 0)}%` : `${fmt(v.p50, dec)} (${fmt(v.p10, dec)}–${fmt(v.p90, dec)})`; })]) }}>
      <TimeSeriesChart ariaLabel={`${label} projection with 10th–90th percentile bands`} height={260} cursorX={cursorDay} onCursor={(x) => { if (x != null) onCursor(x); }}
        yDomain={metric === 'score' || isShare ? [0, 100] : ['auto', 'auto']}
        bands={isShare ? [] : results.map((r) => ({ id: r.slot.key + 'b', label: `${r.slot.key} 10–90 %`, color: r.slot.color, points: r.proj.days.filter((d) => shownDay(d.day)).map((d) => ({ x: d.day, lo: value(d).p10, hi: value(d).p90 })) }))}
        series={results.map((r) => ({ id: r.slot.key, label: `${r.slot.key} · ${r.slot.title}`, color: r.slot.color, points: r.proj.days.map((d) => ({ x: d.day, y: shownDay(d.day) ? value(d).p50 : null })) }))}
        xFormat={(x) => `Day ${x}`} yFormat={(y) => fmt(y, dec)} unit={unit} />
    </ChartFrame>
  );
}

function CursorTable({ results, t }: { results: { slot: Slot; proj: Projection }[]; t: number }) {
  const keys: (MetricKey | 'score')[] = ['score', 'fatigue_1_10', 'heart_rate_bpm', 'reaction_ms', 'sleep_hours'];
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="tabular w-full min-w-[560px] text-sm">
        <thead><tr className="text-left text-xs text-ink-3"><th className="py-1 font-medium">Scenario</th>{keys.map((k) => <th key={k} className="font-medium">{k === 'score' ? 'Index' : METRICS[k].short}</th>)}<th className="font-medium">Runs flagged</th></tr></thead>
        <tbody>{results.map(({ slot, proj }) => {
          const d = proj.days[Math.min(t, proj.days.length - 1)];
          return (
            <tr key={slot.key} className="border-t border-line">
              <td className="py-1.5"><span className="inline-flex items-center gap-1.5 text-ink"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: slot.color }} />{slot.key}</span></td>
              {keys.map((k) => { const dec = k === 'score' ? 0 : METRICS[k].decimals; return <td key={k} className="text-ink-2"><span className="text-ink">{fmt(d[k].p50, dec)}</span> <span className="text-xs text-ink-3">{fmt(d[k].p10, dec)}–{fmt(d[k].p90, dec)}</span></td>; })}
              <td className={cx(d.attention_share >= 0.5 ? 'text-attention' : 'text-ink-2')}>{Math.round(d.attention_share * 100)}%</td>
            </tr>
          );
        })}</tbody>
      </table>
      <p className="mt-1 text-xs text-ink-3">Median with 10th–90th percentile of simulated runs. “Runs flagged” is a model statistic, not a probability of a real event.</p>
    </div>
  );
}

/* ───────────────────────── v0.5 additions ───────────────────────── */

const STEPS: { id: string; label: string }[] = [{ id: 'config', label: 'Configure' }, { id: 'request', label: 'Simulator request' }, { id: 'received', label: 'Results received' }, { id: 'play', label: 'Playback' }, { id: 'done', label: 'Finished' }];

/** Lab console: execution pipeline and playback progress. */
function LabConsole({ status, cursor, horizon, hasResult, slots }: { status: string; cursor: number; horizon: number; hasResult: boolean; slots: number }) {
  const at = status === 'requesting' ? 1 : status === 'finished' ? 4 : status === 'playing' || status === 'paused' ? 3 : hasResult ? 2 : 0;
  return (
    <section aria-label="Simulation process" className="always-dark stage mb-4 rounded-2xl border border-line p-3">
      <ol className="grid gap-2 sm:grid-cols-5">
        {STEPS.map((s, i) => (
          <li key={s.id} aria-current={i === at ? 'step' : undefined} className={cx('hud flex items-center gap-2 rounded-lg px-3 py-2 text-xs', i === at ? 'border-cyan text-ink' : i < at ? 'text-good' : 'text-ink-3')}>
            <span className={cx('grid h-5 w-5 shrink-0 place-items-center rounded-full border text-[10px] font-bold', i < at ? 'border-good bg-good/20' : i === at ? 'border-cyan bg-cyan/20' : 'border-line-strong')}>{i < at ? '✓' : i + 1}</span>
            <span className="truncate">{s.label}{i === 0 ? ` · ${slots} scenario${slots === 1 ? '' : 's'}` : ''}</span>
            {i === at && status === 'requesting' && <span className="ml-auto h-2 w-2 rounded-full bg-cyan" style={{ animation: 'aether-pulse 1s infinite' }} aria-hidden />}
          </li>
        ))}
      </ol>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-line" role="progressbar" aria-label="Playback progress" aria-valuemin={0} aria-valuemax={horizon} aria-valuenow={hasResult ? cursor : 0}>
        <div className="h-full rounded-full bg-gradient-to-r from-teal-600 to-cyan transition-[width] duration-300" style={{ width: `${hasResult ? (cursor / Math.max(1, horizon)) * 100 : 0}%` }} />
      </div>
    </section>
  );
}

type Res = { slot: Slot; proj: Projection; single: SimulationResult }[];
const valueOf = (d: Projection['days'][number], metric: ChartKey) => (metric === 'attention_share' ? d.attention_share * 100 : d[metric as MetricKey | 'score'].p50);
const unitOf = (metric: ChartKey) => (metric === 'score' ? '/100' : metric === 'attention_share' ? '%' : METRICS[metric as MetricKey].unit);
const labelOf = (metric: ChartKey) => CHART_OPTS.find((o) => o.value === metric)!.label;

/** Before/after: difference of medians (B − A) per day for the selected metric. */
function DifferenceCard({ results, metric }: { results: Res; metric: ChartKey }) {
  const [a, setA] = useState(results[0].slot.key);
  const [b, setB] = useState(results[1].slot.key);
  const A = results.find((r) => r.slot.key === a) ?? results[0];
  const B = results.find((r) => r.slot.key === b) ?? results[1];
  const pts = A.proj.days.map((d, i) => ({ x: d.day, y: Math.round((valueOf(B.proj.days[i], metric) - valueOf(d, metric)) * 100) / 100 }));
  const end = pts[pts.length - 1]?.y ?? 0;
  return (
    <Card eyebrow="Before / after" title={`Difference in ${labelOf(metric).toLowerCase()}: ${b} − ${a}`} actions={<>
      <Segmented size="sm" label="Reference (before)" value={a} onChange={setA} options={results.map((r) => ({ value: r.slot.key, label: `A=${r.slot.key}` }))} />
      <Segmented size="sm" label="Compared (after)" value={b} onChange={setB} options={results.map((r) => ({ value: r.slot.key, label: `B=${r.slot.key}` }))} />
    </>}>
      <TimeSeriesChart height={180} ariaLabel={`Daily difference of medians, scenario ${b} minus ${a}`} refLines={[{ y: 0, label: 'no difference' }]}
        series={[{ id: 'diff', label: `${b} − ${a}`, color: 'var(--color-magenta)', points: pts }]} xFormat={(x) => `Day ${x}`} yFormat={(y) => `${y > 0 ? '+' : ''}${fmt(y, 1)}`} unit={unitOf(metric)} />
      <p className="mt-2 text-sm text-ink-2">At the end of the horizon, {B.slot.title} differs from {A.slot.title} by <strong className="tabular text-ink">{end > 0 ? '+' : ''}{fmt(end, 1)} {unitOf(metric)}</strong> (median of simulated runs). Differences between medians do not include run-to-run spread.</p>
    </Card>
  );
}

/** Side-by-side small multiples on a shared y-scale. */
function SideBySide({ results, metric, cursorDay }: { results: Res; metric: ChartKey; cursorDay: number }) {
  const isShare = metric === 'attention_share';
  const all = results.flatMap((r) => r.proj.days.flatMap((d) => (isShare ? [d.attention_share * 100] : [d[metric as MetricKey | 'score'].p10, d[metric as MetricKey | 'score'].p90])));
  const dom: [number, number] = metric === 'score' || isShare ? [0, 100] : [Math.min(...all), Math.max(...all)];
  return (
    <Card eyebrow="Side by side" title={`${labelOf(metric)} · one panel per scenario, shared scale`}>
      <div className="grid gap-4 md:grid-cols-3">
        {results.map(({ slot, proj }) => (
          <div key={slot.key} className="rounded-xl border border-line p-2">
            <div className="mb-1 flex items-center gap-2 text-sm"><span className="grid h-5 w-5 place-items-center rounded text-[11px] font-bold text-white" style={{ background: slot.color }}>{slot.key}</span><span className="truncate text-ink">{slot.title}</span></div>
            <TimeSeriesChart height={150} ariaLabel={`${labelOf(metric)} for scenario ${slot.key}`} yDomain={dom} markers={[{ x: cursorDay, label: "" }]}
              bands={isShare ? [] : [{ id: 'b', label: '10–90 %', color: slot.color, points: proj.days.map((d) => ({ x: d.day, lo: d[metric as MetricKey | 'score'].p10, hi: d[metric as MetricKey | 'score'].p90 })) }]}
              series={[{ id: 's', label: 'median', color: slot.color, points: proj.days.map((d) => ({ x: d.day, y: valueOf(d, metric) })) }]}
              xFormat={(x) => `D${x}`} yFormat={(y) => fmt(y, 0)} unit={unitOf(metric)} />
            <div className="mt-1 text-[11px] text-ink-3">{paramSummary(slot.params)}</div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function exportJson(results: Res, meta: { astronautId: string; day: number; horizon: number; runs: number; seed: number }) {
  downloadText(`AETHER_MissionLab_${meta.astronautId}_day${meta.day}.json`, JSON.stringify({ meta: { ...meta, source: 'simulated (Mission Systems simulator)', exported_at: new Date().toISOString() },
    scenarios: results.map(({ slot, proj, single }) => ({ key: slot.key, title: slot.title, params: slot.params, projection: proj, single_day: single })) }, null, 2), 'application/json');
}
function exportCsv(results: Res, day: number) {
  const keys: (MetricKey | 'score')[] = ['score', 'heart_rate_bpm', 'sleep_hours', 'fatigue_1_10', 'reaction_ms', 'activity_minutes'];
  const head = ['scenario', 'title', 'day', ...keys.flatMap((k) => [`${k}_p10`, `${k}_p50`, `${k}_p90`]), 'attention_share'];
  const lines = [head.join(',')];
  for (const { slot, proj } of results) for (const d of proj.days) lines.push([slot.key, JSON.stringify(slot.title), d.day, ...keys.flatMap((k) => [d[k].p10, d[k].p50, d[k].p90]), d.attention_share].join(','));
  downloadText(`AETHER_MissionLab_day${day}.csv`, lines.join('\n'), 'text/csv');
}

function buildLabReport(results: Res, meta: { astronaut: string; day: number; horizon: number; runs: number; seed: number }) {
  const out = [
    '# AETHER · MISSION LAB summary report', '',
    `- Astronaut: ${meta.astronaut}`, `- Start day: ${meta.day} · horizon ${meta.horizon} days · ${meta.runs} runs · seed ${meta.seed}`,
    '- Source: Mission Systems simulator (illustrative model). **Not a validated prediction.**', '',
    '| Scenario | Inputs | Day-' + meta.day + ' PHANTOM (model) | Unassigned tasks | Index at end (p50, p10–p90) | Runs flagged at end |', '|---|---|---|---|---|---|',
    ...results.map(({ slot, proj, single }) => { const e = proj.days[proj.days.length - 1]; return `| ${slot.key} · ${slot.title} | ${paramSummary(slot.params)} | ${single.phantom.status} (${single.phantom.score ?? '—'}) | ${single.crew.unassigned} | ${e.score.p50} (${e.score.p10}–${e.score.p90}) | ${Math.round(e.attention_share * 100)}% |`; }),
    '', '## Assumptions', '', ...results[0].proj.assumptions.map((a) => `- ${a}`), '', `_${results[0].proj.note}_`, '',
  ];
  return out.join('\n');
}
