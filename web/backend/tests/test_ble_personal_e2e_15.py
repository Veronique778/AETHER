"""AETHER 1.5 BLE PERSONAL INTEGRATION — end-to-end on the REAL SQLite + REAL stdlib server + REAL lifecycle manager.

What is real here: Backend №2 schema/migrations, auth (Argon2id via the opt-in test shim when argon2-cffi is absent),
Bearer sessions, ACL, the stdlib devserver, app.persistence.science_lifecycle (the production ManagedDeviceManager),
the HRS decoder, the canonical storage adapter and PHANTOM. What is simulated (and labelled as such):

* E2E-A uses the SHIPPED explicit simulated strap (app.devices.simulated) → rows are SYNTHETIC (origin 'simulated').
* E2E-R runs the PRODUCTION BleakTransport against tests/fakes/fake_bleak (a test double of the bleak LIBRARY). The
  server derives provenance from the transport class, so those rows are 'real_wearable' in a throw-away database.
  That proves the software path (scan, GATT check, notify, gaps, reconnect, provenance) — NOT the hardware.
* E2E-P (PHANTOM over ≥ 60 min) drives the manager with a scripted SYNTHETIC transport and a manual clock.

hardware_verified is asserted to be False in every response that carries it.
"""
from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from be3_real_backend import PASSWORD, real_db, stdlib_server  # noqa: F401  (fixture import)

FAKE_BLEAK = str(Path(__file__).resolve().parent / 'fakes' / 'fake_bleak')
STRAP = 'C4:7A:1C:00:12:9F'
STRAP16 = 'D8:11:22:33:44:16'
WATCH = 'AA:BB:CC:00:00:01'           # advertises nothing, no HRS in GATT
SILENT_HRS = 'EE:00:00:00:00:5E'      # not advertising HRS, but HRS in GATT


@pytest.fixture
def fake_bleak(monkeypatch):
    """Make `import bleak` resolve to the test double; removed again afterwards (other tests expect no bleak)."""
    for k in [k for k in sys.modules if k == 'bleak' or k.startswith('bleak.')]:
        monkeypatch.delitem(sys.modules, k, raising=False)
    monkeypatch.syspath_prepend(FAKE_BLEAK)
    import bleak
    bleak.configure([
        {'address': STRAP, 'name': 'AETHER Test Strap', 'advertise_hrs': True, 'has_hrs': True, 'hr': 64, 'rr': [960], 'interval_s': 0.1},
        {'address': STRAP16, 'name': 'Wide HR strap', 'advertise_hrs': True, 'has_hrs': True, 'hr': 182, 'uint16': True, 'rr': [],
         'contact': None, 'interval_s': 0.1},
        {'address': WATCH, 'name': 'Smart Watch', 'advertise_hrs': False, 'has_hrs': False},
        {'address': SILENT_HRS, 'name': 'Quiet HRS', 'advertise_hrs': False, 'has_hrs': True, 'hr': 70, 'interval_s': 0.1},
    ])
    yield bleak
    for k in [k for k in sys.modules if k == 'bleak' or k.startswith('bleak.')]:
        sys.modules.pop(k, None)


def _user(call, login):
    code, _ = call('POST', '/api/auth/register', {'login': login, 'password': PASSWORD, 'display_name': login})
    assert code == 201
    code, auth = call('POST', '/api/auth/login', {'login': login, 'password': PASSWORD})
    assert code == 200
    return auth['access_token'], auth['user']['astronaut_id']


def _wait(call, token, did, pred, timeout=8.0):
    deadline = time.time() + timeout
    st = None
    while time.time() < deadline:
        code, st = call('GET', f'/api/devices/{did}/status', token=token)
        assert code == 200, st
        assert st['hardware_validation'] == 'unverified'
        if pred(st):
            return st
        time.sleep(0.1)
    raise AssertionError(f'condition not reached; last status {st}')


def _rows(call, token, sid):
    code, page = call('GET', f'/api/measurements?session_id={sid}&limit=500', token=token)
    assert code == 200, page
    return page['items']


def _register(call, token, address, name='strap'):
    code, dev = call('POST', '/api/devices', {'name': name, 'kind': 'ble', 'external_id': address}, token=token)
    assert code == 201, dev
    return dev['id']


