import { CAPABILITIES, type MetricKey, type RecoveryActivity, type RecoverySession } from '../../api/types';
import { METRICS } from '../../lib/format';
import { navigate } from '../../lib/router';
import { useResource } from '../../lib/useResource';
import { useApp } from '../../state/AppState';
import { useScenarioRun } from '../../state/scenario';
import { Button, Icon, Pill, SourceBadge } from '../../ui';

/**
 * RECOVERY end of the cross-module chain (MISSION LAB → BODY → PHANTOM → SYMBIOSIS → CO-ORBIT → RECOVERY).
 * Transparent rules map the signals PHANTOM flags – on the recorded day and, if a scenario is applied, on the
 * modelled scenario day – to the activities that address them, ranked with the person's own before/after history.
 * Suggestions, not prescriptions; no activity here treats a physiological condition.
 */
const RULES: Record<MetricKey, { activities: RecoveryActivity[]; why: string }> = {
  sleep_hours: { activities: ['zero-g-garden', 'earth-window'], why: 'shorter sleep – slow paced breathing and a quiet rest window before the sleep period' },
  heart_rate_bpm: { activities: ['zero-g-garden'], why: 'higher resting heart rate – paced breathing at ~6 breaths/min' },
  fatigue_1_10: { activities: ['earth-window', 'zero-g-garden'], why: 'higher self-reported fatigue – low-effort restorative break' },
  reaction_ms: { activities: ['mind-pulse', 'earth-window'], why: 'slower reaction – re-check with Mind Pulse after a short rest (a measurement, not a treatment)' },
  activity_minutes: { activities: ['orbit-flow'], why: 'less physical activity – no RECOVERY activity replaces exercise (see the CO-ORBIT exercise block); Orbit Flow offers light engagement' },
};
const NAMES: Record<RecoveryActivity, string> = { 'zero-g-garden': 'Zero-G Garden', 'earth-window': 'Earth Window', 'orbit-flow': 'Orbit Flow', 'mind-pulse': 'Mind Pulse' };

