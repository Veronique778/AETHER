"""AETHER 1.5 — accelerated long-recording and failure scenarios (tests/ble_endurance_03.py).
SIMULATED time and mock transport: proves buffering/persistence logic, not radio or real-time behaviour."""
import pytest

import ble_endurance_03 as e


@pytest.fixture(autouse=True)
def _fresh_hardware_locks():
    """Each test owns its mock devices; the process-wide hardware lock (app.devices.hw_lock) must not leak between tests."""
    from app.devices import hw_lock
    hw_lock._reset_for_tests()
    yield
    hw_lock._reset_for_tests()



def _one(r):
    (p,) = r['per_session'].values()
    return p


@pytest.mark.parametrize('name', ['1h_nominal', '8h_nominal'])
def test_nominal_long_recording_stores_every_value_once(name):
    r = e.run(**e.SCENARIOS[name])
    assert r['lost_value_rows'] == 0 and r['duplicate_ids_in_storage'] == 0
    assert r['value_rows_stored'] == r['accepted_value_rows'] == int(e.SCENARIOS[name]['hours'] * 3600) * 2
    assert r['peak_pending_rows'] < 50 and r['max_commit_delay_s_simulated'] <= 2.0
    assert _one(r)['missing_markers'] == 0 and _one(r)['session_status'] == 'saved'


def test_parallel_sessions_do_not_mix():
    r = e.run(**e.SCENARIOS['3_parallel_sessions_1h'])
    assert r['lost_value_rows'] == 0 and r['duplicate_ids_in_storage'] == 0
    assert all(p['foreign_rows'] == 0 and p['stored_rows'] == 3600 * 3 for p in r['per_session'].values())
    assert sorted(p['astronaut'] for p in r['per_session'].values()) == sorted(e.PIDS[:3])


def test_temporary_storage_outage_recovers_everything():
    r = e.run(**e.SCENARIOS['storage_outage_10min'])
    p = _one(r)
    assert r['lost_value_rows'] == 0 and r['duplicate_ids_in_storage'] == 0 and p['storage_failures'] > 500
    assert 1199 <= r['peak_pending_rows'] <= 1204 and r['max_commit_delay_s_simulated'] >= 600


def test_flaky_storage_no_loss_no_duplicates():
    r = e.run(**e.SCENARIOS['storage_flaky_30pct'])
    assert r['lost_value_rows'] == 0 and r['duplicate_ids_in_storage'] == 0 and _one(r)['storage_failures'] > 100


def test_queue_overflow_loss_is_bounded_counted_and_marked():
    r = e.run(**e.SCENARIOS['queue_overflow_cap_2000'])
    p = _one(r)
    assert r['peak_pending_rows'] <= 2001                       # cap + one loss marker
    assert r['lost_value_rows'] == p['dropped_rows'] > 0 and p['missing_markers'] == 1
    assert r['duplicate_ids_in_storage'] == 0


def test_partial_signal_loss_is_stored_as_such():
    r = e.run(**e.SCENARIOS['partial_loss_10pct_no_contact_and_5min_silence'])
    p = _one(r)
    assert r['lost_value_rows'] == 0 and p['missing_markers'] == 1        # one marker for the 5-minute silence
    assert 0.05 < p['no_contact_rows'] / p['value_rows'] < 0.15          # no-contact samples kept, flagged invalid
    assert r['accepted_value_rows'] == (3600 - 300) * 2
