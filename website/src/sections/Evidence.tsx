import { SOURCES } from '../data/sources';
import { Icon, cx } from '../vendor/aether/ui';
import { Cite, Reveal, SectionHeader } from './common';

const BENCH = [
  ['Stable (no event)', '0 / 60 records flagged', '0 false alarms in 120 h', 'good'],
  ['+5 bpm sustained', '10 / 60 detected (17 %)', 'below the ≈ 10 bpm floor', 'attention'],
  ['+10 bpm sustained', '50 / 60 detected (83 %)', 'median delay 9.5 min', 'info'],
  ['+15 bpm sustained', '59 / 60 detected (98 %)', 'Wilson 95 % [0.911; 0.997]', 'good'],
  ['+20 bpm sustained', '60 / 60 detected (100 %)', 'median delay 7.5 min', 'good'],
  ['Short bursts (not sustained)', '59 / 60 flagged', '1.73 false alarms / h', 'high'],
  ['< 60 min baseline', '60 / 60 insufficient_data', 'never a guess', 'good'],
] as const;

const STATUS: { label: string; state: string; tone: 'good' | 'attention' | 'high'; text: string }[] = [
  { label: 'Synthetic benchmark', state: 'done', tone: 'good', text: 'Pre-registered protocol; one run on held-out seeds (17 scenarios × 60 synthetic subjects).' },
  { label: 'Numerical correctness', state: 'done', tone: 'good', text: '26 reference checks of median, MAD, scale, z, windows, RR conversion and data quality rules.' },
  { label: 'Human-data validation', state: 'not done', tone: 'attention', text: 'No external validation on recorded humans yet; MMASH is the planned next step.' },
  { label: 'Physical Bluetooth', state: 'not verified', tone: 'attention', text: 'Standard Heart Rate Service path is implemented and tested with test doubles; no physical strap verified yet.' },
  { label: 'Clinical / astronaut use', state: 'none', tone: 'high', text: 'Not a medical device, no clinical accuracy claimed, no NASA approval or endorsement.' },
];

export function Evidence() {
  return (
    <section id="evidence" aria-labelledby="evidence-title" className="px-4 py-20 sm:px-6">
      <SectionHeader id="evidence" eyebrow="04 · Scientific evidence" title="What we can show — and what we cannot yet">
        PHANTOM is deliberately simple, so every step can be checked. Results below are from a controlled synthetic heart-rate
        generator: they describe the detector on a model, not accuracy on people.
      </SectionHeader>
      <div className="mx-auto grid max-w-7xl gap-5 lg:grid-cols-3">
        <Reveal className="glass min-w-0 rounded-2xl p-5">
          <h3 className="flex items-center gap-2 text-lg font-semibold"><Icon name="sliders" size={18} className="text-teal-300" />Mathematical basis</h3>
          <div className="mt-4 space-y-3 font-mono text-[13px] text-ink">
            <p className="rounded-lg border border-line bg-canvas/60 p-2.5">M = median(x̄₁ … x̄ₙ), first hour, frozen</p>
            <p className="rounded-lg border border-line bg-canvas/60 p-2.5">s = max(3 bpm, 1.4826 · MAD)</p>
            <p className="rounded-lg border border-line bg-canvas/60 p-2.5">z = |x̄_window − M| / s ; flag ⇔ z ≥ 3.5</p>
          </div>
          <p className="mt-3 text-sm text-ink-2">Robust statistics resist outliers in the baseline<Cite ids={['mad', 'nist']} />. The 3.5 threshold and 3 bpm floor are heuristic and uncalibrated on human events; together they set a minimum detectable shift of ≈ 10 bpm.</p>
        </Reveal>
        <Reveal className="glass min-w-0 rounded-2xl p-5 lg:col-span-2">
          <h3 className="flex items-center gap-2 text-lg font-semibold"><Icon name="table" size={18} className="text-teal-300" />Synthetic benchmark (test split)</h3>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[520px] text-left text-sm">
              <caption className="sr-only">PHANTOM record-level results on the synthetic test split, 60 synthetic subjects per scenario</caption>
              <thead><tr className="border-b border-line text-ink-3"><th className="py-2 pr-3 font-medium">Scenario</th><th className="py-2 pr-3 font-medium">Result</th><th className="py-2 font-medium">Note</th></tr></thead>
              <tbody>{BENCH.map(([s, r, n, tone]) => (
                <tr key={s} className="border-b border-line/60">
                  <td className="py-2 pr-3 text-ink">{s}</td>
                  <td className={cx('py-2 pr-3 tabular', tone === 'high' ? 'text-high' : tone === 'attention' ? 'text-attention' : 'text-ink')}>{r}</td>
                  <td className="py-2 text-ink-2">{n}</td>
                </tr>))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-ink-3">Zero false alarms in the stable scenario is a property of the stationary generator. Real life (movement, posture, caffeine) will produce many more false alarms — the short-burst row shows why.</p>
        </Reveal>
      </div>
      <div className="mx-auto mt-5 grid max-w-7xl gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {STATUS.map((s) => (
          <Reveal key={s.label} className="glass rounded-2xl p-4">
            <p className="mono-label">{s.label}</p>
            <p className={cx('mt-2 inline-flex rounded-full border px-2.5 py-0.5 text-xs font-semibold', s.tone === 'good' ? 'border-good/60 text-good' : s.tone === 'attention' ? 'border-attention/60 text-attention' : 'border-high/60 text-high')}>{s.state}</p>
            <p className="mt-2 text-xs leading-relaxed text-ink-2">{s.text}</p>
          </Reveal>
        ))}
      </div>
      <div className="mx-auto mt-8 max-w-7xl">
        <h3 className="mono-label mb-3">Sources</h3>
        <ul className="grid gap-2 sm:grid-cols-2">
          {Object.values(SOURCES).map((s) => (
            <li key={s.id}>
              <a href={s.url} target="_blank" rel="noopener noreferrer" className="glow-hover block rounded-xl border border-line p-3 text-sm">
                <span className="flex items-center gap-2 font-medium text-ink"><span className="font-mono text-[10px] text-teal-300">{s.id}</span>{s.label}<Icon name="arrowRight" size={13} className="ml-auto text-ink-3" /></span>
                <span className="mt-1 block text-xs text-ink-3">{s.detail}</span>
              </a>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
