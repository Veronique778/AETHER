import { useEffect, useState } from 'react';
import { CAPABILITIES, type ReferenceBands, type ShipState, type SimulationResult, type ZoneEnvironment, type ZoneId } from '../../api/types';
import { BarRows, ChartFrame, TimeSeriesChart } from '../../charts';
import { CREW_HEX, dayLabel, fmt, hourLabel, initials, METRICS } from '../../lib/format';
import { useRoute } from '../../lib/router';
import { useResource } from '../../lib/useResource';
import { useApp, useAstronaut } from '../../state/AppState';
import { Async, Button, Card, cx, EnvPill, Icon, MissingValue, Notice, PendingBackend, PhantomPill, Segmented, SliderField, SourceBadge, TabPanel, Tabs, useTab, type TabDef } from '../../ui';
import { DeckPlan, heat } from '../shared/DeckPlan';
import { ModuleHeader } from '../shared/ModuleHeader';
import { DEMO_CHANNEL_NOTE, demoCabin } from '../../mocks/demoChannels';
import { useScenarioRun } from '../../state/scenario';
import { EngineEnvChart, EngineRunCard } from '../shared/EngineCards';
import { MissionAnalytics } from './MissionAnalytics';
import { EnvironmentEvents } from './EnvironmentEvents';
import { Tooltip } from '../../ui';
import { ENV_ICON, ENV_TEXT, ShipTwin } from '../shared/ShipTwin';

type EnvKey = 'co2_ppm' | 'temperature_c' | 'humidity_pct' | 'light_lux';
const ENV: Record<EnvKey, { label: string; unit: string; decimals: number; icon: 'wind' | 'thermo' | 'droplet' | 'sun'; scale: [number, number] }> = {
  co2_ppm: { label: 'CO₂', unit: 'ppm', decimals: 0, icon: 'wind', scale: [400, 3000] },
  temperature_c: { label: 'Temperature', unit: '°C', decimals: 1, icon: 'thermo', scale: [16, 30] },
  humidity_pct: { label: 'Humidity', unit: '%', decimals: 0, icon: 'droplet', scale: [20, 80] },
  light_lux: { label: 'Lighting', unit: 'lux', decimals: 0, icon: 'sun', scale: [0, 1000] },
};
const ENV_KEYS = Object.keys(ENV) as EnvKey[];
const ZONES: ZoneId[] = ['command', 'habitat', 'medical', 'exercise', 'systems'];
type SyTab = 'plan' | 'history' | 'scenarios';
const TABS: TabDef<SyTab>[] = [
  { id: 'plan', label: 'Compartment plan', icon: 'ship' },
  { id: 'history', label: 'History & before / after', icon: 'activity' },
  { id: 'scenarios', label: 'Scenarios (model)', icon: 'sliders' },
];

function refBand(k: EnvKey, r: ReferenceBands) {
  if (k === 'temperature_c') return { lo: r.temperature_c.low, hi: r.temperature_c.high, label: 'reference' };
  if (k === 'humidity_pct') return { lo: r.humidity_pct.low, hi: r.humidity_pct.high, label: 'reference' };
  if (k === 'co2_ppm') return { lo: ENV.co2_ppm.scale[0], hi: r.co2_ppm.attention, label: 'reference' };
  return undefined;
}
function outOfRef(k: EnvKey, v: number | null | undefined, r: ReferenceBands): 'attention' | 'high' | null {
  if (v == null) return null;
  if (k === 'co2_ppm') return v >= r.co2_ppm.high ? 'high' : v >= r.co2_ppm.attention ? 'attention' : null;
  if (k === 'temperature_c') return v < r.temperature_c.low || v > r.temperature_c.high ? 'attention' : null;
  if (k === 'humidity_pct') return v < r.humidity_pct.low || v > r.humidity_pct.high ? 'attention' : null;
  return null;
}

