import type { ScenarioParams } from '../api/types';
import { navigate } from '../lib/router';
import { useResource } from '../lib/useResource';
import { Button, Icon } from '../ui';
import { useApp } from './AppState';

/**
 * Cross-module scenario propagation.
 * MISSION LAB applies a scenario (AppState.scenario). Each module asks the existing simulator
 * (api.simulate = POST /api/mission-lab/run) for the modelled outcome of that scenario for the
 * selected astronaut and day, and shows it NEXT TO the actual data, labelled "scenario (model)".
 * Rules of propagation are the simulator's own: sleep_delta / workload / CO₂ / crew availability
 * → modelled metrics → PHANTOM analysis → crew plan. Temperature is passed but has no coefficient
 * in the single-day model (stated in the UI).
 */
export function useScenarioRun(astronautId?: string) {
  const { api, scenario, astronautId: ctxId, day, dataVersion } = useApp();
  const id = astronautId ?? ctxId;
  return useResource(scenario ? `scenrun-${api.mode}-${id}-${day}-${JSON.stringify(scenario.params)}-${dataVersion}` : null,
    () => api.simulate({ astronaut_id: id, day, ...scenario!.params }));
}

export function paramSummary(p: ScenarioParams) {
  return `sleep ${p.sleep_delta > 0 ? '+' : ''}${p.sleep_delta} h · workload ${p.workload} · CO₂ ${p.co2_ppm} ppm · ${p.temperature_c} °C · crew ${p.crew_available}/4`;
}

const LINKS = [
  { path: '/symbiosis', name: 'SYMBIOSIS' }, { path: '/phantom', name: 'PHANTOM' }, { path: '/body', name: 'BODY' }, { path: '/co-orbit', name: 'CO-ORBIT' }, { path: '/recovery', name: 'RECOVERY' },
];

/** Global banner while a scenario is applied – one place to see it and reset it. */
export function ScenarioBanner() {
  const { scenario, applyScenario } = useApp();
  if (!scenario) return null;
  return (
    <div role="region" aria-label="Applied scenario" className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-violet/30 bg-violet/10 px-4 py-2 text-sm lg:px-8">
      <Icon name="flask" size={16} className="text-violet" />
      <span className="font-semibold text-ink">Scenario applied: {scenario.title}</span>
      <span className="tabular text-xs text-ink-2">{paramSummary(scenario.params)}</span>
      <span className="text-xs text-ink-3">· modelled effects shown beside actual data in</span>
      <span className="flex flex-wrap gap-1">{LINKS.map((l) => <button key={l.path} type="button" onClick={() => navigate(l.path)} className="rounded-md border border-violet/40 px-1.5 py-0.5 text-xs text-ink hover:bg-violet/20">{l.name}</button>)}</span>
      <Button size="sm" variant="ghost" icon="reset" className="ml-auto" onClick={() => applyScenario(null)}>Reset scenario</Button>
    </div>
  );
}
