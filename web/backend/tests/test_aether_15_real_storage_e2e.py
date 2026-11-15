"""AETHER 1.5 — END-TO-END on Backend №2's REAL storage (Backend №3, package 03A).

Real: Backend №2 SQLite schema + migrations (db.init_db), auth (register/login/Bearer, Argon2id — via the opt-in test shim
when argon2-cffi is absent), access_control, repository, stdlib devserver + security.Policy, Backend №2 device registry.
Simulated: the BLE strap (MockTransport) and the time base (ManualClock). Nothing here verifies physical hardware.

Scenarios
    A  personal PHANTOM: register → login → UUID profile → BE2 device registry → BLE connect → sensor session →
       measurements → PHANTOM → saved → idempotent replay → process restart (fresh interpreter reads the same DB)
    B  two users, two profiles, two mock straps, ONE database: isolation, foreign device, no duplicates, one physical
       device cannot be opened twice (Device Manager + legacy ble_sensor share the hardware lock)
    C  Backend №2 manual entries read by the scientific layer: unit conversion (h → s), no trust upgrade, 409 on a
       changed payload under the same idempotency key
    D  roles: administrator is not a medical superuser; medical officer reads only with a grant and only for the
       mission; cannot run PHANTOM; revocation and logout take effect immediately
    E  fail-closed: storage unavailable → 503 (no fake data, no mock fallback); legacy demo ids are refused on the
       personal API; FastAPI variant reported as not executed in this environment
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from be3_real_backend import canonical_storage, Account, crew, real_db, revoke, stdlib_server  # noqa: F401  (fixture import)

ADDR_A = 'C4:7A:1C:00:12:9F'
ADDR_B = 'D8:11:22:33:44:55'
BACKEND = Path(__file__).resolve().parents[1]


def _start():
    # three hours ago: realistic past timestamps (Backend №2 does not reject future times — see BE2_REQUIRED_CHANGES O-1)
    return (datetime.now(timezone.utc) - timedelta(hours=3)).replace(microsecond=0)


class Rig:
    """Mock BLE transport + Device Manager on the REAL Backend №2 storage adapter."""

    def __init__(self, *addrs, start=None):
        from app.devices import api as dapi
        from app.devices import manager as dm
        from app.science_storage_be2 import Be2ScienceStorage
        from fakes.ble_mock import ManualClock, ManualScheduler, MockTransport
        self.storage = canonical_storage()
        self.batches = []                                     # every batch the Device Manager hands to storage
        save = self.storage.save_measurements

        def recording_save(ctx, items):
            self.batches.append([dict(x) for x in items])
            return save(ctx, items)
        self.storage.save_measurements = recording_save
        self.tr = MockTransport()
        for a in addrs:
            self.tr.add(a)
        self.clock = ManualClock(start=start or _start())
        self.m = dm.DeviceManager(self.storage, self.tr, clock=self.clock, scheduler=ManualScheduler(self.clock))
        dapi.set_manager(self.m)

    def close(self):
        from app.devices import api as dapi
        dapi.set_manager(None)


def register_device(call, acc, addr, name='Polar H10'):
    code, dev = call('POST', '/api/devices', {'name': name, 'kind': 'ble', 'external_id': addr}, acc.token)
    assert code == 201, dev
    return dev['id']


def record(call, rig, acc, did, addr, minutes=90, step_at=60, mission_id=None, seed=3):
    body = {'astronaut_id': acc.astronaut_id, **({'mission_id': mission_id} if mission_id else {})}
    code, con = call('POST', f'/api/devices/{did}/connect', body, acc.token)
    assert code == 200, con
    rng = random.Random(seed)
    for s in range(0, minutes * 60, 2):
        rig.m.scheduler.advance(2)
        hr = (62 if s / 60 < step_at else 74) + rng.gauss(0, 1.0)
        rig.tr.link(addr).hr(int(round(hr)), (int(1024 * 60 / hr),), True)
    code, off = call('POST', f'/api/devices/{did}/disconnect', {}, acc.token)
    assert code == 200 and off['pending_rows'] == 0, off
    return con['session_id'], off


def _count(astronaut_id=None):
    from app import db
    with db.connect() as c:
        if astronaut_id:
            return c.execute('SELECT COUNT(*) FROM raw_measurements WHERE astronaut_id=?', (astronaut_id,)).fetchone()[0]
        # Backend №2 seeds legacy demo rows (A01–A04, data_class legacy_demo) — personal rows only
        return c.execute("SELECT COUNT(*) FROM raw_measurements m JOIN astronaut_profiles p ON p.id=m.astronaut_id "
                         "WHERE p.data_class='personal'").fetchone()[0]


# ------------------------------------------------------------------------------------------------------------------ A
def test_A_personal_phantom_on_real_storage_survives_restart(real_db):
    with stdlib_server() as call:
        code, reg = call('POST', '/api/auth/register', {'login': 'alice', 'password': 'Correct-Horse-Planet-42',
                                                        'display_name': 'Alice'})
        assert code == 201
        code, sess = call('POST', '/api/auth/login', {'login': 'alice', 'password': 'Correct-Horse-Planet-42'})
        assert code == 200
        token = sess['access_token']
        code, me = call('GET', '/api/auth/me', token=token)
        aid = me['user']['astronaut_id']
        from app import identity
        assert identity.astronaut_kind(aid) == identity.PERSONAL               # canonical UUID, not A01–A04

        acc = Account.__new__(Account)
        acc.login, acc.token, acc.user = 'alice', token, me['user']
        rig = Rig(ADDR_A)
        try:
            did = register_device(call, acc, ADDR_A)                            # Backend №2 registry (single source)
            code, devices = call('GET', '/api/devices', token=token)
            assert [d['id'] for d in devices['items']] == [did]
            sid, off = record(call, rig, acc, did, ADDR_A)
            assert off['stored_samples'] == 5400 and _count(aid) == 5400

            code, sessions = call('GET', f'/api/devices/{did}/sessions', token=token)
            assert code == 200 and [s['id'] for s in sessions['items']] == [sid] and sessions['items'][0]['ended_at']

            code, r = call('POST', '/api/phantom-analyses', {'astronaut_id': aid, 'session_id': sid}, token)
            assert code == 201, r
            assert r['outcome'] == 'flag' and r['diagnosis'] is None
            assert r['input']['data_classes'] == ['real_wearable'] and r['input']['astronaut_kind'] == 'personal'
            assert r['input']['valid_count'] == 5400 and r['storage']['backend'] == 'backend2'
            for field in ('processing_version', 'reproducibility', 'idempotency_key'):
                assert r.get(field), field
            assert r['input']['measurement_digest'] and r['input']['digest_schema']
            # BE2_06 (R-8 done): all 5400 input ids are retained with a persistence digest — no silent truncation
            assert r['input_scope'] == {'input_ids_complete': True, 'input_count': 5400}
            assert r['storage'].get('input_count') == 5400 and r['storage'].get('input_digest')

            code, again = call('POST', '/api/phantom-analyses', {'astronaut_id': aid, 'session_id': sid}, token)
            assert code == 200 and again['analysis_id'] == r['analysis_id'] and again['idempotent_replay'] is True
            code, got = call('GET', f'/api/phantom-analyses/{r["analysis_id"]}', token=token)
            assert code == 200 and got['input']['measurement_digest'] == r['input']['measurement_digest']
            code, lst = call('GET', f'/api/phantom-analyses?astronaut_id={aid}', token=token)
            assert code == 200 and [x['analysis_id'] for x in lst['items']] == [r['analysis_id']]
            # Backend №2's own history sees the same analysis row (one store)
            code, be2 = call('GET', '/api/analyses', token=token)
            assert [x['id'] for x in be2['items']] == [r['analysis_id']]
        finally:
            rig.close()

    # process restart: a fresh interpreter opens the same database, logs in again and re-reads everything
    script = f"""
