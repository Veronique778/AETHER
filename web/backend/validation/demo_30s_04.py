"""AETHER 1.5 — reproducible 30-second demo (BE3_04). ONE scientific claim; every data point is labelled SYNTHETIC.

Scenes (real Backend №2 HTTP server + SQLite in a temporary folder; no hardware):
  1  personal account → server-issued astronaut UUID
  2  SYNTHETIC heart rate (seeded generator, origin=simulated) stored through the public batch API
  3  quality / time check of what was stored
  4  PHANTOM personal → flag | no_flag | insufficient_data + explanation
  5  restart (a new Python process, new server) → the same analysis by its id

    cd web/backend && python -I validation/demo_30s_04.py            # needs requirements.txt (argon2-cffi)
    cd web/backend && python -I validation/demo_30s_04.py --test-argon2-shim   # offline build boxes only

The claim shown: "On SYNTHETIC test data with a known +15 bpm sustained step, PHANTOM flags the change against the
person's own frozen baseline and says insufficient_data when the baseline is missing." Nothing about health.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND)]
TOKEN = 'aether-demo-launch-token'
PASSWORD = 'Demo-Only-Password-2026!'          # demo account in a throw-away database
LABEL = 'SYNTHETIC'


def _server(db_path: Path):
    from app import db, security
    from app.devserver import serve
    db.DB_PATH = db_path
    db.init_db()
    srv = serve(port=0, policy=security.Policy(token=TOKEN))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _call(port, method, path, body=None, token=None):
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
    h = {'X-AETHER-Token': TOKEN}
    if token:
        h['Authorization'] = 'Bearer ' + token
    raw = None
    if body is not None:
        raw = json.dumps(body).encode()
        h['Content-Type'] = 'application/json'
    c.request(method, path, body=raw, headers=h)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, (json.loads(data) if data else None)


def synthetic_series(seed=42, minutes=180, step_at=110, step=15.0):
    rng = random.Random(seed)
    t0 = (datetime.now(timezone.utc) - timedelta(hours=4)).replace(microsecond=0)
    out = []
    for i, s in enumerate(range(0, minutes * 60, 2)):
        hr = 64 + rng.gauss(0, 2.0) + (step if s >= step_at * 60 else 0)
        out.append({'idempotency_key': f'demo04-{seed}-{i}', 'source': f'AETHER demo generator ({LABEL})',
                    'signal': 'heart_rate', 'value': float(round(hr)), 'unit': 'bpm',
                    'measured_at': (t0 + timedelta(seconds=s)).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'origin': 'simulated', 'quality': 'screened', 'metadata': {'generator_seed': seed}})
    return t0, out


def scene(n, title):
    print(f'\n[{n}] {title}  — data: {LABEL}', flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--test-argon2-shim', action='store_true')
    ap.add_argument('--restart-check', nargs=3, metavar=('DB', 'LOGIN', 'ANALYSIS_ID'))
    a = ap.parse_args(argv)
    if a.test_argon2_shim:
        sys.path.insert(0, str(BACKEND / 'tests'))
        import be3_argon2_env  # noqa: F401  (offline test shim: real Argon2id from `cryptography`)
    os.environ['AETHER_LEGACY_DEMO'] = '0'
    if a.restart_check:
        db_path, login, aid_ = a.restart_check
        srv = _server(Path(db_path))
        code, s = _call(srv.server_port, 'POST', '/api/auth/login', {'login': login, 'password': PASSWORD})
        code, r = _call(srv.server_port, 'GET', f'/api/phantom-analyses/{aid_}', token=s['access_token'])
        print(json.dumps({'status': code, 'analysis_id': r.get('analysis_id'), 'outcome': r.get('outcome'),
                          'digest': r['input']['measurement_digest'], 'data_label': r['explain']['data_label']}))
        srv.shutdown()
        return 0

    t_start = time.time()
    tmp = Path(tempfile.mkdtemp(prefix='aether_demo04_'))
    db_path = tmp / 'demo.db'
    srv = _server(db_path)
    port = srv.server_port

    scene(1, 'Personal account')
    _call(port, 'POST', '/api/auth/register', {'login': 'demo_astronaut', 'password': PASSWORD, 'display_name': 'Demo'})
    code, s = _call(port, 'POST', '/api/auth/login', {'login': 'demo_astronaut', 'password': PASSWORD})
    tok = s['access_token']
    me = _call(port, 'GET', '/api/auth/me', token=tok)[1]['user']
    aid = me['astronaut_id']
    print(f'    astronaut UUID from the server: {aid}')

    scene(2, 'Heart rate stored (seeded generator, +15 bpm step at 110 min)')
    t0, rows = synthetic_series()
    for i in range(0, len(rows), 500):
        code, body = _call(port, 'POST', '/api/measurements/batch', {'measurements': rows[i:i + 500]}, tok)
        assert code in (200, 201), body
    print(f'    {len(rows)} samples, origin=simulated, source="{rows[0]["source"]}"')

    scene(3, 'Quality and time')
    f, t = t0.strftime('%Y-%m-%dT%H:%M:%SZ'), (t0 + timedelta(minutes=180)).strftime('%Y-%m-%dT%H:%M:%SZ')
    code, r = _call(port, 'POST', '/api/phantom-analyses',
                    {'astronaut_id': aid, 'from': f, 'to': t, 'data_classes': ['synthetic']}, tok)
    assert code in (200, 201), r
    e = r['explain']
    print(f'    {e["signal_quality"]["valid"]}/{e["signal_quality"]["measurements"]} valid, '
          f'usable windows {e["signal_quality"]["usable_test_windows"]}/{e["signal_quality"]["test_windows"]}, '
          f'analysed {e["time_bounds"]["analysed_from"]} → {e["time_bounds"]["analysed_to"]} (UTC)')

    scene(4, 'PHANTOM personal + explanation')
    print(f'    outcome: {r["outcome"]}   label: {e["data_label"]}   method: {e["method"]["processing_version"]}')
    print(f'    baseline median {e["baseline"]["median_hr_bpm"]} bpm, scale {e["baseline"]["robust_scale_bpm"]} bpm;'
          f' largest change {e["deviation"]["difference_from_baseline_bpm"]} bpm (z = {e["deviation"]["max_robust_z"]})')
    print(f'    why: {e["why"][0]}')
    print(f'    next: {e["next_measurement"]}')
    code2, r2 = _call(port, 'POST', '/api/phantom-analyses',
                      {'astronaut_id': aid, 'from': (t0 + timedelta(minutes=20)).strftime('%Y-%m-%dT%H:%M:%SZ'),
                       'to': (t0 + timedelta(minutes=60)).strftime('%Y-%m-%dT%H:%M:%SZ'), 'data_classes': ['synthetic']}, tok)
    print(f'    only 40 minutes (baseline needs 60) → outcome: {r2["outcome"]} ({r2["explain"]["why"][0][:90]}…)')
    srv.shutdown()

    scene(5, 'Restart: new process, same database')
    out = subprocess.run([sys.executable, '-I', str(Path(__file__)), '--restart-check', str(db_path), 'demo_astronaut',
                          r['analysis_id']] + (['--test-argon2-shim'] if a.test_argon2_shim else []),
                         capture_output=True, text=True, timeout=120)
    data = json.loads(out.stdout.strip().splitlines()[-1])
    same = data['analysis_id'] == r['analysis_id'] and data['digest'] == r['input']['measurement_digest']
    print(f'    GET after restart: {data["status"]}, outcome {data["outcome"]}, same analysis and digest: {same}')
    print(f'\nDone in {time.time() - t_start:.1f} s. Claim shown: SYNTHETIC +15 bpm step is flagged; missing baseline → '
          f'insufficient_data. Not a medical device; hardware_verified=false.')
    return 0 if (r['outcome'] == 'flag' and r2['outcome'] == 'insufficient_data' and same) else 1


if __name__ == '__main__':
    raise SystemExit(main())
