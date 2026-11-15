"""AETHER 1.4 one-command QA runner with hard per-stage timeouts.

Each stage runs in its own process with its own timeout, so a hang in one stage
is reported as TIMEOUT instead of stalling the whole run (the 1.3 "combined run
stalled" report). Logs go to validation_1_4/logs/, the summary to
validation_1_4/qa-results.json.

    python tools/run_all_tests_1_4.py [--skip-browser] [--node-paths DIR]

Environment: AETHER_NODE_PATHS (esbuild/tailwindcss/react), AETHER_PLAYWRIGHT_FROM
(node_modules/noop.js containing playwright), PLAYWRIGHT_BROWSERS_PATH.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACK = ROOT / 'web' / 'backend'
FRONT = ROOT / 'web' / 'frontend'
OUT = ROOT / 'validation_1_4'
PY = sys.executable


def free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def run(name, cmd, cwd, timeout, env=None, logs=None):
    started = time.time()
    log = logs / f'{name}.log'
    try:
        r = subprocess.run(cmd, cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True, text=True, timeout=timeout)
        status = 'PASS' if r.returncode == 0 else 'FAIL'
        out = r.stdout + r.stderr
    except subprocess.TimeoutExpired as e:
        status, out = 'TIMEOUT', (e.stdout or '') + (e.stderr or '') if isinstance(e.stdout, str) else 'timeout'
    except FileNotFoundError as e:
        status, out = 'NOT RUN', f'tool missing: {e}'
    log.write_text(out if isinstance(out, str) else str(out), encoding='utf-8')
    tail = [ln for ln in (out or '').splitlines() if ln.strip()][-3:]
    res = {'stage': name, 'status': status, 'seconds': round(time.time() - started, 1), 'command': ' '.join(map(str, cmd)),
           'log': str(log.relative_to(ROOT)), 'summary': tail}
    print(f"{status:8} {name:28} {res['seconds']:>7}s  {tail[-1] if tail else ''}", flush=True)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--skip-browser', action='store_true')
    ap.add_argument('--node-paths', default=os.environ.get('AETHER_NODE_PATHS', ''))
    a = ap.parse_args()
    logs = OUT / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    node = shutil.which('node')
    node_env = {'AETHER_NODE_PATHS': a.node_paths} if a.node_paths else {}
    results = []
    tmp = Path(tempfile.mkdtemp(prefix='aether-qa-'))
    base_env = {'AETHER_DB_PATH': str(tmp / 'qa.sqlite3'), 'AETHER_NASA_DATA_DIR': str(tmp / 'nasa'), **node_env}

    results.append(run('backend-pytest', [PY, '-m', 'pytest', '-q', '-rs', '-o', 'faulthandler_timeout=180'], BACK, 900, base_env, logs))
    results.append(run('repo-extra-pytest', [PY, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'desktop/tests', 'tools'], ROOT, 300, base_env, logs))
    results.append(run('mock-ble-harness', [PY, '-I', str(BACK / 'validation' / 'mock_hrs_harness.py'), '--report', str(OUT / 'mock-hrs-report.json')], BACK, 120, None, logs))
    results.append(run('desktop-smoke-nonfrozen', [PY, str(ROOT / 'desktop_native.py'), '--smoke-test', '--report', str(OUT / 'desktop-smoke-nonfrozen.json')], ROOT, 300, None, logs))
    if node:
        results.append(run('frontend-unit', [node, 'scripts/run-tests.mjs'], FRONT, 300, node_env, logs))
        results.append(run('sensor-bridge', [node, 'tests/sensor-bridge.test.cjs'], FRONT, 60, None, logs))
        tsc = shutil.which('tsc')
        results.append(run('typecheck', [tsc, '-p', 'typecheck-shims/tsconfig.offline.json'] if tsc else ['tsc'], FRONT, 300, None, logs))
    else:
        results.append({'stage': 'frontend (node)', 'status': 'NOT RUN', 'summary': ['node not installed']})
    if node and not a.skip_browser:
        port = free_port()
        srv = subprocess.Popen([PY, '-m', 'app.devserver', '--port', str(port), '--static', str(FRONT / 'dist-offline')], cwd=BACK,
                               env={**os.environ, 'AETHER_DB_PATH': str(tmp / 'e2e10.sqlite3'), 'AETHER_NASA_DATA_DIR': str(tmp / 'n10')},
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(2.5)
            results.append(run('browser-e2e-v10', [node, 'tests/browser/e2e-v10.mjs', f'http://127.0.0.1:{port}/', str(OUT / 'screens-v10')], FRONT, 900, None, logs))
        finally:
            srv.terminate()
        results.append(run('browser-e2e-v14', [node, 'tests/browser/e2e-v14.mjs', str(OUT / 'screens-v14'), str(OUT / 'e2e-v14.json')], FRONT, 900,
                           {'PYTHON': PY}, logs))
    summary = {'release': '1.4.0', 'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
               'environment': {'os': platform.platform(), 'python': platform.python_version(), 'node': subprocess.run([node, '--version'], capture_output=True, text=True).stdout.strip() if node else None},
               'stages': results, 'all_pass': all(r['status'] == 'PASS' for r in results)}
    (OUT / 'qa-results.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print('ALL PASS' if summary['all_pass'] else 'NOT ALL PASS — see validation_1_4/qa-results.json')
    sys.exit(0 if summary['all_pass'] else 1)


if __name__ == '__main__':
    main()
