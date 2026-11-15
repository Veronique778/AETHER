/**
 * SYMBIOSIS cabin-event detection (API 1.0, GET /api/engine/runs/{id}/environment).
 * Three separate things are shown separately on purpose:
 *   1. cabin events (CO₂ increase, temperature drift, ppCO₂ above the NASA-STD-3001 limit),
 *   2. sensor faults (missing / invalid / spike / flat-line) – a fault is NOT a cabin event,
 *   3. per-crew context – co-occurrence is a hypothesis, never a cause or a diagnosis.
 */
import type { EngineRun, EnvFrameState } from '../../api/types';
import { CAPABILITIES } from '../../api/types';
import { useResource } from '../../lib/useResource';
import { useApp } from '../../state/AppState';
import { Async, Notice, Pill } from '../../ui';
import { clock } from '../shared/EngineCards';

const STATE_STYLE: Record<EnvFrameState, { color: string; label: string }> = {
  nominal: { color: 'var(--color-good)', label: 'nominal' },
  environment_event: { color: 'var(--color-attention)', label: 'cabin event' },
  sensor_fault: { color: 'var(--color-ink-3)', label: 'sensor fault' },
};
const KIND: Record<string, string> = {
  co2_increase: 'CO₂ increase', temperature_drift: 'Temperature drift', co2_above_limit: 'ppCO₂ above 3 mmHg (1-h mean)',
  sensor_missing: 'Sensor: missing readings', sensor_invalid: 'Sensor: invalid readings', sensor_out_of_bounds: 'Sensor: out of plausible range',
  sensor_spike: 'Sensor: isolated spike', sensor_flat_line: 'Sensor: flat line (stuck)',
};

export function EnvironmentEvents({ run }: { run: EngineRun }) {
  const { api, hasCapability } = useApp();
  const enabled = hasCapability(CAPABILITIES.environmentDetector);
  const res = useResource(enabled ? `env-${run.id}` : null, () => api.engineEnvironment(run.id));
  if (!enabled) return <Notice tone="unknown">Cabin-event detection needs backend API 1.0 (capability “environment-detector”).</Notice>;
  return (
    <Async res={res} loadingLabel="Detecting cabin events">{(env) => {
      const cabin = env.events.filter((e) => e.category === 'environment');
      const faults = env.events.filter((e) => e.category === 'sensor_fault');
      return (
        <div className="space-y-4" data-testid="environment-events">
          <div>
            <div className="mb-1 text-xs text-ink-3">Cabin state per sample · {env.zone_id}</div>
            <div className="flex h-5 overflow-hidden rounded border border-line" role="img"
              aria-label={`Cabin state timeline: ${env.frames.filter((f) => f.state === 'environment_event').length} event samples, ${env.frames.filter((f) => f.state === 'sensor_fault').length} sensor-fault samples, ${env.frames.length} samples total`}>
              {env.frames.map((f) => <span key={f.minute} className="h-full flex-1" title={`${clock(f.minute)} · ${STATE_STYLE[f.state].label}${f.ppco2_1h_mmhg != null ? ` · ppCO₂ ${f.ppco2_1h_mmhg} mmHg` : ''}`} style={{ background: STATE_STYLE[f.state].color, opacity: f.state === 'nominal' ? 0.35 : 0.9 }} />)}
            </div>
            <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-ink-3">{(Object.keys(STATE_STYLE) as EnvFrameState[]).map((k) => <span key={k} className="flex items-center gap-1"><span className="inline-block h-2 w-3 rounded-sm" style={{ background: STATE_STYLE[k].color }} />{STATE_STYLE[k].label}</span>)}</div>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <section aria-label="Cabin events">
              <h4 className="mb-1 text-sm font-semibold text-ink">Cabin events ({cabin.length})</h4>
              {cabin.length === 0 ? <p className="text-sm text-ink-2">No cabin event detected in this run.</p> : (
                <ul className="space-y-1 text-sm">{cabin.map((e) => <li key={`${e.kind}-${e.start_minute}`}><Pill tone="attention">{KIND[e.kind] ?? e.kind}</Pill> <span className="text-ink-2">{clock(e.start_minute)}–{clock(e.end_minute)}{e.sustained ? ' · sustained (≥ 2 h)' : ''}</span></li>)}</ul>
              )}
              <p className="mt-1 text-[11px] text-ink-3">Limit: {env.co2_limit.mmhg} mmHg ppCO₂, {env.co2_limit.averaging} average – {env.co2_limit.source} (evidence {env.co2_limit.evidence_id}).</p>
            </section>
            <section aria-label="Sensor faults">
              <h4 className="mb-1 text-sm font-semibold text-ink">Sensor faults ({faults.length})</h4>
              {faults.length === 0 ? <p className="text-sm text-ink-2">No sensor fault detected.</p> : (
                <ul className="space-y-1 text-sm">{faults.map((e) => <li key={`${e.kind}-${e.channel}-${e.start_minute}`}><Pill tone="unknown" icon="info">{KIND[e.kind] ?? e.kind}</Pill> <span className="text-ink-2">{e.channel} · {clock(e.start_minute)}–{clock(e.end_minute)}</span></li>)}</ul>
              )}
              <p className="mt-1 text-[11px] text-ink-3">A sensor fault is a data-quality problem, not a change of cabin conditions.</p>
              {Object.entries(env.applicability).filter(([, v]) => v !== 'ok').map(([k, v]) => <p key={k} className="text-[11px] text-ink-3">{k}: {v}</p>)}
            </section>
          </div>
          <section aria-label="Crew context">
            <h4 className="mb-1 text-sm font-semibold text-ink">Crew context – hypotheses, not causes</h4>
            <ul className="grid gap-2 md:grid-cols-3">{env.crew_context.map((c) => (
              <li key={c.crew_id} className="rounded-lg border border-line p-2 text-xs">
                <div className="mb-1 flex items-center gap-2"><span className="font-semibold text-ink">{c.crew_name ?? `Crew ${c.crew_id}`}</span>
                  {c.environment_stressor ? <Pill tone="attention">cabin stressor</Pill> : <Pill tone="good">no cabin stressor</Pill>}</div>
                <p className="text-ink-2">{c.statement}</p>
                <p className="mt-1 text-ink-3">PHANTOM flags: {c.physiology_flagged_samples} (during stressor {c.flagged_during_stressor}) · evidence: {c.evidence}</p>
                {c.suggested_measurements.length > 0 && <p className="mt-1 text-ink-3">Suggested measurements: {c.suggested_measurements.map((m) => m.signal.replace('_', ' ')).join(', ')} – {c.suggested_measurements[0].why}.</p>}
              </li>))}</ul>
            <p className="mt-2 text-xs text-ink-3">{env.note} {env.scope}</p>
          </section>
        </div>
      );
    }}</Async>
  );
}
