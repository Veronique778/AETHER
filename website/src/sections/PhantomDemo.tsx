import { useMemo, useState } from 'react';
import { analyse, THRESHOLD, type Result, type Window } from '../phantom/method';
import { SCENARIOS, type ScenarioId } from '../phantom/scenarios';
import { Icon, cx } from '../vendor/aether/ui';
import { Cite, SectionHeader, SyntheticBadge } from './common';

const OUTCOME: Record<Result['outcome'], { label: string; tone: string; icon: 'alert' | 'checkCircle' | 'info'; meaning: string }> = {
  flag: { label: 'flag · statistical change detected', tone: 'border-attention/70 bg-attention/10 text-attention', icon: 'alert',
    meaning: 'A statistical difference from this person’s own baseline — a prompt to look closer, not a diagnosis.' },
  no_flag: { label: 'no_flag · no statistical change', tone: 'border-good/60 bg-good/10 text-good', icon: 'checkCircle',
    meaning: 'No window crossed the threshold. Changes smaller than ≈ 10 bpm can stay hidden — no_flag does not mean “healthy”.' },
  insufficient_data: { label: 'insufficient_data · cannot judge', tone: 'border-line-strong bg-raised/60 text-ink', icon: 'info',
    meaning: 'Not enough usable data for a personal comparison. AETHER says so instead of guessing.' },
};

function Chart({ windows, result, durationS }: { windows: Window[]; result: Result; durationS: number }) {
  const W = 760, H = 280, L = 44, R = 12, T = 16, B = 34;
  const vals = windows.filter((w) => w.mean !== null).map((w) => w.mean as number);
  const lo = Math.floor(Math.min(...vals, (result.median ?? 64) - 15) - 2);
  const hi = Math.ceil(Math.max(...vals, (result.median ?? 64) + 15) + 2);
  const x = (t: number) => L + ((W - L - R) * t) / durationS;
  const y = (v: number) => T + ((H - T - B) * (hi - v)) / (hi - lo);
  const band = result.median !== null && result.scale !== null ? [result.median - THRESHOLD * result.scale, result.median + THRESHOLD * result.scale] : null;
  const ticks = [];
  for (let m = 0; m <= durationS / 60; m += 30) ticks.push(m);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img"
      aria-label={`SYNTHETIC DEMO chart: 5-minute mean heart rate, ${windows.filter((w) => w.flag).length} flagged windows, baseline ${result.median?.toFixed(1) ?? 'not available'} bpm`}>
      <rect x={L} y={T} width={x(Math.min(3600, durationS)) - L} height={H - T - B} fill="#6ea2ff" fillOpacity=".07" />
      <text x={L + 6} y={T + 14} fill="#7592a8" fontSize="11" fontFamily="JetBrains Mono, monospace">BASELINE HOUR (frozen)</text>
      {band && <rect x={x(3600)} y={y(band[1])} width={x(durationS) - x(3600)} height={y(band[0]) - y(band[1])} fill="#00e5ff" fillOpacity=".06" stroke="#00e5ff" strokeOpacity=".25" strokeDasharray="4 4" />}
      {result.median !== null && <line x1={L} x2={W - R} y1={y(result.median)} y2={y(result.median)} stroke="#a875ff" strokeDasharray="6 4" />}
      {[lo, Math.round((lo + hi) / 2), hi].map((v) => (
        <g key={v}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="#15304a" /><text x={L - 6} y={y(v) + 4} textAnchor="end" fill="#7592a8" fontSize="11">{v}</text></g>
      ))}
      {ticks.map((m, i) => <text key={m} x={x(m * 60)} y={H - 12} textAnchor={i === 0 ? 'start' : m * 60 >= durationS ? 'end' : 'middle'} fill="#7592a8" fontSize="11">{m} min</text>)}
      {windows.map((w) => w.mean === null
        ? <rect key={w.index} x={x(w.start) + 1} y={T} width={x(300) - L - 2} height={H - T - B} fill="#ff647c" fillOpacity=".06"><title>{`Window ${w.index + 1}: unusable (${w.reason}) — left empty`}</title></rect>
        : <circle key={w.index} cx={x(w.start + 150)} cy={y(w.mean)} r={w.flag ? 5 : 3.5} fill={w.flag ? '#ffbf69' : w.baseline ? '#6ea2ff' : '#00e5ff'} stroke={w.flag ? '#020812' : 'none'}>
            <title>{`Window ${w.index + 1}: ${w.mean.toFixed(1)} bpm${w.z !== null ? ` · z ${w.z.toFixed(2)}` : ''}${w.flag ? ' · FLAG' : ''}${w.baseline ? ' · baseline' : ''}`}</title>
          </circle>)}
      <text x={W - R - 6} y={H - B - 8} textAnchor="end" fill="#ffbf69" fontSize="11" fontFamily="JetBrains Mono, monospace">SYNTHETIC DEMO</text>
    </svg>
  );
}

