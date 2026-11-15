"""AETHER 1.5 — device routes through app.api15_science.dispatch (no server needed) and the storage adapter boundary."""
import json
import sys
import types
from pathlib import Path

import pytest

from app import api15_science, science_storage
from app.devices import api as dapi
from app.devices import manager as dm
from app.devices.adapters import registry
from app.science_errors import StorageUnavailable
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
ADDR = 'C4:7A:1C:00:12:9F'
EX = Path(__file__).resolve().parents[3] / 'docs/api_1_5/examples'


@pytest.fixture()
def env():
    st, tr, clock = FakeStorage(), MockTransport(), ManualClock()
    tr.add(ADDR)
    m = dm.DeviceManager(st, tr, clock=clock, scheduler=ManualScheduler(clock))
    api15_science.set_storage(st); dapi.set_manager(m)
    yield types.SimpleNamespace(st=st, tr=tr, m=m, sched=m.scheduler)
    api15_science.set_storage(None); dapi.set_manager(None)


def call(ctx, method, path, body=None, query=None):
    return api15_science.dispatch(ctx, method, path, query or {}, body)


def _example_keys(name):
    """Keys of a contract example; empty set when the contract package is not merged (only the shape check is skipped)."""
    p = EX / f'{name}.json'
    return set(json.loads(p.read_text(encoding='utf-8'))) if p.exists() else set()


def test_full_lifecycle_cycle_and_contract_shapes(env):
    # 03A: the REGISTRY (create/list) belongs to Backend №2; here the fake registry is used through the manager
    dev = env.m.register(A01, {'hardware_address': ADDR, 'name': 'Strap', 'astronaut_id': P1})
    assert _example_keys('device_register_201') - {'registered_by', 'last_seen_at'} <= set(dev) | {'registered_by', 'last_seen_at'}
    did = dev['device_id']
    code, scan = call(A01, 'POST', '/api/devices/scan', {'timeout_seconds': 3})
    assert code == 200 and _example_keys('devices_scan_200') <= set(scan) and scan['found'][0]['registered_device_id'] == did
    code, con = call(A01, 'POST', f'/api/devices/{did}/connect', {'astronaut_id': P1})
    assert code == 200 and _example_keys('device_connect_200') <= set(con) and con['astronaut_id'] == P1
    env.tr.link(ADDR).hr(66, (900,), True)
    code, stt = call(A01, 'GET', f'/api/devices/{did}/status')
    assert code == 200 and _example_keys('device_status_200') <= set(stt) and stt['received_samples'] == 1
    assert stt['device_id'] == did and stt['astronaut_id'] == P1
    code, err = call(A01, 'POST', f'/api/devices/{did}/connect', {'astronaut_id': P1})
    assert code == 409 and err['error']['code'] == 'device_busy'
    code, off = call(A01, 'POST', f'/api/devices/{did}/disconnect', {})
    assert code == 200 and off['connection'] == 'disconnected' and off['stored_samples'] == 2
    assert len(env.st.db['measurements']) == 2


def test_errors_and_access(env):
    did = env.m.register(A01, {'hardware_address': ADDR, 'name': 'S', 'astronaut_id': P1})['device_id']
    code, err = call(A02, 'POST', f'/api/devices/{did}/connect', {'astronaut_id': P2})
    assert code == 404 and err['error']['code'] == 'not_found'          # foreign device: no existence leak
    assert call(A02, 'GET', f'/api/devices/{did}/status')[0] == 404
    code, err = call(A01, 'POST', f'/api/devices/{did}/connect', {})
    assert code == 422 and err['error']['field'] == 'astronaut_id'
    code, err = call(A01, 'POST', f'/api/devices/{did}/connect', {'astronaut_id': 'A01'})
    assert code == 422 and err['error']['code'] == 'legacy_id_not_allowed'
    assert call(A01, 'GET', '/api/devices/not a device/status')[0] == 404       # no route
    env.tr.available, env.tr.reason = False, 'Bluetooth dependency missing (bleak).'
    code, err = call(A01, 'POST', '/api/devices/scan', {})
    assert code == 503 and err['error']['code'] == 'ble_unavailable' and 'bleak' in err['error']['detail']


