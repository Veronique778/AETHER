/**
 * MISSION LAB → "Mission Systems engine" tab.
 * Front end for the research engine delivered as AETHER_Mission_Systems_2 (web/backend/mission_systems):
 * 11 scenario templates, minute-resolution synthetic crew & cabin series, MILP crew scheduling, time controls
 * and PHANTOM research evaluation. "Apply to mission" pushes the run to every module (AppState.engineRun) and
 * maps it onto the cross-module scenario parameters (AppState.scenario).
 */
import { useEffect, useRef, useState } from 'react';
import type { EngineComparison, EngineMetric, EngineRun, EngineRunRequest, EngineState, PlanProfile } from '../../api/types';
import { CAPABILITIES } from '../../api/types';
import { downloadText } from '../../lib/format';
import { navigate } from '../../lib/router';
import { useResource } from '../../lib/useResource';
import { useApp } from '../../state/AppState';
import { Async, Button, Card, cx, Icon, Notice, Pill, Segmented, SliderField, SourceBadge, useToast } from '../../ui';
import { clock, ENGINE_METRICS, EngineCrewChart, EngineDetectorTable, EngineEnvChart, EngineEvaluation, EngineSchedule, PhantomRegimeNote } from '../shared/EngineCards';

const DEFAULTS: Required<Omit<EngineRunRequest, 'template' | 'phantom'>> = {
  seed: 67, duration_minutes: 1440, sample_minutes: 30, sleep_hours: 8, extra_rest_hours: 0, workload_hours: 0,
  intensity: 1, noise: 0.2, co2_ppm: 800, temperature_c: 22, humidity_pct: 45, light_lux: 500, plan_profile: 'standard',
};
const PROFILES: { value: PlanProfile; label: string }[] = [
  { value: 'standard', label: 'Standard day' }, { value: 'high_workload', label: 'High workload' },
  { value: 'reduced_availability', label: 'Reduced availability' }, { value: 'extended_rest', label: 'Extended rest' },
];
const SPEEDS = [{ value: '60', label: '1 min/s' }, { value: '600', label: '10 min/s' }, { value: '3600', label: '1 h/s' }] as const;

