"""AETHER 1.0 · B1 (P0): a failed or empty solver result must never be reported as a valid schedule.

Covers the six reproduction cases of the technical spec (B1.1) and the regression list of B1.5:
valid schedule · infeasible schedule · no incumbent · invalid / empty proposal · time-limited feasible incumbent ·
human approval with an infeasible outcome · previous schedule preserved after a failure.
Real HiGHS solves are used wherever the case can be produced with real input; the solver is replaced by a fake only
for outcomes HiGHS cannot be forced into deterministically (time limit without incumbent, crashes, corrupt output).
"""
import json
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

from app import coorbit_phantom, db, mission_engine as me
from mission_systems.co_orbit import scheduler as S
from mission_systems.co_orbit.optimization import alternatives, commit_if_valid, dropped_tasks, preferred, replan
from mission_systems.contracts import PlanningInput
from mission_systems.mission_lab.scenarios import demo
from mission_systems.storage import Store

REAL_MILP = S.milp


class FakeResult:
    def __init__(self, status, x, message='fake', fun=None):
        self.status, self.x, self.message, self.fun, self.mip_gap = status, x, message, fun, None


def plan_dict(**changes):
    p = demo('normal').planning.model_dump()
    p.update(changes)
    return p


def tiny_plan(*tasks, available=(480, 600), required=True):
    """One crew member, a 2-hour window; each task fits alone."""
    return PlanningInput.model_validate({
        'crew': [{'id': 1, 'name': 'Solo', 'role': 'Engineer', 'skills': ['maintenance'],
                  'available': [{'start': available[0], 'end': available[1]}]}],
        'tasks': [{'id': tid, 'title': tid.title(), 'duration_minutes': d, 'earliest': 480, 'deadline': 600,
                   'required': required} for tid, d in tasks],
        'time_limit_seconds': 5})


def independent_check(plan, result):
    """Re-validate a result with checks that do not use the solver's own code paths."""
    tasks = {t.id: t for t in plan.tasks}
    crew = {c.id: c for c in plan.crew}
    bad = []
    for a in result['assignments']:
        t = tasks[a['task_id']]
        if a['end'] - a['start'] != t.duration_minutes or len(a['crew_ids']) != t.people:
            bad.append('shape ' + t.id)
        if not (t.earliest <= a['start'] and a['end'] <= t.deadline):
            bad.append('window ' + t.id)
        for cid in a['crew_ids']:
            if not t.required_skills <= crew[cid].skills:
                bad.append('skill ' + t.id)
    for cid in crew:
        iv = sorted((a['start'], a['end']) for a in result['assignments'] if cid in a['crew_ids'])
        bad += [f'overlap {cid}' for x, y in zip(iv, iv[1:]) if x[1] > y[0]]
    got = {a['task_id'] for a in result['assignments']}
    bad += [f'required {t.id} missing' for t in plan.tasks if t.required and t.id not in got]
    return bad


def assert_failed(r, solver_status):
    assert r['solver_status'] == solver_status
    assert r['valid'] is False and r['has_feasible_solution'] is False and r['optimality_proven'] is False
    assert r['assignments'] == [] and r['objective_value'] is None
    assert r['reason']                                         # a human-readable reason is always given
    assert len(r['unscheduled']) == len(r['required_tasks']) or r['unscheduled']   # tasks are listed, never dropped
    assert all(u['reason'] for u in r['unscheduled'])


# ------------------------------------------------------------------ valid / infeasible (real solver)
def test_valid_schedule_contract():
    plan = demo('normal').planning
    r = S.solve(plan, 'balanced')
    assert r['solver_status'] == 'optimal' and r['status'] == 'optimal_on_grid'
    assert r['valid'] and r['has_feasible_solution'] and r['optimality_proven']
    assert r['validation_errors'] == [] and isinstance(r['objective_value'], float)
    assert len(r['assignments']) == len(plan.tasks) and r['unscheduled'] == []
    assert 'inspect' in r['required_tasks'] and independent_check(plan, r) == []


def test_infeasible_required_tasks_conflict_real_solver():
    # each 90-min task fits the 2-hour window alone; together they cannot (HiGHS proves infeasibility)
    plan = tiny_plan(('alpha', 90), ('beta', 90))
    r = S.solve(plan)
    assert_failed(r, 'infeasible')
    assert r['status'] == 'infeasible' and 'together they conflict' in r['reason']
    assert {u['task_id'] for u in r['unscheduled']} == {'alpha', 'beta'}


