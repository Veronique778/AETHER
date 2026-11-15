"""AETHER 1.0 · B7: scientific / engine API contracts over HTTP (stdlib server), FastAPI ↔ stdlib route parity.

FastAPI itself cannot be installed in this environment (no network for pip); the FastAPI app (app.main) and the
stdlib server (app.devserver) call the same app.service functions. `test_fastapi_and_stdlib_routes_match` proves
statically that both expose the same method + path set, and the FastAPI variant of these tests runs automatically
where fastapi + httpx are installed.
"""
import ast
import json
import re
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app import db, mission_engine as me

APP = Path(__file__).resolve().parents[1] / 'app'


@pytest.fixture()
def server():
    prev = db.DB_PATH
    with tempfile.TemporaryDirectory() as tmp:
        db.DB_PATH = Path(tmp) / 'api.sqlite3'
        me._sims.clear(); me._baselines.clear()
        from app.devserver import serve
        srv = serve('127.0.0.1', 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{srv.server_address[1]}'

        def call(path, data=None, method=None):
            rq = urllib.request.Request(base + path, data=None if data is None else json.dumps(data).encode(),
                                        headers={'Content-Type': 'application/json'},
                                        method=method or ('POST' if data is not None else 'GET'))
            try:
                with urllib.request.urlopen(rq, timeout=180) as resp:
                    return resp.status, json.loads(resp.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read() or b'{}')
        try:
            yield call
        finally:
            srv.shutdown()
            db.DB_PATH = prev
            me._sims.clear(); me._baselines.clear()


# ------------------------------------------------------------------ route parity (static)
def _fastapi_routes():
    tree = ast.parse((APP / 'main.py').read_text(encoding='utf-8'))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ('get', 'post', 'delete', 'put'):
                    path = d.args[0].value
                    out.add((d.func.attr.upper(), re.sub(r'\{[^}]+\}', '{}', path)))
    return out


def _stdlib_routes():
    from app.devserver import ROUTES
    out = set()
    for method, pattern, _ in ROUTES:
        p = pattern.rstrip('$')
        p = re.sub(r'\(\?P<[^>]+>[^)]+\)', '{}', p)
        out.add((method, p))
    return out


def test_fastapi_and_stdlib_routes_match():
    fa, sd = _fastapi_routes(), _stdlib_routes()
    assert fa - sd == set(), f'only in FastAPI: {fa - sd}'
    assert sd - fa == set(), f'only in stdlib: {sd - fa}'
    for needed in [('GET', '/api/phantom2/{}'), ('GET', '/api/science/evidence'), ('GET', '/api/science/hazards'),
                   ('POST', '/api/science/graph'), ('POST', '/api/science/radiation'), ('GET', '/api/engine/runs/{}/coorbit'),
                   ('GET', '/api/engine/runs/{}/symbiosis'), ('POST', '/api/engine/runs/{}/replan'),
                   ('POST', '/api/engine/runs/{}/coorbit/reject'), ('GET', '/api/engine/runs/{}/environment')]:
        assert needed in fa


# ------------------------------------------------------------------ science endpoints
def test_science_evidence_types_and_integrity(server):
    code, ev = server('/api/science/evidence')
    assert code == 200 and len(ev['entries']) == 16 and ev['verified_on'] == '2026-11-14'
    for e in ev['entries']:
        assert isinstance(e['id'], str) and e['url'].startswith('https://')
        assert e['doi'] is None or (re.match(r'^10\.\d{4,9}/\S+$', e['doi']) and e['url'] == f"https://doi.org/{e['doi']}")
        assert isinstance(e['metrics'], list) and e['finding'] and e['limitation']


def test_science_hazards_and_graph_validation(server):
    code, hz = server('/api/science/hazards')
    assert code == 200 and len(hz['hazards']) == 5 and len(hz['hrp_map']) == 17
    code, g = server('/api/science/graph', {'destination': 'mars', 'mission_days': 900})
    assert code == 200 and g['nodes'] and g['edges']
    assert server('/api/science/graph', {'destination': 'venus'})[0] == 422          # schema validation
    assert server('/api/science/graph', {'mission_days': 0})[0] == 422
    assert server('/api/science/graph', {'co2_ppm': None})[0] == 422                 # null where a number is required


def test_science_radiation_units_and_errors(server):
    code, r = server('/api/science/radiation', {'segments': [{'environment': 'deep_space', 'days': 100}], 'runs': 200, 'seed': 1})
    assert code == 200
    assert isinstance(r['final']['p50'], (int, float)) and r['final']['p5'] <= r['final']['p50'] <= r['final']['p95']
    text = json.dumps(r)
    assert 'mSv' in text or 'msv' in text
    assert server('/api/science/radiation', {'preset': 'nope'})[0] == 400
    assert server('/api/science/radiation', {'segments': [{'environment': 'pluto', 'days': 3}]})[0] == 422
    assert server('/api/science/radiation', {'segments': [{'environment': 'iss', 'days': -1}]})[0] == 422
    code, presets = server('/api/science/radiation/presets')
    assert code == 200 and presets['limits']['career_msv'] == 600


def test_phantom2_daily_contract(server):
    code, p = server('/api/phantom2/A01?day=67')
    assert code == 200 and p['status'] == 'ok'
    assert set(p['today']) >= {'zscore', 'ewma', 'adaptive', 'cusum', 'mahalanobis', 'phantom2'}
    assert all(v in (True, False, None) for v in p['today'].values())
    assert server('/api/phantom2/NOPE')[0] == 404
    assert server('/api/phantom2/A01?day=abc')[0] == 422
    assert server('/api/phantom2/A01?day=0')[0] == 422


# ------------------------------------------------------------------ engine endpoints
def test_engine_coorbit_symbiosis_replan_environment(server):
    assert server('/api/engine/runs', {'template': 'nope'})[0] == 400
    assert server('/api/engine/runs', {'template': 'normal', 'seed': -1})[0] == 422
    code, run = server('/api/engine/runs', {'template': 'multifactor', 'seed': 5})
    assert code == 200 and run['origin'] == 'synthetic'
    rid = run['id']
    for s in run['schedules']['strategies']:          # 1.0 solver contract, legacy `status` kept
        assert {'status', 'solver_status', 'valid', 'has_feasible_solution', 'optimality_proven', 'reason', 'validation_errors'} <= set(s)
        assert isinstance(s['valid'], bool) and isinstance(s['validation_errors'], list)
        assert all(isinstance(u, dict) and u['reason'] for u in s['unscheduled'])
    code, recs = server(f'/api/engine/runs/{rid}/coorbit')
    assert code == 200 and recs['recommendations'] and len(recs['environment_context']) == 3
    code, sym = server(f'/api/engine/runs/{rid}/symbiosis?env_metric=co2&metric=fatigue&crew_id=1')
    assert code == 200 and sym['causal'] is False and len(sym['relationship']) == 5
    assert server(f'/api/engine/runs/{rid}/symbiosis?env_metric=radon')[0] == 400
    assert server(f'/api/engine/runs/{rid}/symbiosis?crew_id=x')[0] == 422
    code, rp = server(f'/api/engine/runs/{rid}/replan', {'crew_updates': [{'id': 2, 'add_rest': [{'start': 600, 'end': 660}]}]})
    assert code == 200 and rp['valid'] is True and rp['decision_status'] == 'proposal_ready' and rp['applied'] is False
    assert server(f'/api/engine/runs/{rid}/replan', {'crew_updates': [{'id': 1, 'available': []}]})[0] == 400
    assert server(f'/api/engine/runs/{rid}/replan', {'crew_updates': [{'available': []}]})[0] == 400
    code, rp = server(f'/api/engine/runs/{rid}/replan', {'crew_updates': [{'id': c['id'], 'add_rest': [{'start': 0, 'end': 1440}]} for c in run['crew']]})
    assert code == 200 and rp['valid'] is False and rp['previous_schedule_preserved'] is True and rp['reason']
    code, env = server(f'/api/engine/runs/{rid}/environment')
    assert code == 200 and env['events'] and all(c['diagnosis'] is None for c in env['crew_context'])
    code, rej = server(f'/api/engine/runs/{rid}/coorbit/reject', {'rejected_ids': [recs['recommendations'][0]['id']], 'reviewed_by': 'Flight surgeon'})
    assert code == 200 and rej['changed'] is False
    assert server(f'/api/engine/runs/{rid}/coorbit/reject', {'rejected_ids': ['x'], 'reviewed_by': 'A'})[0] == 400
    # missing resources
    for path in ('/api/engine/runs/nope', '/api/engine/runs/nope/coorbit', '/api/engine/runs/nope/environment', '/api/engine/runs/nope/symbiosis'):
        assert server(path)[0] == 404, path
    assert server('/api/engine/runs/nope/replan', {})[0] == 404
    assert server('/api/does-not-exist')[0] == 404


def test_health_version_and_capabilities(server):
    code, h = server('/api/health')
    assert code == 200 and h['version'] == '1.0.0' and h['api_contract_version'] == '1.0'
    assert {'environment-detector', 'coorbit-reject', 'coorbit-phantom', 'phantom2', 'science-core'} <= set(h['capabilities'])


def test_serialization_is_strict_json(server):
    """No NaN / Infinity in responses (JSON.parse in the browser rejects them)."""
    code, run = server('/api/engine/runs', {'template': 'missing', 'seed': 3})
    assert code == 200
    for path in (f"/api/engine/runs/{run['id']}", f"/api/engine/runs/{run['id']}/environment", '/api/phantom2/A02', '/api/science/hazards'):
        status, body = server(path)
        assert status == 200
        json.dumps(body, allow_nan=False)


def test_concurrent_requests_and_latency(server):
    code, run = server('/api/engine/runs', {'template': 'sleep_loss', 'seed': 9})
    rid = run['id']
    paths = ['/api/health', '/api/science/evidence', '/api/science/hazards', f'/api/engine/runs/{rid}',
             f'/api/engine/runs/{rid}/coorbit', f'/api/engine/runs/{rid}/environment', '/api/phantom2/A01', '/api/astronauts'] * 2
    t0 = time.time()
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(server, paths))
    assert all(c == 200 for c, _ in res), [c for c, _ in res]
    same = [b for (c, b), p in zip(res, paths) if p == f'/api/engine/runs/{rid}/coorbit']
    assert same[0]['recommendations'] == same[1]['recommendations']        # consistent under concurrency
    assert time.time() - t0 < 120
    t0 = time.time(); server('/api/science/evidence'); assert time.time() - t0 < 2.0
    # two engine runs at once with identical parameters → identical, deterministic ids and data
    with ThreadPoolExecutor(2) as ex:
        a, b = list(ex.map(lambda _: server('/api/engine/runs', {'template': 'pulse_shift', 'seed': 77}), range(2)))
    assert a[0] == b[0] == 200 and a[1]['id'] == b[1]['id'] and a[1]['series'] == b[1]['series']
