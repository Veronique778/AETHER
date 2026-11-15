"""Behavioural conformance suite for the scientific storage protocol (Backend №3, package 03A).

The SAME tests run against
    fake  — tests/fakes/storage_fake.FakeStorage (test double, never used in production)
    be2   — app.science_storage_be2.Be2ScienceStorage on Backend №2's REAL repository + SQLite (temporary database)
so that a behaviour which passes on the fake but not on the real store is visible here, not in production.
Covered: parameters/types, transactions/atomicity, access, idempotency (+409), pagination, ordering, interval
semantics, restart, errors, and save_analysis_bundle failure points, replay, concurrent replays, other user, revocation.
Documented divergences are asserted explicitly (docs/BACKEND_STORAGE_COMPATIBILITY.md §4).
"""
from __future__ import annotations

import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from app import api15_science, signals as reg
from app.science_errors import Conflict, InvalidInput, NotFound, ScienceError, StorageUnavailable
from be3_real_backend import canonical_storage, Account, real_db, require_backend2  # noqa: F401
from fakes.storage_fake import FakeContext, FakeStorage
from helpers_be3_signals_15 import P1, P2, hr_series, span

T0 = (datetime.now(timezone.utc) - timedelta(days=2)).replace(hour=8, minute=0, second=0, microsecond=0)


class _RevocableFakeCtx:
    def __init__(self, inner):
        self.inner, self.revoked = inner, False
        self.user_id, self.role, self.auth_mode = inner.user_id, inner.role, inner.auth_mode

    def can(self, permission, astronaut_id=None, mission_id=None):
        return not self.revoked and self.inner.can(permission, astronaut_id, mission_id)


class FakeBackend:
    name = 'fake'

    def __init__(self, tmp_path):
        self.path = tmp_path / 'fake_store.json'
        self.st = FakeStorage(self.path)
        self.aid, self.aid2 = P1, P2
        self._owner = _RevocableFakeCtx(FakeContext(user_id='a' * 32, astronaut_ids=frozenset({P1})))
        self._other = FakeContext(user_id='b' * 32, astronaut_ids=frozenset({P2}))

    def owner(self):
        return self._owner

    def other(self):
        return self._other

    def revoke_owner(self):
        self._owner.revoked = True

    def restart(self):
        self.st = FakeStorage(self.path)
        return self.st

    def count(self, aid=None):
        return sum(1 for m in self.st.db['measurements'].values() if aid is None or m['astronaut_id'] == aid)

    def analyses(self):
        return len(self.st.db['analyses'])

    @contextmanager
    def fail(self, point):
        self.st.fail_next = {'before': 'save_analysis_bundle', 'during': 'bundle:after_analysis',
                             'history': 'bundle:after_record', 'audit': 'bundle:after_record',
                             'after_commit': 'bundle:after_commit'}[point]
        try:
            yield
        finally:
            self.st.fail_next = None


class Be2Backend:
    name = 'be2'

    def __init__(self):
        from app.science_storage_be2 import Be2ScienceStorage
        self.st = canonical_storage()
        self.a, self.b = Account('alice'), Account('bob')
        self.aid, self.aid2 = self.a.astronaut_id, self.b.astronaut_id

    def owner(self):
        return self.a.ctx()

    def other(self):
        return self.b.ctx()

    def revoke_owner(self):
        self.a.logout()

    def restart(self):
        from app import db
        from app.science_storage_be2 import Be2ScienceStorage
        db.init_db()                                   # migrations are idempotent; same file
        self.st = canonical_storage()
        return self.st

    def count(self, aid=None):
        from app import db
        with db.connect() as c:
            q = ("SELECT COUNT(*) FROM raw_measurements m JOIN astronaut_profiles p ON p.id=m.astronaut_id "
                 "WHERE p.data_class='personal'" + (' AND m.astronaut_id=?' if aid else ''))
            return c.execute(q, (aid,) if aid else ()).fetchone()[0]

    def analyses(self):
        from app import db
        with db.connect() as c:
            return c.execute("SELECT COUNT(*) FROM analysis_runs WHERE model='phantom_hr_univariate_1_4'").fetchone()[0]

    @contextmanager
    def fail(self, point):
        from app.persistence import repository as repo
        orig_save, orig_audit = repo.save_analysis, repo.audit

        def boom(*a, **k):
            raise sqlite3.OperationalError('database is locked (injected)')

        def after_commit(*a, **k):
            orig_save(*a, **k)
            raise sqlite3.OperationalError('connection reset after commit (injected)')

        def audit_fail(c, user_id, action, resource, *a, **k):
            if action == 'create' and resource == 'analysis':
                raise sqlite3.OperationalError('audit write failed (injected)')
            return orig_audit(c, user_id, action, resource, *a, **k)
        if point == 'before':
            repo.save_analysis = boom
        elif point == 'after_commit':
            repo.save_analysis = after_commit
        else:                                          # during / history / audit: last statement inside the transaction
            repo.audit = audit_fail
        try:
            yield
        finally:
            repo.save_analysis, repo.audit = orig_save, orig_audit