/** SYMBIOSIS – spatial view of the spacecraft environment. Selection is the shared mission context. */
export function SymbiosisPage() {
  const { api, day, hour, dataVersion, zoneId, setZoneId } = useApp();
  const { query } = useRoute();
  const qZone = query.get('zone') as ZoneId | null;
  useEffect(() => { if (qZone && ZONES.includes(qZone) && qZone !== zoneId) setZoneId(qZone); }, [qZone]); // eslint-disable-line react-hooks/exhaustive-deps
  const ship = useResource(`ship-${api.mode}-${day}-${hour}-${dataVersion}`, () => api.ship(day, hour));
  const [metric, setMetric] = useState<EnvKey>('co2_ppm');
  const [tab, setTab] = useTab(TABS);
  return (
    <div>
      <ModuleHeader module="/symbiosis" title="Habitat conditions"
        description="Compartment conditions from the environment model (Mission Systems), laid out on the spacecraft plan, with history and what-if scenarios." />
      <Notice tone="info" className="mb-4" title="Analysis and simulation only">
        <span className="inline-flex items-center gap-1"><Icon name="lock" size={14} />AETHER does not control life-support equipment.</span> Scenario controls change model inputs, never hardware set-points. Reference bands are demo values, not flight rules.
      </Notice>
      {ship.data && <ScenarioEnvironment ship={ship.data} />}
      <div className="mb-4"><EngineRunCard eyebrow="Mission Systems engine · habitat model" title="Modelled cabin conditions during the engine run">{(r) => <><EngineEnvChart run={r} metrics={['co2', 'temperature', 'humidity', 'light']} height={150} /><p className="mt-2 text-xs text-ink-3">Deterministic environment model with day/night lighting. Set-points come from MISSION LAB; the derived mean CO₂ and temperature feed the cross-module scenario.</p></>}</EngineRunCard></div>
      <div className="mb-4"><EngineRunCard eyebrow="SYMBIOSIS cabin-event detector · API 1.0" title="Cabin events, sensor faults and crew context">{(r) => <EnvironmentEvents run={r} />}</EngineRunCard></div>
      <div className="mb-4"><EngineRunCard eyebrow="Mission Systems analytics" title="Environment ↔ crew: association, periods, conditions">{(r) => <MissionAnalytics run={r} />}</EngineRunCard></div>
      <Tabs label="SYMBIOSIS sections" tabs={TABS} value={tab} onChange={setTab} />
      <TabPanel label={TABS.find((t) => t.id === tab)!.label}>
        {tab === 'plan' && <Async res={ship} loadingLabel="Loading compartments">{(s) => <PlanView ship={s} metric={metric} setMetric={setMetric} />}</Async>}
        {tab === 'history' && (
          <Async res={ship}>{(s) => (
            <div className="space-y-5">
              <Card eyebrow="History" title={`${ENV[metric].label} · ${s.zones.find((z) => z.id === zoneId)?.name}`} actions={<>
                <select aria-label="Compartment for history" className="field !w-auto !py-1" value={zoneId} onChange={(e) => setZoneId(e.target.value as ZoneId)}>{s.zones.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}</select>
                <Segmented size="sm" label="Parameter" value={metric} onChange={setMetric} options={ENV_KEYS.map((k) => ({ value: k, label: ENV[k].label }))} />
              </>}>
                <ZoneHistoryChart zoneId={zoneId} metric={metric} reference={s.reference} />
              </Card>
              <BeforeAfter ship={s} metric={metric} setMetric={setMetric} />
              <ComparisonTable zones={s.zones.map((z) => ({ id: z.id, name: z.name, env: z.environment }))} selected={zoneId} />
            </div>
          )}</Async>
        )}
        {tab === 'scenarios' && (
          <div className="space-y-5">
            <ScenarioComparison reference={ship.data?.reference} />
            <CrewLink zoneId={zoneId} />
          </div>
        )}
      </TabPanel>
    </div>
  );
}

/* ───────────────────────── Plan view ───────────────────────── */

