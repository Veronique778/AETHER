"""AETHER 1.5 — BLE Device Manager (app/devices/manager.py) on MockTransport + FakeStorage + manual time.
MOCKS ONLY: these tests prove the software paths, NOT that any physical device works (hardware_verified = false)."""
import threading
from datetime import timedelta

import pytest

from app.devices import manager as dm
from app.devices.lifecycle import ALLOWED, State, can, check
from app.science_errors import Conflict, DeviceBusy, DeviceUnavailable, Forbidden, InvalidInput, RoleForbidden, SensorDisconnected
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


A01 = FakeContext(user_id='a' * 32, astronaut_ids=frozenset({P1}))
A02 = FakeContext(user_id='b' * 32, astronaut_ids=frozenset({P2}))
ADMIN = FakeContext(user_id='c' * 32, role='admin')
ADDR1, ADDR2 = 'C4:7A:1C:00:12:9F', 'D1:00:00:00:00:02'


class Env:
    def __init__(self, path=None, **kw):
        self.storage = FakeStorage(path)
        self.transport = MockTransport()
        self.transport.add(ADDR1, 'Strap 1'); self.transport.add(ADDR2, 'Strap 2')
        self.clock = ManualClock()
        self.sched = ManualScheduler(self.clock)
        self.m = dm.DeviceManager(self.storage, self.transport, clock=self.clock, scheduler=self.sched, **kw)

    def start(self, ctx=A01, aid=P1, addr=ADDR1):
        dev = self.m.register(ctx, {'hardware_address': addr, 'name': 'strap', 'astronaut_id': aid})
        out = self.m.connect(ctx, dev['device_id'], {'astronaut_id': aid})
        return dev['device_id'], out['session_id'], self.transport.link(addr)

    def beats(self, link, n, hr=62, rr=(1000,), contact=True, every=1.0):
        for _ in range(n):
            self.sched.advance(every)
            link.hr(hr, rr, contact)

    def rows(self, session_id=None):
        return sorted((r for r in self.storage.db['measurements'].values() if session_id is None or r['session_id'] == session_id),
                      key=lambda r: (r['recorded_at'], r['signal'], r['client_measurement_id']))


@pytest.fixture()
def env():
    return Env()


# ---------------------------------------------------------------- lifecycle
def test_lifecycle_allowed_and_forbidden_transitions():
    assert can(State.DISCONNECTED, State.CONNECTING) and can(State.RECORDING, State.RECONNECTING)
    assert can(State.RECONNECTING, State.RECORDING) and can(State.CONNECTING, State.CONNECTION_FAILED)
    for bad in [(State.DISCONNECTED, State.RECORDING), (State.RECORDING, State.CONNECTING), (State.DISCONNECTED, State.CONNECTED),
                (State.CONNECTION_FAILED, State.RECORDING), (State.SCANNING, State.RECORDING)]:
        assert not can(*bad)
        with pytest.raises(Conflict):
            check(*bad)
    assert all(State.UNAVAILABLE in ALLOWED[s] or s in (State.DISCONNECTING, State.CONNECTION_FAILED, State.UNAVAILABLE)
               for s in State)


def test_connect_goes_through_states_and_session_is_bound(env):
    did, sid, link = env.start()
    st = env.m.status(A01, did)
    assert st['lifecycle_state'] == 'recording' and st['connection'] == 'connected' and st['astronaut_id'] == P1
    s = env.storage.db['sessions'][sid]
    assert (s['astronaut_id'], s['device_id'], s['status'], s['source_type']) == (P1, did, 'recording', 'live_sensor')


