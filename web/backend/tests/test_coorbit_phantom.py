"""AETHER 0.9: PHANTOM → CO-ORBIT with human approval; planning profiles that produce different valid schedules."""
import json
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app import db, mission_engine as me


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


def _independent_violations(plan, assignments):
    """Checks written independently of the solver's own validator."""
    tasks = {t.id: t for t in plan.tasks}
    crew = {c.id: c for c in plan.crew}
    bad = []
    for cid, c in crew.items():
        iv = sorted((a['start'], a['end']) for a in assignments if cid in a['crew_ids'])
        bad += [f'overlap {cid}' for i in range(len(iv) - 1) if iv[i][1] > iv[i + 1][0]]
        for s, e in iv:
            if not any(w.start <= s and e <= w.end for w in c.available):
                bad.append(f'outside availability {cid}')
            if any(s < w.end and w.start < e for w in c.rest):
                bad.append(f'rest violated {cid}')
        if sum(e - s for s, e in iv) > c.max_work_minutes_per_day:
            bad.append(f'daily cap {cid}')
    for a in assignments:
        t = tasks[a['task_id']]
        if a['end'] - a['start'] != t.duration_minutes or len(a['crew_ids']) != t.people:
            bad.append(f'shape {t.id}')
        for d in t.dependencies:
            dep = next((x for x in assignments if x['task_id'] == d), None)
            if dep is None or dep['end'] > a['start']:
                bad.append(f'dependency {t.id}')
    return bad


def test_plan_profiles_give_distinct_valid_schedules(temp_db):
    seen = {}
    for profile in me.PLAN_PROFILES:
        r = me.run(me.EngineRunRequest(template='normal', plan_profile=profile, duration_minutes=720))
        best = r['schedules']['strategies'][1]
        sim = me._sim(r['id'])
        assert best['metrics']['conflicts'] == 0 and not best['metrics']['violations'], profile
        assert _independent_violations(sim.plan, best['assignments']) == [], profile
        seen[profile] = json.dumps(sorted((a['task_id'], a['crew_ids'], a['start']) for a in best['assignments']))
        assert r['plan_profile'] == profile
    assert len(set(seen.values())) == len(me.PLAN_PROFILES) >= 4


def test_no_recommendations_without_phantom_flags(temp_db):
    r = me.run(me.EngineRunRequest(template='normal'))
    assert me.coorbit_recommendations(r['id'])['recommendations'] == []


def test_recommendations_target_affected_person_and_need_approval(temp_db):
    r = me.run(me.EngineRunRequest(template='multifactor'))
    recs = me.coorbit_recommendations(r['id'])['recommendations']
    assert recs and {x['crew_id'] for x in recs} == {1}          # the injected event affects crew 1 only
    assert all(x['requires_human_approval'] for x in recs)
    assert {x['kind'] for x in recs} <= set(me.coorbit_phantom.RULES)
    with pytest.raises(ValueError, match='approve'):
        me.coorbit_apply(r['id'], me.CoorbitApply(approved_ids=[recs[0]['id']], approved_by='  '))
    with pytest.raises(ValueError, match='Unknown'):
        me.coorbit_apply(r['id'], me.CoorbitApply(approved_ids=['rec-nope'], approved_by='Flight surgeon'))
    with pytest.raises(ValueError, match='No recommendation'):
        me.coorbit_apply(r['id'], me.CoorbitApply(approved_ids=[], approved_by='Flight surgeon'))


def test_approved_constraints_change_schedule_without_removing_anyone(temp_db):
    r = me.run(me.EngineRunRequest(template='sleep_loss', plan_profile='high_workload'))
    sim = me._sim(r['id'])
    recs = me.coorbit_recommendations(r['id'])['recommendations']
    out = me.coorbit_apply(r['id'], me.CoorbitApply(approved_ids=[x['id'] for x in recs], approved_by='Flight surgeon (demo)'))
    assert out['valid'] and out['approved_by'] == 'Flight surgeon (demo)'
    assert out['after']['assignments'] != out['before']['assignments']
    assert out['comparison']['changes'] and out['comparison']['explanations']
    orig = {c.id: c for c in sim.plan.crew}
    before, after = out['comparison']['work_minutes_before'], out['comparison']['work_minutes_after']
    wm = lambda d, i: d.get(str(i), d.get(i, 0))
    for u in out['constraints']:
        assert 'available' not in u                                # availability is never removed
        if 'max_work_minutes_per_day' in u:
            assert u['max_work_minutes_per_day'] <= orig[u['id']].max_work_minutes_per_day
            assert u['max_work_minutes_per_day'] >= wm(before, u['id']) * .5     # never below half of the current plan
    assert 0 < wm(after, 1) <= wm(before, 1)                       # the flagged person works less, not zero


