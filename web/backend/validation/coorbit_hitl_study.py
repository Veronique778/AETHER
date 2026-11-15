"""AETHER 1.0 · B5 + B6.3 — CO-ORBIT human-in-the-loop check and counterfactual planning comparison.

    python validation/coorbit_hitl_study.py --out validation/results_1_0

Fresh seeds 201–230 (the 0.9 `reduce_workload` fix used held-out seed 101; 201–230 were never looked at).
Templates normal, sleep_loss, pulse_shift, fatigue_rise, multifactor with the `standard` plan (30 seeds) and sleep_loss,
multifactor with the 11-task `high_workload` plan (seeds 201–210; its MILP needs ≈10 s per strategy).
App protocol: 1-day run, personal baseline = preceding nominal day.

Per run, the ten HITL steps of the spec are checked and recorded (B5):
 1 PHANTOM returns recommendations · 2 they concern the labelled crew member · 3–5 a named reviewer rejects them and
 nothing changes · 6 approval forms constraints · 7 the MILP re-plans · 8 the schedule passes the solver's validator AND
 an independent check · 9 the workload change is shown · 10 tasks that no longer fit are listed with a reason.
Solver quality: feasibility, dependencies, equipment capacity, skills, daily work/load caps, rest, objective status
(optimal vs time-limited feasible – never called optimal unless proven), solve time.
Counterfactual (B6.3): Scenario A = current plan, Scenario B = plan with the approved constraints, same seed. Only planning
quantities are compared – the engine's physiological outputs use illustrative coefficients and are NOT an outcome.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db, mission_engine as me  # noqa: E402
from mission_systems.contracts import PlanningInput  # noqa: E402

STANDARD = (['normal', 'sleep_loss', 'pulse_shift', 'fatigue_rise', 'multifactor'], range(201, 231), 'standard')
HIGH = (['sleep_loss', 'multifactor'], range(201, 211), 'high_workload')


def independent_check(plan: PlanningInput, assignments: list[dict]) -> list[str]:
    """Written without the scheduler's code: skills, windows, overlaps + breaks, rest, caps, dependencies, equipment."""
    tasks = {t.id: t for t in plan.tasks}; crew = {c.id: c for c in plan.crew}; eq = {e.id: e for e in plan.equipment}
    bad = []
    by = {a['task_id']: a for a in assignments}
    for a in assignments:
        t = tasks[a['task_id']]
        if a['end'] - a['start'] != t.duration_minutes: bad.append(f'duration {t.id}')
        if a['start'] < t.earliest or a['end'] > min(t.deadline, plan.horizon_minutes): bad.append(f'window {t.id}')
        if len(set(a['crew_ids'])) != t.people: bad.append(f'team {t.id}')
        for d in t.dependencies:
            if d not in by or by[d]['end'] > a['start']: bad.append(f'dependency {t.id}<-{d}')
        for cid in a['crew_ids']:
            c = crew[cid]
            if not t.required_skills <= c.skills: bad.append(f'skill {t.id}/{cid}')
            if not any(w.start <= a['start'] and a['end'] <= w.end for w in c.available): bad.append(f'availability {t.id}/{cid}')
            if any(a['start'] < w.end and w.start < a['end'] for w in c.rest): bad.append(f'rest {t.id}/{cid}')
            if t.duration_minutes > c.max_continuous_minutes: bad.append(f'continuous {t.id}/{cid}')
    for cid, c in crew.items():
        mine = sorted((a for a in assignments if cid in a['crew_ids']), key=lambda a: a['start'])
        for x, y in zip(mine, mine[1:]):
            if x['end'] + c.break_minutes > y['start']: bad.append(f'break/overlap {cid}')
        if sum(a['end'] - a['start'] for a in mine) > c.max_work_minutes_per_day: bad.append(f'daily cap {cid}')
        load = sum((a['end'] - a['start']) / 60 * (tasks[a['task_id']].physical_load + tasks[a['task_id']].cognitive_load) / 2 for a in mine)
        if load > c.max_load_per_day + 1e-6: bad.append(f'load cap {cid}')
    for e in eq.values():
        pts = sorted({a['start'] for a in assignments} | {a['end'] for a in assignments})
        for p in pts:
            use = sum(tasks[a['task_id']].equipment.get(e.id, 0) for a in assignments if a['start'] <= p < a['end'])
            if use > e.capacity: bad.append(f'equipment {e.id}')
    for t in plan.tasks:
        if t.required and t.id not in by: bad.append(f'required {t.id} missing')
    return sorted(set(bad))