export function PhantomDemo() {
  const [scenario, setScenario] = useState<ScenarioId>('step');
  const [ranFor, setRanFor] = useState<ScenarioId | null>(null);
  const sc = SCENARIOS.find((s) => s.id === scenario)!;
  const run = useMemo(() => (ranFor ? (() => { const s = SCENARIOS.find((x) => x.id === ranFor)!; return { s, r: analyse(s.generate(), s.durationS) }; })() : null), [ranFor]);
  const res = run?.r;
  return (
    <section id="phantom" aria-labelledby="phantom-title" className="px-4 py-20 sm:px-6">
      <SectionHeader id="phantom" eyebrow="03 · PHANTOM interactive demo" title="Is this person still like themselves?">
        Pick a fixed control scenario, run it, and see how a frozen personal baseline turns heart-rate windows into
        <strong className="text-ink"> flag</strong>, <strong className="text-ink">no_flag</strong> or <strong className="text-ink">insufficient_data</strong>.
      </SectionHeader>
      <div className="mx-auto grid max-w-7xl gap-5 lg:grid-cols-[340px_1fr]">
        <div className="glass space-y-3 rounded-2xl p-4">
          <div className="flex items-center justify-between"><p className="mono-label">Control scenario</p><SyntheticBadge /></div>
          <div role="radiogroup" aria-label="Control scenario" className="space-y-2">
            {SCENARIOS.map((s) => (
              <button key={s.id} type="button" role="radio" aria-checked={scenario === s.id} onClick={() => setScenario(s.id)}
                className={cx('w-full rounded-xl border p-3 text-left transition', scenario === s.id ? 'border-teal-300 bg-teal-300/10' : 'border-line hover:border-line-strong')}>
                <span className="block text-sm font-semibold text-ink">{s.label}</span>
                <span className="mt-0.5 block text-xs text-ink-3">{s.description}</span>
              </button>
            ))}
          </div>
          <button type="button" onClick={() => setRanFor(scenario)} className="cta-primary flex w-full items-center justify-center gap-2 rounded-xl py-3 font-semibold">
            <Icon name="play" size={17} /> Run simulation
          </button>
          <p className="text-[11px] leading-snug text-ink-3">
            In-browser illustration of the published PHANTOM formulas on fixed synthetic data. It is <strong>not</strong> the validated
            Windows implementation, uses no backend, Bluetooth, account or personal data, and is not a diagnosis.
          </p>
        </div>

        <div className="glass min-w-0 rounded-2xl p-4 sm:p-5" aria-live="polite">
          {!res || !run ? (
            <div className="grid min-h-[360px] place-items-center text-center">
              <div><Icon name="activity" size={40} className="mx-auto text-teal-300" />
                <p className="mt-3 text-ink-2">Selected: <strong className="text-ink">{sc.label}</strong>. Press <em>Run simulation</em>.</p></div>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <span data-testid="phantom-outcome" className={cx('inline-flex items-center gap-2 rounded-full border px-3 py-1 text-sm font-semibold', OUTCOME[res.outcome].tone)}>
                  <Icon name={OUTCOME[res.outcome].icon} size={15} />{OUTCOME[res.outcome].label}
                </span>
                <SyntheticBadge />
                <span className="text-sm text-ink-2">{run.s.label}</span>
              </div>
              <Chart windows={res.windows} result={res} durationS={run.s.durationS} />
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-ink-3">
                <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-[#6ea2ff]" />baseline window</span>
                <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-[#00e5ff]" />analysed window</span>
                <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-[#ffbf69]" />flagged window</span>
                <span><span className="mr-1 inline-block h-2 w-3 bg-[#ff647c]/40" />unusable window (left empty)</span>
                <span>dashed band = baseline ± {THRESHOLD} robust spreads</span>
              </div>
              <dl className="grid gap-3 text-sm sm:grid-cols-4">
                <div className="rounded-xl border border-line p-3"><dt className="mono-label">Baseline (median)</dt><dd className="mt-1 text-lg font-semibold tabular">{res.median !== null ? `${res.median.toFixed(1)} bpm` : '—'}</dd></div>
                <div className="rounded-xl border border-line p-3"><dt className="mono-label">Robust spread s</dt><dd className="mt-1 text-lg font-semibold tabular">{res.scale !== null ? `${res.scale.toFixed(2)} bpm` : '—'}</dd></div>
                <div className="rounded-xl border border-line p-3"><dt className="mono-label">Largest z</dt><dd className="mt-1 text-lg font-semibold tabular">{res.maxZ !== null ? res.maxZ.toFixed(2) : '—'}</dd></div>
                <div className="rounded-xl border border-line p-3"><dt className="mono-label">Windows flagged</dt><dd className="mt-1 text-lg font-semibold tabular">{res.flaggedWindows} / {res.testWindows}</dd></div>
              </dl>
              <div className="rounded-xl border border-line bg-canvas/50 p-4 text-sm leading-relaxed text-ink-2">
                <p><strong className="text-ink">Why: </strong>{res.reason}</p>
                <p className="mt-2">{OUTCOME[res.outcome].meaning}</p>
                {run.s.id === 'bursts' && <p className="mt-2 text-attention">Known limitation shown on purpose: brief activity of ≥ one 5-minute window also produces a flag.</p>}
              </div>
              <details className="text-sm text-ink-2">
                <summary className="cursor-pointer text-ink">How the comparison is computed</summary>
                <ol className="mt-2 list-decimal space-y-1 pl-5">
                  <li>Split the recording into 5-minute windows; a window is usable only with ≥ 20 valid samples, ≥ 240 s covered, gaps ≤ 60 s and ≥ 80 % valid (no-contact samples are invalid).</li>
                  <li>Baseline = usable windows of the first 60 minutes (≥ 10 needed), frozen. M = median of window means.</li>
                  <li>Robust spread s = max(3 bpm, 1.4826 · MAD)<Cite ids={['mad']} />.</li>
                  <li>Each later window: z = |mean − M| / s; flag when z ≥ {THRESHOLD}<Cite ids={['nist']} />.</li>
                </ol>
              </details>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
