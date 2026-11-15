"""AETHER 1.0 · B4: cabin conditions vs measured physiology vs hypotheses about their link."""
import copy
import json
import tempfile
import threading
import urllib.request
from pathlib import Path

import numpy as np
import pytest

from app import db, environment_detector as ed, mission_engine as me
from mission_systems.contracts import Scenario
from mission_systems.mission_lab.generator import generate
from mission_systems.mission_lab.scenarios import demo
from mission_systems.co_orbit.optimization import alternatives


def dataset(template, seed=7, minutes=2880, event_minute=1800):
    d = demo(template, seed=seed).model_dump(mode='json')
    d['duration_minutes'] = minutes
    for e in d['events']:
        e['minute'] = event_minute
    sc = Scenario.model_validate(d)
    return generate(sc, alternatives(sc.planning)['alternatives'][1])


def detect(frames, **kw):
    m, s = ed.series_from_frames(frames)
    return ed.detect(m, s, **kw)


def noisy(frames, level=1.0, seed=0):
    rng = np.random.default_rng(seed)
    out = copy.deepcopy(frames)
    for f in out:
        for r in f['environment']:
            if r['metric'] in ed.FLOORS:
                r['value'] += float(rng.normal(0, level * ed.FLOORS[r['metric']]))
    return out


# ------------------------------------------------------------------ ground-truth audit (generator labels)
def test_labels_separate_cabin_exposure_from_physiological_change():
    env, multi = dataset('environment'), dataset('multifactor')
    late = lambda ds: [g for g in ds['ground_truth'] if g['minute'] >= 2400]
    for g in late(env):          # cabin change: everyone exposed, nobody has an injected physiological change
        assert g['environment_exposure'] and not g['physiological_change'] and g['anomaly']   # 0.9 label kept for compatibility
    for g in late(multi):
        assert g['environment_exposure']
        assert g['physiological_change'] == (g['crew_id'] == 1) == g['anomaly']
    assert all(not g['environment_exposure'] for g in dataset('sleep_loss')['ground_truth'])
    assert any(f['environment_event'] for f in env['frames']) and not any(f['environment_event'] for f in dataset('normal')['frames'])


def test_labels_are_not_visible_to_phantom_input():
    from mission_systems.mission_lab.experiments import phantom_input
    text = json.dumps(phantom_input(dataset('multifactor')))
    for key in ('environment_event', 'physiological_change', 'environment_exposure', 'ground_truth', 'anomaly'):
        assert key not in text


# ------------------------------------------------------------------ detector behaviour (B4.4)
def test_environment_event_only():
    ds = dataset('environment')
    res = detect(ds['frames'])
    kinds = {e['kind'] for e in res['events']}
    assert {'co2_increase', 'temperature_drift'} <= kinds and not any(e['category'] == 'sensor_fault' for e in res['events'])
    ev = ed.evaluate(res['frames'], ds['frames'], 1440)
    assert ev['fpr'] == 0 and ev['recall'] > .8
    assert all(not f['environment_event'] for f in res['frames'] if f['minute'] < 1800)   # nothing before the event
    assert any(e['sustained'] for e in res['events'])


def test_physiological_anomaly_only_has_no_cabin_event():
    res = detect(dataset('sleep_loss')['frames'])
    assert res['events'] == [] and all(f['state'] == 'nominal' for f in res['frames'])


def test_both_simultaneously_and_crew_specific_context():
    ds = dataset('multifactor')
    res = detect(ds['frames'])
    assert any(f['environment_event'] for f in res['frames'])
    stress = [f['minute'] for f in res['frames'] if f['environment_event']]
    flags = {1: [m for m in stress[2:]], 2: [], 3: []}        # PHANTOM flags only the affected person
    ctx = {c['crew_id']: c for c in ed.crew_context(res, flags)}
    assert 'co-occur' in ctx[1]['statement'] and 'hypothesis' in ctx[1]['statement']
    for cid in (2, 3):
        assert ctx[cid]['environment_stressor'] and 'no confirmed physiological change' in ctx[cid]['statement']
        assert {s['signal'] for s in ctx[cid]['suggested_measurements']} == set(ed.MODEL_LINKED_SIGNALS)
    assert all(c['diagnosis'] is None for c in ctx.values())


def test_context_when_physiology_changes_without_cabin_event():
    res = detect(dataset('sleep_loss')['frames'])
    ctx = ed.crew_context(res, {1: [2000, 2030], 2: []}, {1: {'scored': 49}, 2: {'scored': 0}})
    assert 'without a detected environmental stressor' in ctx[0]['statement']
    assert ctx[1]['statement'].startswith('Insufficient')          # no data ≠ healthy