def constrained_plan(plan: PlanningInput, constraints: list[dict]) -> PlanningInput:
    data = plan.model_dump()
    for u in constraints:
        next(c for c in data['crew'] if c['id'] == u['id']).update(u)
    return PlanningInput.model_validate(data)


def wm(metrics, cid):
    w = metrics['work_minutes']
    return float(w.get(str(cid), w.get(cid, 0)))


def rest_minutes(plan: PlanningInput, cid: int) -> int:
    c = next(x for x in plan.crew if x.id == cid)
    return sum(min(w.end, plan.horizon_minutes) - w.start for w in c.rest if w.start < plan.horizon_minutes)


def one(template, seed, profile):
    t0 = time.time()
    run = me.run(me.EngineRunRequest(template=template, seed=seed, plan_profile=profile))
    sim = me._sim(run['id'])
    run_s = time.time() - t0
    labelled = sorted({g['crew_id'] for g in sim.dataset['ground_truth'] if g.get('physiological_change')})
    base = sim.schedules['alternatives'][1]
    row = {'template': template, 'seed': seed, 'profile': profile, 'labelled_crew': labelled,
           'base_solver_status': base.get('solver_status'), 'base_valid': base.get('valid'),
           'base_independent_violations': len(independent_check(sim.plan, base['assignments'])), 'run_seconds': round(run_s, 1)}
    recs = me.coorbit_recommendations(run['id'])['recommendations']
    row['step1_recommendations'] = len(recs)
    row['step2_on_labelled'] = sum(r['crew_id'] in labelled for r in recs)
    row['step2_on_other'] = len(recs) - row['step2_on_labelled']
    if not recs:
        return row
    before_json = json.dumps(sim.schedules, sort_keys=True)
    rej = me.coorbit_reject(run['id'], me.CoorbitReject(rejected_ids=[r['id'] for r in recs], reviewed_by='study reviewer'))
    row['step4_5_reject_changes_nothing'] = rej['changed'] is False and json.dumps(sim.schedules, sort_keys=True) == before_json
    t1 = time.time()
    dec = me.coorbit_apply(run['id'], me.CoorbitApply(approved_ids=[r['id'] for r in recs], approved_by='study approver'))
    row['replan_seconds'] = round(time.time() - t1, 1)
    row['step6_constraints'] = len(dec['constraints'])
    if not dec['valid']:
        # B1.4 "allow changing the constraints": retry without the rule that made the plan infeasible
        row['rejected_reason'] = dec['reason'][:160]
        subset = [r['id'] for r in recs if r['kind'] != 'shorter_blocks']
        row['retry_subset_size'] = len(subset)
        if subset:
            dec2 = me.coorbit_apply(run['id'], me.CoorbitApply(approved_ids=subset, approved_by='study approver'))
            row['retry_valid'] = dec2['valid']
            if dec2['valid']:
                dec = dec2
                recs = [r for r in recs if r['id'] in subset]
    after = dec['after'] if dec['valid'] else dec['proposal']
    plan_b = constrained_plan(sim.plan, dec['constraints'])
    row.update({'step7_solver_status': after['solver_status'], 'optimality_proven': after['optimality_proven'],
                'step8_valid_reported': dec['valid'], 'step8_independent_violations': len(independent_check(plan_b, after['assignments'])) if dec['valid'] else None,
                'decision_status': dec['decision_status'], 'run_schedule_unchanged': json.dumps(sim.schedules, sort_keys=True) == before_json})
    targets = sorted({r['crew_id'] for r in recs})
    row['step9_target_work_before'] = sum(wm(base['metrics'], c) for c in targets)
    row['step9_target_work_after'] = sum(wm(after['metrics'], c) for c in targets) if dec['valid'] else None
    unsched = {u['task_id'] for u in after.get('unscheduled', [])}
    row['step10_dropped_tasks'] = len(dec['dropped_tasks'])
    row['step10_dropped_listed_with_reason'] = all(d['task_id'] in unsched and d['reason'] for d in dec['dropped_tasks'])
    used = lambda asg: {x for a in asg for x in a['crew_ids']}
    row['anyone_removed'] = bool(used(base['assignments']) - used(after['assignments'])) if dec['valid'] else None
    # ---- B6.3 counterfactual: A = current plan, B = approved constraints, same seed; planning quantities only
    if not dec['valid']:
        row['step10_dropped_tasks'] = 0
        return row
    mA, mB = base['metrics'], after['metrics']
    row.update({'cf_total_work_A': mA['total_work_minutes'], 'cf_total_work_B': mB['total_work_minutes'],
                'cf_max_load_A': round(mA['max_load'], 3), 'cf_max_load_B': round(mB['max_load'], 3),
                'cf_rest_target_A': sum(rest_minutes(sim.plan, c) for c in targets), 'cf_rest_target_B': sum(rest_minutes(plan_b, c) for c in targets),
                'cf_moved_tasks': sum(1 for ch in dec['comparison']['changes'] if ch['change'] in ('reassigned', 'rescheduled')),
                'cf_unscheduled_A': len(base.get('unscheduled', [])), 'cf_unscheduled_B': len(after.get('unscheduled', [])),
                'cf_priority_score_delta': dec['comparison']['delta']['priority_score'],
                'cf_constraint_kinds': sorted({r['kind'] for r in recs}), 'cf_valid_A': base.get('valid'), 'cf_valid_B': dec['valid']})
    return row


