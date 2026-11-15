import type { DetectorName } from '../../api/types';
import { CAPABILITIES } from '../../api/types';
import { TimeSeriesChart } from '../../charts';
import { useRadiationContext } from '../../lib/radiationContext';
import { useResource } from '../../lib/useResource';
import { useApp } from '../../state/AppState';
import { Async, Card, Pill, SourceBadge } from '../../ui';

// Daily record: the backend applies the LEGACY 0.9 PHANTOM 2.0 rule here (the 1.0 noise-adaptive rule is calibrated on
// engine data only – see decision_rule in the response). `phantom2` and `phantom2_v09` are therefore the same decision.
const NAMES: Partial<Record<DetectorName, string>> = {
  zscore: 'PHANTOM 1.0 z', ewma: 'EWMA', adaptive: 'Adaptive base', cusum: 'CUSUM', mahalanobis: 'Mahalanobis', phantom2: 'PHANTOM 2.0 (legacy 0.9 rule)',
};

/** PHANTOM 2.0 on the daily record: multivariate distance, sequential change detection, uncertainty, attribution. */
export function Phantom2Card() {
  const { api, astronautId, day, dataVersion, hasCapability, mode } = useApp();
  const enabled = hasCapability(CAPABILITIES.phantom2);
  const res = useResource(enabled ? `p2-${mode}-${astronautId}-${day}-${dataVersion}` : null, () => api.phantom2(astronautId, day));
  if (!enabled) return null;
  return (
    <Card eyebrow="PHANTOM 2.0 · multivariate · sequential · daily record" title="Beyond single-signal z-scores" className="mb-4" actions={<SourceBadge source="estimated" />}>
      <Async res={res} loadingLabel="Running PHANTOM 2.0">{(r) => r.status !== 'ok' ? <p className="text-sm text-ink-3">{r.detail}</p> : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="phantom2-today-state">
            {r.today_state === 'insufficient_data'
              ? <Pill tone="unknown" icon="info">Day {r.day}: insufficient data – too few signals measured; this is not a normal result</Pill>
              : r.today_state === 'flag' ? <Pill tone="attention">Day {r.day}: deviation flagged (statistical, not a diagnosis)</Pill>
              : r.today_state === 'no_flag' ? <Pill tone="good">Day {r.day}: within personal baseline</Pill> : null}
            {r.decision_rule && <span className="text-xs text-ink-3">Rule: {r.decision_rule.rule}. {r.decision_rule.note}</span>}
          </div>
          <ul className="flex flex-wrap gap-2" aria-label={`Detector decisions for day ${r.day}`}>
            {(Object.keys(NAMES) as DetectorName[]).map((d) => (
              <li key={d}><Pill tone={r.today[d] == null ? 'unknown' : r.today[d] ? 'attention' : 'good'}>{NAMES[d]}: {r.today[d] == null ? 'abstain (not enough data)' : r.today[d] ? 'flag' : 'within baseline'}</Pill></li>
            ))}
          </ul>
          <div className="grid gap-5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <div>
              <div className="mb-1 text-xs text-ink-3">Robust Mahalanobis distance d² per day (after the {r.baseline_window} baseline) · line = χ² threshold</div>
              <TimeSeriesChart height={190} ariaLabel="Multivariate distance over mission days" unit="d²" xFormat={(x) => `D${x}`} yFormat={(y) => y.toFixed(0)}
                series={[{ id: 'd2', label: 'd²', color: 'var(--color-series-1)', points: r.series.map((p) => ({ x: p.day, y: p.d2, tag: p.phantom2 ? 'flag' : undefined })) }]}
                refLines={r.multivariate.threshold ? [{ y: r.multivariate.threshold, label: `χ² ${r.parameters.chi2_quantile}` }] : []} tagLabel={{ flag: 'PHANTOM 2.0 flag' }} />
              {Object.keys(r.cusum_change_start_day).length > 0 && (
                <p className="mt-2 text-sm text-ink-2">CUSUM estimates a sustained change starting on {Object.entries(r.cusum_change_start_day).map(([m, d]) => `${r.labels[m]?.label ?? m}: day ${d}`).join(', ')}.</p>
              )}
            </div>
            <div className="space-y-3 text-sm">
              {r.multivariate.d2 != null && <div>
                <div className="text-xs text-ink-3">Day {r.day}: d² = {r.multivariate.d2} (threshold {r.multivariate.threshold}, {r.multivariate.df} signals)</div>
                {r.multivariate.uncertainty && <div className="text-xs text-ink-2">Bootstrap ({r.multivariate.uncertainty.bootstrap_replicates}×): flag probability {Math.round(r.multivariate.uncertainty.flag_probability * 100)} %, 90 % interval of d² {r.multivariate.uncertainty.d2_interval_90.join('–')}</div>}
              </div>}
              {r.multivariate.attribution && <div>
                <div className="mb-1 text-xs text-ink-3">Attribution – share of the distance</div>
                <ul className="space-y-1">{Object.entries(r.multivariate.attribution).sort((a, b) => b[1] - a[1]).map(([m, v]) => (
                  <li key={m} className="flex items-center gap-2"><span className="w-36 truncate text-xs text-ink-2">{r.labels[m]?.label ?? m}</span>
                    <span className="h-2 rounded bg-teal-400/70" style={{ width: `${Math.max(2, Math.abs(v) * 100)}%` }} aria-hidden="true" />
                    <span className="tabular text-xs text-ink">{Math.round(v * 100)} %</span></li>))}</ul>
              </div>}
              <div>
                <div className="mb-1 text-xs text-ink-3">Next-best measurement</div>
                {r.next_best_measurement.length === 0 ? <p className="text-xs text-ink-2">All signals were recorded today.</p> : (
                  <ol className="list-decimal pl-5 text-xs text-ink-2">{r.next_best_measurement.map((n) => <li key={n.metric}>{r.labels[n.metric]?.label ?? n.metric}: {Math.round(n.p_decision_change * 100)} % chance it changes the decision (expected z {n.expected_z}, ±{n.conditional_sd})</li>)}</ol>
                )}
              </div>
            </div>
          </div>
          <details className="text-xs text-ink-3"><summary className="cursor-pointer">Method, parameters, references and limitations</summary>
            <p className="mt-2 whitespace-pre-line">{r.method}</p>
            <p className="mt-1">Parameters: {Object.entries(r.parameters).map(([k, v]) => `${k} = ${v}`).join(' · ')}. Lag-1 autocorrelation (baseline): {Object.entries(r.autocorrelation).map(([m, v]) => `${m} ${v}`).join(', ')}.</p>
            <ul className="mt-1 list-disc pl-5">{r.references.map((x) => <li key={x}>{x}</li>)}</ul>
            <ul className="mt-1 list-disc pl-5">{r.limitations.map((x) => <li key={x}>{x}</li>)}</ul>
          </details>
        </div>
      )}</Async>
    </Card>
  );
}