@pytest.mark.parametrize('fault', ['dropout', 'spike', 'flat_line', 'invalid', 'out_of_bounds'])
def test_sensor_corruption_is_a_fault_not_a_cabin_event(fault):
    frames = noisy(dataset('normal')['frames'], 1.0, seed=3)
    idx = list(range(60, 72))
    for i in idx:
        r = next(x for x in frames[i]['environment'] if x['metric'] == 'co2')
        if fault == 'dropout':
            r['value'], r['quality'] = None, 'missing'
        elif fault == 'invalid':
            r['value'], r['quality'] = None, 'invalid'
        elif fault == 'spike' and i == 64:
            r['value'] += 20 * ed.FLOORS['co2']
        elif fault == 'flat_line':
            r['value'] = next(x for x in frames[59]['environment'] if x['metric'] == 'co2')['value']
        elif fault == 'out_of_bounds' and i == 64:
            r['value'] = -5.0
    res = detect(frames)
    hit = [i for i in idx if res['frames'][i]['sensor_fault']]
    assert hit and (len(hit) == len(idx) or fault in ('spike', 'out_of_bounds'))
    assert not any(f['environment_event'] for f in res['frames']), 'a sensor fault must not be reported as a cabin event'
    assert any(e['category'] == 'sensor_fault' for e in res['events'])


def test_flat_line_check_is_not_applied_to_a_deterministic_source():
    res = detect(dataset('normal')['frames'])
    assert all('not applicable' in v for v in res['applicability'].values())
    assert not any(f['sensor_fault'] for f in res['frames'])


def test_co2_limit_uses_partial_pressure_and_one_hour_average():
    minutes = list(range(0, 1440 * 2, 30))
    co2 = [800.0] * 48 + [800.0] * 20 + [4200.0] * 4 + [800.0] * (len(minutes) - 72)
    series = {'co2': [{'value': v, 'quality': 'valid'} for v in co2],
              'temperature': [{'value': 22.0, 'quality': 'valid'} for _ in minutes],
              'humidity': [{'value': 45.0, 'quality': 'valid'} for _ in minutes]}
    hi = ed.detect(minutes, series, cabin_pressure_mmhg=760)          # 4200 ppm × 760 mmHg = 3.19 mmHg > 3
    lo = ed.detect(minutes, series, cabin_pressure_mmhg=526)          # reduced cabin pressure: 2.21 mmHg
    over = [f for f in hi['frames'] if any(a['kind'] == 'co2_above_limit' for a in f['alarms'])]
    assert over and all(f['statistics']['ppco2_1h_mmhg'] > 3 for f in over)
    assert not any(a['kind'] == 'co2_above_limit' for f in lo['frames'] for a in f['alarms'])
    assert hi['co2_limit']['evidence_id'] == 'OCHMO-TB-004'
    with pytest.raises(ValueError):
        ed.detect(minutes, series, cabin_pressure_mmhg=50)


def test_noisy_cabin_false_alarm_rate_is_bounded():
    fr = [f for s in range(40, 46) for f in detect(noisy(dataset('normal', seed=s)['frames'], 1.0, seed=s))['frames'] if f['minute'] >= 1440]
    assert np.mean([f['environment_event'] for f in fr]) <= 0.03


# ------------------------------------------------------------------ engine integration + API
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


def test_engine_environment_analysis_for_multiple_crew(temp_db):
    r = me.run(me.EngineRunRequest(template='environment', seed=11))
    out = me.environment_analysis(r['id'])
    assert out['events'] and out['origin'] == 'synthetic' and len(out['crew_context']) == 3
    assert {c['crew_name'] for c in out['crew_context']} == {'Alex', 'Sam', 'Robin'}
    assert all(c['environment_stressor'] and c['diagnosis'] is None for c in out['crew_context'])
    assert out['evaluation_against_hidden_labels']['fp'] == 0
    quiet = me.environment_analysis(me.run(me.EngineRunRequest(template='pulse_shift', seed=11))['id'])
    assert quiet['events'] == [] and not any(c['environment_stressor'] for c in quiet['crew_context'])
    recs = me.coorbit_recommendations(r['id'])
    assert len(recs['environment_context']) == 3
    assert all(x['environment_context'] is not None for x in recs['recommendations'])


def test_environment_route_over_stdlib_server(temp_db):
    from app.devserver import serve
    srv = serve('127.0.0.1', 0)
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        rq = urllib.request.Request(base + '/api/engine/runs', data=json.dumps({'template': 'multifactor'}).encode(),
                                    headers={'Content-Type': 'application/json'}, method='POST')
        run = json.loads(urllib.request.urlopen(rq, timeout=120).read())
        out = json.loads(urllib.request.urlopen(base + f"/api/engine/runs/{run['id']}/environment?cabin_pressure_mmhg=700", timeout=120).read())
        assert out['parameters']['cabin_pressure_mmhg'] == 700 and out['crew_context']
        try:
            urllib.request.urlopen(base + f"/api/engine/runs/{run['id']}/environment?cabin_pressure_mmhg=10", timeout=30)
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 422
    finally:
        srv.shutdown()