export function EnginePanel() {
  const { api, mode, hasCapability, engineRun, setEngineRun, applyScenario, connection, scenario } = useApp();
  const toast = useToast();
  const enabled = hasCapability(CAPABILITIES.engine);
  const templates = useResource(enabled ? `engine-templates-${mode}` : null, () => api.engineTemplates());
  const [template, setTemplate] = useState('multifactor');
  const [p, setP] = useState(DEFAULTS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<EngineMetric>('heart_rate');
  const [session, setSession] = useState<EngineRun[]>(() => (engineRun ? [engineRun] : []));
  const [state, setState] = useState<EngineState | null>(engineRun?.state ?? null);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]['value']>('600');
  const [cmp, setCmp] = useState<{ a: string; b: string; result?: EngineComparison; error?: string } | null>(null);
  const run = engineRun;
  const last = useRef(0);

  useEffect(() => { setState(run?.state ?? null); }, [run?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Playback: the engine advances only on explicit ticks with the real elapsed time (its documented contract).
  useEffect(() => {
    if (!run || state?.status !== 'running') return;
    last.current = performance.now();
    const t = setInterval(() => {
      const now = performance.now();
      const elapsed = (now - last.current) / 1000; last.current = now;
      api.engineControl(run.id, 'tick', elapsed).then(setState, (e: Error) => setError(e.message));
    }, 500);
    return () => clearInterval(t);
  }, [run?.id, state?.status, api]); // eslint-disable-line react-hooks/exhaustive-deps

  const control = async (action: Parameters<typeof api.engineControl>[1], value = 0) => {
    if (!run) return;
    try { setState(await api.engineControl(run.id, action, value)); setError(null); } catch (e) { setError((e as Error).message); }
  };

  const execute = async () => {
    setBusy(true); setError(null);
    try {
      const r = await api.engineRun({ template, ...p, phantom: true });
      // 1.0: a new run replaces the mission's engine run – drop a scenario derived from an OTHER run so no module
      // keeps showing stale warnings/banners (the user can apply the new run explicitly).
      if (scenario?.id.startsWith('engine-') && scenario.id !== `engine-${r.id}`) {
        applyScenario(null);
        toast({ tone: 'info', title: 'Previous engine scenario cleared', body: 'A new run was computed. Use “Apply to mission” to derive the cross-module scenario from it.' });
      }
      setEngineRun(r);
      setSession((s) => [r, ...s.filter((x) => x.id !== r.id)].slice(0, 6));
      setState(r.state);
      await api.engineControl(r.id, 'speed', Number(speed)).then(setState, () => undefined);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  const applyToMission = (r: EngineRun) => {
    const { note: _note, ...params } = r.bridge;
    applyScenario({ id: `engine-${r.id}`, title: `Engine · ${r.title.replace(' · AETHER run', '')}`, params, note: r.bridge.note });
    setEngineRun(r);
    toast({ tone: 'info', title: 'Engine run applied to the mission', body: 'BODY, PHANTOM, SYMBIOSIS, CO-ORBIT and RECOVERY now use this run and its derived scenario.' });
  };

  const compare = async (a: string, b: string) => {
    setCmp({ a, b });
    try { setCmp({ a, b, result: await api.engineCompare(a, b) }); } catch (e) { setCmp({ a, b, error: (e as Error).message }); }
  };

  if (!enabled) {
    return (
      <Notice tone="unknown" title={mode === 'demo' ? 'Not available in Demo Mode' : 'Engine not available on this backend'}>
        The Mission Systems engine (11 templates, MILP crew scheduler, PHANTOM research evaluation) is Python code that runs inside the AETHER
        backend – it is started automatically by the desktop app. {mode === 'demo' ? 'Switch to Live Mode in Settings with the backend running.' : connection === 'online' ? 'The connected backend does not advertise “mission-engine” (numpy / scipy missing or an older version).' : 'The backend is offline.'}
      </Notice>
    );
  }

  const cursor = state?.minute ?? 0;
  const status = state?.status ?? 'ready';
  return (
    <div className="space-y-5">
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card eyebrow="Mission Systems engine · educational-1.0" title="Scenario template and parameters" actions={<SourceBadge source="simulated" />}>
          <Async res={templates} loadingLabel="Loading engine templates">{(ts) => (
            <ul className="mb-4 grid gap-1.5 sm:grid-cols-2" aria-label="Engine scenario templates">
              {ts.map((t) => (
                <li key={t.id}>
                  <button type="button" onClick={() => setTemplate(t.id)} aria-pressed={template === t.id}
                    className={cx('interactive w-full rounded-lg border p-2 text-left text-sm', template === t.id ? 'border-teal-300 bg-teal-600/20' : 'border-line bg-raised/40 hover:border-line-strong')}>
                    <span className="block font-medium text-ink">{t.title}</span><span className="block text-xs text-ink-3">{t.detail}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}</Async>
          <div className="grid gap-3 md:grid-cols-2">
            <SliderField label="Planned sleep" value={p.sleep_hours} min={4} max={10} step={0.25} unit=" h" format={(v) => v.toFixed(2)} onChange={(v) => setP({ ...p, sleep_hours: v })} />
            <SliderField label="Extra rest per day" value={p.extra_rest_hours} min={0} max={4} step={0.25} unit=" h" format={(v) => v.toFixed(2)} onChange={(v) => setP({ ...p, extra_rest_hours: v })} hint="Trims the end of each availability window; visible only when the plan is tight (try High workload)." />
            <SliderField label="Extra workload" value={p.workload_hours} min={0} max={8} step={0.5} unit=" h" format={(v) => v.toFixed(1)} onChange={(v) => setP({ ...p, workload_hours: v })} />
            <SliderField label="Event intensity" value={p.intensity} min={0} max={3} step={0.1} format={(v) => v.toFixed(1)} onChange={(v) => setP({ ...p, intensity: v })} />
            <SliderField label="Measurement noise" value={p.noise} min={0} max={3} step={0.1} format={(v) => v.toFixed(1)} onChange={(v) => setP({ ...p, noise: v })} />
            <SliderField label="Cabin CO₂ set-point" value={p.co2_ppm} min={400} max={5000} step={50} unit=" ppm" onChange={(v) => setP({ ...p, co2_ppm: v })} />
            <SliderField label="Cabin temperature" value={p.temperature_c} min={16} max={30} step={0.5} unit=" °C" format={(v) => v.toFixed(1)} onChange={(v) => setP({ ...p, temperature_c: v })} />
            <SliderField label="Humidity" value={p.humidity_pct} min={20} max={80} step={1} unit=" %" onChange={(v) => setP({ ...p, humidity_pct: v })} />
          </div>
          <label className="mt-3 block text-sm text-ink-2">Crew plan (CO-ORBIT)
            <select className="field mt-1" value={p.plan_profile} onChange={(e) => setP({ ...p, plan_profile: e.target.value as PlanProfile })} aria-describedby="plan-profile-hint">
              {PROFILES.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
            </select>
            <span id="plan-profile-hint" className="mt-1 block text-xs text-ink-3">Each profile changes workload, availability or rest, so the MILP produces a different valid schedule.</span>
          </label>
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <Segmented size="sm" label="Duration" value={String(p.duration_minutes)} onChange={(v) => setP({ ...p, duration_minutes: Number(v) })}
              options={[{ value: '720', label: '12 h' }, { value: '1440', label: '24 h' }, { value: '2880', label: '48 h' }, { value: '4320', label: '72 h' }]} />
            <label className="text-sm text-ink-2">Seed<input className="field mt-1 w-24" type="number" min={0} value={p.seed} onChange={(e) => setP({ ...p, seed: Math.max(0, Math.floor(Number(e.target.value) || 0)) })} /></label>
            <Button variant="ghost" size="sm" icon="reset" onClick={() => setP(DEFAULTS)}>Defaults</Button>
            <Button variant="primary" icon="play" className="ml-auto" disabled={busy} onClick={execute}>{busy ? 'Running engine…' : 'Run engine'}</Button>
          </div>
          {error && <Notice tone="high" className="mt-3" title="Engine error">{error}</Notice>}
        </Card>

        <Card eyebrow="Latest run" title={run ? run.title : 'No engine run yet'} actions={run && <><Button size="sm" icon="download" onClick={() => downloadText(`${run.id}.json`, JSON.stringify(run, null, 2), 'application/json')}>JSON</Button><SourceBadge source="simulated" /></>}>
          {!run ? <p className="text-sm text-ink-3">Choose a template and run the engine. The run is stored in the local database and re-opened on the next start.</p> : (
            <div className="space-y-4">
              <EngineEvaluation run={run} />
              {run.phantom2 && <EngineDetectorTable cmp={run.phantom2.physiology} caption="PHANTOM 1.0 vs 2.0 – physiology only, hidden synthetic labels" />}<PhantomRegimeNote run={run} />
              {run.phantom2 && <details className="text-xs text-ink-3"><summary className="cursor-pointer">Exposure-aware variant (adds cabin CO₂ / temperature / humidity)</summary>
                <div className="mt-2"><EngineDetectorTable cmp={run.phantom2.exposure_aware} caption="With SYMBIOSIS cabin channels" /></div>
                <p className="mt-1">Cabin channels reveal the environment event for everyone in the habitat, but in the multifactor template only the commander is labelled – the label definition, not the detector, causes the extra “false” alarms there.</p></details>}
              <div className="rounded-xl border border-violet/40 bg-violet/10 p-3 text-sm">
                <div className="mb-1 font-medium text-ink">Derived cross-module scenario</div>
                <div className="tabular text-xs text-ink-2">sleep {run.bridge.sleep_delta > 0 ? '+' : ''}{run.bridge.sleep_delta} h · workload {run.bridge.workload} · CO₂ {run.bridge.co2_ppm} ppm · {run.bridge.temperature_c} °C · crew {run.bridge.crew_available}/4</div>
                <p className="mt-1 text-xs text-ink-3">{run.bridge.note}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button size="sm" variant="primary" icon="orbit" onClick={() => applyToMission(run)}>Apply to mission</Button>
                  {[['/body', 'BODY'], ['/phantom', 'PHANTOM'], ['/symbiosis', 'SYMBIOSIS'], ['/co-orbit', 'CO-ORBIT'], ['/recovery', 'RECOVERY']].map(([to, n]) => <Button key={to} size="sm" variant="ghost" onClick={() => navigate(to)}>{n}</Button>)}
                </div>
              </div>
              <ul className="list-disc space-y-0.5 pl-5 text-xs text-ink-3">{run.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
            </div>
          )}
        </Card>
      </div>

      {run && (
        <>
          <Card eyebrow={`Engine playback · ${clock(cursor)} / ${clock(run.duration_minutes)}`} title="Crew time series"
            actions={<Pill tone={status === 'running' ? 'info' : status === 'finished' ? 'good' : 'unknown'} icon="clock">{status}</Pill>}>
            <div className="mb-3 flex flex-wrap items-center gap-2" role="group" aria-label="Engine time controls">
              {status === 'running'
                ? <Button size="sm" icon="pause" onClick={() => control('pause')}>Pause</Button>
                : <Button size="sm" variant="primary" icon="play" onClick={() => control(status === 'paused' ? 'resume' : 'start')}>{status === 'paused' ? 'Resume' : 'Start'}</Button>}
              <Button size="sm" icon="reset" onClick={() => control('reset')}>Reset</Button>
              <Segmented size="sm" label="Playback speed" value={speed} onChange={(v) => { setSpeed(v); void control('speed', Number(v)); }} options={SPEEDS.map((s) => ({ value: s.value, label: s.label }))} />
              <input type="range" aria-label="Engine time cursor (minutes)" min={0} max={run.duration_minutes} step={run.sample_minutes} value={cursor}
                onChange={(e) => void control('seek', Number(e.target.value))} className="min-w-40 flex-1" />
              <span className="tabular w-20 text-right text-sm font-semibold text-ink">{clock(cursor)}</span>
            </div>
            <div className="mb-2"><Segmented size="sm" label="Metric" value={metric} onChange={setMetric} options={ENGINE_METRICS.map((m) => ({ value: m.value, label: m.label }))} /></div>
            <EngineCrewChart run={run} metric={metric} cursor={cursor} onCursor={(m) => { if (m != null) void control('seek', m); }} />
            <p className="mt-1 text-xs text-ink-3">Vertical markers: injected events. Dots: samples flagged by AETHER PHANTOM. Sample policy: {state?.sample_policy ?? 'last sample at or before cursor'}.</p>
          </Card>
          <div className="grid gap-5 xl:grid-cols-2">
            <Card eyebrow="SYMBIOSIS · modelled cabin" title="Habitat environment during the run"><EngineEnvChart run={run} cursor={cursor} /></Card>
            <Card eyebrow="CO-ORBIT · MILP scheduler" title="Optimised crew schedule"><EngineSchedule run={run} /></Card>
          </div>
          {session.length >= 2 && (
            <Card eyebrow="Controlled comparison" title="Compare two engine runs">
              <div className="flex flex-wrap items-end gap-2 text-sm">
                {(['a', 'b'] as const).map((k, i) => (
                  <label key={k} className="text-ink-2">Run {k.toUpperCase()}<select className="field mt-1" value={cmp?.[k] ?? session[i]?.id} onChange={(e) => setCmp({ a: cmp?.a ?? session[0].id, b: cmp?.b ?? session[1].id, [k]: e.target.value })}>
                    {session.map((s) => <option key={s.id} value={s.id}>{s.title} · seed {s.seed}</option>)}</select></label>
                ))}
                <Button icon="layers" onClick={() => compare(cmp?.a ?? session[0].id, cmp?.b ?? session[1].id)}>Compare</Button>
              </div>
              {cmp?.error && <Notice tone="high" className="mt-2">{cmp.error}</Notice>}
              {cmp?.result && (
                <div className="mt-3 grid gap-4 md:grid-cols-2">
                  <table className="tabular w-full text-xs"><caption className="mb-1 text-left text-ink-3">Mean difference (B − A), valid samples</caption>
                    <tbody>{Object.entries(cmp.result.delta_means).sort().slice(0, 16).map(([k, v]) => <tr key={k} className="border-t border-line"><td className="py-1 text-ink-2">{k.replace(':', ' · ')}</td><td className={cx('text-right', Math.abs(v) > 0.01 ? 'text-ink' : 'text-ink-3')}>{v > 0 ? '+' : ''}{v.toFixed(2)}</td></tr>)}</tbody></table>
                  <div className="text-sm text-ink-2">
                    <p>Schedule max load: A {cmp.result.schedule_a.max_load.toFixed(2)} → B {cmp.result.schedule_b.max_load.toFixed(2)}</p>
                    <p>PHANTOM F1: A {cmp.result.evaluation_a.phantom?.f1?.toFixed(2) ?? '—'} → B {cmp.result.evaluation_b.phantom?.f1?.toFixed(2) ?? '—'}</p>
                    <p className="mt-2 flex items-center gap-1 text-xs text-ink-3"><Icon name={cmp.result.same_seed ? 'check' : 'alert'} size={13} />{cmp.result.same_seed ? 'Same seed – differences come from the parameters.' : 'Different seeds – differences mix parameters and random variation.'} {cmp.result.note}</p>
                  </div>
                </div>
              )}
            </Card>
          )}
        </>
      )}
    </div>
  );
}