# ---------------------------------------------------------------- persistence of every sample
def test_every_hr_and_rr_value_is_stored_with_full_metadata(env):
    did, sid, link = env.start()
    env.beats(link, 10, hr=64, rr=(900, 950, 1000))
    env.m.flush(did)
    rows = env.rows(sid)
    assert len(rows) == 10 * 4 and env.m.status(A01, did)['stored_samples'] == 40
    for r in rows:
        assert (r['astronaut_id'], r['device_id'], r['session_id'], r['data_class']) == (P1, did, sid, 'real_wearable')
        assert r['recorded_at'].endswith('Z') and r['received_at'] and r['source'] == dm.SOURCE
        assert r['provenance']['contact'] is True and r['quality'] == 'good' and r['valid']
        assert r['provenance']['received_host_utc'] and 'time_uncertainty_s' in r['provenance']
    rr = sorted((r for r in rows if r['signal'] == 'rr_interval'),
                key=lambda r: (r['provenance']['notification_seq'], r['provenance']['rr_index']))
    assert [round(r['value'], 4) for r in rr[:3]] == [round(x * 1000 / 1024, 4) for x in (900, 950, 1000)]
    assert len({r['client_measurement_id'] for r in rows}) == 40


def test_rr_times_reconstructed_backwards_and_uncertainty_grows(env):
    did, sid, link = env.start()
    env.beats(link, 1, rr=(1024, 1024))                   # two beats of exactly 1 s in one notification
    env.m.flush(did)
    hr = [r for r in env.rows(sid) if r['signal'] == 'heart_rate'][0]
    rr = sorted((r for r in env.rows(sid) if r['signal'] == 'rr_interval'), key=lambda r: r['provenance']['rr_index'])
    assert rr[1]['recorded_at'] == hr['recorded_at']                    # newest RR ends at receipt
    from app.signals import parse_utc
    assert (parse_utc(rr[1]['recorded_at']) - parse_utc(rr[0]['recorded_at'])).total_seconds() == 1.0
    assert rr[0]['provenance']['time_uncertainty_s'] > rr[1]['provenance']['time_uncertainty_s']
    assert rr[0]['provenance']['clock'] == 'receipt-relative beat estimate'


@pytest.mark.parametrize('contact,quality,valid,state', [(True, 'good', True, 'contact'), (False, 'no_contact', False, 'no_contact'),
                                                         (None, 'screened', True, 'not_reported')])
def test_contact_rule_applied_to_hr_and_rr(env, contact, quality, valid, state):
    did, sid, link = env.start()
    env.beats(link, 3, rr=(1000,), contact=contact)
    env.m.flush(did)
    rows = env.rows(sid)
    assert {(r['quality'], r['valid'], r['provenance']['contact']) for r in rows} == {(quality, valid, contact)}
    assert {r['signal'] for r in rows} == {'heart_rate', 'rr_interval'}
    st = env.m.status(A01, did)
    assert st['contact_state'] == state and (st['heart_rate'] is None) == (contact is False)
    if contact is False:
        assert st['quality'] == 'no_contact' and st['no_contact_samples'] == 3


def test_out_of_range_heart_rate_stored_as_invalid_not_dropped(env):
    did, sid, link = env.start()
    env.beats(link, 1, hr=0, rr=())
    env.m.flush(did)
    (r,) = env.rows(sid)
    assert r['value'] == 0 and r['quality'] == 'out_of_range' and not r['valid']


def test_corrupt_packet_counted_not_stored(env):
    did, sid, link = env.start()
    link.send(bytes([0x10, 60, 0x00]))
    env.m.flush(did)
    assert env.rows(sid) == [] and env.m.status(A01, did)['corrupt_packets'] == 1


