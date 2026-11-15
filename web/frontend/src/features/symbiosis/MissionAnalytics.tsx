import { useState } from 'react';
import type { ConditionComparison, EngineRun } from '../../api/types';
import { useResource } from '../../lib/useResource';
import { useApp } from '../../state/AppState';
import { Async, Button, Notice, Segmented } from '../../ui';

const ENV = [{ value: 'co2', label: 'CO₂' }, { value: 'temperature', label: 'Temperature' }, { value: 'humidity', label: 'Humidity' }, { value: 'light', label: 'Light' }] as const;
const PHYS = [{ value: 'fatigue', label: 'Fatigue' }, { value: 'cognition', label: 'Cognition' }, { value: 'heart_rate', label: 'Heart rate' }, { value: 'sleep_quality', label: 'Sleep quality' }] as const;
type Env = (typeof ENV)[number]['value']; type Phys = (typeof PHYS)[number]['value'];
const n = (v: number | null | undefined, d = 2) => (v == null ? '—' : v.toFixed(d));

/** relationship() · compare_periods() · compare_conditions() of the Mission Systems engine, exposed in SYMBIOSIS (0.9). */
export function MissionAnalytics({ run }: { run: EngineRun }) {
  const { api } = useApp();
  const [env, setEnv] = useState<Env>('co2');
  const [metric, setMetric] = useState<Phys>('fatigue');
  const [crew, setCrew] = useState(run.crew[0]?.id ?? 1);
  const res = useResource(`sym-an-${run.id}-${env}-${metric}-${crew}`, () => api.engineSymbiosis(run.id, env, metric, crew));
  const [cond, setCond] = useState({ co2: 4000, temperature: 26, night_light: 50 });
  const [cmp, setCmp] = useState<ConditionComparison | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const compare = () => { setErr(null); api.compareConditions({ a: {}, b: cond }).then(setCmp, (e: Error) => setErr(e.message)); };
  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap items-end gap-3">
        <Segmented size="sm" label="Environment signal" value={env} onChange={setEnv} options={[...ENV]} />
        <Segmented size="sm" label="Crew signal" value={metric} onChange={setMetric} options={[...PHYS]} />
        <label className="text-xs text-ink-3">Crew member <select aria-label="Analytics crew member" className="ml-1 rounded border border-line bg-surface px-1 py-0.5 text-ink" value={crew} onChange={(e) => setCrew(Number(e.target.value))}>{run.crew.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
      </div>
      <Async res={res} loadingLabel="Computing associations">{(a) => (
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <h3 className="mb-1 text-xs font-semibold text-ink-3">Lagged association (Pearson r, aligned samples)</h3>
            <table aria-label="Lagged association" className="tabular w-full text-xs"><thead><tr className="text-left text-ink-3"><th>Lag</th><th>r</th><th>Pairs</th></tr></thead>
              <tbody>{a.relationship.map((r) => <tr key={r.lag_minutes} className="border-t border-line"><td className="py-0.5">{r.lag_minutes} min</td><td>{r.pearson_r == null ? r.reason : n(r.pearson_r)}</td><td>{r.pairs}</td></tr>)}</tbody></table>
          </div>
          <div>
            <h3 className="mb-1 text-xs font-semibold text-ink-3">Period comparison (before / after minute {a.split_minute}, {a.split_basis})</h3>
            <table aria-label="Period comparison" className="tabular w-full text-xs"><thead><tr className="text-left text-ink-3"><th>Signal</th><th>Mean A</th><th>Mean B</th><th>Trend B / h</th></tr></thead>
              <tbody>{Object.entries(a.periods).map(([m, p]) => <tr key={m} className="border-t border-line"><td className="py-0.5">{m}</td><td>{n(p.a?.mean)} {p.a?.unit}</td><td>{n(p.b?.mean)} {p.b?.unit}</td><td>{n(p.b?.slope_per_hour, 3)}</td></tr>)}</tbody></table>
          </div>
          <p className="lg:col-span-2 text-xs text-ink-3">{a.note}</p>
        </div>
      )}</Async>
      <div>
        <h3 className="mb-1 text-xs font-semibold text-ink-3">Condition comparison (engine habitat model, nominal A vs B)</h3>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-ink-3">CO₂ B (ppm)<input aria-label="Condition B CO2" type="number" className="ml-1 w-20 rounded border border-line bg-transparent px-1 text-ink" value={cond.co2} onChange={(e) => setCond({ ...cond, co2: Number(e.target.value) })} /></label>
          <label className="text-xs text-ink-3">Temperature B (°C)<input aria-label="Condition B temperature" type="number" className="ml-1 w-16 rounded border border-line bg-transparent px-1 text-ink" value={cond.temperature} onChange={(e) => setCond({ ...cond, temperature: Number(e.target.value) })} /></label>
          <label className="text-xs text-ink-3">Night light B (lux)<input aria-label="Condition B night light" type="number" className="ml-1 w-16 rounded border border-line bg-transparent px-1 text-ink" value={cond.night_light} onChange={(e) => setCond({ ...cond, night_light: Number(e.target.value) })} /></label>
          <Button size="sm" icon="play" onClick={compare}>Compare conditions</Button>
        </div>
        {err && <Notice tone="high" className="mt-2">{err}</Notice>}
        {cmp && <table aria-label="Condition comparison" className="tabular mt-2 w-full max-w-xl text-xs"><thead><tr className="text-left text-ink-3"><th>Outcome</th><th>A</th><th>B</th><th>B − A</th></tr></thead>
          <tbody>{Object.keys(cmp.delta).map((k) => <tr key={k} className="border-t border-line"><td className="py-0.5">{k}</td><td>{n(cmp.a[k], 1)}</td><td>{n(cmp.b[k], 1)}</td><td>{n(cmp.delta[k], 1)}</td></tr>)}</tbody></table>}
        {cmp && <p className="mt-1 text-xs text-ink-2">{cmp.recommendations.join(' ')}</p>}
        <p className="mt-1 text-xs text-ink-3">Outcomes come from the engine’s illustrative coupling coefficients (model assumptions), not from measured dose–response.</p>
      </div>
    </div>
  );
}
