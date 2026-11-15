"""AETHER 1.4 local-API security: Host, Origin, session token, body limits, CORS, CSV export."""
import asyncio
import http.client
import json
import threading

import pytest

from app import db, security
from app.devserver import serve

TOKEN = 'aether-test-token'


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'sec.sqlite3')
    static = tmp_path / 'dist'
    static.mkdir()
    (static / 'index.html').write_text('<!doctype html><html><head><title>t</title></head><body>AETHER</body></html>')
    (tmp_path / 'secret.txt').write_text('outside the static root')
    (tmp_path / 'dist-evil').mkdir()
    (tmp_path / 'dist-evil' / 'x.txt').write_text('sibling directory')
    srv = serve(port=0, static=str(static), policy=security.Policy(token=TOKEN, require_token=True))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_port
    srv.shutdown(); srv.server_close()


def raw(port, method, path, headers=None, body=None):
    """http.client: no global urllib opener, so no token is added implicitly."""
    con = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    h = {'Host': f'127.0.0.1:{port}', **(headers or {})}
    con.request(method, path, body=body, headers=h)
    r = con.getresponse()
    data = r.read()
    hdrs = {k.lower(): v for k, v in r.getheaders()}
    con.close()
    return r.status, hdrs, data


def test_health_is_public_but_data_routes_need_the_token(server):
    assert raw(server, 'GET', '/api/health')[0] == 200
    for path in ('/api/nasa/imports', '/api/biosignals/sessions', '/api/astronauts', '/api/connectors'):
        assert raw(server, 'GET', path)[0] == 401, path
        assert raw(server, 'GET', path, {'X-AETHER-Token': 'wrong'})[0] == 401, path
        assert raw(server, 'GET', path, {'X-AETHER-Token': TOKEN})[0] == 200, path


def test_state_changing_routes_refuse_missing_token(server):
    body = json.dumps({'confirm_simulated': True}).encode()
    status, _, _ = raw(server, 'POST', '/api/biosignals/demo/recording', {'Content-Type': 'application/json'}, body)
    assert status == 401
    status, _, _ = raw(server, 'POST', '/api/nasa/verified-csv', {'Content-Type': 'application/json'},
                       json.dumps({'study_id': 575, 'filename': 'x.csv'}).encode())
    assert status == 401


def test_foreign_origin_and_cross_site_are_refused_even_with_token(server):
    ok = {'X-AETHER-Token': TOKEN}
    assert raw(server, 'GET', '/api/nasa/imports', {**ok, 'Origin': 'https://evil.example'})[0] == 403
    assert raw(server, 'GET', '/api/nasa/imports', {**ok, 'Sec-Fetch-Site': 'cross-site'})[0] == 403
    assert raw(server, 'GET', '/api/nasa/imports', {**ok, 'Origin': 'null'})[0] == 403
    assert raw(server, 'GET', '/api/session', {'Origin': 'https://evil.example'})[0] == 403
    assert raw(server, 'GET', '/api/nasa/imports', {**ok, 'Origin': f'http://127.0.0.1:{server}'})[0] == 200


def test_dns_rebinding_host_is_refused(server):
    status, _, _ = raw(server, 'GET', '/', {'Host': 'attacker.example:80'})
    assert status == 421
    assert raw(server, 'GET', '/api/health', {'Host': 'attacker.example'})[0] == 421


def test_no_wildcard_cors(server):
    _, h, _ = raw(server, 'GET', '/api/health', {'Origin': 'https://evil.example'})
    assert h.get('access-control-allow-origin') != '*'
    _, h, _ = raw(server, 'GET', '/api/health', {'Origin': 'http://localhost:5173'})
    assert h.get('access-control-allow-origin') == 'http://localhost:5173'
    _, h, _ = raw(server, 'GET', '/api/health')
    assert 'access-control-allow-origin' not in h


def test_index_carries_token_and_session_bootstrap_is_same_origin(server):
    status, h, data = raw(server, 'GET', '/')
    assert status == 200 and f'name="aether-session-token" content="{TOKEN}"' in data.decode()
    assert h['cache-control'] == 'no-store'
    status, _, data = raw(server, 'GET', '/api/session')
    assert status == 200 and json.loads(data)['token'] == TOKEN


