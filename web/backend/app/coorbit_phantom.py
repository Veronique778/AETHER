"""PHANTOM → CO-ORBIT: human-approved workload constraints for the MILP scheduler (AETHER 0.9).

Flow:
  1. PHANTOM 2.0 flags in the recent part of an engine run are turned into *recommendations* per crew member
     (reduce daily work, protect a rest window, shorten continuous work blocks). Rules are explicit and listed
     in RULES; each recommendation states the signals behind it.
  2. Nothing is applied automatically. A named person must approve individual recommendations.
  3. Approved recommendations become planning constraints (Crew fields of the MILP model); the schedule is
     re-optimised, validated, compared before/after and every change is explained.

Safety: no rule removes a person from the schedule or sets availability to zero – a statistical deviation is
not a medical decision. Constraints only reduce load or add rest; at least half of the original daily work
capacity is always kept.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from . import phantom2_engine as pe

RECENT_FRACTION = .25       # recommendations look at the most recent quarter of the run
MIN_FLAGGED_SHARE = .2      # a person needs ≥ 20 % flagged recent samples to get a recommendation
MIN_CAPACITY_SHARE = .5     # never cut a person's work below half of what the current plan gives them

RULES = {
    'reduce_workload': {'metrics': {'fatigue', 'workload', 'cognition'},
                        'summary': 'Reduce maximum daily work and weighted load by 25 %',
                        'why': 'fatigue / workload / cognition deviate unfavourably from the personal baseline'},
    'protected_rest': {'metrics': {'sleep_hours', 'sleep_quality'},
                       'summary': 'Protect a 60-minute rest window at 13:00–14:00',
                       'why': 'sleep duration / quality deviate unfavourably from the personal baseline'},
    'shorter_blocks': {'metrics': {'heart_rate', 'activity'},
                       'summary': 'Limit continuous work blocks to 60 min with 20-min breaks',
                       'why': 'heart rate / activity deviate from the personal baseline'},
}


def _rid(run_id: str, cid: int, kind: str) -> str:
    return 'rec-' + hashlib.sha256(f'{run_id}:{cid}:{kind}'.encode()).hexdigest()[:10]


def recommendations(sim, phantom_input, baseline_dataset: dict | None = None) -> list[dict]:
    payload = phantom_input(sim.dataset)
    res = pe.detect(payload, explain=True, baseline_payload=phantom_input(baseline_dataset) if baseline_dataset else None)
    flags, details = res['flags']['phantom2'], res['details']
    crew = {c.id: c for c in sim.plan.crew}
    by_crew: dict[int, list] = {}
    for s in payload['samples']:
        by_crew.setdefault(s['crew_id'], []).append(s)
    recs = []
    for cid, samples in sorted(by_crew.items()):
        samples.sort(key=lambda s: s['timestamp'])
        recent = samples[int(len(samples) * (1 - RECENT_FRACTION)):]
        flagged = [s for s in recent if flags.get(s['sample_id'])]
        share = len(flagged) / max(1, len(recent))
        if share < MIN_FLAGGED_SHARE:
            continue
        # which metrics drive the flags: mean unfavourable z over flagged samples (attribution as tie-breaker)
        zsum: dict[str, float] = {}
        for s in flagged:
            d = details.get(s['sample_id']) or {}
            for m, z in (d.get('z') or {}).items():
                zsum[m] = zsum.get(m, 0) + max(0.0, z)
        mean_z = {m: v / len(flagged) for m, v in zsum.items()}
        drivers = sorted(((m, z) for m, z in mean_z.items() if z >= 1.0), key=lambda x: -x[1])
        for kind, rule in RULES.items():
            hit = [(m, z) for m, z in drivers if m in rule['metrics']]
            if not hit:
                continue
            recs.append({
                'id': _rid(sim.scenario.id, cid, kind), 'crew_id': cid, 'crew_name': crew[cid].name, 'kind': kind,
                'summary': rule['summary'], 'flagged_share': round(share, 2),
                'signals': [{'metric': m, 'mean_unfavourable_z': round(z, 2)} for m, z in hit],
                'reason': f"{crew[cid].name}: {int(share * 100)} % of recent samples flagged by PHANTOM 2.0; {rule['why']} "
                          f"({', '.join(f'{m} z̄={z:.1f}' for m, z in hit)}).",
                'requires_human_approval': True,
                'evidence_level': 'statistical deviation from a personal baseline (synthetic data) – not a diagnosis',
            })
    return recs


def constraints_for(plan, approved: list[dict], before: dict | None = None) -> list[dict]:
    """Crew updates for the MILP model; never removes availability.

    reduce_workload caps daily work at 75 % of what the current schedule (`before`) gives the person – a cap on the
    nominal maximum alone is usually not binding (0.9 validation, experiment 4) – and never below 50 % of it."""
    updates: dict[int, dict] = {}
    worked = {}
    if before is not None:
        wm = before['metrics']['work_minutes']
        worked = {c.id: float(wm.get(str(c.id), wm.get(c.id, 0))) for c in plan.crew}
    for rec in approved:
        c = next(x for x in plan.crew if x.id == rec['crew_id'])
        u = updates.setdefault(c.id, {'id': c.id})
        if rec['kind'] == 'reduce_workload':
            ref = worked.get(c.id) or c.max_work_minutes_per_day
            cap = int(ref * .75 // 15 * 15)
            floor = int(-(-ref * MIN_CAPACITY_SHARE // 15) * 15)
            u['max_work_minutes_per_day'] = min(c.max_work_minutes_per_day, max(cap, floor, 15))
            u['max_load_per_day'] = round(max(c.max_load_per_day * MIN_CAPACITY_SHARE, c.max_load_per_day * .75), 2)
        elif rec['kind'] == 'protected_rest':
            rest = [w.model_dump() for w in c.rest] + [{'start': 780, 'end': 840}]
            merged = []
            for w in sorted(rest, key=lambda w: w['start']):
                if merged and w['start'] <= merged[-1]['end']:
                    merged[-1]['end'] = max(merged[-1]['end'], w['end'])
                else:
                    merged.append(dict(w))
            u['rest'] = merged
        elif rec['kind'] == 'shorter_blocks':
            u['max_continuous_minutes'] = min(c.max_continuous_minutes, 60)
            u['break_minutes'] = max(c.break_minutes, 20)
    return list(updates.values())


def diff(plan, before: dict, after: dict, approved: list[dict]) -> dict:
    tasks = {t.id: t for t in plan.tasks}
    names = {c.id: c.name for c in plan.crew}
    b = {a['task_id']: a for a in before['assignments']}
    a_ = {a['task_id']: a for a in after['assignments']}
    changes, explanations = [], []
    why = {}
    for r in approved:
        why.setdefault(r['crew_id'], []).append(r['summary'].lower())
    for tid in sorted(set(b) | set(a_)):
        x, y = b.get(tid), a_.get(tid)
        title = tasks[tid].title if tid in tasks else tid
        if x and not y:
            changes.append({'task_id': tid, 'change': 'unscheduled'})
            explanations.append(f"“{title}” could not be scheduled under the approved constraints – review the trade-off.")
        elif y and not x:
            changes.append({'task_id': tid, 'change': 'newly scheduled'})
        elif x['crew_ids'] != y['crew_ids'] or x['start'] != y['start']:
            moved_from = [c for c in x['crew_ids'] if c not in y['crew_ids']]
            reason = '; '.join(f"{names[c]}: {', '.join(why.get(c, ['no constraint – re-optimised around the approved changes']))}" for c in (moved_from or x['crew_ids']))
            changes.append({'task_id': tid, 'change': 'reassigned' if moved_from else 'rescheduled',
                            'before': {'crew': [names[c] for c in x['crew_ids']], 'start': x['start']},
                            'after': {'crew': [names[c] for c in y['crew_ids']], 'start': y['start']}})
            explanations.append(f"“{title}”: {', '.join(names[c] for c in x['crew_ids'])} @ {x['start'] // 60:02d}:{x['start'] % 60:02d} → "
                                f"{', '.join(names[c] for c in y['crew_ids'])} @ {y['start'] // 60:02d}:{y['start'] % 60:02d} ({reason}).")
    mb, ma = before['metrics'], after['metrics']
    return {'changes': changes, 'explanations': explanations or ['The approved constraints did not change the optimal schedule.'],
            'metrics_before': mb, 'metrics_after': ma,
            'delta': {k: round(ma[k] - mb[k], 3) for k in ('scheduled_tasks', 'priority_score', 'total_work_minutes', 'max_load', 'load_std')},
            'work_minutes_before': mb['work_minutes'], 'work_minutes_after': ma['work_minutes']}


STRATEGY_KEYS = ('strategy', 'status', 'solver_status', 'valid', 'has_feasible_solution', 'optimality_proven', 'objective_value',
                 'reason', 'validation_errors', 'assignments', 'unscheduled', 'required_tasks', 'metrics', 'criteria', 'mip_gap')
NEXT_ACTIONS_FAILED = ['Approve fewer or different recommendations and re-plan.',
                       'Change the plan (task time window, team size, availability) and re-plan.',
                       'Cancel: nothing has been changed – the current schedule stays in force.']


def strategy_view(s: dict) -> dict:
    return {k: s[k] for k in STRATEGY_KEYS if k in s}


def _check_reviewer(name: str, ids: list[str], recs: list[dict], verb: str) -> list[dict]:
    if not name.strip():
        field = 'approved_by' if verb == 'approve' else 'reviewed_by'
        raise ValueError(f'A named person must {verb} PHANTOM-derived constraints ({field} is empty).')
    known = {r['id']: r for r in recs}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise ValueError(f'Unknown recommendation ids: {unknown}')
    if not ids:
        raise ValueError('No recommendation approved.' if verb == 'approve' else 'No recommendation selected.')
    return [known[i] for i in ids]


def apply(sim, approved_ids: list[str], approved_by: str, recs: list[dict], replan, store=None, note: str = '') -> dict:
    """Approved recommendations → constraints → re-optimised *proposal*. The run's schedule is never modified here.

    If the solver finds no validated feasible schedule, the decision is `rejected_no_feasible_schedule`: `valid` is
    False, the comparison shows no change and the current schedule (`before`) stays in force."""
    from mission_systems.co_orbit.optimization import dropped_tasks, preferred
    from mission_systems.co_orbit.scheduler import is_valid
    approved = _check_reviewer(approved_by, approved_ids, recs, 'approve')
    before = sim.schedules['alternatives'][1]
    updates = constraints_for(sim.plan, approved, before)
    new_plan, alts = replan(sim.plan, crew_updates=updates)
    after = preferred(alts)
    valid = is_valid(after)
    if valid:
        dropped = dropped_tasks(before, after, sim.plan)
        comparison = diff(sim.plan, before, after, approved)
        status = 'proposal_ready'
        reason = after.get('reason', '')
        if dropped:
            reason += f" {len(dropped)} task(s) scheduled today would no longer fit: " + ', '.join(d['title'] for d in dropped) + ' – review the trade-off.'
    else:
        dropped = []
        comparison = diff(sim.plan, before, before, approved)
        reason = 'No feasible schedule under the approved constraints: ' + (after.get('reason') or after.get('status', '')).removeprefix('No feasible schedule: ')
        comparison['explanations'] = [reason, 'The current schedule is kept unchanged.']
        status = 'rejected_no_feasible_schedule'
    out = {'approved_by': approved_by.strip(), 'approved_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
           'note': note, 'approved': approved, 'constraints': updates,
           'before': before,
           # rejected → `after` shows the schedule that stays in force; the failed solver result is in `proposal`
           'after': strategy_view(after) if valid else strategy_view(before),
           'proposal': strategy_view(after),
           'valid': valid, 'decision_status': status, 'reason': reason.strip(),
           'applied': False, 'previous_schedule_preserved': True,
           'dropped_tasks': dropped, 'requires_review': (not valid) or bool(dropped),
           'next_actions': [] if valid else NEXT_ACTIONS_FAILED,
           'comparison': comparison,
           'policy': 'Constraints only reduce load or add rest; no one is removed from the schedule. '
                     'The new schedule is a proposal for the crew / flight surgeon, not an automatic order.'}
    if store is not None:
        store.save('coorbit_decision', f"{sim.scenario.id}:{hashlib.sha256(json.dumps(approved_ids).encode()).hexdigest()[:8]}", out)
    return out


def reject(sim, rejected_ids: list[str], reviewed_by: str, recs: list[dict], store=None, note: str = '') -> dict:
    """Human rejection of recommendations: recorded for audit, changes nothing in the plan or schedule."""
    rejected = _check_reviewer(reviewed_by, rejected_ids, recs, 'review')
    out = {'reviewed_by': reviewed_by.strip(), 'reviewed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
           'note': note, 'rejected': rejected, 'decision_status': 'rejected_by_human', 'changed': False,
           'schedule': strategy_view(sim.schedules['alternatives'][1]),
           'policy': 'Rejected recommendations are recorded only; plan and schedule are unchanged.'}
    if store is not None:
        store.save('coorbit_decision', f"{sim.scenario.id}:reject:{hashlib.sha256(json.dumps(rejected_ids).encode()).hexdigest()[:8]}", out)
    return out