def test_flush_by_size_and_by_time(env):
    did, sid, link = env.start()
    for _ in range(dm.FLUSH_ROWS // 2 - 1):             # 2 rows per notification, below the size threshold
        link.hr(60, (1000,))
    assert len(env.rows(sid)) == 0
    link.hr(60, (1000,))                                 # reaches FLUSH_ROWS → immediate flush
    assert len(env.rows(sid)) == dm.FLUSH_ROWS
    link.hr(60, (1000,))
    env.sched.advance(dm.FLUSH_INTERVAL_S + dm.TICK_S)   # time-based flush on the next tick
    assert len(env.rows(sid)) == dm.FLUSH_ROWS + 2


# ---------------------------------------------------------------- duplicates, storage failures
def test_storage_outage_then_recovery_loses_and_duplicates_nothing(env):
    did, sid, link = env.start()
    for _ in range(5):
        link.hr(62, (1000,))                             # no time passes → nothing flushed yet
    env.storage.fail_next = 'save_measurements'
    env.m.flush(did)
    st = env.m.status(A01, did)
    assert st['storage_failures'] == 1 and st['pending_rows'] == 10 and 'Storage unavailable' in st['error']
    env.beats(link, 5)
    env.m.flush(did)
    assert len(env.rows(sid)) == 20 and env.m.status(A01, did)['duplicate_rows'] == 0


def test_lost_ack_retry_is_deduplicated_by_deterministic_ids(env):
    did, sid, link = env.start()
    for _ in range(5):
        link.hr(62, (1000,))
    real = env.storage.save_measurements
    def ack_lost(ctx, items):
        real(ctx, items)
        raise TimeoutError('ack lost')
    env.storage.save_measurements = ack_lost
    env.m.flush(did)                                    # stored, but the manager thinks it failed
    env.storage.save_measurements = real
    env.m.flush(did)                                    # retry
    st = env.m.status(A01, did)
    assert len(env.rows(sid)) == 10                      # exactly once in storage
    assert st['duplicate_rows'] == 10 and st['stored_samples'] == 0 and st['pending_rows'] == 0 and st['storage_failures'] == 1


def test_buffer_is_bounded_during_long_outage(env, monkeypatch):
    monkeypatch.setattr(dm, 'MAX_PENDING_ROWS', 40)
    did, sid, link = env.start()
    class Down(Exception): pass
    real = env.storage.save_measurements
    env.storage.save_measurements = lambda ctx, items: (_ for _ in ()).throw(Down())
    env.beats(link, 50)                                  # 100 rows produced, only 40 fit (+1 loss marker)
    st = env.m.status(A01, did)
    assert st['pending_rows'] == 41 and st['dropped_rows'] == 60
    env.storage.save_measurements = real
    env.m.flush(did)
    rows = env.rows(sid)
    markers = [r for r in rows if r['provenance'].get('event') == 'rows_dropped_storage_outage']
    assert len(rows) == 41 and len(markers) == 1 and markers[0]['value'] is None and markers[0]['quality'] == 'missing'


# ---------------------------------------------------------------- gaps, link loss, reconnect
def test_no_notifications_creates_one_missing_marker_not_values(env):
    did, sid, link = env.start()
    env.beats(link, 3)
    env.sched.advance(dm.STALE_S + 3 * dm.TICK_S)       # sensor silent
    env.m.flush(did)
    rows = env.rows(sid)
    gaps = [r for r in rows if r['value'] is None]
    assert len(gaps) == 1 and gaps[0]['provenance']['event'] == 'no_notifications' and gaps[0]['quality'] == 'missing'
    assert len(rows) == 3 * 2 + 1
    st = env.m.status(A01, did)
    assert st['heart_rate'] is None and st['quality'] == 'missing' and st['gaps'] == 1
    env.beats(link, 1)
    assert env.m.status(A01, did)['quality'] == 'good'


def test_link_loss_reconnects_into_the_same_session(env):
    did, sid, link = env.start()
    env.beats(link, 3)
    link.drop('out_of_range')
    st = env.m.status(A01, did)
    assert st['lifecycle_state'] == 'reconnecting' and st['connection'] == 'reconnecting' and st['heart_rate'] is None
    env.transport.fail_connects[ADDR1] = 1               # first attempt fails, second succeeds
    env.sched.advance(sum(dm.RECONNECT_DELAYS_S[:2]) + 0.01)
    st = env.m.status(A01, did)
    assert st['lifecycle_state'] == 'recording' and st['reconnects'] == 1 and st['session_id'] == sid
    env.beats(env.transport.link(ADDR1), 3)
    env.m.flush(did)
    rows = env.rows(sid)
    assert len(rows) == 3 * 2 + 1 + 3 * 2               # values + ONE link-loss marker, nothing invented in the gap
    assert [r['provenance']['event'] for r in rows if r['value'] is None] == ['out_of_range']


def test_reconnect_gives_up_and_finishes_session(env):
    did, sid, link = env.start()
    env.beats(link, 2)
    env.transport.never_connect.add(ADDR1)
    link.drop('device_off')
    env.sched.advance(sum(dm.RECONNECT_DELAYS_S) + 1)
    st = env.m.status(A01, did)
    assert st['lifecycle_state'] == 'disconnected' and 'reconnection failed' in st['error']
    assert env.storage.db['sessions'][sid]['status'] == 'saved_after_connection_loss'
    assert len(env.rows(sid)) == 2 * 2 + 1


def test_late_packets_of_old_link_are_ignored(env):
    did, sid, link = env.start()
    env.m.disconnect(A01, did)
    link.alive = True                                    # stack delivers a stale notification afterwards
    link.hr(70, (900,))
    env.m.flush(did)
    assert env.rows(sid) == []


def test_user_disconnect_finishes_session_and_flushes(env):
    did, sid, link = env.start()
    env.beats(link, 4)
    out = env.m.disconnect(A01, did)
    assert out['session_status'] == 'saved' and out['stored_samples'] == 8 and out['pending_rows'] == 0
    assert env.storage.db['sessions'][sid]['status'] == 'saved'
    assert env.m.status(A01, did)['lifecycle_state'] == 'disconnected' and not link.alive
    assert env.m.disconnect(A01, did)['changed'] is False


def test_bluetooth_switched_off_during_recording(env):
    did, sid, link = env.start()
    env.beats(link, 2)
    env.transport.available = False
    link.drop('adapter_off')
    env.sched.advance(sum(dm.RECONNECT_DELAYS_S) + 1)
    assert env.storage.db['sessions'][sid]['status'] == 'saved_after_connection_loss'
    with pytest.raises(DeviceUnavailable):
        env.m.connect(A01, did, {'astronaut_id': P1})


# ---------------------------------------------------------------- crash, restart, recovery
def test_crash_loses_at_most_the_documented_buffer_and_recovery_closes_session(tmp_path):
    p = tmp_path / 'store.json'
    e = Env(p)
    did, sid, link = e.start()
    e.beats(link, 40)                                    # flushed periodically
    stored_before_crash = len(e.rows(sid))
    pending = e.m.status(A01, did)['pending_rows']
    assert pending < dm.FLUSH_ROWS and stored_before_crash + pending == 80
    # --- process killed: no flush, no finish. New process: ---
    e2 = Env(p)
    assert e2.storage.db['sessions'][sid]['status'] == 'recording'
    closed = e2.m.recover_interrupted_sessions(ADMIN)
    assert closed == [sid]
    s = e2.storage.db['sessions'][sid]
    assert s['status'] == 'interrupted' and 'nothing was added' in s['metadata']['reason']
    assert len(e2.rows(sid)) == stored_before_crash                 # stored data kept, nothing invented
    assert e2.m.recover_interrupted_sessions(ADMIN) == []           # idempotent


def test_recovery_does_not_close_live_sessions(env):
    did, sid, link = env.start()
    assert env.m.recover_interrupted_sessions(ADMIN) == []
    assert env.storage.db['sessions'][sid]['status'] == 'recording'


def test_shutdown_flushes_and_finishes_all_sessions(env):
    d1, s1, l1 = env.start()
    d2, s2, l2 = env.start(A02, P2, ADDR2)
    env.beats(l1, 3); env.beats(l2, 3)
    env.m.shutdown()
    assert {env.storage.db['sessions'][s]['status'] for s in (s1, s2)} == {'saved_on_shutdown'}
    assert len(env.rows(s1)) == len(env.rows(s2)) == 6 and not l1.alive and not l2.alive
    with pytest.raises(DeviceUnavailable):
        env.m.connect(A01, d1, {'astronaut_id': P1})


def test_finish_failure_is_reported_and_recoverable(env):
    did, sid, link = env.start()
    env.storage.fail_next = 'finish_session'
    env.m.disconnect(A01, did)
    assert 'recover_interrupted_sessions' in env.m.status(A01, did)['error']
    assert env.m.recover_interrupted_sessions(ADMIN) == [sid]


# ---------------------------------------------------------------- binding, isolation, busy, access
def test_device_bound_to_other_astronaut_cannot_record_for_me(env):
    dev = env.m.register(ADMIN, {'hardware_address': ADDR1, 'name': 's', 'astronaut_id': P2})
    with pytest.raises(Forbidden):
        env.m.connect(A01, dev['device_id'], {'astronaut_id': P1})
    with pytest.raises(Forbidden):
        env.m.connect(ADMIN, dev['device_id'], {'astronaut_id': P1})     # even admin: binding is explicit


def test_unassigned_device_must_be_assigned_first(env):
    dev = env.m.register(ADMIN, {'hardware_address': ADDR1, 'name': 's'})
    with pytest.raises(Conflict):
        env.m.connect(ADMIN, dev['device_id'], {'astronaut_id': P1})
    with pytest.raises(RoleForbidden):
        env.m.register(A01, {'hardware_address': ADDR2, 'name': 's'})


def test_busy_device_refuses_second_session(env):
    did, sid, link = env.start()
    with pytest.raises(DeviceBusy) as e:
        env.m.connect(A01, did, {'astronaut_id': P1})
    assert e.value.code == 'device_busy' and e.value.status == 409
    with pytest.raises(Conflict):
        env.m.update(A01, did, {'astronaut_id': None})
    with pytest.raises(Conflict):
        env.m.remove(A01, did)


def test_duplicate_hardware_registration_refused(env):
    env.m.register(A01, {'hardware_address': ADDR1, 'name': 's', 'astronaut_id': P1})
    with pytest.raises(Conflict) as e:
        env.m.register(A01, {'hardware_address': ADDR1, 'name': 's2', 'astronaut_id': P1})
    assert e.value.code == 'device_already_registered'


def test_reregistration_after_removal_and_rebinding(env):
    did, sid, link = env.start()
    env.m.disconnect(A01, did)
    env.m.remove(A01, did)
    assert env.m.list(A01) == [] and sid in env.storage.db['sessions']      # session record kept
    dev = env.m.register(ADMIN, {'hardware_address': ADDR2, 'name': 'x', 'astronaut_id': P1})
    out = env.m.update(ADMIN, dev['device_id'], {'astronaut_id': P2})
    assert out['astronaut_id'] == P2 and 'lifecycle_state' in out


def test_parallel_sessions_of_two_astronauts_are_isolated_under_threads(env):
    d1, s1, l1 = env.start()
    d2, s2, l2 = env.start(A02, P2, ADDR2)
    def pump(link, hr):
        for _ in range(300):
            link.hr(hr, (900, 910))
    ts = [threading.Thread(target=pump, args=(l1, 61)), threading.Thread(target=pump, args=(l2, 99))]
    [t.start() for t in ts]; [t.join() for t in ts]
    env.m.flush(d1); env.m.flush(d2)
    r1, r2 = env.rows(s1), env.rows(s2)
    assert len(r1) == len(r2) == 900
    assert {(r['astronaut_id'], r['device_id']) for r in r1} == {(P1, d1)}
    assert {(r['astronaut_id'], r['device_id']) for r in r2} == {(P2, d2)}
    assert {r['value'] for r in r1 if r['signal'] == 'heart_rate'} == {61.0}
    assert {r['value'] for r in r2 if r['signal'] == 'heart_rate'} == {99.0}
    assert len({r['client_measurement_id'] for r in r1 + r2}) == 1800


def test_software_concurrency_limit(env):
    m = dm.DeviceManager(env.storage, env.transport, clock=env.clock, scheduler=env.sched, max_concurrent=1)
    env.m = m
    env.start()
    with pytest.raises(DeviceBusy) as e:
        env.start(A02, P2, ADDR2)
    assert e.value.code == 'adapter_limit'


def test_access_checks(env):
    did, sid, link = env.start()
    with pytest.raises(Forbidden):
        env.m.status(A02, did)
    with pytest.raises(Forbidden):
        env.m.disconnect(A02, did)
    with pytest.raises(Forbidden):
        env.m.list(A02, P1)
    assert env.m.list(A02) == []
    with pytest.raises(InvalidInput):
        env.m.get(A01, 'not a valid id!')
    with pytest.raises(InvalidInput):
        env.m.connect(A01, did, {'astronaut_id': 'A01'})          # legacy demo id cannot record real data (03A)


# ---------------------------------------------------------------- failures of the BLE stack
def test_bleak_missing_or_no_adapter(env):
    env.transport.available, env.transport.reason = False, 'Bluetooth dependency missing (bleak).'
    with pytest.raises(DeviceUnavailable) as e:
        env.m.scan(A01)
    assert e.value.code == 'ble_unavailable' and e.value.status == 503 and 'bleak' in e.value.message
    dev = env.m.register(A01, {'hardware_address': ADDR1, 'name': 's', 'astronaut_id': P1})
    with pytest.raises(DeviceUnavailable):
        env.m.connect(A01, dev['device_id'], {'astronaut_id': P1})
    assert env.storage.db['sessions'] == {}                       # nothing created


def test_connection_failure_closes_session_and_allows_retry(env):
    dev = env.m.register(A01, {'hardware_address': ADDR1, 'name': 's', 'astronaut_id': P1})
    env.transport.fail_connects[ADDR1] = 1
    with pytest.raises(SensorDisconnected) as e:
        env.m.connect(A01, dev['device_id'], {'astronaut_id': P1})
    assert e.value.code == 'connection_failed'
    assert [s['status'] for s in env.storage.db['sessions'].values()] == ['connection_failed']
    assert env.m.status(A01, dev['device_id'])['lifecycle_state'] == 'connection_failed'
    out = env.m.connect(A01, dev['device_id'], {'astronaut_id': P1})
    assert out['recording']


def test_scan_marks_registered_devices(env):
    dev = env.m.register(A01, {'hardware_address': ADDR1, 'name': 's', 'astronaut_id': P1})
    found = {f['hardware_address']: f for f in env.m.scan(A01)['found']}
    assert found[ADDR1]['registered_device_id'] == dev['device_id'] and found[ADDR2]['registered_device_id'] is None
    with pytest.raises(InvalidInput):
        env.m.scan(A01, {'timeout_seconds': 99})


def test_clock_regression_is_flagged_not_corrected(env):
    did, sid, link = env.start()
    env.beats(link, 1)
    env.clock.wall_offset = -30.0                                 # host clock jumps back 30 s
    env.beats(link, 1)
    env.m.flush(did)
    hr = [r for r in env.rows(sid) if r['signal'] == 'heart_rate']
    assert sum(1 for r in hr if r['provenance'].get('clock_regression')) == 1
    assert env.m.status(A01, did)['clock_regressions'] == 1


def test_create_session_failure_leaves_device_retryable(env):
    dev = env.m.register(A01, {'hardware_address': ADDR1, 'name': 's', 'astronaut_id': P1})
    env.storage.fail_next = 'create_session'
    with pytest.raises(Exception):
        env.m.connect(A01, dev['device_id'], {'astronaut_id': P1})
    assert env.m.connect(A01, dev['device_id'], {'astronaut_id': P1})['recording']
