"""03A — Device Manager on Backend №2's REAL storage: crash recovery, single BLE source, restart.
Mock transport (no physical device). Scenario B of test_aether_15_real_storage_e2e.py covers 2 users / 2 straps."""
import pytest

from be3_real_backend import canonical_storage, Account, real_db  # noqa: F401

ADDR = 'C4:7A:1C:00:12:9F'


def _manager(storage=None, tr=None, clock=None):
    from app.devices import manager as dm
    from app.science_storage_be2 import Be2ScienceStorage
    from fakes.ble_mock import ManualClock, ManualScheduler, MockTransport
    if tr is None:
        tr = MockTransport()
        tr.add(ADDR)
    clock = clock or ManualClock()
    return dm.DeviceManager(storage or canonical_storage(), tr, clock=clock, scheduler=ManualScheduler(clock)), tr, clock


def _rows(aid):
    from app import db
    with db.connect() as c:
        return c.execute('SELECT COUNT(*) FROM raw_measurements WHERE astronaut_id=?', (aid,)).fetchone()[0]


def test_crash_then_new_process_recovers_the_open_session(real_db):
    from app.devices import hw_lock
    from app.persistence import repository as repo
    alice = Account('alice')
    dev = repo.create_device(alice.user, {'name': 'strap', 'kind': 'ble', 'external_id': ADDR})
    m1, tr, clock = _manager()
    con = m1.connect(alice.ctx(), dev['id'], {'astronaut_id': alice.astronaut_id})
    for _ in range(30):
        m1.scheduler.advance(2)
        tr.link(ADDR).hr(64, (960,), True)
    m1.scheduler.advance(10)                                   # periodic flush
    stored = _rows(alice.astronaut_id)
    assert stored > 0
    # "crash": the process dies — no disconnect, the Backend №2 session stays open, the radio lock dies with it
    hw_lock._reset_for_tests()
    m2, tr2, _ = _manager()
    st = m2.storage
    assert st.get_session(alice.ctx(), con['session_id'])['status'] == 'recording'
    con2 = m2.connect(alice.ctx(), dev['id'], {'astronaut_id': alice.astronaut_id})
    assert con2['session_id'] != con['session_id']
    old = st.get_session(alice.ctx(), con['session_id'])
    # BE2_06 (R-3 done): the durable terminal status is stored; recovery after a crash is 'interrupted'
    assert old['status'] == 'interrupted' and old['finished_at']    # recovered before the new connect, by the owner
    assert _rows(alice.astronaut_id) == stored                  # nothing duplicated, nothing invented
    m2.disconnect(alice.ctx(), dev['id'])


def test_only_ble_devices_can_be_connected_and_registry_is_backend2(real_db):
    from app.persistence import repository as repo
    from app.science_errors import ScienceError
    alice = Account('alice')
    manual = repo.create_device(alice.user, {'name': 'scale', 'kind': 'manual', 'external_id': None})
    m, _, _ = _manager()
    with pytest.raises(ScienceError) as e:
        m.connect(alice.ctx(), manual['id'], {'astronaut_id': alice.astronaut_id})
    assert e.value.code == 'device_not_ble'
    # BE2_06 (R-4 done): the canonical registry allows a rename only; owner and hardware address are immutable
    ble = repo.create_device(alice.user, {'name': 'strap', 'kind': 'ble', 'external_id': ADDR})
    out = m.storage.upsert_device(alice.ctx(), {'device_id': ble['id'], 'name': 'renamed', 'astronaut_id': alice.astronaut_id,
                                                'hardware_address': ADDR})
    assert out['name'] == 'renamed'
    with pytest.raises(ScienceError):
        m.storage.upsert_device(alice.ctx(), {'device_id': ble['id'], 'name': 'x', 'astronaut_id': alice.astronaut_id,
                                              'hardware_address': 'AA:BB:CC:DD:EE:FF'})


def test_token_expiry_during_recording_fails_closed_and_keeps_rows(real_db):
    """A recording longer than the Backend №2 token lifetime (12 h / 30 min idle) cannot keep writing with the
    owner's session: buffered rows stay pending (not dropped, not written under another identity). BE2 R-6."""
    from app.persistence import repository as repo
    alice = Account('alice')
    dev = repo.create_device(alice.user, {'name': 'strap', 'kind': 'ble', 'external_id': ADDR})
    m, tr, clock = _manager()
    m.connect(alice.ctx(), dev['id'], {'astronaut_id': alice.astronaut_id})
    for _ in range(10):
        m.scheduler.advance(2)
        tr.link(ADDR).hr(64, (960,), True)
    m.scheduler.advance(10)
    before = _rows(alice.astronaut_id)
    alice.logout()                                              # same effect as expiry / idle timeout
    for _ in range(10):
        m.scheduler.advance(2)
        tr.link(ADDR).hr(65, (950,), True)
    m.scheduler.advance(10)
    st = m.status(alice.relogin().ctx(), dev['id'])
    assert _rows(alice.astronaut_id) == before                 # nothing written without a valid session
    assert st['pending_rows'] > 0 and 'Unauthenticated' in st['error']   # visible, not silently dropped