# ============================================================================ E2E-A  simulated strap (SYNTHETIC)
def test_e2e_a_live_mode_simulated_hrs_to_sqlite_phantom_history(real_db):
    with stdlib_server() as call:
        token, aid = _user(call, 'ble_alice')
        # protected scan / diagnostics / device routes: no Bearer → 401 (no legacy bypass)
        for method, path in [('POST', '/api/devices/scan'), ('GET', '/api/devices/ble-diagnostics'), ('POST', '/api/devices/simulated'),
                             ('GET', '/api/devices/active'), ('POST', '/api/biosignals/sensor/scan')]:
            assert call(method, path, {} if method == 'POST' else None)[0] == 401, path
        code, diag = call('GET', '/api/devices/ble-diagnostics', token=token)
        assert code == 200 and diag['hardware_verified'] is False and diag['authenticated_owner']['astronaut_id'] == aid
        assert diag['radio_data_class'] == 'real_wearable' and diag['simulated_hrs_available'] is True
        assert {'radio_available', 'ble_dependency_available', 'scan_available', 'supported_protocol', 'reason_code'} <= set(diag)
        code, sim = call('POST', '/api/devices/simulated', {}, token=token)
        assert code == 201 and sim['data_class'] == 'synthetic' and sim['hardware_address'].startswith('AETHER-SIM-HRS-')
        code, again = call('POST', '/api/devices/simulated', {}, token=token)
        assert code == 200 and again['device_id'] == sim['device_id']            # idempotent: one strap per account
        did = sim['device_id']
        code, conn = call('POST', f'/api/devices/{did}/connect', {'astronaut_id': aid}, token=token)
        assert code == 200 and conn['recording'] is True
        st = _wait(call, token, did, lambda s: s['stored_samples'] >= 6, timeout=15)
        assert st['phase'] == 'receiving' and st['simulated'] is True and st['data_class'] == 'synthetic' and st['hrs_verified']
        assert st['heart_rate'] is not None and st['contact_state'] == 'contact' and st['rr_available'] is True
        code, active = call('GET', '/api/devices/active', token=token)
        assert code == 200 and [a['device_id'] for a in active['items']] == [did]
        code, stop = call('POST', f'/api/devices/{did}/disconnect', {}, token=token)
        assert code == 200 and stop['session_status'] == 'saved' and stop['stored_samples'] >= 6
        rows = _rows(call, token, stop['session_id'])
        assert rows and all(r['origin'] == 'simulated' and r['device_id'] == did for r in rows)
        assert not any((r['metadata'] or {}).get('data_class') == 'real_wearable' for r in rows)
        assert {r['signal'] for r in rows} == {'heart_rate', 'rr_interval'}
        code, sessions = call('GET', f'/api/devices/{did}/sessions', token=token)
        assert code == 200 and sessions['items'][-1]['id'] == stop['session_id'] and sessions['items'][-1]['end_status'] == 'saved'
        # PHANTOM on a short recording: honest insufficient_data, no fake flag
        t0 = min(r['measured_at'] for r in rows); t1 = max(r['measured_at'] for r in rows)
        end = (datetime.fromisoformat(t1.replace('Z', '+00:00')) + timedelta(seconds=1)).isoformat().replace('+00:00', 'Z')
        code, res = call('POST', '/api/phantom-analyses', {'astronaut_id': aid, 'from': t0, 'to': end, 'data_classes': ['synthetic']}, token=token)
        assert code == 201 and res['outcome'] == 'insufficient_data' and res['explain']['data_label'] == 'SYNTHETIC'
        # the same interval holds ZERO real-sensor rows: synthetic never leaks into the real path
        code, real = call('POST', '/api/phantom-analyses', {'astronaut_id': aid, 'from': t0, 'to': end, 'data_classes': ['real_wearable']}, token=token)
        assert code == 201 and real['outcome'] == 'insufficient_data' and real['explain']['signal_quality']['measurements'] == 0
        saved_ids = {res['analysis_id'], real['analysis_id']}
    # restart: a NEW server process surface on the same SQLite file → same history
    with stdlib_server() as call:
        code, auth = call('POST', '/api/auth/login', {'login': 'ble_alice', 'password': PASSWORD})
        token2 = auth['access_token']
        assert len(_rows(call, token2, stop['session_id'])) == len(rows)
        code, hist = call('GET', '/api/phantom-analyses', token=token2)
        assert code == 200 and saved_ids <= {a['analysis_id'] for a in hist['items']}
        code, sessions = call('GET', f'/api/devices/{did}/sessions', token=token2)
        assert sessions['items'][-1]['end_status'] == 'saved'


