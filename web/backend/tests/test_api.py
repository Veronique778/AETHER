"""HTTP-level tests.

The same scenario runs against
  * the FastAPI app (skipped automatically if fastapi is not installed), and
  * the stdlib fallback server (always runs).
"""
import json
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app import db


@pytest.fixture()
def temp_db():
    previous = db.DB_PATH
    with tempfile.TemporaryDirectory() as tmp:
        db.DB_PATH = Path(tmp) / 'test.sqlite3'
        try:
            yield
        finally:
            db.DB_PATH = previous


def scenario(get, post):
    assert get('/api/health')[0] == 200
    people = get('/api/astronauts')[1]
    assert len(people) == 4
    timeline = get('/api/astronauts/A01/timeline')[1]
    assert len(timeline) == 67
    result = get('/api/phantom/A01')[1]
    assert result['status'] == 'attention'
    assert result['multi_signal_pattern'] is True
    assert result['uncertainty'] in ['low', 'medium', 'high']
    assert result['method']['flag_threshold_z'] == 2.0
    assert get('/api/phantom/bad-id')[0] == 404
    assert post('/api/astronauts/A01/measurements', {'day': 68, 'sleep_hours': 30})[0] == 422
    assert post('/api/astronauts/A01/measurements', {'day': 68})[0] == 400

    # Partial manual entry must not wipe other metrics (v0.1 bug).
    before = get('/api/astronauts/A01/timeline?day=67')[1][-1]
    assert post('/api/astronauts/A01/measurements', {'day': 67, 'reaction_ms': 300})[0] == 200
    after = get('/api/astronauts/A01/timeline?day=67')[1][-1]
    assert after['reaction_ms'] == 300 and after['source'] == 'manual'
    assert after['heart_rate_bpm'] == before['heart_rate_bpm']

    scen = post('/api/mission-lab/run', {'sleep_delta': 1, 'workload': 30})[1]
    assert scen['source'] == 'simulated'
    assert scen['metrics']['sleep_hours'] > before['sleep_hours']
    schedule = get('/api/co-orbit?reduce_a01=true')[1]['schedule']
    assert schedule['loads']['A01'] <= 2

    ship = get('/api/ship?day=67&hour=10')[1]
    assert len(ship['zones']) == 5 and len(ship['crew']) == 4
    assert all(z['environment']['source'] == 'estimated' for z in ship['zones'])
    assert 'heart_rate_bpm' not in json.dumps(ship['crew'])  # no raw physiology in crew view
    assert get('/api/ship?hour=24')[0] == 422

    hist = get('/api/symbiosis/history?zone=habitat&start=50&end=67')[1]
    assert len(hist['points']) == 18
    assert get('/api/symbiosis/history?zone=nope')[0] == 404

    ph = get('/api/phantom/A01/history?day=67&start=41')[1]
    assert len(ph['points']) == 27 and ph['alerts'] and ph['alerts'][0]['ongoing']
    corr = get('/api/phantom/A01/correlations?day=67&window=30')[1]
    assert len(corr['matrix']) == 25
    diag = [c for c in corr['matrix'] if c['a'] == c['b']]
    assert all(c['rho'] == 1.0 for c in diag)

    cal = get('/api/co-orbit/calendar?day=67')[1]
    assert set(cal['blocks']) == {'A01', 'A02', 'A03', 'A04'}
    plan = post('/api/co-orbit/plan', {'unavailable': ['A02'], 'capacity': {'A04': 3}})[1]
    assert all(t['astronaut_id'] != 'A02' for t in plan['assignments'])
    assert plan['loads']['A04'] <= 3
    dup = post('/api/co-orbit/plan', {'tasks': [
        {'id': 'X', 'title': 'a', 'skill': 'science', 'hours': 1, 'priority': 1},
        {'id': 'X', 'title': 'b', 'skill': 'science', 'hours': 1, 'priority': 1}]})
    assert dup[0] == 400

    proj = post('/api/mission-lab/project', {'start_day': 67, 'horizon_days': 10, 'runs': 50,
                                            'sleep_delta': -1.5, 'workload': 85})[1]
    assert len(proj['days']) == 11
    d = proj['days'][-1]
    assert d['fatigue_1_10']['p10'] <= d['fatigue_1_10']['p50'] <= d['fatigue_1_10']['p90']
    assert post('/api/mission-lab/project', {'start_day': 10})[0] == 422

    session = post('/api/recovery/sessions', {'activity': 'mind-pulse', 'before_mood': 4, 'after_mood': 6,
                                              'duration_seconds': 100, 'details': {'median_rt_ms': 312}})
    assert session[0] == 200
    rec = get('/api/recovery/sessions/A01')[1]
    assert len(rec) == 1 and rec[0]['details']['median_rt_ms'] == 312
    assert post('/api/recovery/sessions', {'activity': 'chess', 'before_mood': 4, 'after_mood': 6,
                                           'duration_seconds': 1})[0] == 422


def test_fastapi_app(temp_db):
    pytest.importorskip('fastapi')
    pytest.importorskip('httpx')
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, base_url='http://127.0.0.1', headers={'X-AETHER-Token': 'aether-test-token'}) as client:
        def get(p):
            r = client.get(p)
            return r.status_code, r.json()

        def post(p, b):
            r = client.post(p, json=b)
            return r.status_code, r.json()
        scenario(get, post)


def test_stdlib_server(temp_db):
    from app.devserver import serve
    srv = serve('127.0.0.1', 0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f'http://127.0.0.1:{port}'

    def req(path, data=None):
        r = urllib.request.Request(base + path, method='POST' if data is not None else 'GET',
                                   data=None if data is None else json.dumps(data).encode(),
                                   headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b'{}')
    try:
        scenario(lambda p: req(p), lambda p, b: req(p, b))
    finally:
        srv.shutdown()


def test_insufficient_analysis():
    from app.analytics import analyze
    result = analyze([{'day': 5, 'sleep_hours': 7.2}], 5)
    assert result['status'] == 'insufficient'
    assert result['uncertainty'] == 'high'
