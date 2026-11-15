import { useState } from 'react';
import { CAPABILITIES, type RadiationResult } from '../../api/types';
import { ChartFrame, TimeSeriesChart } from '../../charts';
import { downloadText } from '../../lib/format';
import { publishRadiation } from '../../lib/radiationContext';
import { useResource } from '../../lib/useResource';
import { useApp } from '../../state/AppState';
import { Async, Button, Card, Empty, Notice, SliderField, SourceBadge } from '../../ui';

const COLORS = ['var(--color-series-1)', 'var(--color-series-2)', 'var(--color-series-3)', 'var(--color-series-4)'];
const KIND: Record<string, string> = {
  solar_particle_event: 'Solar particle event (user-set)', median_reaches_50pct_career_limit: 'Median reaches 50 % of the career limit', median_reaches_100pct_career_limit: 'Median reaches the career limit',
};

/** MISSION LAB · radiation exposure simulator (dose bookkeeping against NASA limits; no clinical model). */
export function RadiationPanel() {
  const { api, hasCapability, mode } = useApp();
  const enabled = hasCapability(CAPABILITIES.science);
  const presets = useResource(enabled ? `rad-presets-${mode}` : null, () => api.radiationPresets());
  const [chosen, setChosen] = useState<string[]>(['iss_6_months', 'lunar_30_days', 'mars_conjunction']);
  const [shield, setShield] = useState(1);
  const [speDose, setSpeDose] = useState(0);
  const [runs, setRuns] = useState<RadiationResult[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!enabled) return <Empty title="Radiation model needs the AETHER backend" icon="info">Open the desktop app or switch to Live Mode.</Empty>;

  const run = async () => {
    setBusy(true); setError(null);
    try {
      const out: RadiationResult[] = [];
      for (const id of chosen) {
        const r = await api.radiation({ preset: id, shielding_factor: shield });
        if (speDose > 0) {
          const spe = await api.radiation({ title: `${r.title} + SPE ${speDose} mSv (day ${Math.min(90, r.days - 1)})`, segments: r.inputs.segments, spe: [{ day: Math.min(90, r.days - 1), dose_msv: speDose }], shielding_factor: shield });
          out.push(r, spe);
        } else out.push(r);
      }
      setRuns(out);
      const worst = [...out].sort((a, b) => b.final.p50 - a.final.p50)[0];
      if (worst) publishRadiation(worst);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const exportCsv = () => runs && downloadText('aether-radiation.csv', ['scenario,day,p5_msv,p50_msv,p95_msv,environment', ...runs.flatMap((r) => r.series.map((s) => `"${r.title}",${s.day},${s.p5},${s.p50},${s.p95},${s.environment}`))].join('\n'), 'text/csv');

  return (
    <div className="space-y-4">
      <Card eyebrow="MISSION LAB · radiation" title="Radiation exposure simulator" actions={<SourceBadge source="estimated" />}>
        <Async res={presets} loadingLabel="Loading dose rates">{(p) => (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <fieldset className="space-y-1 text-sm"><legend className="mb-1 text-xs text-ink-3">Scenarios to compare</legend>
              {Object.entries(p.presets).map(([id, title]) => (
                <label key={id} className="flex items-center gap-2"><input type="checkbox" checked={chosen.includes(id)} onChange={(e) => setChosen(e.target.checked ? [...chosen, id] : chosen.filter((x) => x !== id))} />{title}</label>))}
            </fieldset>
            <div className="space-y-3">
              <SliderField label="Shielding multiplier (model assumption)" value={shield} min={0.5} max={1.5} step={0.05} onChange={setShield} format={(v) => `×${v.toFixed(2)}`} hint="1.0 = shielding of the measuring instrument. Not a transport calculation." />
              <SliderField label="Add a solar particle event (user-set dose)" value={speDose} min={0} max={300} step={10} unit="mSv" onChange={setSpeDose} hint={`Event probability is not modelled. Short-term SPE limit: ${p.limits.spe_msv} mSv.`} />
              <Button variant="primary" icon="play" disabled={busy || chosen.length === 0} onClick={() => void run()}>Run radiation model</Button>
            </div>
            <div className="lg:col-span-2 overflow-x-auto">
              <table aria-label="Dose-rate sources" className="w-full min-w-[620px] text-xs"><thead><tr className="text-left text-ink-3"><th className="py-1">Environment</th><th>Dose-equivalent rate</th><th>Source</th><th>Uncertainty used</th></tr></thead>
                <tbody>{Object.entries(p.environments).filter(([k]) => k !== 'earth').map(([k, e]) => <tr key={k} className="border-t border-line"><td className="py-1">{e.label}</td><td className="tabular">{e.rate_msv_per_day} mSv/day</td><td>{e.source}</td><td className="text-ink-3">{e.uncertainty}</td></tr>)}</tbody></table>
            </div>
          </div>
        )}</Async>
        {error && <Notice tone="high" title="Radiation model failed" className="mt-3">{error}</Notice>}
      </Card>
      {runs && (
        <Card eyebrow={`${runs.length} scenarios · Monte Carlo over rate uncertainty`} title="Cumulative effective dose" actions={<><Button size="sm" icon="download" onClick={exportCsv}>CSV</Button><Button size="sm" icon="download" onClick={() => downloadText('aether-radiation.json', JSON.stringify(runs, null, 2), 'application/json')}>JSON</Button><SourceBadge source="estimated" /></>}>
          <ChartFrame caption="Cumulative effective dose (median and 5–95 % band)" table={{ columns: ['Scenario', 'Day', 'Median mSv', '5–95 %'], rows: runs.flatMap((r) => r.series.filter((_, i) => i % 20 === 0).map((s) => [r.title, s.day, s.p50, `${s.p5}–${s.p95}`])) }}>
            <TimeSeriesChart ariaLabel="Cumulative effective dose by mission day with 5–95 % bands" height={260} unit="mSv" xFormat={(x) => `Day ${x}`} yFormat={(y) => y.toFixed(0)}
              bands={runs.map((r, i) => ({ id: `b${i}`, label: `${r.title} 5–95 %`, color: COLORS[i % 4], points: r.series.map((s) => ({ x: s.day, lo: s.p5, hi: s.p95 })) }))}
              series={runs.map((r, i) => ({ id: `s${i}`, label: r.title, color: COLORS[i % 4], points: r.series.map((s) => ({ x: s.day, y: s.p50 })) }))}
              refLines={[{ y: runs[0].limits.career_msv, label: `Career limit ${runs[0].limits.career_msv} mSv` }]} />
          </ChartFrame>
          <div className="mt-3 overflow-x-auto">
            <table aria-label="Radiation scenario comparison" className="tabular w-full min-w-[720px] text-xs">
              <thead><tr className="text-left text-ink-3"><th className="py-1">Scenario</th><th>Days</th><th>Median (5–95 %) mSv</th><th>Share of 600 mSv</th><th>P(≥ career limit)</th><th>Events</th></tr></thead>
              <tbody>{runs.map((r) => <tr key={r.title} className="border-t border-line align-top"><td className="py-1 pr-2">{r.title}</td><td>{r.days}</td><td>{r.final.p50} ({r.final.p5}–{r.final.p95})</td>
                <td>{Math.round(r.fraction_of_career_limit.p50 * 100)} %</td><td>{Math.round(r.probability_exceeds_career_limit * 100)} %</td>
                <td>{r.events.length ? r.events.map((e) => `day ${e.day + 1}: ${KIND[e.kind] ?? e.kind}${e.exceeds_spe_limit ? ' (≥ SPE limit)' : ''}`).join('; ') : '—'}</td></tr>)}</tbody>
            </table>
          </div>
          <Notice tone="unknown" title="What this model does not do" className="mt-3">Dose bookkeeping only, compared with the NASA-STD-3001 permissible-exposure limits ({runs[0].limits.source}). Not modelled: {runs[0].not_modelled.join('; ')}. The scenario with the highest median was sent to PHANTOM as exposure context.</Notice>
        </Card>
      )}
    </div>
  );
}