def test_infeasible_when_no_crew_member_has_the_skill():
    p = plan_dict(); p['tasks'][0]['required_skills'] = ['eva_certified']
    r = S.solve(PlanningInput.model_validate(p))
    assert_failed(r, 'infeasible')
    assert 'eva_certified' in r['reason'] and 'only 0 crew member' in r['reason']
    assert r['solver_message'].startswith('presolve')


def test_infeasible_incompatible_time_window():
    p = plan_dict(); p['tasks'][0].update({'duration_minutes': 90, 'earliest': 480, 'deadline': 540})
    r = S.solve(PlanningInput.model_validate(p))
    assert_failed(r, 'infeasible')
    assert 'shorter than the duration' in r['reason']


def test_required_task_makes_its_dependency_required():
    p = plan_dict()
    by_id = {t['id']: t for t in p['tasks']}
    by_id['report']['required'] = True                      # report ← experiment ← samples
    by_id['samples']['required_skills'] = ['eva_certified']  # nobody can collect samples
    r = S.solve(PlanningInput.model_validate(p))
    assert_failed(r, 'infeasible')
    assert 'Required by experiment' in r['reason'] or 'Required by report' in r['reason']


def test_optional_task_without_option_is_listed_with_reason():
    p = plan_dict(); p['tasks'][5]['required_skills'] = ['eva_certified']; p['tasks'][5]['required'] = False   # explicitly optional
    r = S.solve(PlanningInput.model_validate(p))
    assert r['valid'] and r['solver_status'] == 'optimal'
    miss = {u['task_id']: u for u in r['unscheduled']}
    assert set(miss) == {'inventory'} and 'eva_certified' in miss['inventory']['reason']


def test_empty_plan_is_the_only_valid_empty_schedule():
    r = S.solve(PlanningInput.model_validate(plan_dict(tasks=[])))
    assert r['valid'] and r['assignments'] == [] and 'no tasks' in r['reason']


def test_optional_only_plan_where_nothing_fits_is_explicit():
    p = plan_dict()
    for t in p['tasks']:
        t['required'] = False
    for c in p['crew']:
        c['rest'] = [{'start': 0, 'end': 1440}]
    r = S.solve(PlanningInput.model_validate(p))
    # allowed by the spec only because there are no required tasks – and every task is reported with a reason
    assert r['valid'] and r['assignments'] == [] and r['required_tasks'] == []
    assert len(r['unscheduled']) == 6 and all('No feasible' in u['reason'] or 'Dependency' in u['reason'] for u in r['unscheduled'])


# ------------------------------------------------------------------ solver outcomes that need a fake solver
def test_time_limit_without_incumbent():
    with mock.patch.object(S, 'milp', lambda *a, **k: FakeResult(1, None, 'Time limit reached')):
        r = S.solve(demo('normal').planning)
    assert_failed(r, 'time_limit_no_solution')
    assert r['status'] == 'no_incumbent' and 'Time limit' in r['reason']


def test_time_limit_with_only_trivial_empty_incumbent_is_not_a_solution():
    p = plan_dict()
    for t in p['tasks']:
        t['required'] = False
    with mock.patch.object(S, 'milp', lambda c, **k: FakeResult(1, np.zeros(len(c)), 'Time limit reached', 0.0)):
        r = S.solve(PlanningInput.model_validate(p))
    assert_failed(r, 'time_limit_no_solution')
    assert 'trivial empty schedule' in r['reason']


def test_infeasible_status_from_solver():
    with mock.patch.object(S, 'milp', lambda *a, **k: FakeResult(2, None, 'infeasible')):
        r = S.solve(demo('normal').planning)
    assert_failed(r, 'infeasible')


def test_solver_exception_is_reported_not_raised():
    def boom(*a, **k):
        raise RuntimeError('HiGHS crashed')
    with mock.patch.object(S, 'milp', boom):
        r = S.solve(demo('normal').planning)
        alts = alternatives(demo('normal').planning)
    assert_failed(r, 'error')
    assert 'HiGHS crashed' in r['solver_message'] and r['status'] == 'solver_error'
    assert alts['has_feasible_solution'] is False and alts['explanation'].startswith('No feasible schedule')


