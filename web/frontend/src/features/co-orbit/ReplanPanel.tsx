import { useState } from 'react';
import type { EngineRun, ReplanResult } from '../../api/types';
import { useApp } from '../../state/AppState';
import { Button, Notice } from '../../ui';
import { clock } from '../shared/EngineCards';
import { ProposalOutcomeView } from './ProposalOutcome';

/** CO-ORBIT replan(): add a rest window for one person and/or an urgent task, then re-optimise (0.9). Never removes availability. */
export function ReplanPanel({ run }: { run: EngineRun }) {
  const { api } = useApp();
  const [crew, setCrew] = useState(run.crew[0]?.id ?? 1);
  const [restStart, setRestStart] = useState(600);
  const [restLen, setRestLen] = useState(60);
  const [urgent, setUrgent] = useState(true);
  const [res, setRes] = useState<ReplanResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const go = () => {
    setBusy(true); setErr(null);
    api.engineReplan(run.id, {
      crew_updates: restLen > 0 ? [{ id: crew, add_rest: [{ start: restStart, end: restStart + restLen }] }] : [],
      task_updates: urgent ? [{ id: 'urgent_repair', title: 'Urgent life-support repair', duration_minutes: 60, priority: 5, required_skills: ['maintenance'], earliest: 600, deadline: 960 }] : [],
    }).then(setRes, (e: Error) => setErr(e.message)).finally(() => setBusy(false));
  };
  return (
    <section aria-label="Re-plan after a change" className="mt-4 rounded-lg border border-line p-3 text-sm">
      <h3 className="text-sm font-semibold text-ink">Re-plan after a change</h3>
      <div className="mt-2 flex flex-wrap items-end gap-3 text-xs text-ink-3">
        <label>Crew member <select aria-label="Re-plan crew member" className="ml-1 rounded border border-line bg-surface px-1 text-ink" value={crew} onChange={(e) => setCrew(Number(e.target.value))}>{run.crew.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
        <label>Extra rest from <input aria-label="Extra rest start minute" type="number" step={15} min={0} max={1380} className="ml-1 w-16 rounded border border-line bg-transparent px-1 text-ink" value={restStart} onChange={(e) => setRestStart(Number(e.target.value))} /> ({clock(restStart)})</label>
        <label>for <input aria-label="Extra rest minutes" type="number" step={15} min={0} max={240} className="ml-1 w-14 rounded border border-line bg-transparent px-1 text-ink" value={restLen} onChange={(e) => setRestLen(Number(e.target.value))} /> min</label>
        <label className="flex items-center gap-1"><input type="checkbox" checked={urgent} onChange={(e) => setUrgent(e.target.checked)} />Add urgent repair task (60 min, priority 5)</label>
        <Button size="sm" icon="rotate" disabled={busy} onClick={go}>{busy ? 'Re-planning…' : 'Re-plan'}</Button>
      </div>
      {err && <Notice tone="high" className="mt-2">{err}</Notice>}
      {res && <div className="mt-3 space-y-2">
        <ProposalOutcomeView run={{ ...run, schedules: { ...run.schedules, tasks: [...run.schedules.tasks, ...res.tasks.filter((t) => !run.schedules.tasks.some((x) => x.id === t.id)).map((t) => ({ ...t, duration_minutes: 60, people: 1, skills: [], dependencies: [], equipment: {} }))] } }}
          outcome={res} before={res.before} after={res.after} testId="replan-result" />
        {res.valid && <p className="text-xs text-ink-2">Changes: {Object.entries(res.comparison.delta).map(([k, v]) => `${k} ${typeof v === 'number' ? (v > 0 ? '+' : '') + Math.round(v * 100) / 100 : v}`).join(' · ')}</p>}
        <p className="text-xs text-ink-3">Decision support only: the crew or flight controllers decide whether to adopt the re-plan.</p>
      </div>}
    </section>
  );
}