@pytest.fixture(params=['fake', 'be2'])
def be(request, tmp_path):
    if request.param == 'fake':
        b = FakeBackend(tmp_path)
        yield b
    else:
        request.getfixturevalue('real_db')
        yield Be2Backend()
    api15_science.set_storage(None)


def _session(be, ctx=None, aid=None, addr='C4:7A:1C:00:12:9F'):
    ctx, aid = ctx or be.owner(), aid or be.aid
    dev = be.st.upsert_device(ctx, {'hardware_address': addr, 'name': 'strap', 'astronaut_id': aid, 'kind': 'ble_hrs'})
    # BE2_06: wearable rows must carry the SAME source as their live BLE session (server-side provenance check)
    sid = be.st.create_session(ctx, aid, 'live_sensor', 'test fixture HRS stream', device_id=dev['device_id'])
    return dev['device_id'], sid


def _rows(be, minutes=90, aid=None, **kw):
    did, sid = _session(be, aid=aid) if 'session_id' not in kw else (kw.pop('device_id'), kw.pop('session_id'))
    return hr_series(minutes=minutes, astronaut=aid or be.aid, session_id=sid, device_id=did, start=T0,
                     quality='good', **kw), sid


def _store(be, rows, ctx=None):
    for i in range(0, len(rows), 500):
        be.st.save_measurements(ctx or be.owner(), rows[i:i + 500])


def _all(be, ctx=None, **kw):
    out, cur = [], None
    while True:
        p = be.st.query_measurements(ctx or be.owner(), kw.pop('aid', be.aid), cursor=cur, **kw)
        out += p['items']
        cur = p['next_cursor']
        if not cur:
            return out


# ------------------------------------------------------------------------------------------- measurements
def test_round_trip_types_and_canonical_shape(be):
    rows, sid = _rows(be, minutes=2)
    res = be.st.save_measurements(be.owner(), rows)
    assert res['saved'] == len(rows) == 120 and res['duplicates'] == 0
    got = _all(be, session_id=sid)
    assert len(got) == 120
    for m in got:
        assert m['astronaut_id'] == be.aid and m['session_id'] == sid
        assert isinstance(m['value'], float) and m['unit'] in ('bpm', 'ms')
        assert m['recorded_at'].endswith('Z') and reg.parse_utc(m['recorded_at'])
        assert m['data_class'] == 'real_wearable' and m['quality'] == 'good' and m['valid'] is True
        assert m['provenance'].get('contact') is True and m['client_measurement_id']
    assert {m['signal'] for m in got} == {'heart_rate', 'rr_interval'}


def test_batch_is_atomic_one_bad_row_stores_nothing(be):
    rows, _ = _rows(be, minutes=1)
    bad = [*rows[:10], {**rows[10], 'value': float('nan')}]
    with pytest.raises(InvalidInput):
        be.st.save_measurements(be.owner(), bad)
    assert be.count(be.aid) == 0
    bad = [*rows[:10], {**rows[10], 'recorded_at': '2026-11-01T10:00:00'}]          # no UTC offset
    with pytest.raises(InvalidInput):
        be.st.save_measurements(be.owner(), bad)
    assert be.count(be.aid) == 0


def test_idempotent_replay_and_409_on_changed_payload(be):
    rows, _ = _rows(be, minutes=1)
    be.st.save_measurements(be.owner(), rows)
    again = be.st.save_measurements(be.owner(), rows)
    assert again['saved'] == 0 and again['duplicates'] == len(rows) and be.count(be.aid) == len(rows)
    changed = [{**rows[0], 'value': rows[0]['value'] + 1}]
    with pytest.raises(Conflict) as e:
        be.st.save_measurements(be.owner(), changed)
    assert e.value.status == 409 and e.value.code == 'idempotency_conflict' and be.count(be.aid) == len(rows)
    # a batch containing one conflicting row stores nothing new either
    fresh = hr_series(minutes=1, astronaut=be.aid, session_id=rows[0]['session_id'], device_id=rows[0]['device_id'],
                      start=T0 + timedelta(hours=5), quality='good')
    with pytest.raises(Conflict):
        be.st.save_measurements(be.owner(), fresh + changed)
    assert be.count(be.aid) == len(rows)