function PlanView({ ship, metric, setMetric }: { ship: ShipState; metric: EnvKey; setMetric: (k: EnvKey) => void }) {
  const { zoneId, setZoneId, day, hour, openWith } = useApp();
  const [view, setView] = useState<'plan' | '3d'>('plan');
  const zone = ship.zones.find((z) => z.id === zoneId)!;
  const values = ship.zones.map((z) => z.environment[metric]).filter((v): v is number => v != null);
  const range: [number, number] = [Math.min(...values), Math.max(...values)];
  const crew = ship.crew.filter((c) => c.zone === zoneId);
  return (
    <div className="always-dark stage rounded-2xl border border-line p-3">
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_380px]">
        <section aria-label="Spacecraft environment plan" className="hud flex min-w-0 flex-col rounded-xl p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2"><span className="mono-label text-good">{dayLabel(day)} · {hourLabel(hour)}</span><SourceBadge source="estimated" /></div>
            <div className="flex flex-wrap items-center gap-2">
              <div role="radiogroup" aria-label="Parameter shown on plan" className="flex flex-wrap gap-1">
                {ENV_KEYS.map((k) => (
                  <button key={k} type="button" role="radio" aria-checked={metric === k} onClick={() => setMetric(k)}
                    className={cx('interactive flex items-center gap-1 rounded-md border px-2 py-1 text-xs', metric === k ? 'border-good bg-good/15 text-ink' : 'border-line text-ink-3 hover:text-ink')}>
                    <Icon name={ENV[k].icon} size={13} />{ENV[k].label}
                  </button>
                ))}
              </div>
              <Segmented size="sm" label="View" value={view} onChange={setView} options={[{ value: 'plan', label: 'Plan 2D', icon: 'layers' }, { value: '3d', label: 'Model 3D', icon: 'ship' }]} />
            </div>
          </div>
          {view === 'plan' ? (
            <>
              <DeckPlan title={`Deck plan coloured by ${ENV[metric].label}`} mode="heat" range={range} selectedZone={zoneId} onZone={setZoneId} crew={ship.crew}
                zones={ship.zones.map((z) => ({ id: z.id, name: z.name, value: z.environment[metric], status: z.environment.status, label: `${fmt(z.environment[metric], ENV[metric].decimals)} ${ENV[metric].unit}` }))} />
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-ink-3">
                <span className="flex items-center gap-2">
                  <span className="tabular">{fmt(range[0], ENV[metric].decimals)}</span>
                  <span className="h-2 w-28 rounded-full" style={{ background: `linear-gradient(90deg, ${heat(0)}, ${heat(1)})` }} aria-hidden="true" />
                  <span className="tabular">{fmt(range[1], ENV[metric].decimals)} {ENV[metric].unit}</span>
                  <span>· darker = higher (relative across compartments now)</span>
                </span>
                <span>Status outline: green nominal · amber attention · red high</span>
              </div>
            </>
          ) : (
            <ShipTwin ship={ship} zoneId={zoneId} onZone={setZoneId} showCrew={false} colourByStatus focusSelected height={380} className="!bg-transparent" />
          )}
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
            {ship.zones.map((z) => (
              <button key={z.id} type="button" aria-pressed={z.id === zoneId} onClick={() => setZoneId(z.id)}
                className={cx('interactive rounded-lg border px-2.5 py-2 text-left', z.id === zoneId ? 'border-good bg-good/10' : 'border-line bg-raised/40 hover:border-line-strong')}>
                <div className="truncate text-xs font-medium text-ink">{z.name}</div>
                <div className={cx('tabular mt-0.5 flex items-center gap-1 text-sm font-semibold', ENV_TEXT[z.environment.status])}>
                  <Icon name={ENV_ICON[z.environment.status]} size={12} />{fmt(z.environment[metric], ENV[metric].decimals)}<span className="text-[10px] font-normal text-ink-3">{ENV[metric].unit}</span>
                </div>
              </button>
            ))}
          </div>
        </section>

        <section aria-label={`Selected compartment: ${zone.name}`} className="hud flex flex-col rounded-xl p-4">
          <div className="flex items-start justify-between gap-2">
            <div><div className="mono-label text-ink-3">Selected compartment</div><h2 className="text-lg font-semibold text-ink">{zone.name}</h2></div>
            <EnvPill status={zone.environment.status} />
          </div>
          <p className="mt-1 text-xs text-ink-3">{zone.environment.occupants} crew scheduled · volume {zone.volume_m3} m³ · {zone.environment.source}</p>
          <div className="mt-3 space-y-3">
            {ENV_KEYS.map((k) => <Gauge key={k} k={k} value={zone.environment[k]} reference={ship.reference} active={metric === k} onClick={() => setMetric(k)} />)}
            <ExtraCabin zone={zoneId} />
          </div>
          <div className="mt-4">
            <div className="mono-label mb-1 text-ink-3">Crew here now</div>
            {crew.length ? (
              <ul className="flex flex-wrap gap-1.5">
                {crew.map((c) => (
                  <li key={c.id}><button type="button" onClick={() => openWith('/body', { astronautId: c.id })} aria-label={`Open BODY twin of ${c.name}`}
                    className="interactive flex items-center gap-1.5 rounded-full border border-line py-0.5 pl-0.5 pr-2.5 text-xs text-ink-2 hover:border-line-strong">
                    <span className="grid h-6 w-6 place-items-center rounded-full text-[9px] font-bold text-white" style={{ background: CREW_HEX[c.id] }}>{initials(c.name)}</span>{c.name.split(' ')[0]} · {c.activity}
                  </button></li>
                ))}
              </ul>
            ) : <p className="text-sm text-ink-3">Nobody scheduled here at {hourLabel(hour)}.</p>}
          </div>
          <div className="mt-auto flex flex-wrap gap-2 border-t border-line pt-3">
            <Button size="sm" icon="flask" onClick={() => openWith('/mission-lab', {})}>Model a change</Button>
            <Button size="sm" variant="ghost" icon="ship" onClick={() => openWith('/', { zoneId })}>Show on spacecraft</Button>
          </div>
        </section>
      </div>
      <div className="mt-3 grid gap-3 xl:grid-cols-2">
        <div className="hud rounded-xl p-4"><DailyProfile zoneId={zoneId} metric={metric} /></div>
        <div className="hud rounded-xl p-4"><CrewLinkBody zoneId={zoneId} compact /></div>
      </div>
    </div>
  );
}

/** O₂ and pressure: demo channels in Demo Mode, "not provided by API" in Live Mode. */
function ExtraCabin({ zone }: { zone: ZoneId }) {
  const { api, day, hour } = useApp();
  const v = demoCabin(zone, day, hour);
  const demo = api.mode === 'demo';
  return (
    <div className="rounded-lg border border-dashed border-line-strong p-2.5">
      <div className="mb-1 flex items-center justify-between">
        <span className="mono-label">Atmosphere</span>
        {demo ? <Tooltip text={DEMO_CHANNEL_NOTE}>{(id) => <span aria-describedby={id} tabIndex={0} className="rounded border border-dashed border-attention/70 px-1.5 text-[10px] uppercase tracking-wide text-attention">demo channel</span>}</Tooltip>
          : <span className="text-[10px] text-ink-3">not provided by API</span>}
      </div>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <span className="flex items-center gap-1.5 text-ink-2"><Icon name="wind" size={14} className="text-aqua" />O₂ <span className="tabular ml-auto font-semibold text-ink">{demo ? `${v.o2_pct} %` : '—'}</span></span>
        <span className="flex items-center gap-1.5 text-ink-2"><Icon name="gauge" size={14} className="text-aqua" />Pressure <span className="tabular ml-auto font-semibold text-ink">{demo ? `${v.pressure_kpa} kPa` : '—'}</span></span>
      </div>
    </div>
  );
}

