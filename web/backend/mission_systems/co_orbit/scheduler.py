"""Time-indexed mixed-integer scheduling with independent feasibility validation."""
from collections import defaultdict
from itertools import combinations
from math import ceil
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix
from ..contracts import Assignment, PlanningInput


def overlap(a, b, c, d):
    return a < d and c < b


def work_by_day(start, end):
    return {day: max(0, min(end,(day+1)*1440)-max(start,day*1440))
            for day in range(start//1440, (end-1)//1440+1)}


def load(task):
    return (task.physical_load + task.cognitive_load) / 2


def validate_schedule(plan: PlanningInput, assignments, *, require_all_required: bool = False):
    """Checks arbitrary/manual schedules too; never trusts the optimizer.

    The default is intentionally permissive for legacy callers that only care about assignment-level
    feasibility. The API and solver enforce required-task coverage explicitly when a schedule must
    represent a valid plan rather than an arbitrary partial proposal.
    """
    tasks = {t.id:t for t in plan.tasks};crew = {c.id:c for c in plan.crew}
    equipment = {e.id:e for e in plan.equipment};errors=[];seen={};by_crew=defaultdict(list)
    by_equipment=defaultdict(list);daily=defaultdict(float);weighted=defaultdict(float)
    for raw in assignments:
        a=Assignment.model_validate(raw)
        if a.task_id not in tasks:
            errors.append(f'Unknown task {a.task_id}');continue
        t=tasks[a.task_id]
        if a.task_id in seen:errors.append(f'Duplicate task {t.id}')
        seen[t.id]=a
        if len(a.crew_ids)!=t.people or len(set(a.crew_ids))!=t.people:
            errors.append(f'{t.id}: wrong team size')
        if a.end-a.start!=t.duration_minutes or not (t.earliest<=a.start<a.end<=min(t.deadline,plan.horizon_minutes)):
            errors.append(f'{t.id}: duration/time window')
        for cid in a.crew_ids:
            if cid not in crew:errors.append(f'{t.id}: unknown crew');continue
            c=crew[cid]
            if not t.required_skills<=c.skills:errors.append(f'{t.id}: missing skills for {cid}')
            if not any(w.start<=a.start and a.end<=w.end for w in c.available):
                errors.append(f'{t.id}: unavailable crew {cid}')
            if any(overlap(a.start,a.end,w.start,w.end) for w in c.rest):errors.append(f'{t.id}: rest conflict {cid}')
            if t.duration_minutes>c.max_continuous_minutes:errors.append(f'{t.id}: continuous work limit {cid}')
            by_crew[cid].append(a)
            if a.end>a.start:
                for day,minutes in work_by_day(a.start,a.end).items():
                    daily[cid,day]+=minutes;weighted[cid,day]+=minutes/60*load(t)
        for eid,n in t.equipment.items():
            e=equipment[eid]
            if any(overlap(a.start,a.end,w.start,w.end) for w in e.unavailable):
                errors.append(f'{t.id}: equipment unavailable {eid}')
            by_equipment[eid].append((a,n))
    for cid,rows in by_crew.items():
        rows.sort(key=lambda a:a.start)
        for a,b in zip(rows,rows[1:]):
            if a.end+crew[cid].break_minutes>b.start:errors.append(f'Overlap/break violation for crew {cid}')
    for (cid,day),minutes in daily.items():
        if minutes>crew[cid].max_work_minutes_per_day:errors.append(f'Crew {cid} day {day}: work limit')
        if weighted[cid,day]>crew[cid].max_load_per_day+1e-7:errors.append(f'Crew {cid} day {day}: load limit')
    for eid,rows in by_equipment.items():
        points=sorted({a.start for a,n in rows}|{a.end for a,n in rows})
        if any(sum(n for a,n in rows if a.start<=p<a.end)>equipment[eid].capacity for p in points):
            errors.append(f'Equipment capacity conflict: {eid}')
    for tid,a in seen.items():
        for dep in tasks[tid].dependencies:
            if dep not in seen or seen[dep].end>a.start:errors.append(f'{tid}: dependency {dep} not completed')
    if require_all_required:
        for t in plan.tasks:
            if t.required and t.id not in seen:
                errors.append(f'Unscheduled required task: {t.id}')
    return list(dict.fromkeys(errors))


def candidates(plan):
    options=[];by_task=defaultdict(list);eq={e.id:e for e in plan.equipment}
    for t in plan.tasks:
        eligible=[c for c in plan.crew if t.required_skills<=c.skills and t.duration_minutes<=c.max_continuous_minutes]
        first=ceil(t.earliest/plan.step_minutes)*plan.step_minutes
        for start in range(first,min(t.deadline,plan.horizon_minutes)-t.duration_minutes+1,plan.step_minutes):
            end=start+t.duration_minutes
            if any(eq[k].capacity<n or any(overlap(start,end,w.start,w.end) for w in eq[k].unavailable) for k,n in t.equipment.items()):continue
            available=[c for c in eligible if any(w.start<=start and end<=w.end for w in c.available)
                       and not any(overlap(start,end,w.start,w.end) for w in c.rest)]
            for team in combinations(available,t.people):
                if any(any(m>c.max_work_minutes_per_day or m/60*load(t)>c.max_load_per_day for m in work_by_day(start,end).values()) for c in team):continue
                by_task[t.id].append(len(options))
                options.append(Assignment(task_id=t.id,crew_ids=[c.id for c in team],start=start,end=end))
                if len(options)>30000:raise ValueError('Planning model too large: increase step_minutes or shorten horizon')
    return options,by_task


def metrics(plan, assignments):
    rows=[Assignment.model_validate(a) for a in assignments];tasks={t.id:t for t in plan.tasks}
    work={c.id:0.0 for c in plan.crew};loads=dict(work)
    for a in rows:
        if a.task_id not in tasks:continue
        for cid in a.crew_ids:
            if cid in work:
                work[cid]+=a.end-a.start;loads[cid]+=(a.end-a.start)/60*load(tasks[a.task_id])
    errors=validate_schedule(plan,rows)
    # 1.0: a required task that is not scheduled is a violation of the plan (team decision: all tasks mandatory by default)
    assigned={a.task_id for a in rows}
    errors+=[f'Unscheduled required task: {t.id}' for t in plan.tasks if t.required and t.id not in assigned]
    availability={}
    for c in plan.crew:
        points=sorted({0,plan.horizon_minutes}|{min(plan.horizon_minutes,w.start) for w in c.available+c.rest}|{min(plan.horizon_minutes,w.end) for w in c.available+c.rest})
        availability[c.id]=sum(b-a for a,b in zip(points,points[1:]) if any(w.start<=a and b<=w.end for w in c.available) and not any(overlap(a,b,w.start,w.end) for w in c.rest))
    return {'scheduled_tasks':len(rows),'priority_score':sum(10**(tasks[a.task_id].priority-1) for a in rows if a.task_id in tasks),
            'high_priority_completed':sum(tasks[a.task_id].priority>=4 for a in rows if a.task_id in tasks),
            'work_minutes':{str(k):v for k,v in work.items()},'load_hours':{str(k):v for k,v in loads.items()},'total_work_minutes':sum(work.values()),
            'load_std':float(np.std(list(loads.values()))),'max_load':max(loads.values(),default=0),
            'available_minutes':{str(k):v for k,v in availability.items()},'conflicts':len(errors),'violations':errors,
            'rest_constraints_met':not any('rest' in e or 'break' in e or 'continuous' in e for e in errors)}


# ---------------------------------------------------------------- 1.0 (B1): solver result contract
# solver_status (new, explicit)  -> legacy `status` string kept for the 0.9 frontend
LEGACY_STATUS = {'optimal': 'optimal_on_grid', 'feasible': 'feasible_time_limit', 'time_limit_no_solution': 'no_incumbent',
                 'infeasible': 'infeasible', 'unbounded': 'unbounded', 'error': 'solver_error', 'invalid_output': 'invalid_output'}
FEASIBLE_STATUSES = ('optimal', 'feasible')


def required_closure(plan, roots=None):
    """Required tasks (or `roots`) plus every task they depend on, directly or transitively."""
    tasks = {t.id: t for t in plan.tasks}
    roots = [t.id for t in plan.tasks if t.required] if roots is None else list(roots)
    out, stack = {}, [(tid, None) for tid in roots]
    while stack:
        tid, by = stack.pop()
        if tid in out:
            continue
        out[tid] = by
        stack += [(d, tid) for d in tasks[tid].dependencies]
    return out          # task id -> id of the required task that needs it (None if required itself)


def diagnose(plan, task):
    """Plain-language reason why a task has no feasible (time, team, equipment) option on the planning grid."""
    eq = {e.id: e for e in plan.equipment}
    skilled = [c for c in plan.crew if task.required_skills <= c.skills]
    need = f"{task.people} crew member{'s' if task.people > 1 else ''}"
    skills = ', '.join(sorted(task.required_skills)) or 'no special skills'
    if len(skilled) < task.people:
        return f'needs {need} with skills [{skills}]; only {len(skilled)} crew member(s) have them'
    if all(task.duration_minutes > c.max_continuous_minutes for c in skilled):
        return f'duration {task.duration_minutes} min exceeds the continuous-work limit of every qualified crew member'
    first = ceil(task.earliest / plan.step_minutes) * plan.step_minutes
    if min(task.deadline, plan.horizon_minutes) - first < task.duration_minutes:
        return (f'time window {task.earliest}–{min(task.deadline, plan.horizon_minutes)} min (on a {plan.step_minutes}-min grid) '
                f'is shorter than the duration {task.duration_minutes} min')
    for k, n in task.equipment.items():
        if eq[k].capacity < n:
            return f'needs {n}× {k}, capacity is {eq[k].capacity}'
    verb = 'is' if task.people == 1 else 'are'
    return (f'no start time in {task.earliest}–{min(task.deadline, plan.horizon_minutes)} min where {need} with [{skills}] {verb} '
            f'available, outside rest windows, within daily work/load limits and with the equipment free')


def _strategy_result(plan, strategy, solver_status, *, assignments=(), reason='', validation_errors=(), solver_message='',
                     objective_value=None, mip_gap=None, by_task=None, rejected=None, diagnostics=None):
    tasks = {t.id: t for t in plan.tasks}
    feasible = solver_status in FEASIBLE_STATUSES and not validation_errors
    chosen = list(assignments) if feasible else []
    selected = {a.task_id for a in chosen}
    reasons = diagnostics or {}
    unscheduled = []
    for t in plan.tasks:
        if t.id in selected:
            continue
        if not feasible:
            why = reasons.get(t.id) or f'No schedule accepted ({solver_status})'
        elif by_task is not None and not by_task[t.id]:
            why = 'No feasible time/team/equipment option: ' + diagnose(plan, t)
        elif any(d not in selected for d in t.dependencies):
            why = 'Dependency not scheduled: ' + ', '.join(d for d in t.dependencies if d not in selected)
        else:
            why = 'Resource/dependency limits with higher-priority tasks' + (' or solver time limit' if solver_status == 'feasible' else '')
        unscheduled.append({'task_id': t.id, 'title': t.title, 'priority': t.priority, 'required': t.required, 'reason': why})
    out = {'strategy': strategy, 'status': LEGACY_STATUS[solver_status], 'solver_status': solver_status,
           'has_feasible_solution': feasible, 'valid': feasible, 'optimality_proven': feasible and solver_status == 'optimal',
           'objective_value': objective_value if feasible else None,
           'objective_definition': 'minimise −Σ10^(priority−1)·x + small start-time / max-load terms (internal units)',
           'reason': reason, 'validation_errors': list(validation_errors),
           'solver_message': solver_message, 'mip_gap': mip_gap, 'step_minutes': plan.step_minutes,
           'assignments': [a.model_dump() for a in chosen], 'unscheduled': unscheduled,
           'required_tasks': sorted(t.id for t in plan.tasks if t.required),
           'metrics': metrics(plan, chosen),
           'criteria': 'Maximize sum of 10^(priority-1); then ' + ('minimize maximum crew load' if strategy == 'balanced' else 'favor earlier starts'),
           'limitations': ['Optimality applies to the chosen start-time grid and weighted objective.',
                           'Each assigned member must have all required skills. A break follows every task.',
                           'A schedule is reported valid only if the solver returned an incumbent that passed the independent '
                           'validator and contains every required task.']}
    if rejected is not None:
        out['rejected_assignments'] = [a.model_dump() for a in rejected]   # solver output that failed validation (debugging)
    return out


def _build_model(plan, options, by_task, strategy, required):
    tasks = {t.id: t for t in plan.tasks}; crew = {c.id: c for c in plan.crew}
    n = len(options); rows = []; lower = []; upper = []
    def constraint(values, lo=-np.inf, hi=np.inf):
        rows.append(values); lower.append(lo); upper.append(hi)
    # Last continuous variable is an upper bound on total weighted work per person.
    for t in plan.tasks:
        constraint({i: 1 for i in by_task[t.id]}, lo=1 if t.id in required else -np.inf, hi=1)
    resources = defaultdict(list); daily = defaultdict(dict); weighted = defaultdict(dict); totals = defaultdict(dict)
    for i, a in enumerate(options):
        t = tasks[a.task_id]
        for cid in a.crew_ids:
            resources['crew', cid].append((a.start, a.end + crew[cid].break_minutes, i, 1))
            totals[cid][i] = t.duration_minutes / 60 * load(t)
            for day, m in work_by_day(a.start, a.end).items():
                daily[cid, day][i] = m; weighted[cid, day][i] = m / 60 * load(t)
        for eid, count in t.equipment.items():
            resources['equipment', eid].append((a.start, a.end, i, count))
    eq = {e.id: e for e in plan.equipment}
    for (kind, key), intervals in resources.items():
        events = defaultdict(lambda: [[], []])
        for start, end, i, amount in intervals:
            events[start][1].append((i, amount)); events[end][0].append(i)
        active = {}; previous = None
        for point in sorted(events):
            for i in events[point][0]:
                active.pop(i, None)
            for i, amount in events[point][1]:
                active[i] = amount
            sig = tuple(sorted(active))
            if active and sig != previous:
                constraint(dict(active), hi=1 if kind == 'crew' else eq[key].capacity)
            previous = sig
    for (cid, day), values in daily.items():
        constraint(values, hi=crew[cid].max_work_minutes_per_day)
    for (cid, day), values in weighted.items():
        constraint(values, hi=crew[cid].max_load_per_day)
    for cid, values in totals.items():
        constraint({**values, n: -1}, hi=0)
    horizon = plan.horizon_minutes
    for task in plan.tasks:
        for dep in task.dependencies:
            # Child selected => predecessor selected.
            constraint({**{i: 1 for i in by_task[task.id]}, **{i: -1 for i in by_task[dep]}}, hi=0)
            v = {i: options[i].end for i in by_task[dep]}
            v.update({i: horizon - options[i].start for i in by_task[task.id]})
            constraint(v, hi=horizon)
    r = []; c = []; v = []
    for row, values in enumerate(rows):
        for col, value in values.items():
            r.append(row); c.append(col); v.append(value)
    matrix = coo_matrix((v, (r, c)), shape=(len(rows), n + 1)).tocsc()
    objective = np.zeros(n + 1)
    for i, a in enumerate(options):
        objective[i] = -10 ** (tasks[a.task_id].priority - 1) + .05 * a.start / (max(1, len(tasks)) * horizon)
    objective[n] = (.4 if strategy == 'balanced' else .001) / (horizon / 60 * len(crew) + 1)
    bounds = Bounds(np.zeros(n + 1), np.array([1] * n + [horizon / 60]))
    return objective, np.array([1] * n + [0]), bounds, LinearConstraint(matrix, np.array(lower), np.array(upper))


def _run_milp(plan, options, by_task, strategy, required, time_limit):
    objective, integrality, bounds, cons = _build_model(plan, options, by_task, strategy, required)
    result = milp(objective, integrality=integrality, bounds=bounds, constraints=cons,
                  options={'time_limit': time_limit, 'mip_rel_gap': 0.0})
    return objective, result


def _explain_infeasible(plan, options, by_task, strategy, required):
    """Which required tasks are individually impossible? (cheap check, run only after an infeasible solve)."""
    own = [t for t in plan.tasks if t.required]
    if not 1 < len(own) <= 10:
        return ''
    alone = []
    for t in own:
        only = required_closure(plan, [t.id])
        _, res = _run_milp(plan, options, by_task, strategy, only, min(2.0, plan.time_limit_seconds))
        if res.status == 2:
            alone.append(t.id)
    if alone:
        return 'Individually impossible required task(s): ' + ', '.join(alone) + '.'
    return 'Each required task fits on its own; together they conflict over crew time, equipment or daily limits.'


def solve(plan: PlanningInput, strategy='balanced'):
    """Solve the MILP and return a result that is only marked valid when a validated feasible schedule exists.

    The scheduler never trusts the solver's success flag: an incumbent must exist, be integral, match the reported
    objective, pass the independent validator and contain every required task. Failures are returned as data
    (solver_status / reason / validation_errors) with an empty `assignments` list instead of being raised, so callers
    can keep the previous schedule."""
    if strategy not in ('balanced', 'earliest'):
        raise ValueError('Unknown strategy')
    plan = PlanningInput.model_validate(plan)
    options, by_task = candidates(plan)          # ValueError for oversized models = input error (HTTP 400)
    tasks = {t.id: t for t in plan.tasks}
    required = required_closure(plan)
    if not plan.tasks:
        return _strategy_result(plan, strategy, 'optimal', reason='Plan contains no tasks; the empty schedule is valid.',
                                objective_value=0.0, by_task=by_task)
    # Presolve: a required task without a single feasible option makes the whole plan infeasible.
    blocked = {tid: by for tid, by in required.items() if not by_task[tid]}
    if blocked:
        diag = {}
        for tid, by in blocked.items():
            diag[tid] = 'Required' + (f' by {by}' if by else '') + ': ' + diagnose(plan, tasks[tid])
        return _strategy_result(plan, strategy, 'infeasible', by_task=by_task, diagnostics=diag,
                                solver_message='presolve: required task has no feasible option',
                                reason='No feasible schedule: ' + '; '.join(f"“{tasks[t].title}” – {d}" for t, d in diag.items()))
    try:
        objective, result = _run_milp(plan, options, by_task, strategy, required, plan.time_limit_seconds)
    except Exception as exc:  # solver crash / library error: report, never raise into the API layer
        return _strategy_result(plan, strategy, 'error', by_task=by_task, solver_message=f'{type(exc).__name__}: {exc}',
                                reason=f'Solver error ({type(exc).__name__}); the schedule was not changed.')
    message = str(getattr(result, 'message', ''))
    gap = getattr(result, 'mip_gap', None)
    gap = float(gap) if gap is not None and np.isfinite(gap) else None
    x = getattr(result, 'x', None)
    code = getattr(result, 'status', 4)
    if code == 2:
        return _strategy_result(plan, strategy, 'infeasible', by_task=by_task, solver_message=message,
                                reason='No feasible schedule contains all required tasks ('
                                       + ', '.join(sorted(required)) + '). ' + _explain_infeasible(plan, options, by_task, strategy, required))
    if code == 3:
        return _strategy_result(plan, strategy, 'unbounded', by_task=by_task, solver_message=message,
                                reason='Solver reported an unbounded model (modelling error).')
    if x is None:
        if code == 1:
            return _strategy_result(plan, strategy, 'time_limit_no_solution', by_task=by_task, solver_message=message,
                                    reason=f'Time limit {plan.time_limit_seconds:g} s reached before any feasible schedule was found.')
        return _strategy_result(plan, strategy, 'error', by_task=by_task, solver_message=message,
                                reason=f'Solver returned no solution (status {code}).')
    x = np.asarray(x, dtype=float)
    n = len(options)
    errors = []
    if x.shape != (n + 1,) or not np.all(np.isfinite(x)):
        errors.append('Solver output has the wrong shape or non-finite values')
    else:
        if np.any(np.abs(x[:n] - np.round(x[:n])) > 1e-6):
            errors.append('Solver output is not integral')
        fun = getattr(result, 'fun', None)
        if fun is not None and np.isfinite(fun) and abs(float(objective @ x) - float(fun)) > 1e-6 * (1 + abs(float(fun))) + 1e-9:
            errors.append('Reported objective does not match the returned solution')
    chosen = [a for i, a in enumerate(options) if x.shape == (n + 1,) and x[i] > .5]
    chosen.sort(key=lambda a: (a.start, a.task_id))
    errors += validate_schedule(plan, chosen, require_all_required=True)
    errors += [f'Required task {tid} not scheduled' for tid in required if tid not in {a.task_id for a in chosen}]
    if not chosen and not errors:
        # An empty incumbent can only be optimal if no single dependency-free task has a feasible option
        # (every option has a negative objective coefficient, so scheduling one improves on the empty plan).
        schedulable = [t.id for t in plan.tasks if by_task[t.id] and not t.dependencies]
        if schedulable and code == 0:
            errors.append('Solver reported an empty optimal schedule although task(s) '
                          + ', '.join(schedulable) + ' can be scheduled')
        elif schedulable:
            return _strategy_result(plan, strategy, 'time_limit_no_solution', by_task=by_task, solver_message=message,
                                    reason=f'Time limit {plan.time_limit_seconds:g} s reached; only the trivial empty schedule was found.')
    if errors:
        return _strategy_result(plan, strategy, 'invalid_output', by_task=by_task, solver_message=message,
                                validation_errors=errors, rejected=chosen,
                                reason='Solver output rejected by the independent validator: ' + '; '.join(errors[:5]))
    status = 'optimal' if code == 0 else 'feasible'
    fun = getattr(result, 'fun', None)
    if chosen:
        reason = ('Optimal on the planning grid.' if status == 'optimal' else
                  f'Feasible schedule found within the {plan.time_limit_seconds:g} s time limit; optimality not proven'
                  + (f' (MIP gap {gap:.3g}).' if gap is not None else '.'))
    else:
        reason = 'No task can be placed under the current constraints and the plan has no required tasks; every task is listed in `unscheduled`.'
    return _strategy_result(plan, strategy, status, assignments=chosen, by_task=by_task, solver_message=message, mip_gap=gap,
                            objective_value=float(fun) if fun is not None and np.isfinite(fun) else None, reason=reason)


def is_valid(strategy_result) -> bool:
    """Validity of a stored strategy result, including results saved by AETHER 0.9 (no `valid` field)."""
    if 'valid' in strategy_result:
        return bool(strategy_result['valid'])
    m = strategy_result.get('metrics', {})
    return strategy_result.get('status') in ('optimal_on_grid', 'feasible_time_limit') and m.get('conflicts') == 0 \
        and not m.get('violations') and bool(strategy_result.get('assignments'))


def baseline_schedule(plan):
    options,_=candidates(plan);chosen=[];remaining={t.id:t for t in plan.tasks}
    while remaining:
        progressed=False
        for t in sorted(remaining.values(),key=lambda t:(-t.priority,t.id)):
            if any(d in remaining for d in t.dependencies):continue
            for a in options:
                if a.task_id==t.id and not validate_schedule(plan,chosen+[a]):chosen.append(a);break
            del remaining[t.id];progressed=True
        if not progressed:break
    return {'assignments':[a.model_dump() for a in chosen], 'metrics':metrics(plan,chosen)}