def test_access_other_astronaut_cannot_read_or_write(be):
    rows, sid = _rows(be, minutes=1)
    _store(be, rows)
    with pytest.raises(ScienceError) as e:
        be.st.query_measurements(be.other(), be.aid)
    assert e.value.status == 404                                              # hidden, not 403
    with pytest.raises(ScienceError) as e:
        be.st.save_measurements(be.other(), [{**rows[0], 'client_measurement_id': 'attack-1'}])
    assert e.value.status == 404 and be.count(be.aid) == len(rows)
    assert be.count(be.aid2) == 0


def test_pagination_has_no_gaps_or_duplicates_and_ordering_is_not_assumed(be):
    rows, sid = _rows(be, minutes=30)                                         # 1800 rows
    shuffled = rows[900:] + rows[:900]                                        # inserted out of time order
    _store(be, shuffled)
    got = _all(be, session_id=sid, limit=137)
    ids = [m['measurement_id'] for m in got]
    assert len(ids) == len(set(ids)) == 1800
    assert sorted(m['client_measurement_id'] for m in got) == sorted(r['client_measurement_id'] for r in rows)
    # BE2_06 closed divergence D-1: the canonical scientific read sorts (measured_at, id) like the fake
    times = [m['recorded_at'] for m in got]
    assert times == sorted(times)


def test_interval_is_half_open_start_inclusive_end_exclusive(be):
    rows, sid = _rows(be, minutes=2, rr=False)                                # one row every 2 s
    _store(be, rows)
    start = reg.iso_utc(T0 + timedelta(seconds=10))
    end = reg.iso_utc(T0 + timedelta(seconds=20))
    got = sorted(m['recorded_at'] for m in _all(be, start=start, end=end))
    assert got[0] == start and end not in got and len(got) == 5


def test_signal_filter_and_unknown_cursor(be):
    rows, sid = _rows(be, minutes=1)
    _store(be, rows)
    assert {m['signal'] for m in _all(be, signals=['rr_interval'])} == {'rr_interval'}
    assert len(_all(be, signals=['heart_rate', 'rr_interval'])) == len(rows)


def test_restart_keeps_everything(be):
    rows, sid = _rows(be, minutes=3)
    _store(be, rows)
    before = sorted(m['measurement_id'] for m in _all(be))
    be.restart()
    assert sorted(m['measurement_id'] for m in _all(be)) == before
    assert be.st.get_session(be.owner(), sid)['session_id'] == sid


def test_sessions_owner_only_and_closing(be):
    did, sid = _session(be)
    s = be.st.get_session(be.owner(), sid)
    assert s['astronaut_id'] == be.aid and s['device_id'] == did and s['source_type'] == 'live_sensor'
    be.st.finish_session(be.owner(), sid, 'saved')
    assert be.st.get_session(be.owner(), sid)['finished_at']
    with pytest.raises(ScienceError) as e:
        be.st.get_session(be.other(), sid)
    assert e.value.status == 404
    with pytest.raises(ScienceError):
        be.st.create_session(be.other(), be.aid, 'live_sensor', 'x', device_id=did)


def test_devices_foreign_device_hidden_and_duplicate_address_refused(be):
    did, _ = _session(be)
    with pytest.raises(ScienceError) as e:
        be.st.get_device(be.other(), did)
    assert e.value.status == 404
    with pytest.raises(Conflict) as e:
        be.st.upsert_device(be.owner(), {'hardware_address': 'C4:7A:1C:00:12:9F', 'name': 'again', 'astronaut_id': be.aid,
                                         'kind': 'ble_hrs'})
    assert e.value.code == 'device_already_registered'
    # the same physical address may belong to another astronaut's registry entry (Backend №2 UNIQUE per astronaut)
    d2 = be.st.upsert_device(be.other(), {'hardware_address': 'C4:7A:1C:00:12:9F', 'name': 'b', 'astronaut_id': be.aid2,
                                          'kind': 'ble_hrs'})
    assert d2['device_id'] != did


# ------------------------------------------------------------------------------------------- analysis bundle
def _request(be, sid):
    return {'astronaut_id': be.aid, 'session_id': sid}


def _run(be, sid, ctx=None):
    api15_science.set_storage(be.st)
    return api15_science.dispatch(ctx or be.owner(), 'POST', '/api/phantom-analyses', {}, _request(be, sid))


@pytest.fixture
def recorded(be):
    rows, sid = _rows(be, minutes=90)
    _store(be, rows)
    return sid