def test_body_limits(server):
    big = b'{"x":"' + b'a' * 300_000 + b'"}'
    assert raw(server, 'POST', '/api/mission-lab/run', {'X-AETHER-Token': TOKEN, 'Content-Type': 'application/json'}, big)[0] == 413
    bio = b'{"x":"' + b'a' * 20_000 + b'"}'
    assert raw(server, 'POST', '/api/biosignals/sensor/scan', {'X-AETHER-Token': TOKEN, 'Content-Type': 'application/json'}, bio)[0] == 413


def test_static_traversal_and_sibling_prefix(server):
    for path in ('/../secret.txt', '/%2e%2e/secret.txt', '/..%2fsecret.txt', '/../dist-evil/x.txt'):
        status, _, data = raw(server, 'GET', path)
        assert b'outside the static root' not in data and b'sibling directory' not in data, path


def test_session_id_and_offset_validation(server):
    ok = {'X-AETHER-Token': TOKEN}
    assert raw(server, 'GET', '/api/biosignals/sessions/..%2f..%2fetc', ok)[0] == 400
    assert raw(server, 'GET', '/api/biosignals/sessions/' + 'a' * 32 + '/csv?offset=-5', ok)[0] == 400


def test_check_function_unit():
    p = security.Policy(token='t', require_token=True, extra_origins=())
    h = {'host': '127.0.0.1:9'}
    assert security.check(p, 'GET', '/api/health', h) is None
    assert security.check(p, 'GET', '/api/x', h)[0] == 401
    assert security.check(p, 'GET', '/api/x', {**h, 'x-aether-token': 't'}) is None
    assert security.check(p, 'GET', '/api/x', {'host': 'evil.tld', 'x-aether-token': 't'})[0] == 421
    assert security.check(p, 'GET', '/api/x', {'host': '[::1]:8000', 'x-aether-token': 't'}) is None
    assert security.check(p, 'GET', '/api/x', {'host': 'localhost.evil.tld:80', 'x-aether-token': 't'})[0] == 421
    assert security.check(p, 'POST', '/api/x', {**h, 'x-aether-token': 't'}, 10_000_000)[0] == 413


def test_asgi_middleware_without_fastapi():
    """The FastAPI server uses security.ASGISecurity; exercise it as plain ASGI."""
    calls = []

    async def app(scope, receive, send):
        calls.append(scope['path'])
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'{}'})

    mw = security.ASGISecurity(app, security.Policy(token='t', require_token=True))

    def run(path, headers):
        sent = []

        async def send(m):
            sent.append(m)

        async def receive():
            return {'type': 'http.request', 'body': b''}
        scope = {'type': 'http', 'method': 'GET', 'path': path,
                 'headers': [(k.encode(), v.encode()) for k, v in headers.items()]}
        asyncio.run(mw(scope, receive, send))
        return sent[0]['status'], dict(sent[0]['headers'])

    assert run('/api/nasa/imports', {'host': '127.0.0.1:8000'})[0] == 401
    assert run('/api/nasa/imports', {'host': '127.0.0.1:8000', 'origin': 'https://evil.example', 'x-aether-token': 't'})[0] == 403
    status, headers = run('/api/nasa/imports', {'host': '127.0.0.1:8000', 'origin': 'http://localhost:5173', 'x-aether-token': 't'})
    assert status == 200 and headers[b'access-control-allow-origin'] == b'http://localhost:5173'
    assert calls == ['/api/nasa/imports']


@pytest.mark.parametrize('cell,expected', [('=HYPERLINK("x")', '\'=HYPERLINK("x")'), ('+SUM(A1)', "'+SUM(A1)"),
                                           ('@cmd', "'@cmd"), ('-12.5', '-12.5'), ('-x', "'-x"), (72.0, 72.0),
                                           (None, None), ('plain', 'plain'), ('\t=1', "'\t=1")])
def test_csv_formula_injection_neutralised(cell, expected):
    assert security.csv_safe(cell) == expected


def test_biosignal_csv_export_is_sanitised(tmp_path, monkeypatch):
    from app import biosignals as bio
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'csv.sqlite3')
    db.init_db(); bio.init()
    sid = bio.create('=cmd|calc', 'research', '@evil')
    bio.append(sid, [bio.measurement(1.0, 'heart_rate', 60.0, 'bpm', '=1+1', None, 'screened', {'k': '=x'})])
    out = bio.csv_page(sid)['csv']
    assert ",'=1+1," in out and ',60.0,' in out