export function RecoveryRecommendations({ sessions }: { sessions?: RecoverySession[] }) {
  const { api, astronautId, day, dataVersion, scenario, engineRun, hasCapability } = useApp();
  const actual = useResource(`rec-ph-${api.mode}-${astronautId}-${day}-${dataVersion}`, () => api.phantom(astronautId, day));
  const p2on = hasCapability(CAPABILITIES.phantom2);
  const p2 = useResource(p2on ? `rec-p2-${api.mode}-${astronautId}-${day}-${dataVersion}` : null, () => api.phantom2(astronautId, day));
  const modelled = useScenarioRun();
  const sources: { label: string; keys: MetricKey[] }[] = [];
  if (actual.data) sources.push({ label: `recorded day ${day}`, keys: actual.data.signals.filter((s) => s.flagged).map((s) => s.key) });
  if (scenario && modelled.data) sources.push({ label: `scenario “${scenario.title}”, model`, keys: modelled.data.phantom.signals.filter((s) => s.flagged).map((s) => s.key) });

  // PHANTOM 2.0: when today's multivariate decision is a flag, the signals that carry the distance in the
  // unfavourable direction (attribution ≥ 15 %, z ≥ 1) also feed the rules, weighted by their share.
  const p2keys = p2Drivers(p2.data);
  const score = new Map<RecoveryActivity, { pts: number; reasons: string[] }>();
  const add = (k: MetricKey, label: string, weight: number) => {
    RULES[k].activities.forEach((a, i) => {
      const cur = score.get(a) ?? { pts: 0, reasons: [] };
      cur.pts += (i === 0 ? 2 : 1) * weight;
      const r = `${METRICS[k].label}: ${RULES[k].why} (${label})`;
      if (!cur.reasons.includes(r)) cur.reasons.push(r);
      score.set(a, cur);
    });
  };
  for (const src of sources) for (const k of src.keys) add(k, src.label, 1);
  for (const d of p2keys) add(d.key, `PHANTOM 2.0: ${Math.round(d.share * 100)} % of today’s multivariate distance, z +${d.z.toFixed(1)}`, 0.5 + d.share);
  const personal = (a: RecoveryActivity) => {
    const mine = sessions?.filter((s) => s.activity === a) ?? [];
    return mine.length ? mine.reduce((t, s) => t + s.after_mood - s.before_mood, 0) / mine.length : null;
  };
  const ranked = [...score.entries()].map(([a, v]) => ({ a, ...v, mood: personal(a) }))
    .sort((x, y) => y.pts - x.pts || (y.mood ?? 0) - (x.mood ?? 0)).slice(0, 3);
  const co2High = scenario && scenario.params.co2_ppm >= 2000;
  const engineFlags = engineRun ? Object.values(engineRun.phantom_flags).reduce((t, f) => t + f.length, 0) : 0;

  return (
    <section aria-label="Suggested recovery activities" className="card mb-5 p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div><div className="mono-label text-teal-300">Suggested for today · from PHANTOM{scenario ? ' and the applied scenario' : ''}</div>
          <h2 className="text-base font-semibold text-calm">What might help right now</h2></div>
        <SourceBadge source="estimated" />
      </div>
      {actual.loading && !actual.data ? <p className="text-sm text-ink-3">Reading PHANTOM…</p> : ranked.length === 0 ? (
        <p className="text-sm text-ink-2">No signal is flagged{scenario ? ' on the recorded or modelled day' : ''} – any activity is fine; choose what you enjoy.</p>
      ) : (
        <ul className="grid gap-3 md:grid-cols-3">
          {ranked.map((r, i) => (
            <li key={r.a} className="flex flex-col gap-2 rounded-xl border border-line p-3">
              <div className="flex items-center gap-2"><span className="grid h-6 w-6 place-items-center rounded-md bg-teal-600/30 text-xs font-bold text-teal-100">{i + 1}</span><span className="font-semibold text-calm">{NAMES[r.a]}</span>
                {r.mood != null && <Pill tone={r.mood > 0 ? 'good' : 'unknown'}>you: {r.mood >= 0 ? '+' : ''}{r.mood.toFixed(1)} mood</Pill>}</div>
              <ul className="list-disc space-y-0.5 pl-4 text-xs text-ink-2">{r.reasons.slice(0, 3).map((x) => <li key={x}>{x}</li>)}</ul>
              <Button size="sm" variant="primary" icon="play" className="mt-auto self-start" onClick={() => navigate(`/recovery/${r.a}`)}>Begin</Button>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-xs text-ink-3">
        <Icon name="info" size={12} className="mr-1 inline" />Transparent rules (flagged signal → activity), ranked by how often a rule fires and by your own mood change in past sessions. Suggestions, not prescriptions.
        {co2High && ' The applied scenario has elevated cabin CO₂ – that is an environment issue for SYMBIOSIS, not something a recovery activity fixes.'}
        {p2keys.length > 0 && ' PHANTOM 2.0 contributors are included with weight 0.5 + their share of the multivariate distance.'}
        {engineFlags > 0 && ` The current Mission Systems engine run has ${engineFlags} PHANTOM-flagged crew samples.`}
      </p>
    </section>
  );
}

const KEYS: MetricKey[] = ['heart_rate_bpm', 'sleep_hours', 'fatigue_1_10', 'reaction_ms', 'activity_minutes'];
/** Signals that drive a PHANTOM 2.0 flag in the unfavourable direction. Exported for unit tests. */
export function p2Drivers(r: { status: string; today: Record<string, boolean | null>; multivariate: { attribution: Record<string, number> | null }; z: Record<string, number> | null } | undefined) {
  if (!r || r.status !== 'ok' || !r.today.phantom2 || !r.multivariate.attribution || !r.z) return [];
  return KEYS.filter((k) => (r.multivariate.attribution![k] ?? 0) >= 0.15 && (r.z![k] ?? 0) >= 1)
    .map((k) => ({ key: k, share: r.multivariate.attribution![k], z: r.z![k] }))
    .sort((a, b) => b.share - a.share);
}
