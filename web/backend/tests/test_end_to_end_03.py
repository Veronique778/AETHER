"""AETHER 1.5 — end-to-end: mock BLE strap → Device Manager → storage (fake) → personal PHANTOM → history → API.
Mock transport + simulated time: the PIPELINE is verified, not a physical device."""
import pytest
import random

from app import api15_science
from app.devices import api as dapi
from app.devices import manager as dm
from fakes.ble_mock import ManualClock, ManualScheduler, MockTransport
from fakes.storage_fake import FakeContext, FakeStorage
from helpers_be3_signals_15 import P1, P2, P3, P4


@pytest.fixture(autouse=True)
def _fresh_hardware_locks():
    """Each test owns its mock devices; the process-wide hardware lock (app.devices.hw_lock) must not leak between tests."""
    from app.devices import hw_lock
    hw_lock._reset_for_tests()
    yield
    hw_lock._reset_for_tests()


CTX = FakeContext(user_id='a' * 32, astronaut_ids=frozenset({P1}))
ADDR = 'C4:7A:1C:00:12:9F'


def _setup():
    st, tr, clock = FakeStorage(), MockTransport(), ManualClock()
    tr.add(ADDR)
    m = dm.DeviceManager(st, tr, clock=clock, scheduler=ManualScheduler(clock))
    api15_science.set_storage(st); dapi.set_manager(m)
    return st, tr, clock, m


def _record(st, tr, m, minutes=90, step_at=60, gap=None, contact_loss=None):
    dev = m.register(CTX, {'hardware_address': ADDR, 'name': 'strap', 'astronaut_id': P1})   # registry (fake here)
    did = dev['device_id']
    code, con = api15_science.dispatch(CTX, 'POST', f'/api/devices/{did}/connect', {}, {'astronaut_id': P1})
    rng = random.Random(3)
    for s in range(0, minutes * 60, 2):
        m.scheduler.advance(2)
        mm = s / 60
        if gap and gap[0] <= mm < gap[1]:
            if mm == gap[0]:
                tr.link(ADDR).drop('out_of_range')
            continue
        if gap and mm >= gap[1] and m.status(CTX, did)['lifecycle_state'] != 'recording':
            m.scheduler.advance(1)
        hr = (62 if mm < step_at else 74) + rng.gauss(0, 1.0)
        contact = not (contact_loss and contact_loss[0] <= mm < contact_loss[1])
        tr.link(ADDR).hr(int(round(hr)), (int(1024 * 60 / hr),), contact)
    api15_science.dispatch(CTX, 'POST', f'/api/devices/{did}/disconnect', {}, {})
    return did, con['session_id']


def _analyse(sid):
    return api15_science.dispatch(CTX, 'POST', '/api/phantom-analyses', {}, {'astronaut_id': P1, 'session_id': sid})


def test_strap_to_phantom_flag_with_history():
    st, tr, clock, m = _setup()
    try:
        did, sid = _record(st, tr, m)
        code, r = _analyse(sid)
        assert code == 201 and r['outcome'] == 'flag' and r['input']['data_classes'] == ['real_wearable']
        assert r['input']['session_ids'] == [sid] and r['signal_quality']['heart_rate']['contact'] == {'reported_true': 2700}
        assert r['input']['excluded'] == {} and r['diagnosis'] is None
        code, got = api15_science.dispatch(CTX, 'GET', f'/api/phantom-analyses/{r["analysis_id"]}')
        assert code == 200 and got['outcome'] == 'flag'
        kinds = [x['kind'] for x in st.db['records']]
        assert 'phantom_analysis' in kinds and 'measurement_batch' in kinds
        assert st.db['sessions'][sid]['status'] == 'saved'
    finally:
        api15_science.set_storage(None); dapi.set_manager(None)


def test_link_loss_and_contact_loss_are_visible_in_the_analysis_not_filled():
    st, tr, clock, m = _setup()
    try:
        did, sid = _record(st, tr, m, step_at=999, gap=(70, 80), contact_loss=(30, 40))
        code, r = _analyse(sid)
        reasons = {w['unusable_reason'] for w in r['windows'] if w['role'] == 'test'}
        assert 'no_measurements' in reasons or 'coverage_too_short' in reasons
        base = [w for w in r['windows'] if w['role'] == 'baseline']
        assert sum(w['mean_hr_bpm'] is None for w in base) == 2           # the two no-contact windows (30–40 min)
        assert r['input']['excluded'].get('no_contact_reported', 0) > 0
        assert r['outcome'] == 'no_flag' and m.status(CTX, did)['reconnects'] == 1
    finally:
        api15_science.set_storage(None); dapi.set_manager(None)