@pytest.mark.parametrize('required', [True, False])
def test_empty_optimal_proposal_is_rejected(required):
    p = plan_dict()
    for t in p['tasks']:
        t['required'] = required and t['id'] == 'inspect'
    with mock.patch.object(S, 'milp', lambda c, **k: FakeResult(0, np.zeros(len(c)), 'Optimal', 0.0)):
        r = S.solve(PlanningInput.model_validate(p))
    assert_failed(r, 'invalid_output')
    assert ('Required task inspect not scheduled' in r['reason']) if required else ('empty optimal schedule' in r['reason'])


def test_non_integral_or_inconsistent_output_is_rejected():
    plan = demo('normal').planning
    _, real = S._run_milp(plan, *S.candidates(plan), 'balanced', S.required_closure(plan), 10)
    half = real.x.copy(); half[:-1] = np.where(half[:-1] > .5, .7, 0)
    with mock.patch.object(S, 'milp', lambda c, **k: FakeResult(0, half, 'Optimal', float(c @ half))):
        r = S.solve(plan)
    assert_failed(r, 'invalid_output'); assert 'not integral' in r['reason']
    with mock.patch.object(S, 'milp', lambda c, **k: FakeResult(0, real.x, 'Optimal', float(c @ real.x) - 5)):
        r = S.solve(plan)
    assert_failed(r, 'invalid_output'); assert 'objective does not match' in r['reason']


def test_output_violating_constraints_is_rejected_with_evidence():
    plan = demo('normal').planning
    options, by_task = S.candidates(plan)
    x = np.zeros(len(options) + 1)
    # choose every option of 'inspect' -> duplicate task, overlaps, toolkit capacity
    for i in by_task['inspect'][:3]:
        x[i] = 1
    with mock.patch.object(S, 'milp', lambda c, **k: FakeResult(0, x, 'Optimal', float(c @ x))):
        r = S.solve(plan)
    assert_failed(r, 'invalid_output')
    assert any('Duplicate task inspect' in e for e in r['validation_errors'])
    assert len(r['rejected_assignments']) == 3                 # rejected output kept for debugging, not as a schedule


def test_time_limited_feasible_incumbent_is_valid_but_not_optimal():
    def time_limited(c, **k):
        res = REAL_MILP(c, **k)
        return FakeResult(1, res.x, 'Time limit reached', res.fun)
    plan = demo('normal').planning
    with mock.patch.object(S, 'milp', time_limited):
        r = S.solve(plan)
    assert r['solver_status'] == 'feasible' and r['status'] == 'feasible_time_limit'
    assert r['valid'] and r['has_feasible_solution'] and not r['optimality_proven']
    assert 'optimality not proven' in r['reason'] and independent_check(plan, r) == []


def test_real_time_limit_invariants():
    """Real HiGHS on the 11-task profile with a 1 s limit: whatever happens, the mapping must be consistent."""
    p = me.apply_plan_profile(demo('normal').planning.model_dump(mode='json'), 'high_workload')
    p['time_limit_seconds'] = 1
    plan = PlanningInput.model_validate(p)
    r = S.solve(plan)
    assert r['solver_status'] in ('optimal', 'feasible', 'time_limit_no_solution')
    if r['valid']:
        assert independent_check(plan, r) == [] and r['optimality_proven'] == (r['solver_status'] == 'optimal')
    else:
        assert r['assignments'] == []


def test_legacy_results_without_valid_field():
    assert S.is_valid({'status': 'optimal_on_grid', 'assignments': [{'task_id': 'x'}], 'metrics': {'conflicts': 0, 'violations': []}})
    assert not S.is_valid({'status': 'no_incumbent', 'assignments': [], 'metrics': {'conflicts': 0, 'violations': []}})
    assert not S.is_valid({'status': 'optimal_on_grid', 'assignments': [], 'metrics': {'conflicts': 0, 'violations': []}})


