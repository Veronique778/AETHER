"""Lifecycle tests for the desktop backend sidecar (run: python -m pytest desktop/tests -q).

Runs the sidecar from source (`aether_backend.py`). The same tests can be pointed at the packaged
executable with AETHER_SIDECAR=path\\to\\aether-backend.exe (used by the Windows CI workflow).
"""
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
# 1.4: the backend requires a per-launch session token on data routes; tests pass a fixed one.
TOKEN = 'sidecar-test-token'


class _Token(urllib.request.BaseHandler):
    handler_order = 100

    def http_request(self, request):
        request.add_header('X-AETHER-Token', TOKEN)
        return request


urllib.request.install_opener(urllib.request.build_opener(_Token()))
SIDECAR = os.environ.get('AETHER_SIDECAR')
CMD = [SIDECAR] if SIDECAR else [sys.executable, str(HERE.parent / 'backend' / 'aether_backend.py')]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def get(url: str, timeout=2.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def start(tmp_path, *extra, port=None):
    port = port or free_port()
    env = {**os.environ, 'AETHER_DB_PATH': str(tmp_path / 'data' / 'aether.sqlite3'), 'AETHER_SESSION_TOKEN': TOKEN}
    p = subprocess.Popen([*CMD, '--port', str(port), *extra], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            get(f'http://127.0.0.1:{port}/api/health')
            return p, port
        except OSError:
            if p.poll() is not None:
                raise AssertionError('sidecar exited: ' + (p.stdout.read() if p.stdout else ''))
            time.sleep(0.2)
    p.kill()
    raise AssertionError('sidecar not ready within 30 s')


def stop(p):
    if p.poll() is None:
        p.terminate()
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            p.kill()


def test_health_and_localhost_only(tmp_path):
    p, port = start(tmp_path)
    try:
        h = get(f'http://127.0.0.1:{port}/api/health')
        assert h['status'] == 'ok' and h['project'] == 'AETHER'
        # Not reachable through a non-loopback address of this machine (if it has one).
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except OSError:
            ip = '127.0.0.1'
        if not ip.startswith('127.'):
            with pytest.raises(OSError):
                get(f'http://{ip}:{port}/api/health', timeout=1.0)
    finally:
        stop(p)


def test_data_persists_in_app_data_dir(tmp_path):
    p, port = start(tmp_path)
    try:
        req = urllib.request.Request(f'http://127.0.0.1:{port}/api/astronauts/A02/measurements', method='POST',
                                     data=json.dumps({'day': 67, 'reaction_ms': 299}).encode(), headers={'Content-Type': 'application/json'})
        assert json.loads(urllib.request.urlopen(req, timeout=3).read())['saved'] is True
    finally:
        stop(p)
    assert (tmp_path / 'data' / 'aether.sqlite3').exists()
    p, port = start(tmp_path)
    try:
        rows = get(f'http://127.0.0.1:{port}/api/astronauts/A02/timeline?day=67')
        assert [r for r in rows if r['day'] == 67][0]['reaction_ms'] == 299
    finally:
        stop(p)


def test_graceful_stop(tmp_path):
    p, _ = start(tmp_path)
    t = time.time()
    if os.name == 'nt':
        p.terminate()
    else:
        p.send_signal(signal.SIGTERM)
    p.wait(10)
    assert time.time() - t < 6
    if os.name != 'nt':
        assert p.returncode == 0


def test_exits_when_parent_dies(tmp_path):
    parent = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    p, _ = start(tmp_path, '--parent-pid', str(parent.pid))
    try:
        parent.kill()
        parent.wait()
        p.wait(10)  # raises TimeoutExpired if the sidecar is orphaned
    finally:
        stop(p)
        stop(parent)