def summary(rows):
    def share(key, sel):
        v = [r[key] for r in sel if r.get(key) is not None]
        return f'{sum(bool(x) for x in v)}/{len(v)}' if v else '–'
    out = []
    for prof in ('standard', 'high_workload'):
        for t in sorted({r['template'] for r in rows if r['profile'] == prof}):
            sel = [r for r in rows if r['profile'] == prof and r['template'] == t]
            wr = [r for r in sel if r.get('step1_recommendations')]
            mean = lambda k, s=wr: round(st.mean([r[k] for r in s if r.get(k) is not None]), 1) if [r for r in s if r.get(k) is not None] else None
            out.append({'profile': prof, 'template': t, 'runs': len(sel), 'base_schedule_valid': share('base_valid', sel),
                        'base_independent_violations': sum(r['base_independent_violations'] for r in sel),
                        'runs_with_recs': len(wr), 'recs_on_labelled': sum(r['step2_on_labelled'] for r in sel), 'recs_on_other': sum(r['step2_on_other'] for r in sel),
                        'reject_changes_nothing': share('step4_5_reject_changes_nothing', wr), 'valid_after_approval': share('step8_valid_reported', wr),
                        'first_approval_rejected': sum(1 for r in wr if 'rejected_reason' in r), 'valid_after_subset_retry': share('retry_valid', wr),
                        'independent_violations_after': sum(r.get('step8_independent_violations') or 0 for r in wr),
                        'optimality_proven': share('optimality_proven', wr), 'run_schedule_unchanged': share('run_schedule_unchanged', wr),
                        'target_work_before_mean': mean('step9_target_work_before'), 'target_work_after_mean': mean('step9_target_work_after'),
                        'dropped_tasks_total': sum(r.get('step10_dropped_tasks') or 0 for r in wr), 'dropped_listed_with_reason': share('step10_dropped_listed_with_reason', wr),
                        'anyone_removed': sum(bool(r.get('anyone_removed')) for r in wr),
                        'cf_max_load_A': mean('cf_max_load_A'), 'cf_max_load_B': mean('cf_max_load_B'),
                        'cf_rest_target_A': mean('cf_rest_target_A'), 'cf_rest_target_B': mean('cf_rest_target_B'),
                        'cf_moved_tasks_mean': mean('cf_moved_tasks'), 'cf_unscheduled_A': mean('cf_unscheduled_A'), 'cf_unscheduled_B': mean('cf_unscheduled_B'),
                        'cf_priority_score_delta_mean': mean('cf_priority_score_delta'), 'replan_seconds_mean': mean('replan_seconds')})
    return out


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    db.DB_PATH = Path(tempfile.mkdtemp()) / 'hitl.sqlite3'
    t0 = time.time(); rows = []
    for templates, seeds, profile in (STANDARD, HIGH):
        for t in templates:
            for s in seeds:
                rows.append(one(t, s, profile))
                me._sims.clear(); me._baselines.clear()
    res = {'doc': __doc__, 'rows': rows, 'summary': summary(rows), 'runtime_s': round(time.time() - t0, 1)}
    (out / 'b5_coorbit_hitl.json').write_text(json.dumps(res, indent=1, default=str), encoding='utf-8')
    print(json.dumps(res['summary'], indent=1)); print('runtime', res['runtime_s'])


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default=str(ROOT / 'validation' / 'results_1_0'))
    main(Path(ap.parse_args().out))
