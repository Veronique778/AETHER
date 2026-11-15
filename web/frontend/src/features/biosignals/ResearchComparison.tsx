import { useApp } from '../../state/AppState';
import { useBiosignal, bioApi } from './BiosignalPage';
import { useState } from 'react';
import { Button } from '../../ui';

export function ResearchComparison() {
  const { engineRun } = useApp(); const { sessionId } = useBiosignal();
  const [recorded, setRecorded] = useState<any>(null); const [error, setError] = useState('');
  const compare = async () => {
    setError(''); try { setRecorded({ session: await bioApi('/sessions/' + sessionId), analysis: await bioApi('/sessions/' + sessionId + '/analysis') }); } catch (e) { setError((e as Error).message); }
  };
  const values = engineRun ? Object.values(engineRun.series).flatMap(s => s.heart_rate).filter((v): v is number => v != null) : [];
  const summary = values.length ? { samples: values.length, mean_hr_bpm: values.reduce((x, y) => x + y, 0) / values.length, min_hr_bpm: Math.min(...values), max_hr_bpm: Math.max(...values) } : null;
  const result = { comparison: 'Descriptive comparison; different populations and sampling policies, not efficacy validation', synthetic: engineRun ? { id: engineRun.id, template: engineRun.template, seed: engineRun.seed, source: engineRun.origin, sample_minutes: engineRun.sample_minutes, summary, labelled_evaluation: engineRun.evaluation } : null, recording: recorded };
  return <section className="card mb-5 space-y-3 p-5"><h2 className="text-lg font-semibold">Research comparison · simulation and recorded humans</h2>
    <p className="text-sm text-ink-3">Run a synthetic Mission Systems scenario in the engine tab, then select a recording in BIOSIGNALS. These sources keep independent identities, clocks and environmental context.</p>
    <p>Synthetic run: {engineRun ? `${engineRun.title} · seed ${engineRun.seed}` : 'none selected'} · recording: {sessionId || 'none selected'}</p>
    <Button disabled={!sessionId || !engineRun} onClick={() => void compare()}>Compare selected sources</Button>
    {error && <p role="alert">{error}</p>}
    {recorded && <><div className="grid gap-4 md:grid-cols-2"><div><strong>Synthetic mission</strong><pre className="whitespace-pre-wrap text-xs">{JSON.stringify({ summary, evaluation: engineRun?.evaluation }, null, 2)}</pre></div><div><strong>{recorded.session.source_type} · {recorded.session.participant}</strong><p>Method: {recorded.analysis.method}</p><p>Baseline HR: {recorded.analysis.baseline_hr_bpm ?? 'insufficient'} bpm · flag rate: {recorded.analysis.flag_rate ?? 'unavailable'}</p><p className="text-sm text-ink-3">{recorded.analysis.uncertainty}</p></div></div>
      <p className="text-sm text-ink-3">Synthetic event metrics rely on synthetic labels. The recording has no event ground truth; its flag rate is not a false-positive rate. Synthetic cabin CO₂ and radiation are never attributed to the research participant.</p>
      <Button onClick={() => { const u = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' })); const a = document.createElement('a'); a.href = u; a.download = 'AETHER-source-comparison.json'; a.click(); setTimeout(() => URL.revokeObjectURL(u), 1000); }}>Export comparison</Button></>}
  </section>;
}