def test_bundle_created_then_replayed_identically(be, recorded):
    code, r = _run(be, recorded)
    assert code == 201 and r['outcome'] == 'flag' and be.analyses() == 1
    code, again = _run(be, recorded)
    assert code == 200 and again['idempotent_replay'] and again['analysis_id'] == r['analysis_id'] and be.analyses() == 1
    strip = lambda d: {k: v for k, v in d.items() if k not in ('idempotent_replay', 'created_at', 'storage', 'input_scope')}
    assert strip(again) == strip(r)


@pytest.mark.parametrize('point', ['before', 'during', 'history', 'audit'])
def test_bundle_failure_leaves_nothing_and_a_resend_succeeds(be, recorded, point):
    with be.fail(point):
        code, err = _run(be, recorded)
    assert code == 503 and err['error']['code'] == 'storage_unavailable' and be.analyses() == 0
    assert 'safe to resend' in err['error']['detail']
    code, r = _run(be, recorded)
    assert code == 201 and be.analyses() == 1


def test_bundle_lost_ack_then_replay_returns_the_committed_analysis(be, recorded):
    with be.fail('after_commit'):
        code, err = _run(be, recorded)
    assert code == 503 and be.analyses() == 1                                  # committed, the ack was lost
    code, r = _run(be, recorded)
    assert code == 200 and r['idempotent_replay'] and be.analyses() == 1


def test_bundle_same_key_changed_payload_is_409(be, recorded):
    code, r = _run(be, recorded)
    payload = be.st.get_analysis(be.owner(), r['analysis_id'])
    tampered = {**payload, 'outcome': 'no_flag'}
    with pytest.raises(Conflict) as e:
        be.st.save_analysis_bundle(be.owner(), 'phantom_analysis', be.aid, tampered,
                                   record={'kind': 'phantom_analysis', 'ref_ids': [r['idempotency_key']], 'astronaut_id': be.aid,
                                           'data_class': 'derived', 'summary': 'x'},
                                   audit={'action': 'phantom_analysis.create', 'target_kind': 'phantom_analysis',
                                          'target_id': r['idempotency_key'], 'outcome': 'success'},
                                   idempotency_key=r['idempotency_key'], input_ids=[])
    assert e.value.status == 409 and be.analyses() == 1


def test_bundle_after_restart_replays(be, recorded):
    code, r = _run(be, recorded)
    be.restart()
    code, again = _run(be, recorded)
    assert code == 200 and again['analysis_id'] == r['analysis_id'] and be.analyses() == 1


def test_bundle_concurrent_replays_store_exactly_one(be, recorded):
    with ThreadPoolExecutor(4) as ex:
        results = list(ex.map(lambda _: _run(be, recorded), range(4)))
    ok = [r for c, r in results if c in (200, 201)]
    assert ok and len({r['analysis_id'] for r in ok}) == 1 and be.analyses() == 1
    assert sum(c == 201 for c, _ in results) <= 1
    for c, r in results:                                                       # a lost race may only fail closed
        assert c in (200, 201, 503), (c, r)


def test_bundle_other_user_cannot_run_or_read(be, recorded):
    code, r = _run(be, recorded)
    code, err = _run(be, recorded, ctx=be.other())
    assert code == 404 and be.analyses() == 1 and be.aid not in str(err)
    api15_science.set_storage(be.st)
    assert api15_science.dispatch(be.other(), 'GET', f'/api/phantom-analyses/{r["analysis_id"]}')[0] == 404


def test_bundle_permission_revoked_mid_operation_saves_nothing(be, recorded):
    orig = be.st.save_analysis_bundle

    def revoke_then_save(*a, **k):
        be.revoke_owner()                                                    # between data read and the write
        return orig(*a, **k)
    be.st.save_analysis_bundle = revoke_then_save
    try:
        code, err = _run(be, recorded)
    finally:
        be.st.save_analysis_bundle = orig
    assert code in (401, 404) and be.analyses() == 0


def test_analysis_listing_only_phantom_and_own(be, recorded):
    code, r = _run(be, recorded)
    page = be.st.list_analyses(be.owner(), astronaut_id=be.aid)
    assert [x['analysis_id'] for x in page['items']] == [r['analysis_id']]
    with pytest.raises(ScienceError) as e:
        be.st.list_analyses(be.other(), astronaut_id=be.aid)
    assert e.value.status == 404
    with pytest.raises(ScienceError) as e:
        be.st.get_analysis(be.owner(), str(uuid.uuid4()))
    assert e.value.status == 404
