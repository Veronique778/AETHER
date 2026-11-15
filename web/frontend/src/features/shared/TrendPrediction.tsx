import type { ScenarioParams } from '../../api/types';
import { TimeSeriesChart } from '../../charts';
import { useResource } from '../../lib/useResource';
import { useApp } from '../../state/AppState';
import { Async, SourceBadge } from '../../ui';

/** Nominal inputs = the simulator's own "baseline" preset (fallback mirrors its published values). */
const NOMINAL: ScenarioParams = { sleep_delta: 0, workload: 50, co2_ppm: 850, temperature_c: 22, crew_available: 4 };

/**
 * Observed vs predicted PHANTOM index.
 * Observed = PHANTOM history (analysis of recorded data). Predicted = Mission Systems projection
 * (median and 10–90 % of simulated runs) from the selected day with the applied scenario, or nominal inputs.
 */
export function TrendPrediction({ astronautId, horizon = 7, height = 190, compact }: { astronautId?: string; horizon?: number; height?: number; compact?: boolean }) {
  const { api, astronautId: ctxId, day, scenario, dataVersion, hasCapability } = useApp();
  const id = astronautId ?? ctxId;
  const presets = useResource(`scen-${api.mode}`, () => api.scenarios());
  const base = presets.data?.find((s) => s.id === 'baseline');
  const params: ScenarioParams = scenario?.params ?? (base ? { sleep_delta: base.sleep_delta, workload: base.workload, co2_ppm: base.co2_ppm, temperature_c: base.temperature_c, crew_available: base.crew_available ?? 4 } : NOMINAL);
  const history = useResource(hasCapability('phantom-history') ? `phh-${api.mode}-${id}-${day}-${dataVersion}` : null, () => api.phantomHistory(id, day, 41));
  const proj = useResource(presets.data || presets.error ? `trend-${api.mode}-${id}-${day}-${JSON.stringify(params)}-${horizon}` : null,
    () => api.project({ astronaut_id: id, start_day: day, horizon_days: horizon, runs: 100, seed: 67, ...params }));
  return (
    <div>
      {!compact && <div className="mb-1 flex items-center justify-between gap-2 text-xs text-ink-3"><span>Observed: PHANTOM history · Predicted: {scenario ? `scenario “${scenario.title}”` : 'nominal inputs'} (model)</span><SourceBadge source="simulated" /></div>}
      <Async res={proj} loadingLabel="Projecting">{(p) => {
        const obs = (history.data?.points ?? []).filter((x) => x.day > day - 14);
        return (
          <TimeSeriesChart height={height} ariaLabel={`PHANTOM index: observed last 14 days and predicted next ${horizon} days`} yDomain={[0, 100]}
            series={[
              { id: 'obs', label: 'Observed (analysis)', color: 'var(--color-cyan)', points: [...obs.map((x) => ({ x: x.day, y: x.score })), ...p.days.filter((d) => d.day > day).map((d) => ({ x: d.day, y: null }))] },
              { id: 'pred', label: 'Predicted (model median)', color: 'var(--color-magenta)', dashed: true, points: [...obs.filter((x) => x.day < day).map((x) => ({ x: x.day, y: null })), ...(obs.find((x) => x.day === day) ? [{ x: day, y: obs.find((x) => x.day === day)!.score }] : []), ...p.days.filter((d) => d.day > day).map((d) => ({ x: d.day, y: d.score.p50 }))] },
            ]}
            bands={[{ id: 'band', label: 'Predicted 10–90 %', color: 'var(--color-magenta)', points: p.days.filter((d) => d.day >= day).map((d) => ({ x: d.day, lo: d.score.p10, hi: d.score.p90 })) }]}
            refLines={[{ y: 50, label: 'review level' }]} markers={[{ x: day, label: 'now' }]} xFormat={(x) => (x === day ? 'Now' : x > day ? `+${x - day} d` : `D${x}`)} unit="/100" />
        );
      }}</Async>
    </div>
  );
}
