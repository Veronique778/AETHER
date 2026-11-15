"""Backend №3 (03A) test helpers for running the scientific modules on Backend №2's REAL persistence.

Nothing here is used by application code. It never writes SQL into Backend №2 tables except one documented case:
promoting a test account to `administrator` (Backend №2's own tests do the same — there is no public API for it).

Every fixture uses a fresh temporary SQLite file through Backend №2's db.init_db() (the same single database the
application uses) — no second store. Requires Backend №2's app.auth, i.e. argon2-cffi, or the opt-in test shim:
    PYTHONPATH=tests python -m pytest -p be3_argon2_env tests/...
"""
from __future__ import annotations

import http.client
import json
import threading
from contextlib import contextmanager

import pytest

PASSWORD = 'Correct-Horse-Planet-42'          # same test password style as Backend №2's helpers_15 (no real secret)
LAUNCH_TOKEN = 'aether-test-token'


def require_backend2():
    """Skip (with a reason) when Backend №2's auth cannot be imported in this environment."""
    pytest.importorskip('argon2', reason='Backend №2 auth needs argon2-cffi (or -p be3_argon2_env test shim)')
    try:
        from app import auth  # noqa: F401
        from app.persistence import repository  # noqa: F401
    except ImportError as exc:                    # pragma: no cover - environment dependent
        pytest.skip(f'integration_pending: Backend №2 persistence not importable ({exc})')


@pytest.fixture
def real_db(tmp_path, monkeypatch):
    """Fresh Backend №2 database (schema + migrations by Backend №2's own init_db)."""
    require_backend2()
    from app import db, science_storage
    monkeypatch.setenv('AETHER_LEGACY_DEMO', '0')
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'aether_be2_test.db')
    db.init_db()
    science_storage.set_storage(None)               # production resolution: must find Be2ScienceStorage, never a fake
    from app.devices import hw_lock
    hw_lock._reset_for_tests()
    yield tmp_path / 'aether_be2_test.db'
    science_storage.set_storage(None)
    hw_lock._reset_for_tests()


class Account:
    """A registered Backend №2 user with a personal session token (token never printed: repr redacted)."""

    def __init__(self, login: str, peer: str | None = None):
        from app import auth
        reg = auth.register(login, PASSWORD, login, peer=peer or login)
        self.login = login
        self.recovery_code = reg.get('recovery_code')
        self.token = auth.login(login, PASSWORD, peer=peer or login)['access_token']
        self.user = auth.authenticate(self.token)

    def __repr__(self):
        return f'Account({self.login!r}, <token redacted>)'

    @property
    def id(self):
        return self.user['id']

    @property
    def astronaut_id(self):
        return self.user['astronaut_id']

    def ctx(self):
        from app.science_storage_be2 import Be2Context
        return Be2Context(self.token)

    def relogin(self):
        from app import auth
        self.token = auth.login(self.login, PASSWORD, peer=self.login)['access_token']
        self.user = auth.authenticate(self.token)
        return self

    def logout(self):
        from app import auth
        auth.logout(self.user, self.token)


def canonical_storage():
    """The production factory (BE2_06): app.persistence.science_storage() → CanonicalScienceStorage. Direct
    instantiation of the BE3 base adapter is not the integrated storage and cannot write wearable provenance."""
    from app.persistence import science_storage
    return science_storage()


def make_admin(acc: Account) -> Account:
    from app import db
    with db.connect() as c:                         # same as Backend №2's tests/test_permissions_15.setup_crew
        c.execute("UPDATE users SET role='administrator' WHERE id=?", (acc.id,))
    acc.user = {**acc.user, 'role': 'administrator'}
    return acc


def crew(names=('alice', 'medic', 'admin'), can_review=False, grant=True):
    """alice (astronaut) + medic (medical_officer) in one mission, admin administrator. Optional medical_access grant."""
    from app.persistence import missions
    a, med, adm = (Account(n) for n in names)
    make_admin(adm)
    mid = missions.create_mission(adm.user, {'name': 'Alpha'})['id']
    for acc, role in [(a, 'astronaut'), (med, 'medical_officer')]:
        missions.membership(adm.user, mid, {'user_id': acc.id, 'role': role})
    if grant:
        missions.grant(adm.user, mid, {'officer_id': med.id, 'astronaut_id': a.astronaut_id, 'can_review': can_review})
    return a, med, adm, mid


def revoke(adm: Account, mid: str, officer: Account, astronaut: Account):
    from app.persistence import missions
    missions.revoke(adm.user, mid, officer.id, astronaut.astronaut_id)


@contextmanager
def stdlib_server():
    """Backend №2's stdlib devserver with the ONE documented hook (BE2_REQUIRED_CHANGES R-1) applied in-process:
    science_http.handle is consulted before Backend №2's own dispatcher; Backend №2 code is not edited."""
    import inspect
    from app import api_15, science_http, security
    from app.devserver import serve
    original = api_15.dispatch
    already_wired = 'science_http' in inspect.getsource(original)   # after Backend №2 applies R-1: test the real hook

    def hooked(method, path, headers, raw, query, peer='local'):
        science = science_http.handle(method, path, headers, raw, query, peer)
        return science if science is not None else original(method, path, headers, raw, query, peer)

    if not already_wired:
        api_15.dispatch = hooked
    srv = serve(port=0, policy=security.Policy(token=LAUNCH_TOKEN))
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()

    def call(method, path, body=None, token=None, headers=None, raw=None):
        c = http.client.HTTPConnection('127.0.0.1', srv.server_port, timeout=20)
        h = {'X-AETHER-Token': LAUNCH_TOKEN, **(headers or {})}
        if token:
            h['Authorization'] = 'Bearer ' + token
        if body is not None:
            raw = json.dumps(body).encode()
            h.setdefault('Content-Type', 'application/json')
        c.request(method, path, body=raw, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        try:
            return r.status, (json.loads(data) if data else None)
        except ValueError:
            return r.status, data
    try:
        yield call
    finally:
        api_15.dispatch = original
        srv.shutdown()
        srv.server_close()
        th.join(timeout=3)
