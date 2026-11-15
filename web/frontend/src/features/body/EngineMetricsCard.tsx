import { useState } from 'react';
import type { EngineMetric } from '../../api/types';
import { Segmented } from '../../ui';
import { ENGINE_METRICS, EngineCrewChart, EngineRunCard } from '../shared/EngineCards';

/** BODY view of the shared Mission Systems engine run: minute-resolution physiology of the engine crew. */
export function EngineMetricsCard() {
  const [metric, setMetric] = useState<EngineMetric>('heart_rate');
  return (
    <EngineRunCard eyebrow="Mission Systems engine · within-day physiology" title="Engine crew time series (synthetic)">
      {(r) => (
        <>
          <div className="mb-2"><Segmented size="sm" label="Metric" value={metric} onChange={setMetric} options={ENGINE_METRICS.map((m) => ({ value: m.value, label: m.label }))} /></div>
          <EngineCrewChart run={r} metric={metric} height={200} />
          <p className="mt-1 text-xs text-ink-3">The engine models a 3-person crew with individual baselines at {r.sample_minutes}-minute resolution; the daily AETHER record above is a separate synthetic dataset. Injected events: {r.events.length ? r.events.map((e) => `${e.kind.replace('_', ' ')} at minute ${e.minute}`).join(', ') : 'none'}.</p>
        </>
      )}
    </EngineRunCard>
  );
}
