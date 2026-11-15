"""03A — security of the scientific routes behind Backend №2's server (stdlib devserver + the R-1 hook, real auth/DB).

IDOR on every scientific route, invalid / revoked Bearer, forged "system" context, request limits, the shared error
envelope, no route collision with Backend №2, and no secrets in logs.
"""
import logging
import re
import uuid

import pytest

from app import api15_science
from be3_real_backend import canonical_storage, Account, crew, real_db, revoke, stdlib_server  # noqa: F401

ADDR = 'C4:7A:1C:00:12:9F'


@pytest.fixture
def world(real_db):
    from app.devices import api as dapi
    from app.devices import manager as dm
    from app.science_storage_be2 import Be2ScienceStorage
    from fakes.ble_mock import ManualClock, ManualScheduler, MockTransport
    alice, med, adm, mid = crew()
    bob = Account('bob')
    tr = MockTransport()
    tr.add(ADDR)
    clock = ManualClock()
    dapi.set_manager(dm.DeviceManager(canonical_storage(), tr, clock=clock, scheduler=ManualScheduler(clock)))
    with stdlib_server() as call:
        code, dev = call('POST', '/api/devices', {'name': 'strap', 'kind': 'ble', 'external_id': ADDR}, alice.token)
        assert code == 201
        yield {'call': call, 'alice': alice, 'bob': bob, 'med': med, 'adm': adm, 'mid': mid, 'did': dev['id']}
    dapi.set_manager(None)


def _envelope(body):
    assert set(body) == {'error'} and {'code', 'detail'} <= set(body['error']), body
    return body['error']


def _foreign_requests(w):
    a = w['alice'].astronaut_id
    return [('POST', f'/api/devices/{w["did"]}/connect', {'astronaut_id': a}),
            ('POST', f'/api/devices/{w["did"]}/disconnect', {}),
            ('GET', f'/api/devices/{w["did"]}/status', None),
            ('POST', '/api/phantom-analyses', {'astronaut_id': a, 'from': '2026-11-01T00:00:00Z', 'to': '2026-11-01T03:00:00Z'}),
            ('GET', f'/api/phantom-analyses?astronaut_id={a}', None),
            ('GET', f'/api/phantom-analyses/{uuid.uuid4()}', None)]


@pytest.mark.parametrize('who', ['bob', 'adm', 'med'])
def test_idor_every_route_hidden_as_404(world, who):
    call, tok = world['call'], world[who].token
    for method, path, body in _foreign_requests(world):
        code, resp = call(method, path, body, tok)
        assert code == 404, (who, method, path, code, resp)
        err = _envelope(resp)
        assert err['code'] == 'not_found' and world['alice'].astronaut_id not in err['detail']
        assert world['did'] not in err['detail']


@pytest.mark.parametrize('header', [None, 'Bearer ', 'Bearer x', 'Bearer ' + 'A' * 43, 'Basic abc', 'bearer abc'])
def test_invalid_bearer_is_401_on_every_route(world, header):
    call = world['call']
    for method, path, body in _foreign_requests(world) + [('GET', '/api/signals', None), ('POST', '/api/devices/scan', {})]:
        code, resp = call(method, path, body, headers={'Authorization': header} if header else None)
        assert code == 401 and _envelope(resp)['code'] == 'unauthenticated', (method, path, header)


def test_revoked_session_and_changed_password_take_effect(world):
    call, alice = world['call'], world['alice']
    assert call('GET', '/api/signals', token=alice.token)[0] == 200
    alice.logout()
    assert call('GET', '/api/signals', token=alice.token)[0] == 401
    alice.relogin()
    assert call('GET', '/api/signals', token=alice.token)[0] == 200


def test_system_context_cannot_be_forged(world):
    call, bob, a = world['call'], world['bob'], world['alice'].astronaut_id
    forged = {'X-AETHER-System': '1', 'X-AETHER-Role': 'system', 'X-AETHER-User': world['alice'].id,
              'X-Forwarded-User': world['alice'].id, 'X-AETHER-Astronaut': a}
    for method, path, body in _foreign_requests(world):
        assert call(method, path, body, bob.token, headers=forged)[0] == 404
        assert call(method, path, body, headers=forged)[0] == 401
    body = {'astronaut_id': a, 'from': '2026-11-01T00:00:00Z', 'to': '2026-11-01T03:00:00Z', 'ctx': 'system',
            'role': 'administrator', 'user_id': world['alice'].id, 'system': True}
    code, resp = call('POST', '/api/phantom-analyses', body, bob.token)
    assert code in (404, 422)                                       # unknown fields refused or access hidden
    from app import science_storage_be2
    assert not hasattr(science_storage_be2, 'SystemContext')
    assert not any('system' in n.lower() for n in dir(science_storage_be2.Be2Context) if not n.startswith('_'))


def test_request_limits_and_envelope(world):
    call, tok = world['call'], world['alice'].token
    code, resp = call('POST', '/api/phantom-analyses', raw=b'{"a":"' + b'x' * 17000 + b'"}', token=tok,
                      headers={'Content-Type': 'application/json'})
    assert code in (413, 400) and _envelope(resp)
    code, resp = call('POST', '/api/phantom-analyses', raw=b'{}', token=tok, headers={'Content-Type': 'text/plain'})
    assert code == 415 and _envelope(resp)['code'] == 'content_type'
    code, resp = call('POST', '/api/phantom-analyses', raw=b'[1,2]', token=tok, headers={'Content-Type': 'application/json'})
    assert code == 422 and _envelope(resp)
    code, resp = call('POST', '/api/phantom-analyses', raw=b'{bad', token=tok, headers={'Content-Type': 'application/json'})
    assert code == 400 and _envelope(resp)['code'] == 'invalid_request'
    a = world['alice'].astronaut_id
    code, resp = call('GET', f'/api/phantom-analyses?astronaut_id={a}&astronaut_id={a}', token=tok)
    assert code == 422 and _envelope(resp)['code'] == 'query_duplicate'


def test_no_route_collision_with_backend2():
    from be3_real_backend import require_backend2
    require_backend2()                                                  # app.api_15 imports Backend №2 auth
    from app import api_15
    for method, pattern, *_ in api15_science.ROUTES:
        sample = re.sub(r'\(\?P<[^>]+>[^)]*\)', 'abc-1', pattern).lstrip('^').rstrip('$')
        assert api15_science.match(method, sample), (method, sample)
        assert not any(rx.fullmatch(sample) and r.method == method for r, rx in api_15.COMPILED), (method, pattern)
    # the device REGISTRY is Backend №2's only
    assert api15_science.match('POST', '/api/devices') is None and api15_science.match('GET', '/api/devices') is None
    assert any(r.method == 'POST' and r.path == '/api/devices' for r, _ in api_15.COMPILED)


def test_tokens_and_passwords_never_logged(world, caplog):
    call, alice = world['call'], world['alice']
    caplog.set_level(logging.DEBUG)
    call('GET', '/api/signals', token=alice.token)
    call('POST', f'/api/devices/{world["did"]}/connect', {'astronaut_id': alice.astronaut_id}, world['bob'].token)
    call('POST', '/api/phantom-analyses', {'astronaut_id': alice.astronaut_id}, alice.token)
    text = caplog.text
    for secret in (alice.token, world['bob'].token, 'Correct-Horse-Planet-42'):
        assert secret not in text
    from app import db
    with db.connect() as c:
        dump = '\n'.join(str(tuple(r)) for r in c.execute('SELECT * FROM audit_logs'))
    assert alice.token not in dump and world['bob'].token not in dump
