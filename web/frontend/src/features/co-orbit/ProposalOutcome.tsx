/**
 * API 1.0 proposal outcome (coorbit/apply and replan). A proposal is NEVER applied by the system:
 * `before` is the schedule in force, `after` is what stays in force / the valid proposal, `proposal` is the solver result.
 * A rejected optimisation is shown as rejected – with the backend's reason and next actions – and the current
 * schedule stays visible.
 */
import type { EngineRun, ProposalOutcome as Outcome, EngineStrategy } from '../../api/types';
import { Icon, Notice, Pill } from '../../ui';
import { EngineSchedule, solverLabel } from '../shared/EngineCards';

export function decisionLabel(o: Outcome): { text: string; tone: 'good' | 'attention' | 'high' } {
  if (o.decision_status === 'rejected_no_feasible_schedule' || !o.valid) return { text: 'Rejected – no feasible schedule', tone: 'high' };
  if (o.requires_review) return { text: 'Proposal ready – needs review', tone: 'attention' };
  return { text: 'Proposal ready – not applied', tone: 'good' };
}

export function ProposalOutcomeView({ run, outcome, before, after, testId }: { run: EngineRun; outcome: Outcome; before: EngineStrategy; after: EngineStrategy; testId: string }) {
  const d = decisionLabel(outcome);
  const rejected = d.tone === 'high';
  const proposal = outcome.proposal;
  return (
    <div className="space-y-3" data-testid={testId} data-decision-status={outcome.decision_status ?? (outcome.valid ? 'proposal_ready' : 'rejected')}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Pill tone={d.tone} icon={rejected ? 'alert' : 'checkCircle'}>{d.text}</Pill>
        <Pill tone="unknown">not applied automatically</Pill>
        {outcome.previous_schedule_preserved && <Pill tone="info">current schedule kept</Pill>}
      </div>
      {outcome.reason && <Notice tone={rejected ? 'high' : outcome.requires_review ? 'attention' : 'good'} title={rejected ? 'Why the optimisation failed' : 'Solver result'}>{outcome.reason}</Notice>}
      {outcome.dropped_tasks && outcome.dropped_tasks.length > 0 && (
        <Notice tone="attention" title="Tasks that would no longer fit (optional tasks only)">
          <ul className="list-disc pl-4">{outcome.dropped_tasks.map((t) => <li key={t.task_id}>{t.title}: {t.reason}</li>)}</ul>
        </Notice>
      )}
      {rejected && outcome.next_actions && outcome.next_actions.length > 0 && (
        <div className="rounded-lg border border-line p-2 text-sm">
          <div className="mb-1 text-xs text-ink-3">What you can do next</div>
          <ul className="list-disc space-y-0.5 pl-5 text-ink-2">{outcome.next_actions.map((a) => <li key={a}>{a}</li>)}</ul>
        </div>
      )}
      {rejected ? (
        <div>
          <div className="mb-1 flex items-center gap-2 text-xs text-ink-3"><Icon name="checkCircle" size={12} />Schedule in force (unchanged)</div>
          <EngineSchedule run={run} strategy={after} label="Schedule in force – unchanged" />
          {proposal && <p className="mt-2 text-xs text-ink-3">Rejected solver result: {solverLabel(proposal).text}{proposal.validation_errors?.length ? ` · ${proposal.validation_errors.join('; ')}` : ''}.</p>}
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          <div><div className="mb-1 text-xs text-ink-3">Current schedule (in force)</div><EngineSchedule run={run} strategy={before} label="Current schedule" /></div>
          <div><div className="mb-1 text-xs text-ink-3">Proposed schedule – awaiting crew / flight-surgeon decision</div><EngineSchedule run={run} strategy={after} label="Proposed schedule" /></div>
        </div>
      )}
    </div>
  );
}
