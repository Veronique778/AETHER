"""Behaviour of the storage fake = the agreed behaviour of Backend №2's app/storage (contract §2.3).
IR-2: Backend №2 runs this file against the real implementation (replace the `storage` fixture)."""
import pytest

from app.science_errors import Conflict, Forbidden, InvalidUnits, NotFound, StorageUnavailable
from fakes.storage_fake import FakeContext, FakeStorage
from helpers_be3_signals_15 import hr_series, span, store
from helpers_be3_signals_15 import P1, P2, P3, P4

A01 = FakeContext(user_id='a' * 32, astronaut_ids=frozenset({P1}))
A02 = FakeContext(user_id='b' * 32, astronaut_ids=frozenset({P2}))


@pytest.fixture()
def storage():
    return FakeStorage()


def test_every_measurement_saved_with_binding_time_and_provenance(storage):
    sid = storage.create_session(A01, P1, 'live_sensor', 'test', device_id='d' * 32)
    rows = hr_series(minutes=2, session_id=sid, device_id='d' * 32)
    store(storage, A01, rows)
    got = storage.query_measurements(A01, P1, limit=10_000)['items']
    assert len(got) == len(rows)
    for r, g in zip(sorted(rows, key=lambda r: (r['recorded_at'], r['signal'])), sorted(got, key=lambda r: (r['recorded_at'], r['signal']))):
        assert (g['astronaut_id'], g['device_id'], g['session_id'], g['recorded_at'], g['provenance']) == \
               (r['astronaut_id'], r['device_id'], r['session_id'], r['recorded_at'], r['provenance'])
        assert g['received_at'].endswith('Z') and len(g['measurement_id']) == 32


def test_idempotent_replay_creates_no_duplicates(storage):
    rows = hr_series(minutes=1)
    first = storage.save_measurements(A01, rows)
    again = storage.save_measurements(A01, rows)
    assert first['saved'] == len(rows) and again['saved'] == 0 and again['duplicates'] == len(rows)
    assert len(storage.query_measurements(A01, P1, limit=10_000)['items']) == len(rows)


def test_batch_is_atomic(storage):
    rows = hr_series(minutes=1)
    rows[5] = {**rows[5], 'unit': 'Hz'}
    with pytest.raises(InvalidUnits):
        storage.save_measurements(A01, rows)
    assert storage.query_measurements(A01, P1)['items'] == []


def test_injected_failure_loses_nothing_on_retry(storage):
    rows = hr_series(minutes=1)
    storage.fail_next = 'save_measurements'
    with pytest.raises(StorageUnavailable):
        storage.save_measurements(A01, rows)
    storage.save_measurements(A01, rows)
    assert len(storage.query_measurements(A01, P1, limit=10_000)['items']) == len(rows)


def test_authorisation_and_isolation(storage):
    store(storage, A01, hr_series(minutes=1))
    store(storage, A02, hr_series(minutes=1, astronaut=P2, seed=9))
    with pytest.raises(Forbidden):
        storage.query_measurements(A02, P1)
    with pytest.raises(Forbidden):
        storage.save_measurements(A02, hr_series(minutes=1))
    assert {r['astronaut_id'] for r in storage.query_measurements(A01, P1, limit=10_000)['items']} == {P1}


def test_session_of_other_astronaut_rejected(storage):
    sid = storage.create_session(A01, P1, 'live_sensor', 'test')
    admin = FakeContext(role='admin')
    with pytest.raises(Forbidden):
        storage.save_measurements(admin, hr_series(minutes=1, astronaut=P2, session_id=sid))


def test_finished_session_accepts_no_more_data(storage):
    sid = storage.create_session(A01, P1, 'live_sensor', 'test')
    storage.finish_session(A01, sid, 'saved')
    with pytest.raises(Conflict):
        storage.save_measurements(A01, hr_series(minutes=1, session_id=sid))
    with pytest.raises(NotFound):
        storage.finish_session(A01, 'f' * 32, 'saved')


def test_half_open_time_interval(storage):
    store(storage, A01, hr_series(minutes=4, rr=False, every_s=60))     # minutes 0,1,2,3
    f, t = span(2)
    got = storage.query_measurements(A01, P1, start=f, end=t)['items']
    assert [g['recorded_at'][14:16] for g in got] == ['00', '01']


def test_persistence_across_restart(tmp_path):
    p = tmp_path / 'store.json'
    s1 = FakeStorage(p)
    store(s1, A01, hr_series(minutes=1))
    aid = s1.save_analysis(A01, 'phantom_personal', P1, {'outcome': 'no_flag'})
    s2 = FakeStorage(p)                     # "restarted server"
    assert len(s2.query_measurements(A01, P1, limit=10_000)['items']) == 60
    assert s2.get_analysis(A01, aid)['outcome'] == 'no_flag'


def test_invalidate_keeps_record(storage):
    out = storage.save_measurements(A01, hr_series(minutes=1, rr=False, every_s=30))
    mid = out['items'][0]['measurement_id']
    storage.invalidate(A01, mid, 'loose strap')
    assert len(storage.query_measurements(A01, P1)['items']) == 1
    assert len(storage.query_measurements(A01, P1, include_invalid=True)['items']) == 2
    with pytest.raises(Conflict):
        storage.invalidate(A01, mid, 'again')
