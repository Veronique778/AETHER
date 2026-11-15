/**
 * CO-ORBIT ← PHANTOM (AETHER 1.0): recommendations derived from PHANTOM 2.0 flags, turned into a MILP
 * scheduler only after a named person approves them. Shows the schedule before/after and why it changed.
 */
import { useEffect, useState } from 'react';
import type { CoorbitDecision, CoorbitRecommendations, CoorbitRejection, EngineRun } from '../../api/types';
import { CAPABILITIES } from '../../api/types';
import { useApp } from '../../state/AppState';
import { Button, cx, Icon, Notice, Pill } from '../../ui';
import { ProposalOutcomeView } from './ProposalOutcome';

export function PhantomConstraints({ run }: { run: EngineRun }) {
  const { api, hasCapability, role } = useApp();
  const [recs, setRecs] = useState<CoorbitRecommendations | null>(null);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [approver, setApprover] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [decision, setDecision] = useState<CoorbitDecision | null>(null);
  const [rejection, setRejection] = useState<CoorbitRejection | null>(null);
  const canReject = hasCapability(CAPABILITIES.coorbitReject);
  const enabled = hasCapability(CAPABILITIES.coorbitPhantom);

  useEffect(() => {
    if (!enabled) return;
    setRecs(null); setDecision(null); setRejection(null); setSel(new Set()); setError(null);
    api.engineCoorbit(run.id).then(setRecs, (e: Error) => setError(e.message));
  }, [run.id, api, enabled]);

  if (!enabled) return null;
  const toggle = (id: string) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const apply = async () => {
    setBusy(true); setError(null); setRejection(null);
    try { setDecision(await api.engineCoorbitApply(run.id, { approved_ids: [...sel], approved_by: approver })); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const reject = async () => {
    setBusy(true); setError(null); setDecision(null);
    try { setRejection(await api.engineCoorbitReject(run.id, { rejected_ids: [...sel], reviewed_by: approver })); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <section aria-label="PHANTOM-derived planning constraints" className="mt-4 rounded-xl border border-line p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-ink">PHANTOM → CO-ORBIT · human-approved constraints</h3>
        <Pill tone="info" icon="users">approval required</Pill>
      </div>
      {!recs && !error && <p className="text-sm text-ink-3" role="status">Reading PHANTOM 2.0 flags…</p>}
      {recs && recs.recommendations.length === 0 && <p className="text-sm text-ink-2">PHANTOM 2.0 flags fewer than 20 % of anyone’s recent samples – no change to the plan is suggested.</p>}
      {recs && recs.recommendations.length > 0 && (
        <>
          <ul className="space-y-2" aria-label="Recommendations">
            {recs.recommendations.map((r) => (
              <li key={r.id} className={cx('rounded-lg border p-2 text-sm', sel.has(r.id) ? 'border-teal-300 bg-teal-600/10' : 'border-line')}>
                <label className="flex cursor-pointer items-start gap-2">
                  <input type="checkbox" className="mt-1" checked={sel.has(r.id)} onChange={() => toggle(r.id)} aria-label={`Approve: ${r.crew_name} – ${r.summary}`} />
                  <span><span className="font-medium text-ink">{r.crew_name}: {r.summary}</span>
                    <span className="block text-xs text-ink-2">{r.reason}</span>
                    <span className="block text-[11px] text-ink-3">{r.evidence_level}</span>
                    {r.environment_context && <span className="block text-[11px] text-ink-3">Cabin context: {r.environment_context.statement}</span>}</span>
                </label>
              </li>
            ))}
          </ul>
          <div className="mt-3 flex flex-wrap items-end gap-2">
            <label className="text-sm text-ink-2">Approved by
              <input className="field mt-1 w-56" value={approver} onChange={(e) => setApprover(e.target.value)} placeholder={role === 'crew' ? 'Name and role' : 'Flight surgeon name'} />
            </label>
            <Button variant="primary" icon="check" disabled={busy || sel.size === 0 || !approver.trim()} onClick={apply}>{busy ? 'Working…' : `Approve ${sel.size} → compute proposal`}</Button>
            {canReject && <Button variant="ghost" disabled={busy || sel.size === 0 || !approver.trim()} onClick={reject}>Reject {sel.size}</Button>}
          </div>
          <p className="mt-2 text-xs text-ink-3"><Icon name="info" size={12} className="mr-1 inline" />{recs.policy}</p>
        </>
      )}
      {error && <Notice tone="high" className="mt-2">{error}</Notice>}
      {rejection && (
        <Notice tone="info" className="mt-3" title="Recommendations rejected – nothing changed">
          {rejection.rejected.length} recommendation(s) rejected by {rejection.reviewed_by} at {rejection.reviewed_at.replace('T', ' ')}. {rejection.policy}
        </Notice>
      )}
      {decision && (
        <div className="mt-4 space-y-3">
          <p className="text-xs text-ink-3">Reviewed by {decision.approved_by} · {decision.approved_at.replace('T', ' ')}</p>
          <ProposalOutcomeView run={run} outcome={decision} before={decision.before} after={decision.after} testId="coorbit-decision" />
          {decision.valid && <>
            <table className="tabular text-xs"><caption className="mb-1 text-left text-ink-3">Change (proposal − current)</caption><tbody>
              {Object.entries(decision.comparison.delta).map(([k, v]) => <tr key={k}><td className="pr-4 text-ink-2">{k.replace(/_/g, ' ')}</td><td className={v ? 'text-ink' : 'text-ink-3'}>{v > 0 ? '+' : ''}{v}</td></tr>)}
              {run.crew.map((c) => <tr key={c.id}><td className="pr-4 text-ink-2">work minutes · {c.name}</td><td>{decision.comparison.work_minutes_before[String(c.id)] ?? 0} → {decision.comparison.work_minutes_after[String(c.id)] ?? 0}</td></tr>)}
            </tbody></table>
            <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2" aria-label="Why the schedule changed">{decision.comparison.explanations.map((x) => <li key={x}>{x}</li>)}</ul>
          </>}
          <p className="text-xs text-ink-3">{decision.policy}</p>
        </div>
      )}
    </section>
  );
}