def test_preferred_uses_a_valid_alternative():
    plan = demo('normal').planning
    calls = []

    def flaky(c, **k):
        calls.append(1)
        return FakeResult(1, None, 'Time limit') if len(calls) == 2 else REAL_MILP(c, **k)   # balanced fails
    with mock.patch.object(S, 'milp', flaky):
        alts = alternatives(plan)
    assert not alts['alternatives'][1]['valid'] and alts['alternatives'][0]['valid']
    assert preferred(alts) is alts['alternatives'][0] and alts['has_feasible_solution']


# ------------------------------------------------------------------ engine flows: approval, replan, persistence
@pytest.fixture()
def temp_db():
    prev = db.DB_PATH
    with tempfile.TemporaryDirectory() as tmp:
        db.DB_PATH = Path(tmp) / 't.sqlite3'
        me._sims.clear(); me._baselines.clear()
        try:
            yield
        finally:
            db.DB_PATH = prev
            me._sims.clear(); me._baselines.clear()


def _stored(run_id):
    return me._store().get('simulation', run_id)['schedules']


def test_human_approval_with_infeasible_outcome_keeps_current_schedule(temp_db):
    r = me.run(me.EngineRunRequest(template='multifactor'))
    sim = me._sim(r['id'])
    before_mem = json.dumps(sim.schedules, sort_keys=True)
    before_db = json.dumps(_stored(r['id']), sort_keys=True)
    recs = me.coorbit_recommendations(r['id'])['recommendations']
    assert recs

    def harsh_replan(plan, crew_updates=None, **kw):     # approved constraints that leave no feasible schedule
        return replan(plan, crew_updates=[{'id': c.id, 'rest': [{'start': 0, 'end': 1440}]} for c in plan.crew])
    out = coorbit_phantom.apply(sim, [recs[0]['id']], 'Flight surgeon', recs, harsh_replan, store=me._store())
    assert out['valid'] is False and out['decision_status'] == 'rejected_no_feasible_schedule'
    assert out['applied'] is False and out['previous_schedule_preserved'] is True and out['requires_review']
    assert out['proposal']['solver_status'] == 'infeasible' and out['proposal']['assignments'] == []
    assert out['after']['assignments'] == out['before']['assignments']        # the schedule that stays in force
    assert 'Cabin inspection' in out['reason'] and out['next_actions']
    assert all(v == 0 for v in out['comparison']['delta'].values()) and out['comparison']['changes'] == []
    assert out['comparison']['work_minutes_after'] == out['comparison']['work_minutes_before']
    assert json.dumps(sim.schedules, sort_keys=True) == before_mem
    assert json.dumps(_stored(r['id']), sort_keys=True) == before_db


def test_replan_failure_preserves_previous_schedule(temp_db):
    r = me.run(me.EngineRunRequest(template='normal', duration_minutes=720))
    before = json.dumps(me._sim(r['id']).schedules, sort_keys=True)
    body = me.ReplanRequest(crew_updates=[{'id': c['id'], 'add_rest': [{'start': 0, 'end': 1440}]} for c in r['crew']])
    out = me.replan_run(r['id'], body)
    assert out['valid'] is False and out['decision_status'] == 'rejected_no_feasible_schedule'
    assert out['previous_schedule_preserved'] and out['applied'] is False
    assert 'Cabin inspection' in out['reason']
    assert all(v == 0 for v in out['comparison']['delta'].values())
    assert json.dumps(me._sim(r['id']).schedules, sort_keys=True) == before
    assert me.get_run(r['id'])['schedules']['strategies'][1]['assignments'] == json.loads(before)['alternatives'][1]['assignments']


def test_replan_that_cannot_keep_every_task_is_rejected(temp_db):
    """Team decision: every task is mandatory by default, so a re-plan that cannot keep all tasks is not valid."""
    r = me.run(me.EngineRunRequest(template='normal', duration_minutes=720))
    upd = [{'id': 3, 'add_rest': [{'start': 480, 'end': 1200}]}, {'id': 1, 'add_rest': [{'start': 480, 'end': 900}]}]
    out = me.replan_run(r['id'], me.ReplanRequest(crew_updates=upd))
    assert out['valid'] is False and out['decision_status'] == 'rejected_no_feasible_schedule'
    assert out['after']['assignments'] == out['before']['assignments'] and out['reason']
    # the same change with the low-priority tasks explicitly optional: valid, and the dropped tasks are listed
    opt = [{'id': t, 'required': False} for t in ('experiment', 'report', 'inventory', 'samples')]
    out = me.replan_run(r['id'], me.ReplanRequest(crew_updates=upd, task_updates=opt))
    assert out['valid'] is True and out['dropped_tasks'] and out['requires_review']
    assert {d['task_id'] for d in out['dropped_tasks']} <= {u['task_id'] for u in out['after']['unscheduled']}
    assert all(d['reason'] for d in out['dropped_tasks'])