# ============================================================================ E2E-B  authorization
def test_e2e_b_user_isolation_logout_and_revocation(real_db, fake_bleak):
    with stdlib_server() as call:
        ta, aa = _user(call, 'ble_owner')
        tb, ab = _user(call, 'ble_other')
        did = _register(call, ta, STRAP, 'Owner strap')
        assert call('POST', f'/api/devices/{did}/connect', {'astronaut_id': aa}, token=ta)[0] == 200
        _wait(call, ta, did, lambda s: s['stored_samples'] > 0)
        # B cannot see / stop / restart / impersonate A's device, session or astronaut
        assert call('GET', f'/api/devices/{did}/status', token=tb)[0] == 404
        assert call('POST', f'/api/devices/{did}/disconnect', {}, token=tb)[0] == 404
        assert call('POST', f'/api/devices/{did}/connect', {'astronaut_id': aa}, token=tb)[0] == 404
        assert call('GET', f'/api/devices/{did}/sessions', token=tb)[0] == 404
        assert call('GET', '/api/devices/active', token=tb)[1]['items'] == []
        # B registers the SAME physical strap for itself → may exist in its registry, but cannot open it concurrently
        did_b = _register(call, tb, STRAP, 'Same strap')
        code, err = call('POST', f'/api/devices/{did_b}/connect', {'astronaut_id': ab}, token=tb)
        assert code == 409 and err['error']['code'] == 'device_busy'
        code, err = call('POST', f'/api/devices/{did_b}/connect', {'astronaut_id': aa}, token=tb)
        assert code == 404                                                      # foreign astronaut id: not found
        assert call('GET', '/api/measurements', token=tb)[1]['items'] == []
        # A logs out while recording → recording stopped at once, pending rows flushed while the token is valid, strap
        # released; the session is closed 'failed' (BE2_06 contract for an ended personal session), commits kept
        st_before = call('GET', f'/api/devices/{did}/status', token=ta)[1]
        assert call('POST', '/api/auth/logout', {}, token=ta)[0] == 200
        assert call('GET', f'/api/devices/{did}/status', token=ta)[0] == 401
        code, auth = call('POST', '/api/auth/login', {'login': 'ble_owner', 'password': PASSWORD}); ta = auth['access_token']
        st = call('GET', f'/api/devices/{did}/status', token=ta)[1]
        assert st['lifecycle_state'] == 'disconnected' and st['last_session_status'] == 'failed' and st['revoked']
        code, sessions = call('GET', f'/api/devices/{did}/sessions', token=ta)
        assert sessions['items'][-1]['id'] == st_before['session_id'] and sessions['items'][-1]['end_status'] == 'failed'
        assert len(_rows(call, ta, st_before['session_id'])) >= st_before['stored_samples'] > 0
        # now B may use the physical strap — its rows go only to B
        assert call('POST', f'/api/devices/{did_b}/connect', {'astronaut_id': ab}, token=tb)[0] == 200
        _wait(call, tb, did_b, lambda s: s['stored_samples'] > 0)
        # B's session is revoked server-side mid-recording (e.g. expiry / admin): recording stops, nothing goes elsewhere
        from app import db
        with db.connect() as c:
            c.execute('UPDATE auth_sessions SET revoked_at=? WHERE revoked_at IS NULL AND user_id=(SELECT id FROM users WHERE login=?)',
                      (datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'), 'ble_other'))
        from app.devices import api as dapi
        m = dapi.get_manager()
        deadline = time.time() + 15
        while time.time() < deadline and m._slots[did_b].state.value != 'disconnected':
            time.sleep(0.2)
        slot = m._slots[did_b]
        assert slot.state.value == 'disconnected' and slot.revoked and slot.last_session_status == 'failed'
        from app.devices import hw_lock
        assert hw_lock.holder(STRAP) is None
        with db.connect() as c:
            owners = {r[0] for r in c.execute('SELECT DISTINCT astronaut_id FROM raw_measurements WHERE device_id=?', (did_b,))}
            assert owners <= {ab}
            end = c.execute("SELECT status FROM session_end_states WHERE session_id=?", (slot.last_session_id,)).fetchone()
            assert end and end[0] == 'failed'


# ============================================================================ E2E-R  production transport, fake bleak
def test_e2e_r_scan_connect_gatt_check_notifications_real_path(real_db, fake_bleak):
    with stdlib_server() as call:
        token, aid = _user(call, 'ble_real')
        code, diag = call('GET', '/api/devices/ble-diagnostics', token=token)
        assert code == 200 and diag['ble_dependency_available'] is True and diag['scan_available'] is True
        code, hrs_only = call('POST', '/api/devices/scan', {'include_unadvertised': False, 'timeout_seconds': 1}, token=token)
        assert code == 200 and {d['hardware_address'] for d in hrs_only['found']} == {STRAP, STRAP16}
        code, everything = call('POST', '/api/devices/scan', {'include_unadvertised': True, 'timeout_seconds': 1}, token=token)
        by = {d['hardware_address']: d for d in everything['found']}
        assert by[WATCH]['advertised_hrs'] is False and by[WATCH]['compatibility'] == 'unverified_gatt_check_on_connect'
        assert by[STRAP]['compatibility'] == 'hrs_advertised'
        # unsupported watch: GATT check refuses before any recording; nothing stored, strap released
        wid = _register(call, token, WATCH, 'Smart Watch')
        code, err = call('POST', f'/api/devices/{wid}/connect', {'astronaut_id': aid}, token=token)
        assert code == 422 and err['error']['code'] == 'device_not_hrs'
        assert call('GET', '/api/measurements', token=token)[1]['items'] == []
        # non-advertising device WITH HRS in GATT is accepted after the GATT check
        qid = _register(call, token, SILENT_HRS, 'Quiet HRS')
        assert call('POST', f'/api/devices/{qid}/connect', {'astronaut_id': aid}, token=token)[0] == 200
        _wait(call, token, qid, lambda s: s['stored_samples'] > 0)
        assert call('POST', f'/api/devices/{qid}/disconnect', {}, token=token)[0] == 200
        # 8-bit HR + RR + contact
        did = _register(call, token, STRAP, 'AETHER Test Strap')
        assert call('POST', f'/api/devices/{did}/connect', {'astronaut_id': aid}, token=token)[0] == 200
        st = _wait(call, token, did, lambda s: s['stored_samples'] >= 10)
        assert st['phase'] == 'receiving' and st['data_class'] == 'real_wearable' and st['simulated'] is False
        assert st['heart_rate'] == 64 and st['contact_state'] == 'contact' and st['hrs_verified'] is True
        code, stop = call('POST', f'/api/devices/{did}/disconnect', {}, token=token)
        rows = _rows(call, token, stop['session_id'])
        hr = [r for r in rows if r['signal'] == 'heart_rate']; rr = [r for r in rows if r['signal'] == 'rr_interval']
        assert hr and all(r['value'] == 64 and r['origin'] == 'real' for r in hr)
        assert rr and all(abs(r['value'] - 960 * 1000 / 1024) < 1e-6 for r in rr)       # RR 1/1024 s → ms, not NN/HRV
        assert all(r['metadata']['data_class'] == 'real_wearable' and r['metadata']['contact'] is True for r in rows)
        # 16-bit HR, no RR, contact not reported → quality 'screened' (never 'good')
        d16 = _register(call, token, STRAP16, 'Wide HR strap')
        assert call('POST', f'/api/devices/{d16}/connect', {'astronaut_id': aid}, token=token)[0] == 200
        st = _wait(call, token, d16, lambda s: s['stored_samples'] >= 4)
        assert st['contact_state'] == 'not_reported' and st['rr_available'] is False
        stop16 = call('POST', f'/api/devices/{d16}/disconnect', {}, token=token)[1]
        rows16 = _rows(call, token, stop16['session_id'])
        assert rows16 and all(r['signal'] == 'heart_rate' and r['value'] == 182 and r['metadata']['hr_format'] == 'uint16' for r in rows16)
        assert all(r['metadata']['be3_quality'] == 'screened' for r in rows16)


# ============================================================================ E2E-C  quality / link loss / forgery
def test_e2e_c_no_contact_corrupt_stale_reconnect_and_forgery(real_db, fake_bleak, monkeypatch):
    from app.devices import manager as dm
    monkeypatch.setattr(dm, 'STALE_S', 1.0)
    fake_bleak.configure([{'address': STRAP, 'name': 'AETHER Test Strap', 'hr': 61, 'rr': [1000], 'contact': False,
                           'interval_s': 0.1, 'corrupt_every': 3}])
    with stdlib_server() as call:
        token, aid = _user(call, 'ble_quality')
        did = _register(call, token, STRAP)
        assert call('POST', f'/api/devices/{did}/connect', {'astronaut_id': aid}, token=token)[0] == 200
        st = _wait(call, token, did, lambda s: s['corrupt_packets'] >= 2 and s['stored_samples'] >= 4)
        assert st['phase'] == 'no_contact' and st['heart_rate'] is None and st['quality'] == 'no_contact'
        # silence → stale: no current HR, explicit gap stored, never filled
        fake_bleak.device(STRAP)['silent'] = True
        st = _wait(call, token, did, lambda s: s['phase'] == 'signal_lost' and s['gaps'] >= 1, timeout=10)
        assert st['heart_rate'] is None and st['stale'] is True
        # link loss → reconnecting → same session → recording again
        fake_bleak.device(STRAP).update(silent=False, contact=True, corrupt_every=0)
        sid = st['session_id']
        assert fake_bleak.drop_link(STRAP)
        st = _wait(call, token, did, lambda s: s['reconnects'] >= 1 and s['phase'] == 'receiving', timeout=15)
        assert st['session_id'] == sid
        stop = call('POST', f'/api/devices/{did}/disconnect', {}, token=token)[1]
        rows = _rows(call, token, sid)
        assert any(r['quality'] == 'no_contact' for r in rows)                           # stored as unusable
        assert any(r['value'] is None and r['quality'] == 'connection_lost' for r in rows)  # gaps preserved as missing
        assert len({r['id'] for r in rows}) == len(rows)                                   # no duplicated rows
        assert stop['session_status'] == 'saved'
        # PHANTOM excludes no_contact / missing rows; interval with no baseline → insufficient_data
        t0 = min(r['measured_at'] for r in rows)
        to = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat().replace('+00:00', 'Z')
        code, res = call('POST', '/api/phantom-analyses', {'astronaut_id': aid, 'from': t0, 'to': to, 'data_classes': ['real_wearable']}, token=token)
        assert code == 201 and res['outcome'] == 'insufficient_data'
        # forgery: a client cannot write wearable provenance through the public API
        base = {'idempotency_key': 'forge-1', 'source': 'BLE Heart Rate Service', 'signal': 'heart_rate', 'value': 70, 'unit': 'bpm',
                'measured_at': to, 'origin': 'manual', 'quality': 'validated'}
        for md in ({'data_class': 'real_wearable'}, {'contact': True}, {'written_via': 'device_manager'}, {'be3_quality': 'good'}):
            code, err = call('POST', '/api/measurements', {**base, 'metadata': md}, token=token)
            assert code == 422 and err['error']['code'] == 'reserved_provenance', md
        code, err = call('POST', '/api/measurements', {**base, 'origin': 'real'}, token=token)
        assert code == 422                                                                 # 'real' needs device + session
        code, own_session = call('POST', '/api/sensor-sessions', {'device_id': did, 'source': 'BLE Heart Rate Service', 'origin': 'real',
                                 'started_at': to, 'metadata': {'source_type': 'live_sensor'}}, token=token)
        assert code == 201
        code, row = call('POST', '/api/measurements', {**base, 'idempotency_key': 'forge-2', 'origin': 'real', 'device_id': did,
                         'session_id': own_session['id']}, token=token)
        assert code == 201                                                                 # stored, but never as real_wearable:
        code, res = call('POST', '/api/phantom-analyses', {'astronaut_id': aid, 'from': to, 'to': (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat().replace('+00:00', 'Z'),
                         'data_classes': ['real_wearable']}, token=token)
        assert code == 201 and res['explain']['signal_quality']['measurements'] == 0


def test_e2e_c_bluetooth_unavailable_is_actionable(real_db, fake_bleak):
    fake_bleak.STATE['radio'] = 'off'
    with stdlib_server() as call:
        token, aid = _user(call, 'ble_radio_off')
        code, err = call('POST', '/api/devices/scan', {'include_unadvertised': False, 'timeout_seconds': 1}, token=token)
        assert code == 503 and err['error']['code'] == 'bluetooth_off'
        fake_bleak.STATE['radio'] = 'no_adapter'
        code, err = call('POST', '/api/devices/scan', {}, token=token)
        assert code == 503 and err['error']['code'] == 'bluetooth_adapter_missing'
        fake_bleak.STATE['radio'] = 'on'


def test_e2e_c_dependency_missing_reports_reason_without_crash(real_db, monkeypatch):
    for k in [k for k in sys.modules if k == 'bleak' or k.startswith('bleak.')]:
        monkeypatch.delitem(sys.modules, k, raising=False)
    import importlib.util
    if importlib.util.find_spec('bleak') is not None:
        pytest.skip('a real bleak is installed in this environment')
    with stdlib_server() as call:
        from app.devices import api as dapi
        dapi.get_manager().transport._dep = None          # the in-process lifecycle manager may outlive earlier tests
        token, aid = _user(call, 'ble_nodep')
        code, diag = call('GET', '/api/devices/ble-diagnostics', token=token)
        assert code == 200 and diag['scan_available'] is False and diag['reason_code'] == 'bluetooth_dependency_missing'
        code, err = call('POST', '/api/devices/scan', {}, token=token)
        assert code == 503 and err['error']['code'] == 'bluetooth_dependency_missing'
        # the simulated strap still works and stays SYNTHETIC
        code, sim = call('POST', '/api/devices/simulated', {}, token=token)
        assert code == 201 and sim['data_class'] == 'synthetic'


# ============================================================================ E2E-P  ≥ 60 min baseline → frozen PHANTOM
class ScriptedSyntheticStrap:
    """Manager-level scripted strap on a manual clock. Declares no radio provenance → rows are SYNTHETIC."""
    KIND = 'scripted_test_strap'

    def __init__(self):
        self.links = {}

    def availability(self):
        return True, None

    def connect(self, address, on_notify, on_disconnect, timeout_s):
        self.links[address] = on_notify
        return address

    def disconnect(self, handle):
        self.links.pop(handle, None)


def test_e2e_p_recording_with_baseline_runs_frozen_phantom(real_db):
    from app.devices import manager as dm, hrs
    from app.science_storage_be2 import Be2Context
    from app.persistence import science_storage
    from fakes.ble_mock import ManualClock, ManualScheduler
    from app import auth
    auth.register('ble_long', PASSWORD, 'ble_long', peer='ble_long')
    token = auth.login('ble_long', PASSWORD, peer='ble_long')['access_token']
    ctx = Be2Context(token)
    storage = science_storage()
    start = (datetime.now(timezone.utc) - timedelta(hours=4)).replace(microsecond=0)
    clock = ManualClock(start=start); sched = ManualScheduler(clock)
    strap = ScriptedSyntheticStrap()
    m = dm.DeviceManager(storage, strap, clock=clock, scheduler=sched)
    dev = storage.upsert_device(ctx, {'name': 'scripted', 'hardware_address': 'SCRIPTED:01', 'astronaut_id': ctx.astronaut_id})
    sess = m.connect(ctx, dev['device_id'], {'astronaut_id': ctx.astronaut_id})
    for i in range(180 * 60 // 2):                                  # 3 h, one notification every 2 s
        bpm = 64 + (15 if i * 2 >= 110 * 60 else 0)                 # sustained step after 110 min
        strap.links['SCRIPTED:01'](hrs.encode(bpm, [int(60000 / bpm * 1024 / 1000)], contact=True))
        sched.advance(2)
        if i % 200 == 0:
            ctx.user                                                # keep the idle timer of the test session fresh
    out = m.disconnect(ctx, dev['device_id'])
    assert out['session_status'] == 'saved' and out['stored_samples'] > 10000
    with stdlib_server() as call:
        req = {'astronaut_id': ctx.astronaut_id, 'from': start.isoformat().replace('+00:00', 'Z'),
               'to': (start + timedelta(hours=3, minutes=1)).isoformat().replace('+00:00', 'Z')}
        code, res = call('POST', '/api/phantom-analyses', {**req, 'data_classes': ['synthetic']}, token=token)
        assert code == 201 and res['outcome'] == 'flag' and res['explain']['data_label'] == 'SYNTHETIC', res.get('outcome')
        assert res['explain']['baseline'] is not None
        code, res_real = call('POST', '/api/phantom-analyses', {**req, 'data_classes': ['real_wearable']}, token=token)
        assert code == 201 and res_real['outcome'] == 'insufficient_data'           # zero synthetic rows in the real path
        code, short = call('POST', '/api/phantom-analyses', {**req, 'to': (start + timedelta(minutes=50)).isoformat().replace('+00:00', 'Z'),
                                                             'data_classes': ['synthetic']}, token=token)
        assert code == 201 and short['outcome'] == 'insufficient_data'               # < 60 min baseline