def test_reduce_workload_is_binding_and_never_increases_work(temp_db):
    # 0.9 validation found that a cap of 75 % of the nominal maximum was not binding: work could even rise.
    ran = 0
    for template, seed in (('sleep_loss', 101), ('sleep_loss', 104), ('multifactor', 102)):
        r = me.run(me.EngineRunRequest(template=template, seed=seed))
        recs = [x for x in me.coorbit_recommendations(r['id'])['recommendations'] if x['kind'] == 'reduce_workload']
        if not recs:
            continue
        out = me.coorbit_apply(r['id'], me.CoorbitApply(approved_ids=[x['id'] for x in recs], approved_by='test'))
        b, a = out['comparison']['work_minutes_before'], out['comparison']['work_minutes_after']
        for x in recs:
            cid = x['crew_id']
            wb, wa = b.get(str(cid), b.get(cid, 0)), a.get(str(cid), a.get(cid, 0))
            assert wa <= wb * .75 + 1e-9 or wb == 0, (template, seed, wb, wa)
            assert wa >= wb * .5 - 15, (template, seed, wb, wa)
            ran += 1
    assert ran > 0
    # the original run stays untouched: approval yields a proposal
    assert me._sim(r['id']).schedules['alternatives'][1]['assignments'] == out['before']['assignments']


def test_routes_over_stdlib_server(temp_db):
    from app.devserver import serve
    srv = serve('127.0.0.1', 0)
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def req(path, data=None):
        rq = urllib.request.Request(base + path, data=None if data is None else json.dumps(data).encode(),
                                    headers={'Content-Type': 'application/json'}, method='POST' if data is not None else 'GET')
        try:
            with urllib.request.urlopen(rq, timeout=120) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b'{}')
    try:
        assert len(req('/api/engine/plan-profiles')[1]) == 4
        run = req('/api/engine/runs', {'template': 'pulse_shift'})[1]
        recs = req(f"/api/engine/runs/{run['id']}/coorbit")[1]['recommendations']
        assert recs
        assert req(f"/api/engine/runs/{run['id']}/coorbit/apply", {'approved_ids': [recs[0]['id']], 'approved_by': ''})[0] == 400
        code, out = req(f"/api/engine/runs/{run['id']}/coorbit/apply", {'approved_ids': [recs[0]['id']], 'approved_by': 'Commander'})
        assert code == 200 and not out['valid']
        assert out['after']['assignments'] == out['before']['assignments']
        assert out['reason']
    finally:
        srv.shutdown()


def test_scheduler_marks_infeasible_plan_as_invalid():
    from mission_systems.co_orbit.scheduler import solve
    from mission_systems.contracts import Crew, PlanningInput, Task

    plan = PlanningInput(
        crew=[
            Crew(id=1, name='A', role='Researcher', skills={'science'}, available=[{'start': 480, 'end': 720}],
                 rest=[], max_work_minutes_per_day=240, max_continuous_minutes=120, break_minutes=15, max_load_per_day=8)
        ],
        tasks=[
            Task(id='task1', title='Required task', duration_minutes=300, priority=5, people=1,
                 required_skills={'science'}, earliest=0, deadline=720, dependencies=[], equipment={})
        ],
        equipment=[],
        horizon_minutes=720,
        step_minutes=30,
        time_limit_seconds=2,
    )

    out = solve(plan)
    assert out['solver_status'] == 'infeasible'
    assert out['has_feasible_solution'] is False
    assert out['assignments'] == []
    assert out['metrics']['conflicts'] >= 1


def test_scheduler_accepts_feasible_plan_with_explicit_state():
    from mission_systems.co_orbit.scheduler import solve
    from mission_systems.contracts import Crew, PlanningInput, Task

    plan = PlanningInput(
        crew=[
            Crew(id=1, name='A', role='Researcher', skills={'science'}, available=[{'start': 480, 'end': 1200}],
                 rest=[], max_work_minutes_per_day=480, max_continuous_minutes=300, break_minutes=15, max_load_per_day=8)
        ],
        tasks=[
            Task(id='task1', title='Required task', duration_minutes=120, priority=5, people=1,
                 required_skills={'science'}, earliest=480, deadline=1200, dependencies=[], equipment={})
        ],
        equipment=[],
        horizon_minutes=1200,
        step_minutes=30,
        time_limit_seconds=5,
    )

    out = solve(plan)
    assert out['solver_status'] == 'optimal'
    assert out['has_feasible_solution'] is True
    assert out['assignments']
    assert out['optimality_proven'] is True