def test_successful_approval_still_valid(temp_db):
    r = me.run(me.EngineRunRequest(template='sleep_loss', plan_profile='high_workload'))
    recs = me.coorbit_recommendations(r['id'])['recommendations']
    out = me.coorbit_apply(r['id'], me.CoorbitApply(approved_ids=[x['id'] for x in recs], approved_by='Flight surgeon'))
    assert out['valid'] and out['decision_status'] == 'proposal_ready' and out['after']['has_feasible_solution']
    assert out['after']['solver_status'] in ('optimal', 'feasible')
    assert out['after']['optimality_proven'] == (out['after']['solver_status'] == 'optimal')


def test_rejection_changes_nothing(temp_db):
    r = me.run(me.EngineRunRequest(template='multifactor'))
    before = json.dumps(me._sim(r['id']).schedules, sort_keys=True)
    recs = me.coorbit_recommendations(r['id'])['recommendations']
    with pytest.raises(ValueError, match='reviewed_by'):
        me.coorbit_reject(r['id'], me.CoorbitReject(rejected_ids=[recs[0]['id']], reviewed_by=' '))
    out = me.coorbit_reject(r['id'], me.CoorbitReject(rejected_ids=[x['id'] for x in recs], reviewed_by='Flight surgeon'))
    assert out['decision_status'] == 'rejected_by_human' and out['changed'] is False
    assert json.dumps(me._sim(r['id']).schedules, sort_keys=True) == before
    assert me.coorbit_recommendations(r['id'])['recommendations'] == recs     # recommendations unchanged too


def test_mission_systems_store_keeps_previous_plan_on_failure():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / 'ms.sqlite3')
        plan = demo('normal').planning
        ok = alternatives(plan)
        assert commit_if_valid(store, 'p', plan, ok)['persisted']
        saved_plan, saved_sched = store.get('planning', 'p'), store.get('schedules', 'p')
        bad_plan, bad = replan(plan, crew_updates=[{'id': c.id, 'rest': [{'start': 0, 'end': 1440}]} for c in plan.crew])
        state = commit_if_valid(store, 'p', bad_plan, bad)
        assert state == {'persisted': False, 'valid': False, 'reason': preferred(bad)['reason'], 'previous_schedule_preserved': True}
        assert store.get('planning', 'p') == saved_plan and store.get('schedules', 'p') == saved_sched


def test_dropped_tasks_helper():
    before = {'assignments': [{'task_id': 'a'}, {'task_id': 'b'}]}
    after = {'assignments': [{'task_id': 'a'}], 'unscheduled': [{'task_id': 'b', 'reason': 'no slot'}]}
    assert dropped_tasks(before, after) == [{'task_id': 'b', 'title': 'b', 'reason': 'no slot'}]


def test_api_reports_failure_instead_of_crashing(temp_db):
    from app.devserver import serve
    srv = serve('127.0.0.1', 0)
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def post(path, data):
        rq = urllib.request.Request(base + path, data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(rq, timeout=120) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b'{}')
    try:
        run = post('/api/engine/runs', {'template': 'normal', 'duration_minutes': 720})[1]

        def boom(*a, **k):
            raise RuntimeError('HiGHS crashed')
        with mock.patch.object(S, 'milp', boom):
            code, out = post(f"/api/engine/runs/{run['id']}/replan", {'crew_updates': [], 'task_updates': []})
        assert code == 200 and out['valid'] is False and out['proposal']['solver_status'] == 'error'
        assert out['previous_schedule_preserved'] is True
        with mock.patch.object(me, 'replan_run', side_effect=TypeError('unexpected')):
            code, out = post(f"/api/engine/runs/{run['id']}/replan", {})
        assert code == 500 and 'TypeError' in out['detail']       # a response is always sent
    finally:
        srv.shutdown()