import sys, json
sys.path[:0] = [{str(BACKEND)!r}, {str(BACKEND / 'tests')!r}]
import be3_argon2_env
from pathlib import Path
from app import db, auth
db.DB_PATH = Path({str(real_db)!r}); db.init_db()
from app.science_storage_be2 import Be2Context
from app.persistence import science_storage as canonical_storage
tok = auth.login('alice', 'Correct-Horse-Planet-42', peer='restart')['access_token']
ctx = Be2Context(tok); st = canonical_storage()
a = st.get_analysis(ctx, {r['analysis_id']!r})
page = st.query_measurements(ctx, ctx.astronaut_id, limit=500)
print(json.dumps({{'outcome': a['outcome'], 'digest': a['input']['measurement_digest'], 'n': len(page['items']),
                  'aid': ctx.astronaut_id, 'cursor': page['next_cursor'] is not None}}))
"""
    out = subprocess.run([sys.executable, '-I', '-c', script], capture_output=True, text=True, timeout=120,
                         env={k: v for k, v in os.environ.items() if k != 'PYTHONPATH'})
    assert out.returncode == 0, out.stderr[-2000:]
    data = json.loads(out.stdout.strip().splitlines()[-1])
    assert data == {'outcome': 'flag', 'digest': r['input']['measurement_digest'], 'n': 500, 'aid': aid, 'cursor': True}


# ------------------------------------------------------------------------------------------------------------------ B
def test_B_two_users_two_straps_one_database_isolated(real_db):
    from app import ble_sensor
    from app.devices import manager as dm
    from app.science_errors import DeviceBusy
    alice, bob = Account('alice'), Account('bob')
    assert alice.astronaut_id != bob.astronaut_id and alice.id != bob.id
    with stdlib_server() as call:
        rig = Rig(ADDR_A, ADDR_B)
        try:
            da = register_device(call, alice, ADDR_A)
            db_ = register_device(call, bob, ADDR_B)
            # the same hardware address may be registered by two astronauts (Backend №2 UNIQUE(astronaut_id, external_id))
            # but not twice by the same one
            code, dup = call('POST', '/api/devices', {'name': 'x', 'kind': 'ble', 'external_id': ADDR_A}, alice.token)
            assert code == 409 and dup['error']['code'] == 'device_exists'
            # foreign device: Bob cannot connect / read status of Alice's strap; the response does not leak existence
            code, err = call('POST', f'/api/devices/{da}/connect', {'astronaut_id': bob.astronaut_id}, bob.token)
            assert code == 404 and err['error']['code'] == 'not_found'
            code, err = call('POST', f'/api/devices/{da}/connect', {'astronaut_id': alice.astronaut_id}, bob.token)
            assert code == 404
            assert call('GET', f'/api/devices/{da}/status', token=bob.token)[0] == 404

            sa, _ = record(call, rig, alice, da, ADDR_A, minutes=20, step_at=999, seed=1)
            # while Alice's strap is NOT open any more, open it again and try a second opener of the SAME radio
            code, con = call('POST', f'/api/devices/{da}/connect', {'astronaut_id': alice.astronaut_id}, alice.token)
            assert code == 200
            other = dm.DeviceManager(rig.storage, rig.tr, clock=rig.clock, scheduler=rig.m.scheduler)
            with pytest.raises(DeviceBusy):                               # second manager (e.g. second server process)
                other.connect(alice.ctx(), da, {'astronaut_id': alice.astronaut_id})
            legacy = ble_sensor.Sensor()                                     # legacy single-strap path, same radio
            legacy.devices[ADDR_A] = object()
            with pytest.raises(ValueError):
                legacy.call(legacy.connect(ADDR_A))
            assert legacy.state['connection'] == 'disconnected'
            legacy.loop.call_soon_threadsafe(legacy.loop.stop)
            assert call('POST', f'/api/devices/{da}/disconnect', {}, alice.token)[0] == 200

            sb, _ = record(call, rig, bob, db_, ADDR_B, minutes=20, step_at=999, seed=2)
            na, nb = _count(alice.astronaut_id), _count(bob.astronaut_id)
            assert na == 1200 and nb == 1200 and _count() == na + nb          # no duplicates, nothing cross-written

            # a replay of exactly the batch the Device Manager flushed (lost ack → resend) creates no new rows
            res = rig.storage.save_measurements(alice.ctx(), rig.batches[0])
            assert res['saved'] == 0 and res['duplicates'] == len(rig.batches[0]) > 0 and _count() == na + nb

            # history isolation through BOTH layers
            code, err = call('GET', f'/api/measurements?astronaut_id={alice.astronaut_id}', token=bob.token)
            assert code == 404
            code, err = call('POST', '/api/phantom-analyses', {'astronaut_id': alice.astronaut_id, 'session_id': sa}, bob.token)
            assert code == 404 and alice.astronaut_id not in json.dumps(err)
            code, own = call('GET', '/api/devices', token=bob.token)
            assert [d['id'] for d in own['items']] == [db_]
        finally:
            rig.close()

    # restart: new storage instance + new manager; open sessions were closed, devices and rows are intact
    from app.science_storage_be2 import Be2ScienceStorage
    st = canonical_storage()
    assert {s['session_id'] for s in st.list_sessions(alice.ctx())} == {sa, con['session_id']}
    assert all(s['status'] in ('saved', 'interrupted', 'recovered', 'failed') and s['finished_at']
               for s in st.list_sessions(alice.ctx()))                       # BE2_06: durable terminal status
    assert [s['session_id'] for s in st.list_sessions(bob.ctx())] == [sb]


# ------------------------------------------------------------------------------------------------------------------ C
def test_C_backend2_manual_entries_are_converted_not_upgraded(real_db):
    from app.science_errors import Conflict
    from app.science_storage_be2 import Be2ScienceStorage
    alice = Account('alice')
    t = (datetime.now(timezone.utc) - timedelta(hours=10)).strftime('%Y-%m-%dT%H:%M:%SZ')
    with stdlib_server() as call:
        base = {'source': 'manual form', 'measured_at': t, 'origin': 'manual'}
        for key, sig, val, unit in [('s1', 'sleep_hours', 7.5, 'h'), ('f1', 'fatigue_1_10', 4.0, 'score'),
                                    ('r1', 'reaction_ms', 320.0, 'ms'), ('a1', 'activity_minutes', 45.0, 'min')]:
            code, body = call('POST', '/api/measurements', {**base, 'idempotency_key': key, 'signal': sig, 'value': val,
                                                            'unit': unit}, alice.token)
            assert code == 201, body
        code, body = call('POST', '/api/measurements', {**base, 'idempotency_key': 's1', 'signal': 'sleep_hours',
                                                        'value': 6.0, 'unit': 'h'}, alice.token)
        assert code == 409 and body['error']['code'] == 'idempotency_conflict'      # changed payload, same key
    st = canonical_storage()
    items = {x['signal']: x for x in st.query_measurements(alice.ctx(), alice.astronaut_id, include_invalid=True)['items']}
    sleep = items['sleep_duration']
    assert sleep['value'] == 27000.0 and sleep['unit'] == 's'                       # 7.5 h × 3600, converted once
    assert sleep['provenance']['source_signal'] == 'sleep_hours' and sleep['provenance']['source_value'] == 7.5
    assert sleep['provenance']['source_unit'] == 'h' and sleep['provenance']['conversion']
    assert set(items) == {'sleep_duration', 'fatigue_1_10', 'reaction_ms', 'activity_minutes'}
    for x in items.values():
        assert x['data_class'] == 'manual' and x['quality'] != 'good' and not x['valid']   # manual/unverified ≠ good
    # BE3 write with a changed payload under an existing client id → 409 (never a silent overwrite)
    row = {'astronaut_id': alice.astronaut_id, 'signal': 'reaction_ms', 'value': 400.0, 'unit': 'ms', 'recorded_at': t,
           'data_class': 'manual', 'source': 'manual', 'client_measurement_id': 'r1'}
    with pytest.raises(Conflict) as e:
        st.save_measurements(alice.ctx(), [row])
    assert e.value.code == 'idempotency_conflict'


# ------------------------------------------------------------------------------------------------------------------ D
def test_D_roles_admin_officer_grant_revocation_logout(real_db):
    alice, med, adm, mid = crew()
    with stdlib_server() as call:
        rig = Rig(ADDR_A)
        try:
            did = register_device(call, alice, ADDR_A)
            sid, _ = record(call, rig, alice, did, ADDR_A, minutes=90, mission_id=mid)
            code, r = call('POST', '/api/phantom-analyses', {'astronaut_id': alice.astronaut_id, 'session_id': sid,
                                                              'mission_id': mid}, alice.token)
            assert code == 201 and r['mission_id'] == mid, r
            aid_ = r['analysis_id']
            # administrator: NOT a medical superuser (404 everywhere, no existence leak)
            for path in (f'/api/phantom-analyses/{aid_}', f'/api/phantom-analyses?astronaut_id={alice.astronaut_id}',
                         f'/api/phantom-analyses?astronaut_id={alice.astronaut_id}&mission_id={mid}'):
                assert call('GET', path, token=adm.token)[0] == 404, path
            assert call('POST', f'/api/devices/{did}/connect', {'astronaut_id': alice.astronaut_id}, adm.token)[0] == 404
            # medical officer with a grant: read inside the mission only
            code, got = call('GET', f'/api/phantom-analyses/{aid_}', token=med.token)
            assert code == 200 and got['analysis_id'] == aid_
            code, lst = call('GET', f'/api/phantom-analyses?astronaut_id={alice.astronaut_id}&mission_id={mid}', token=med.token)
            assert code == 200 and [x['analysis_id'] for x in lst['items']] == [aid_]
            assert call('GET', f'/api/phantom-analyses?astronaut_id={alice.astronaut_id}', token=med.token)[0] == 404
            # … but never write: cannot run PHANTOM, cannot use the strap
            code, err = call('POST', '/api/phantom-analyses', {'astronaut_id': alice.astronaut_id, 'session_id': sid,
                                                                'mission_id': mid}, med.token)
            assert code == 404
            assert call('POST', f'/api/devices/{did}/connect', {'astronaut_id': alice.astronaut_id}, med.token)[0] == 404
            # revocation takes effect on the very next request
            revoke(adm, mid, med, alice)
            assert call('GET', f'/api/phantom-analyses/{aid_}', token=med.token)[0] == 404
            # logout: the token is dead for the scientific routes too
            alice.logout()
            code, err = call('GET', f'/api/phantom-analyses/{aid_}', token=alice.token)
            assert code == 401 and err['error']['code'] == 'unauthenticated'
        finally:
            rig.close()


# ------------------------------------------------------------------------------------------------------------------ E
def test_E_fail_closed_no_fake_no_legacy_upgrade(real_db, monkeypatch, tmp_path):
    from app import db, science_storage
    alice = Account('alice')
    with stdlib_server() as call:
        # resolver picks Backend №2's store; there is no FakeStorage anywhere in the production path
        st = science_storage.resolve(('measurements', 'analyses'))
        from app.science_storage_be2 import Be2ScienceStorage
        assert isinstance(st, Be2ScienceStorage) and type(st).__module__.startswith('app.persistence')   # BE2_06 canonical
        assert 'fake' not in type(st).__module__.lower()
        # legacy demo id on the personal API → refused, never upgraded to a personal profile
        code, err = call('POST', '/api/phantom-analyses', {'astronaut_id': 'A01', 'from': '2026-11-01T00:00:00Z',
                                                            'to': '2026-11-01T02:00:00Z'}, alice.token)
        assert code == 422 and err['error']['code'] in ('legacy_id_not_allowed', 'validation_error'), err
        # no token / forged token / launch token only
        assert call('GET', '/api/signals')[0] == 401
        assert call('GET', '/api/signals', token='x' * 43)[0] == 401
        assert call('GET', '/api/signals', headers={'X-AETHER-System': '1', 'X-AETHER-User': alice.id})[0] == 401
        # Backend №2's own legacy isolation is untouched
        assert call('GET', '/api/astronauts', token=alice.token)[0] == 410
        # storage becomes unavailable → 503 storage_unavailable; nothing is fabricated
        broken = tmp_path / 'dir_not_db'
        broken.mkdir()
        monkeypatch.setattr(db, 'DB_PATH', broken)
        code, err = call('POST', '/api/phantom-analyses', {'astronaut_id': alice.astronaut_id,
                                                            'from': '2026-11-01T00:00:00Z', 'to': '2026-11-01T02:00:00Z'},
                         alice.token)
        assert code in (401, 503), err                                   # auth itself needs the DB: fail closed
        assert 'outcome' not in (err or {})


def test_E_fastapi_variant_is_reported_not_executed():
    try:
        import fastapi  # noqa: F401
    except ImportError:
        pytest.skip('integration_pending: FastAPI is not installed in this environment; '
                    'run this file on the BE2 tree with FastAPI (INTEGRATION.md §5)')
    pytest.skip('integration_pending: FastAPI middleware hook (BE2_REQUIRED_CHANGES R-1) is owned by Backend №2')
