"""AETHER 1.0 · B6: MISSION LAB scenario engine – events, time, seeds, reproducibility, comparison, persistence and
propagation MISSION LAB → BODY → PHANTOM → SYMBIOSIS → CO-ORBIT (RECOVERY consumes PHANTOM in the UI)."""
import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from app import db, mission_engine as me, phantom2_engine as pe
from mission_systems.mission_lab.experiments import phantom_input
from mission_systems.mission_lab.simulator import Simulator
from mission_systems.mission_lab.scenarios import demo


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


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


@pytest.mark.parametrize('template', me.SCENARIOS)
def test_templates_create_their_defined_event(template):
    sc = demo(template, seed=3)
    sim = Simulator(sc)
    kinds = {e['kind'] for f in sim.dataset['frames'] for e in f['events']}
    if template == 'normal':
        assert kinds == set() and not any(g['anomaly'] for g in sim.dataset['ground_truth'])
    else:
        assert kinds == {template}
        first = min(f['minute'] for f in sim.dataset['frames'] if f['events'])
        assert first >= sc.events[0].minute                                  # nothing before the event
        assert all(f['events'] == [] for f in sim.dataset['frames'] if f['minute'] < sc.events[0].minute)


def test_time_controls_do_not_jump():
    sim = Simulator(demo('normal'))
    sim.set_speed(3600)                                  # time multiplier: 3600× real time = 60 simulated min per real second
    sim.start(); st = sim.tick(2)
    assert st['minute'] == 120 and st['frame']['minute'] == 120
    st = sim.tick(0.25)                                  # 15 min: cursor between samples → last sample at or before it
    assert st['minute'] == 135 and st['frame']['minute'] == 120
    st = sim.tick(10_000)                                # clamps at the end, no overshoot
    assert st['minute'] == sim.scenario.duration_minutes and st['status'] == 'finished'
    sim.pause(); st = sim.tick(5)
    assert st['minute'] == sim.scenario.duration_minutes        # paused / finished clock does not move
    for bad in (-1, float('nan'), float('inf')):
        with pytest.raises(ValueError):
            sim.tick(bad)
    with pytest.raises(ValueError):
        sim.seek(sim.scenario.duration_minutes + 1)
    with pytest.raises(ValueError):
        sim.set_speed(0)


def test_seed_controls_randomness_and_reproduces():
    a, b, c = Simulator(demo('noise', seed=5)), Simulator(demo('noise', seed=5)), Simulator(demo('noise', seed=6))
    assert digest(a.dataset) == digest(b.dataset)
    assert digest(a.dataset['frames']) != digest(c.dataset['frames'])


def test_engine_run_is_reproducible_and_persists(temp_db):
    req = me.EngineRunRequest(template='sleep_loss', seed=42)
    r1 = me.run(req)
    sim1 = me._sim(r1['id'])
    d1 = digest(sim1.dataset)
    me._sims.clear(); me._baselines.clear()              # new process / restart: history comes from SQLite
    assert any(x['id'] == r1['id'] for x in me.list_runs())
    restored = me.get_run(r1['id'])
    assert digest(me._sim(r1['id']).dataset) == d1
    assert restored['series'] == r1['series'] and restored['schedules'] == r1['schedules']
    r2 = me.run(req)                                     # same parameters → same id, same data
    assert r2['id'] == r1['id'] and digest(me._sim(r2['id']).dataset) == d1


def test_run_comparison_is_correct(temp_db):
    a = me.run(me.EngineRunRequest(template='normal', seed=9))
    b = me.run(me.EngineRunRequest(template='normal', seed=9, co2_ppm=3000))
    cmp = me.compare(me.EngineCompare(a=a['id'], b=b['id']))
    assert cmp['same_seed'] is True
    # independent recomputation of one delta
    def mean_co2(run_id):
        v = [r['value'] for f in me._sim(run_id).dataset['frames'] for r in f['environment'] if r['metric'] == 'co2' and r['quality'] == 'valid']
        return sum(v) / len(v)
    key = 'habitat:co2'
    assert cmp['delta_means'][key] == pytest.approx(mean_co2(b['id']) - mean_co2(a['id']))
    assert cmp['delta_means'][key] == pytest.approx(2200)


def test_results_reach_the_other_modules(temp_db):
    r = me.run(me.EngineRunRequest(template='multifactor', seed=13))
    sim = me._sim(r['id'])
    ds = sim.dataset
    # BODY: the summary series are exactly the engine readings
    first = {(m['crew_id'], m['metric']): m['value'] for m in ds['frames'][0]['measurements']}
    assert r['series']['1']['heart_rate'][0] == round(first[(1, 'heart_rate')], 3)
    # PHANTOM: flags reference engine samples of this run only
    p2 = pe.detect(phantom_input(ds), baseline_payload=phantom_input(me.baseline_day(sim)))
    sample_ids = {g['sample_id'] for g in ds['ground_truth']}
    assert set(p2['flags']['phantom2']) == sample_ids
    assert sum(len(v) for v in r['phantom2']['flags'].values()) == sum(bool(f) for f in p2['flags']['phantom2'].values())
    # SYMBIOSIS: the bridge CO₂ is the mean modelled cabin CO₂ of this run
    co2 = [x for x in r['environment']['co2'] if x is not None]
    assert r['bridge']['co2_ppm'] == int(max(350, min(5000, round(sum(co2) / len(co2)))))
    env = me.environment_analysis(r['id'])
    assert len(env['frames']) == len(ds['frames'])
    # CO-ORBIT: recommendations concern crew of this run and carry the cabin context
    recs = me.coorbit_recommendations(r['id'])
    assert {x['crew_id'] for x in recs['recommendations']} <= {c.id for c in sim.plan.crew}
    assert recs['recommendations'][0]['environment_context']['environment_stressor'] is True
    # data origin is labelled everywhere
    assert r['origin'] == env['origin'] == 'synthetic' and ds['origin'] == 'synthetic'


def test_scenario_update_validates_before_mutation():
    sim = Simulator(demo('normal'))
    before = digest(sim.dataset)
    with pytest.raises(Exception):
        sim.update({'duration_minutes': -5})
    assert digest(sim.dataset) == before
