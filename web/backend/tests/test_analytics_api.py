"""0.9: SYMBIOSIS relationship/compare_periods/compare_conditions, CO-ORBIT replan and /api/science/* over the stdlib server."""
import json
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app import db, mission_engine as me


@pytest.fixture(scope='module')
def server():
    prev = db.DB_PATH
    with tempfile.TemporaryDirectory() as tmp:
        db.DB_PATH = Path(tmp) / 't.sqlite3'
        me._sims.clear(); me._baselines.clear()
        from app.devserver import serve
        srv = serve('127.0.0.1', 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{srv.server_address[1]}'

        def req(path, data=None):
            rq = urllib.request.Request(base + path, data=None if data is None else json.dumps(data).encode(),
                                        headers={'Content-Type': 'application/json'}, method='POST' if data is not None else 'GET')
            try:
                with urllib.request.urlopen(rq, timeout=180) as resp:
                    return resp.status, json.loads(resp.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read() or b'{}')
        try:
            yield req
        finally:
            srv.shutdown(); db.DB_PATH = prev; me._sims.clear(); me._baselines.clear()


@pytest.fixture(scope='module')
def env_run(server):
    code, run = server('/api/engine/runs', {'template': 'environment'})
    assert code == 200
    return run


def test_relationship_and_periods(server, env_run):
    code, a = server(f"/api/engine/runs/{env_run['id']}/symbiosis?env_metric=co2&metric=fatigue&crew_id=1")
    assert code == 200 and a['causal'] is False and 'not evidence of causation' in a['note']
    assert [r['lag_minutes'] for r in a['relationship']] == me.LAGS
    assert all(r['pairs'] >= 3 for r in a['relationship'])
    # the environment template raises CO2 after its event: period B must have the higher mean
    assert a['periods']['co2']['b']['mean'] > a['periods']['co2']['a']['mean']
    assert server(f"/api/engine/runs/{env_run['id']}/symbiosis?env_metric=radon")[0] == 400
    assert server('/api/engine/runs/nope/symbiosis')[0] == 404


def test_compare_conditions_direction(server):
    code, c = server('/api/symbiosis/compare-conditions', {'a': {}, 'b': {'co2': 4000, 'temperature': 27, 'night_light': 60}})
    assert code == 200 and c['human_review_required'] and c['actuation'] is False
    assert c['delta']['fatigue'] > 0 and c['delta']['cognition'] < 0      # worse conditions → modelled worse outcomes
    code, same = server('/api/symbiosis/compare-conditions', {'a': {}, 'b': {}})
    assert code == 200 and all(abs(v) < 1e-9 for v in same['delta'].values())


def test_replan_adds_rest_and_urgent_task(server, env_run):
    code, r = server(f"/api/engine/runs/{env_run['id']}/replan", {
        'crew_updates': [{'id': 2, 'add_rest': [{'start': 600, 'end': 720}]}],
        'task_updates': [{'id': 'urgent_repair', 'title': 'Urgent repair', 'duration_minutes': 60, 'priority': 5,
                          'required_skills': ['maintenance'], 'earliest': 600, 'deadline': 960}]})
    assert code == 200 and r['valid']
    ur = [a for a in r['after']['assignments'] if a['task_id'] == 'urgent_repair']
    assert ur and 600 <= ur[0]['start'] and ur[0]['end'] <= 960
    for a in r['after']['assignments']:          # crew 2 is not scheduled inside the new rest window
        if 2 in a['crew_ids']:
            assert a['end'] <= 600 or a['start'] >= 720
    assert server(f"/api/engine/runs/{env_run['id']}/replan", {'crew_updates': [{'id': 1, 'available': []}]})[0] == 400


def test_science_routes(server):
    code, ev = server('/api/science/evidence')
    assert code == 200 and all(e['url'] and e['verified_on'] for e in ev['entries'])
    code, hz = server('/api/science/hazards')
    assert code == 200 and len(hz['hazards']) == 5 and len(hz['hrp_map']) == 17
    code, g = server('/api/science/graph', {'destination': 'mars', 'mission_days': 900})
    assert code == 200 and g['nodes'] and g['edges']
    assert server('/api/science/graph', {'destination': 'venus'})[0] in (400, 422)
    code, r = server('/api/science/radiation', {'preset': 'mars_conjunction'})
    assert code == 200 and r['final']['p50'] > 600
    code, r = server('/api/science/radiation', {'segments': [{'environment': 'iss', 'days': 10}], 'spe': [{'day': 50, 'dose_msv': 1}]})
    assert code == 400