/** Applied MISSION LAB scenario: its cabin inputs against the selected compartment, and the modelled crew effect. */
function ScenarioEnvironment({ ship }: { ship: ShipState }) {
  const { scenario, zoneId, astronauts, astronautId } = useApp();
  const run = useScenarioRun();
  if (!scenario) return null;
  const z = ship.zones.find((x) => x.id === zoneId)!;
  const p = scenario.params;
  const co2s = outOfRef('co2_ppm', p.co2_ppm, ship.reference);
  const ts = outOfRef('temperature_c', p.temperature_c, ship.reference);
  return (
    <section aria-label="Scenario environment" className="card mb-4 border-violet/40 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div><div className="mono-label text-violet">Scenario (model input) · {scenario.title}</div><h2 className="text-base font-semibold text-ink">Cabin conditions under the scenario vs {z.name} now</h2></div>
        <SourceBadge source="simulated" />
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {[{ k: 'co2_ppm' as EnvKey, actual: z.environment.co2_ppm, model: p.co2_ppm, st: co2s }, { k: 'temperature_c' as EnvKey, actual: z.environment.temperature_c, model: p.temperature_c, st: ts }].map((r) => (
          <div key={r.k} className="rounded-xl border border-line bg-raised/40 p-3">
            <div className="flex items-center gap-1.5 text-xs text-ink-2"><Icon name={ENV[r.k].icon} size={14} />{ENV[r.k].label}</div>
            <div className="mt-1 flex items-baseline gap-2"><span className={cx('tabular text-xl font-semibold', r.st ? ENV_TEXT[r.st] : 'text-violet')}>{fmt(r.model, ENV[r.k].decimals)}</span><span className="text-xs text-ink-3">{ENV[r.k].unit} scenario</span></div>
            <div className="tabular text-xs text-ink-3">actual {fmt(r.actual, ENV[r.k].decimals)} {ENV[r.k].unit} · Δ {r.model - r.actual > 0 ? '+' : ''}{fmt(r.model - r.actual, ENV[r.k].decimals)}{r.st ? ` · ${r.st} vs demo reference` : ' · within demo reference'}</div>
          </div>
        ))}
        <div className="rounded-xl border border-line bg-raised/40 p-3">
          <div className="text-xs text-ink-2">Modelled crew effect · {astronauts.find((a) => a.id === astronautId)?.name}</div>
          <Async res={run}>{(r) => (
            <div className="mt-1 space-y-1 text-sm">
              <div className="flex items-center gap-2"><PhantomPill status={r.phantom.status} /><span className="tabular text-ink-2">index {r.phantom.score ?? '—'}</span></div>
              <div className="tabular text-xs text-ink-3">fatigue {fmt(r.metrics.fatigue_1_10, 1)}/10 · reaction {fmt(r.metrics.reaction_ms, 0)} ms</div>
            </div>
          )}</Async>
        </div>
      </div>
      <p className="mt-2 text-xs text-ink-3">Rules used by the simulator: in the single-day model CO₂ above 850 ppm raises modelled resting heart rate (+1.8 bpm per 600 ppm) and temperature has no coefficient; in the multi-day projection CO₂ and temperature above 24 °C form an environment index that shifts heart rate, fatigue and reaction time. Illustrative coefficients, not validated effects. Actual compartment data are unchanged.</p>
    </section>
  );
}

/** Linear gauge with the demo reference band shaded; text repeats the status. */
function Gauge({ k, value, reference, active, onClick }: { k: EnvKey; value: number | null; reference: ReferenceBands; active: boolean; onClick: () => void }) {
  const info = ENV[k];
  const [lo, hi] = [info.scale[0], Math.max(info.scale[1], (value ?? 0) * 1.1)];
  const pct = (v: number) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
  const band = refBand(k, reference);
  const st = outOfRef(k, value, reference);
  return (
    <button type="button" onClick={onClick} aria-pressed={active} className={cx('interactive block w-full rounded-lg border p-2.5 text-left', active ? 'border-good bg-good/10' : 'border-line bg-raised/40 hover:border-line-strong')}>
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-xs text-ink-2"><Icon name={info.icon} size={14} className={st ? ENV_TEXT[st] : 'text-good'} />{info.label}</span>
        <span className={cx('tabular text-base font-semibold', st ? ENV_TEXT[st] : 'text-ink')}>{value == null ? <MissingValue /> : fmt(value, info.decimals)}<span className="ml-0.5 text-xs font-normal text-ink-3">{info.unit}</span></span>
      </div>
      <div className="relative mt-2 h-2 rounded-full bg-line" aria-hidden="true">
        {band && <div className="absolute inset-y-0 rounded-full bg-good/30" style={{ left: `${pct(band.lo)}%`, width: `${pct(band.hi) - pct(band.lo)}%` }} />}
        {value != null && <div className={cx('absolute top-1/2 h-4 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full', st === 'high' ? 'bg-high' : st ? 'bg-attention' : 'bg-ink')} style={{ left: `${pct(value)}%` }} />}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-ink-3"><span>{fmt(lo, info.decimals)}</span><span>{band ? `reference ${fmt(band.lo, info.decimals)}–${fmt(band.hi, info.decimals)}` : 'no reference band'}{st ? ` · ${st}` : ''}</span><span>{fmt(hi, info.decimals)}</span></div>
    </button>
  );
}