def test_no_second_device_registry_is_routed():
    """Exactly one POST /api/devices in AETHER: Backend №2's. The science table serves the BLE lifecycle only."""
    for m, path in dapi.REGISTRY_ROUTES_OWNED_BY_BACKEND2 + [('GET', '/api/devices/abc'), ('PATCH', '/api/devices/abc'),
                                                            ('DELETE', '/api/devices/abc')]:
        assert api15_science.match(m, path.replace('{id}', 'abc')) is None, (m, path)
    for m, path in [('POST', '/api/devices/scan'), ('POST', '/api/devices/abc-1/connect'),
                    ('POST', '/api/devices/abc-1/disconnect'), ('GET', '/api/devices/abc-1/status'), ('GET', '/api/devices/adapters')]:
        assert api15_science.match(m, path), (m, path)


def test_adapter_descriptors_are_honest(env):
    code, out = call(A01, 'GET', '/api/devices/adapters')
    by = {a['id']: a for a in out['adapters']}
    assert code == 200 and set(by) == {'ble_hrs', 'apple_healthkit', 'android_health_connect', 'garmin'}
    assert all(a['hardware_verified'] is False for a in by.values())
    assert by['ble_hrs']['status'] == 'automated_tested' and by['ble_hrs']['signals'] == ['heart_rate', 'rr_interval']
    for k in ('apple_healthkit', 'android_health_connect', 'garmin'):
        assert by[k]['status'] in ('integration_pending', 'unsupported') and by[k]['available_here'] is False and by[k]['signals'] == []


# ---------------------------------------------------------------- storage adapter boundary
def test_fake_storage_conforms_to_the_full_protocol():
    assert science_storage.conformance(FakeStorage()) == []


def test_nonconforming_adapter_reports_precise_problems():
    class Partial:
        def save_measurements(self, ctx, items): ...
        def query_measurements(self, ctx, astronaut_id, start=None): ...
    probs = science_storage.conformance(Partial(), ('measurements', 'sessions'))
    assert any('query_measurements() lacks parameter(s) signals' in p for p in probs)
    assert any('missing create_session()' in p for p in probs) and any('missing list_sessions()' in p for p in probs)


def test_resolve_without_backend2_is_503_not_fake(monkeypatch):
    science_storage.set_storage(None)
    monkeypatch.setitem(sys.modules, 'app.persistence', None)
    monkeypatch.setitem(sys.modules, 'app.persistence.repository', None)
    monkeypatch.setitem(sys.modules, 'app.storage.api', None)
    with pytest.raises(StorageUnavailable) as e:
        science_storage.resolve(('measurements',))
    assert 'no app.storage.api and no app.persistence science adapter' in e.value.message


def test_resolve_through_app_persistence_adapter(monkeypatch):
    science_storage.set_storage(None)
    fake = FakeStorage()
    mod = types.ModuleType('app.persistence'); mod.science_storage = lambda: fake
    monkeypatch.setitem(sys.modules, 'app.storage.api', None)
    monkeypatch.setitem(sys.modules, 'app.persistence', mod)
    assert science_storage.resolve(('measurements', 'sessions', 'devices', 'analyses', 'history')) is fake


def test_app_persistence_without_adapter_is_explained(monkeypatch):
    science_storage.set_storage(None)
    monkeypatch.setitem(sys.modules, 'app.persistence.repository', None)     # Backend №3's own BE2 adapter unavailable
    mod = types.ModuleType('app.persistence')
    mod.SCIENCE_STORAGE = types.SimpleNamespace(save_measurements=lambda ctx, items: None)
    monkeypatch.setitem(sys.modules, 'app.storage.api', None)
    monkeypatch.setitem(sys.modules, 'app.persistence', mod)
    with pytest.raises(StorageUnavailable) as e:
        science_storage.resolve(('measurements',))
    assert 'app.persistence.SCIENCE_STORAGE' in e.value.message and 'query_measurements' in e.value.message


def test_registry_function_lists_all_adapters():
    assert [a['id'] for a in registry()] == ['ble_hrs', 'apple_healthkit', 'android_health_connect', 'garmin']
