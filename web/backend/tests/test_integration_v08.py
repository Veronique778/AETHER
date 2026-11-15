"""v0.8 integration: former pending contracts + Mission Systems engine, over the stdlib HTTP server
(and the FastAPI app when installed). Uses a temporary SQLite database."""
import json
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app import db, mission_engine


@pytest.fixture()
def temp_db():
    previous = db.DB_PATH
    with tempfile.TemporaryDirectory() as tmp:
        db.DB_PATH = Path(tmp) / 'test.sqlite3'
        mission_engine._sims.clear()
        try:
            yield
        finally:
            db.DB_PATH = previous
            mission_engine._sims.clear()


EXPERIMENT = {
    'id': 'exp-1', 'name': 'Sleep vs workload', 'created_at': '2026-11-13T10:00:00Z', 'astronaut_id': 'A01',
    'start_day': 67, 'horizon_days': 14, 'runs': 200, 'seed': 67,
    'scenarios': [{'key': 'a', 'title': 'Nominal', 'params': {'sleep_delta': 0, 'workload': 50, 'co2_ppm': 850, 'temperature_c': 22, 'crew_available': 4},
                   'end': {'score_p50': 10, 'score_p10': 5, 'score_p90': 20, 'attention_share': .1, 'fatigue_p50': 3}}],
}


def scenario(get, post, delete):
    health = get('/api/health')[1]
    for cap in ('symbiosis-crew-association', 'recovery-biofeedback', 'mission-lab-experiments', 'mission-engine'):
        assert cap in health['capabilities']
    assert health['mission_engine']['available'] is True

    assoc = get('/api/symbiosis/crew-association?day=67&zone=habitat')[1]
    assert {r['astronaut_id'] for r in assoc['rows']} == {'A01', 'A02', 'A03', 'A04'}
    assert assoc['source'] == 'simulated' and all(r['n'] >= 8 for r in assoc['rows'])
    assert get('/api/symbiosis/crew-association?zone=nope')[0] == 404

    bio = get('/api/recovery/biofeedback?astronaut_id=A02')[1]
    assert bio['source'] == 'simulated' and 4 <= bio['breathing_rate_bpm'] <= 8
    assert get('/api/recovery/biofeedback?astronaut_id=ZZ')[0] == 404

    assert post('/api/mission-lab/experiments', EXPERIMENT)[0] == 200
    assert [e['id'] for e in get('/api/mission-lab/experiments')[1]] == ['exp-1']
    assert post('/api/mission-lab/experiments', {**EXPERIMENT, 'scenarios': []})[0] == 422
    assert delete('/api/mission-lab/experiments/exp-1')[0] == 200
    assert delete('/api/mission-lab/experiments/exp-1')[0] == 404
    assert get('/api/mission-lab/experiments')[1] == []

    templates = get('/api/engine/templates')[1]
    assert len(templates) == 11 and templates[0]['id'] == 'normal'
    assert post('/api/engine/runs', {'template': 'nope'})[0] == 400
    assert post('/api/engine/runs', {'template': 'normal', 'sleep_hours': 30})[0] == 422

    code, run = post('/api/engine/runs', {'template': 'multifactor', 'sleep_hours': 6.5, 'co2_ppm': 1400})
    assert code == 200, run
    assert run['origin'] == 'synthetic' and len(run['times']) == len(run['series']['1']['heart_rate'])
    assert run['evaluation']['phantom_status'] == 'evaluated'
    ev = run['evaluation']['phantom']
    assert ev['tp'] + ev['fp'] + ev['tn'] + ev['fn'] == 3 * len(run['times'])
    best = run['schedules']['strategies'][1]
    assert best['metrics']['conflicts'] == 0 and best['assignments']
    assert run['bridge']['sleep_delta'] < 0 and 350 <= run['bridge']['co2_ppm'] <= 5000

    rid = run['id']
    assert get(f'/api/engine/runs/{rid}')[1]['id'] == rid
    assert post(f'/api/engine/runs/{rid}/control', {'action': 'start'})[1]['status'] == 'running'
    post(f'/api/engine/runs/{rid}/control', {'action': 'speed', 'value': 60})
    st = post(f'/api/engine/runs/{rid}/control', {'action': 'tick', 'value': 30})[1]
    assert st['minute'] == 30
    assert post(f'/api/engine/runs/{rid}/control', {'action': 'seek', 'value': 99999})[0] == 400
    assert get('/api/engine/runs/unknown-run')[0] == 404
    assert get(f'/api/engine/runs/{rid}/evaluation')[1]['phantom_status'] == 'evaluated'

    other = post('/api/engine/runs', {'template': 'normal'})[1]
    cmp_ = post('/api/engine/compare', {'a': other['id'], 'b': rid})[1]
    assert cmp_['same_seed'] is True and cmp_['delta_means']
    assert any(r['id'] == rid for r in get('/api/engine/runs')[1])


def test_stdlib_server(temp_db):
    from app.devserver import serve
    srv = serve('127.0.0.1', 0)
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def req(path, data=None, method=None):
        r = urllib.request.Request(base + path, method=method or ('POST' if data is not None else 'GET'),
                                   data=None if data is None else json.dumps(data).encode(),
                                   headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(r, timeout=60) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b'{}')
    try:
        scenario(req, lambda p, b: req(p, b), lambda p: req(p, method='DELETE'))
    finally:
        srv.shutdown()


def test_fastapi_app(temp_db):
    pytest.importorskip('fastapi')
    pytest.importorskip('httpx')
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, base_url='http://127.0.0.1', headers={'X-AETHER-Token': 'aether-test-token'}) as client:
        scenario(lambda p: (lambda r: (r.status_code, r.json()))(client.get(p)),
                 lambda p, b: (lambda r: (r.status_code, r.json()))(client.post(p, json=b)),
                 lambda p: (lambda r: (r.status_code, r.json()))(client.delete(p)))


def test_aether_phantom_never_sees_labels(temp_db):
    """The adapter receives only the label-free PHANTOM input; scores beat chance on a clear event."""
    from mission_systems.mission_lab.experiments import phantom_input
    from mission_systems.mission_lab.scenarios import demo
    from mission_systems.mission_lab.simulator import Simulator
    sim = Simulator(demo('pulse_shift'))
    payload = phantom_input(sim.dataset)
    assert 'ground_truth' not in json.dumps(payload) and 'injected' not in json.dumps(payload)
    report = sim.submit_phantom(mission_engine.aether_phantom(payload))['evaluation']['phantom']
    assert report['recall'] > .5 and report['precision'] > .5


def test_lazy_engine_template_list_matches_engine():
    assert mission_engine.SCENARIOS == mission_engine._load().SCENARIOS