/** Radiation exposure events handed over from MISSION LAB. Context only – PHANTOM detectors do not use dose. */
export function RadiationContextCard() {
  const ctx = useRadiationContext();
  if (!ctx) return null;
  return (
    <Card eyebrow="Exposure context · from MISSION LAB radiation model" title="Radiation exposure context" className="mb-4" actions={<SourceBadge source="estimated" />}>
      <p className="text-sm text-ink-2">{ctx.title}: median cumulative dose {ctx.final.p50} mSv (5–95 % {ctx.final.p5}–{ctx.final.p95}) over {ctx.days} days, {Math.round(ctx.fraction.p50 * 100)} % of the 600 mSv career limit.</p>
      {ctx.events.length > 0 && <ul aria-label="Radiation exposure events" className="mt-2 list-disc pl-5 text-xs text-ink-2">{ctx.events.map((e) => <li key={`${e.kind}-${e.day}`}>Mission day {e.day + 1}: {e.kind.replace(/_/g, ' ')} ({e.dose_msv} mSv)</li>)}</ul>}
      <p className="mt-2 text-xs text-ink-3">Shown so that physiological deviations can be read against the exposure history. AETHER has no biological radiation marker; dose is not an input to any PHANTOM detector and no health effect is inferred.</p>
    </Card>
  );
}