/* ───────────────────────── Before / after ───────────────────────── */

function BeforeAfter({ ship, metric, setMetric }: { ship: ShipState; metric: EnvKey; setMetric: (k: EnvKey) => void }) {
  const { api, day, zoneId, setZoneId, dataVersion } = useApp();
  const all = useResource(`zh-all-${api.mode}-${day}-${dataVersion}`, () => Promise.all(ZONES.map((z) => api.zoneHistory(z, 1, day))));
  const [a, setA] = useState(Math.max(1, day - 26));
  const [b, setB] = useState(day);
  const A = Math.min(a, day), B = Math.min(b, day);
  return (
    <Card eyebrow="Before / after" title={`${ENV[metric].label}: ${dayLabel(A)} vs ${dayLabel(B)}`} actions={<Segmented size="sm" label="Parameter" value={metric} onChange={setMetric} options={ENV_KEYS.map((k) => ({ value: k, label: ENV[k].label }))} />}>
      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        <SliderField label="Before (day A)" value={A} min={1} max={day} onChange={setA} format={(v) => dayLabel(v)} />
        <SliderField label="After (day B)" value={B} min={1} max={day} onChange={setB} format={(v) => dayLabel(v)} />
      </div>
      <Async res={all}>{(hs) => {
        const at = (z: ZoneId, d: number) => hs.find((h) => h.zone === z)?.points.find((p) => p.day === d);
        const mk = (d: number) => ship.zones.map((z) => { const e = at(z.id, d); return { id: z.id, name: z.name, value: e?.[metric] ?? null, status: e?.status, label: `${fmt(e?.[metric], ENV[metric].decimals)} ${ENV[metric].unit}` }; });
        const za = mk(A), zb = mk(B);
        const vals = [...za, ...zb].map((z) => z.value).filter((v): v is number => v != null);
        const range: [number, number] = [Math.min(...vals), Math.max(...vals)];
        return (
          <div className="space-y-4">
            <div className="always-dark grid gap-3 rounded-xl bg-space p-3 lg:grid-cols-2">
              <div><div className="mono-label mb-1 text-ink-3">A · {dayLabel(A)}</div><DeckPlan title={`Plan on ${dayLabel(A)}`} mode="heat" range={range} zones={za} selectedZone={zoneId} onZone={setZoneId} compact /></div>
              <div><div className="mono-label mb-1 text-ink-3">B · {dayLabel(B)}</div><DeckPlan title={`Plan on ${dayLabel(B)}`} mode="heat" range={range} zones={zb} selectedZone={zoneId} onZone={setZoneId} compact /></div>
            </div>
            <ul className="space-y-2" aria-label="Change per compartment">
              {ship.zones.map((z, i) => {
                const va = za[i].value, vb = zb[i].value;
                const d = va != null && vb != null ? vb - va : null;
                const [lo, hi] = [range[0] - (range[1] - range[0]) * 0.05, range[1] + (range[1] - range[0]) * 0.05];
                const p = (v: number) => ((v - lo) / (hi - lo || 1)) * 100;
                return (
                  <li key={z.id} className={cx('grid grid-cols-[130px_minmax(0,1fr)_90px] items-center gap-3 text-sm', z.id === zoneId && 'font-medium')}>
                    <span className="truncate text-ink-2">{z.name}</span>
                    <span className="relative h-5" aria-hidden="true">
                      <span className="absolute inset-x-0 top-1/2 h-px bg-line" />
                      {va != null && vb != null && <span className="absolute top-1/2 h-1 -translate-y-1/2 rounded bg-line-strong" style={{ left: `${Math.min(p(va), p(vb))}%`, width: `${Math.abs(p(vb) - p(va))}%` }} />}
                      {va != null && <span className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-ink-2 bg-surface" style={{ left: `${p(va)}%` }} />}
                      {vb != null && <span className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-good" style={{ left: `${p(vb)}%` }} />}
                    </span>
                    <span className={cx('tabular text-right', d == null ? 'text-ink-3' : d > 0 ? 'text-ink' : 'text-ink-2')}>{d == null ? '—' : `${d > 0 ? '+' : ''}${fmt(d, ENV[metric].decimals)} ${ENV[metric].unit}`}</span>
                  </li>
                );
              })}
            </ul>
            <p className="flex items-center gap-3 text-xs text-ink-3"><span className="flex items-center gap-1"><span className="h-3 w-3 rounded-full border-2 border-ink-2" />A</span><span className="flex items-center gap-1"><span className="h-3 w-3 rounded-full bg-good" />B</span>Daily estimates at the model’s reference hour; colour scale shared by both plans.</p>
          </div>
        );
      }}</Async>
    </Card>
  );
}

function ZoneHistoryChart({ zoneId, metric, reference }: { zoneId: ZoneId; metric: EnvKey; reference: ReferenceBands }) {
  const { api, day } = useApp();
  const hist = useResource(`zh-${api.mode}-${zoneId}-1-${day}`, () => api.zoneHistory(zoneId, 1, day));
  const info = ENV[metric];
  return (
    <Async res={hist}>{(h) => (
      <ChartFrame caption={`${info.label} history`} table={{ columns: ['Day', `${info.label} (${info.unit})`, 'Status'], rows: h.points.map((p) => [p.day, fmt(p[metric], info.decimals), p.status]) }}>
        <TimeSeriesChart ariaLabel={`${info.label} by mission day`} height={260} series={[{ id: metric, label: info.label, color: 'var(--color-teal-300)', points: h.points.map((p) => ({ x: p.day, y: p[metric] })) }]}
          refBand={refBand(metric, reference)} refLines={metric === 'co2_ppm' ? [{ y: reference.co2_ppm.attention, label: `reference ${reference.co2_ppm.attention} ppm` }] : []}
          xFormat={(x) => `Day ${x}`} yFormat={(y) => fmt(y, info.decimals)} unit={info.unit} />
      </ChartFrame>
    )}</Async>
  );
}

function DailyProfile({ zoneId, metric }: { zoneId: ZoneId; metric: EnvKey }) {
  const { api, day, hour, setHour } = useApp();
  const profile = useResource(`prof-${api.mode}-${day}`, () => Promise.all(Array.from({ length: 24 }, (_, h) => api.ship(day, h))));
  const info = ENV[metric];
  return (
    <div>
      <div className="mb-1 flex items-center justify-between"><span className="mono-label text-ink-3">24-hour profile · {info.label}</span><SourceBadge source="estimated" /></div>
      <Async res={profile}>{(all) => {
        const pts: ZoneEnvironment[] = all.map((s) => s.zones.find((z) => z.id === zoneId)!.environment);
        return <TimeSeriesChart ariaLabel={`${info.label} by hour`} height={170} cursorX={Math.floor(hour)}
          series={[{ id: 'p', label: info.label, color: 'var(--color-good)', points: pts.map((p) => ({ x: p.hour, y: p[metric] })) }]}
          xFormat={(x) => hourLabel(x)} yFormat={(y) => fmt(y, info.decimals)} unit={info.unit} />;
      }}</Async>
      <div className="mt-2 flex items-center justify-between text-xs text-ink-3"><span>Cursor = mission time {hourLabel(hour)}</span>
        <span className="flex gap-1">{[0, 6, 12, 18].map((h) => <button key={h} type="button" onClick={() => setHour(h)} className="interactive tabular min-h-7 rounded border border-line px-1.5 py-1 hover:border-line-strong hover:text-ink">{hourLabel(h)}</button>)}</span>
      </div>
    </div>
  );
}

function ComparisonTable({ zones, selected }: { zones: { id: ZoneId; name: string; env: ZoneEnvironment }[]; selected: ZoneId }) {
  return (
    <Card eyebrow="Compare" title="All compartments now">
      <div className="overflow-x-auto">
        <table className="tabular w-full min-w-[620px] text-sm">
          <caption className="sr-only">Current conditions in every compartment</caption>
          <thead><tr className="text-left text-xs text-ink-3"><th className="py-1.5 font-medium">Compartment</th>{(Object.keys(ENV) as EnvKey[]).map((k) => <th key={k} className="font-medium">{ENV[k].label} ({ENV[k].unit})</th>)}<th className="font-medium">Crew</th><th className="font-medium">Status</th></tr></thead>
          <tbody>{zones.map((z) => (
            <tr key={z.id} className={cx('border-t border-line', z.id === selected && 'bg-teal-600/10')}>
              <th scope="row" className="py-2 text-left font-medium text-ink">{z.name}</th>
              {(Object.keys(ENV) as EnvKey[]).map((k) => <td key={k} className="text-ink-2">{z.env[k] == null ? <MissingValue /> : fmt(z.env[k], ENV[k].decimals)}</td>)}
              <td className="text-ink-2">{z.env.occupants}</td>
              <td><EnvPill status={z.env.status} /></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </Card>
  );
}

type Cond = { key: 'A' | 'B' | 'C'; name: string; co2: number; temp: number };
const PRESETS: Omit<Cond, 'key'>[] = [
  { name: 'Reference cabin', co2: 850, temp: 22 },
  { name: 'Day-67 cabin', co2: 1450, temp: 25 },
  { name: 'Scrubber degraded (model)', co2: 2400, temp: 24 },
  { name: 'Warm cabin', co2: 1000, temp: 28 },
];
const COLORS = { A: 'var(--color-series-1)', B: 'var(--color-series-2)', C: 'var(--color-series-3)' };

/** Compare up to three cabin condition sets; results come from POST /api/mission-lab/run. */
function ScenarioComparison({ reference }: { reference?: ReferenceBands }) {
  const { api, astronautId, day } = useApp();
  const astronaut = useAstronaut();
  const [conds, setConds] = useState<Cond[]>([{ key: 'A', ...PRESETS[0] }, { key: 'B', ...PRESETS[1] }]);
  const [active, setActive] = useState<Cond['key']>('B');
  const [results, setResults] = useState<{ cond: Cond; r: SimulationResult }[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cur = conds.find((c) => c.key === active) ?? conds[0];
  const update = (patch: Partial<Cond>) => { setConds(conds.map((c) => (c.key === cur.key ? { ...c, ...patch } : c))); setResults(null); };
  const run = async () => {
    setBusy(true); setError(null);
    try {
      const out = await Promise.all(conds.map(async (c) => ({ cond: c, r: await api.simulate({ astronaut_id: astronautId, day, sleep_delta: 0, workload: 50, crew_available: 4, co2_ppm: c.co2, temperature_c: c.temp }) })));
      setResults(out);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Card eyebrow="What-if (model only)" title="Compare cabin conditions" actions={<SourceBadge source="simulated" />}>
      <div className="grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <Segmented label="Condition set" value={active} onChange={setActive} options={conds.map((c) => ({ value: c.key, label: `Set ${c.key}` }))} />
            {conds.length < 3 && <Button size="sm" icon="plus" onClick={() => { const key = (['A', 'B', 'C'] as const).find((k) => !conds.some((c) => c.key === k))!; setConds([...conds, { key, ...PRESETS[2] }]); setActive(key); setResults(null); }}>Add set</Button>}
            {conds.length > 1 && <Button size="sm" variant="ghost" icon="x" onClick={() => { const rest = conds.filter((c) => c.key !== cur.key); setConds(rest); setActive(rest[0].key); setResults(null); }}>Remove {cur.key}</Button>}
          </div>
          <div>
            <div className="eyebrow mb-1.5">Scenario preset for set {cur.key}</div>
            <div className="flex flex-wrap gap-1.5">{PRESETS.map((p) => <Button key={p.name} size="sm" variant={cur.name === p.name ? 'primary' : 'secondary'} onClick={() => update(p)}>{p.name}</Button>)}</div>
          </div>
          <SliderField label="CO₂" value={cur.co2} min={400} max={3000} step={50} unit=" ppm" onChange={(v) => update({ co2: v, name: 'Custom' })} />
          <SliderField label="Temperature" value={cur.temp} min={16} max={30} step={0.5} unit=" °C" format={(v) => v.toFixed(1)} onChange={(v) => update({ temp: v, name: 'Custom' })} />
          {reference && <ConditionMap conds={conds} active={cur.key} onSelect={setActive} reference={reference} />}
          <Button variant="primary" icon="play" onClick={run} disabled={busy}>{busy ? 'Requesting model…' : `Run for ${astronaut?.name ?? astronautId}`}</Button>
          {error && <Notice tone="high">{error}</Notice>}
        </div>
        <div className="min-w-0">
          {!results ? (
            <div className="flex h-full min-h-40 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-line-strong p-6 text-center text-sm text-ink-3"><Icon name="sliders" size={22} />Configure up to three condition sets and run them to compare the model’s response.</div>
          ) : (
            <div className="space-y-4">
              <h3 className="text-sm font-medium text-ink">Modelled PHANTOM index · day {day}</h3>
              <BarRows max={100} unit="/100" format={(v) => String(Math.round(v))} rows={results.map(({ cond, r }) => ({ label: <span className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: COLORS[cond.key] }} />Set {cond.key} · {cond.name}</span>, value: r.phantom.score ?? 0, color: COLORS[cond.key], note: r.phantom.status }))} />
              <table className="tabular w-full text-sm">
                <caption className="sr-only">Model output per condition set</caption>
                <thead><tr className="text-left text-xs text-ink-3"><th className="py-1 font-medium">Set</th><th className="font-medium">CO₂ / °C</th><th className="font-medium">Heart rate</th><th className="font-medium">Fatigue</th><th className="font-medium">Reaction</th><th className="font-medium">PHANTOM</th></tr></thead>
                <tbody>{results.map(({ cond, r }) => (
                  <tr key={cond.key} className="border-t border-line">
                    <td className="py-1.5 text-ink">{cond.key}</td><td className="text-ink-2">{cond.co2} / {cond.temp}</td>
                    <td className="text-ink-2">{fmt(r.metrics.heart_rate_bpm, 1)} bpm</td><td className="text-ink-2">{fmt(r.metrics.fatigue_1_10, 1)}</td><td className="text-ink-2">{fmt(r.metrics.reaction_ms, 0)} ms</td>
                    <td><PhantomPill status={r.phantom.status} /></td>
                  </tr>
                ))}</tbody>
              </table>
              <p className="text-xs text-ink-3">{results[0].r.assumptions} In the current model temperature is recorded but has no coefficient for the single-day run.</p>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

function CrewLink({ zoneId }: { zoneId: ZoneId }) {
  return <Card eyebrow="Environment ↔ crew" title="Possible association with crew fatigue"><CrewLinkBody zoneId={zoneId} /></Card>;
}

function CrewLinkBody({ zoneId, compact }: { zoneId: ZoneId; compact?: boolean }) {
  const { api, day, astronauts, hasCapability, dataVersion, openWith } = useApp();
  const enabled = hasCapability(CAPABILITIES.envAssociation);
  const res = useResource(enabled ? `envlink-${api.mode}-${day}-${zoneId}-${dataVersion}` : null, () => api.environmentAssociation(day, zoneId));
  return (
    <div>
      {compact && <div className="mb-2 flex items-center justify-between"><span className="mono-label text-ink-3">Environment ↔ crew link</span>{enabled && <SourceBadge source={res.data?.source ?? 'simulated'} />}</div>}
      {!enabled ? <PendingBackend contract="GET /api/symbiosis/crew-association" owner="Mission Systems / Human Systems" /> : (
        <Async res={res}>{(d) => (
          <>
            <ul className="space-y-2">
              {d.rows.map((r) => (
                <li key={r.astronaut_id} className="grid grid-cols-[minmax(0,1fr)_120px_auto] items-center gap-3 text-sm">
                  <button type="button" onClick={() => openWith('/phantom?tab=relationships', { astronautId: r.astronaut_id })} className="interactive flex min-h-7 items-center gap-2 truncate text-left text-ink hover:text-violet">
                    <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: CREW_HEX[r.astronaut_id] }} />{astronauts.find((a) => a.id === r.astronaut_id)?.name}
                  </button>
                  <span className="relative h-2 rounded-full bg-line" aria-hidden="true">
                    <span className="absolute inset-y-0 left-1/2 w-px bg-line-strong" />
                    {r.rho != null && <span className="absolute inset-y-0 rounded-full bg-violet" style={{ left: `${r.rho < 0 ? 50 + r.rho * 50 : 50}%`, width: `${Math.abs(r.rho) * 50}%` }} />}
                  </span>
                  <span className="tabular text-right text-ink-2">{r.rho == null ? <MissingValue label="Too few days" /> : <>ρ {r.rho.toFixed(2)}</>} <span className="text-ink-3">n={r.n}</span></span>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-ink-3">{d.method} between compartment CO₂ and {METRICS[d.outcome_metric].label.toLowerCase()}. {d.note} Association is not causation.</p>
          </>
        )}</Async>
      )}
    </div>
  );
}

/** Scenario sets plotted on the CO₂ × temperature plane with the demo reference region. Points select a set. */
function ConditionMap({ conds, active, onSelect, reference }: { conds: Cond[]; active: Cond['key']; onSelect: (k: Cond['key']) => void; reference: ReferenceBands }) {
  const W = 340, H = 200, M = { l: 40, r: 10, t: 10, b: 30 };
  const sx = (v: number) => M.l + ((v - 400) / 2600) * (W - M.l - M.r);
  const sy = (v: number) => M.t + (1 - (v - 16) / 14) * (H - M.t - M.b);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded-lg border border-line bg-canvas" role="group" aria-label="Condition sets on a CO₂ versus temperature map, with the demo reference region">
      <rect x={sx(400)} y={sy(reference.temperature_c.high)} width={sx(reference.co2_ppm.attention) - sx(400)} height={sy(reference.temperature_c.low) - sy(reference.temperature_c.high)} fill="var(--color-good)" opacity={0.12} stroke="var(--color-good)" strokeOpacity={0.5} strokeDasharray="4 3" />
      <text x={sx(420)} y={sy(reference.temperature_c.high) - 4} fontSize="10" fill="var(--color-ink-3)">reference region</text>
      {[1000, 2000, 3000].map((v) => <text key={v} x={sx(v)} y={H - 12} textAnchor="middle" fontSize="10" fill="var(--color-ink-3)">{v}</text>)}
      {[18, 22, 26, 30].map((v) => <text key={v} x={M.l - 6} y={sy(v) + 3} textAnchor="end" fontSize="10" fill="var(--color-ink-3)">{v}°</text>)}
      <text x={(W + M.l) / 2} y={H - 1} textAnchor="middle" fontSize="10" fill="var(--color-ink-3)">CO₂ ppm</text>
      {conds.map((c) => (
        <g key={c.key} role="button" tabIndex={0} aria-pressed={c.key === active} aria-label={`Set ${c.key}: ${c.co2} ppm, ${c.temp} °C`} onClick={() => onSelect(c.key)}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(c.key); } }} className="cursor-pointer outline-none [&:focus-visible>circle]:stroke-[var(--color-cyan)]">
          <circle cx={sx(c.co2)} cy={sy(c.temp)} r={c.key === active ? 13 : 10} fill={COLORS[c.key]} stroke={c.key === active ? 'var(--color-ink)' : 'var(--color-surface)'} strokeWidth={2.5} />
          <text x={sx(c.co2)} y={sy(c.temp) + 4} textAnchor="middle" fontSize="11" fontWeight="700" fill="#fff">{c.key}</text>
        </g>
      ))}
    </svg>
  );
}
