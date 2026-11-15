"""HTTP handlers for API Contract 1.5 §3.6 (BLE devices) — registered through app.api15_science (Backend №2 wires them).

    Routed (BLE lifecycle on devices registered in Backend №2's registry):
    POST   /api/devices/scan                    discover HRS monitors
    POST   /api/devices/{device_id}/connect     start a recording session {astronaut_id, mission_id?}
    POST   /api/devices/{device_id}/disconnect  stop and finish the session
    GET    /api/devices/{device_id}/status      live state and counters
    GET    /api/devices/adapters                SensorAdapter compatibility descriptors (amendment A-15)
    GET    /api/devices/ble-diagnostics         structured Bluetooth status for the signed-in user (1.5 BLE personal)
    GET    /api/devices/active                  the caller's active recordings (UI restore after reload)
    POST   /api/devices/simulated               register/get the caller's explicit SIMULATED HRS strap (SYNTHETIC)
    NOT routed (owned by Backend №2, api_15.py): GET/POST /api/devices, GET /api/devices/{id}/sessions.
"""
from __future__ import annotations

import threading

from .. import science_storage
from .adapters import BleHrsAdapter, registry
from .manager import DeviceManager, transport_data_class
from .runtime import SUPPORTED_PROTOCOL, BleakTransport
from .simulated import SIM_ADDRESS_PREFIX, SIM_DEVICE_NAME, SimulatedHrsTransport, is_simulated_address

_MANAGER = None
_LOCK = threading.Lock()
VERIFIED_MAX_CONCURRENT = 0      # no simultaneous links were verified on real hardware


def set_manager(manager) -> None:
    global _MANAGER
    _MANAGER = manager


def get_manager() -> DeviceManager:
    global _MANAGER
    with _LOCK:
        if _MANAGER is None:
            storage = science_storage.resolve(('measurements', 'sessions', 'devices', 'history'))
            _MANAGER = DeviceManager(storage, BleakTransport(), sim_transport=SimulatedHrsTransport())
        return _MANAGER


def peek_manager():
    """The manager if one was created in this process (never creates one — used by logout/shutdown hooks)."""
    return _MANAGER


def on_logout(token: str) -> list[dict]:
    """Stop & save recordings started with `token` before the logout revokes it (AUTH-02)."""
    m = _MANAGER
    if m is None or not token:
        return []
    try:
        return m.stop_for_token(token)
    except Exception:
        return []


def shutdown() -> None:
    m = _MANAGER
    if m is not None:
        m.shutdown()


def _q(query, key):
    v = (query or {}).get(key)
    return v[0] if isinstance(v, list) else v


def h_list(ctx, match, query, body):
    m = get_manager()
    ok, why = m.transport.availability()
    return {'items': m.list(ctx, _q(query, 'astronaut_id')), 'next_cursor': None, 'ble_available': ok,
            'ble_unavailable_reason': why, 'max_concurrent_connections_software': m.max_concurrent,
            'max_concurrent_connections_verified': VERIFIED_MAX_CONCURRENT}


def h_scan(ctx, match, query, body):
    return get_manager().scan(ctx, body)


def h_register(ctx, match, query, body):
    return 201, get_manager().register(ctx, body)


def h_get(ctx, match, query, body):
    return get_manager().get(ctx, match['device_id'])


def h_patch(ctx, match, query, body):
    return get_manager().update(ctx, match['device_id'], body or {})


def h_delete(ctx, match, query, body):
    return get_manager().remove(ctx, match['device_id'])


def h_connect(ctx, match, query, body):
    return get_manager().connect(ctx, match['device_id'], body or {})


def h_disconnect(ctx, match, query, body):
    return get_manager().disconnect(ctx, match['device_id'])


def h_status(ctx, match, query, body):
    return get_manager().status(ctx, match['device_id'])


def h_diagnostics(ctx, match, query, body):
    m = get_manager()
    t = m.transport
    diag = t.diagnostics() if hasattr(t, 'diagnostics') else {
        'ble_dependency_available': t.availability()[0], 'scan_available': t.availability()[0],
        'reason': t.availability()[1], 'reason_code': None if t.availability()[0] else 'ble_unavailable',
        'radio_available': None, 'radio_state': 'unknown', 'supported_protocol': SUPPORTED_PROTOCOL, 'transport': 'unknown'}
    user = ctx.user
    return {'backend': 'connected', 'authenticated_owner': {'login': user.get('login'), 'astronaut_id': user.get('astronaut_id')},
            **diag, 'radio_data_class': transport_data_class(t), 'hardware_verified': False,
            'simulated_hrs_available': m.sim_transport is not None,
            'max_concurrent_connections_software': m.max_concurrent,
            'max_concurrent_connections_verified': VERIFIED_MAX_CONCURRENT,
            'active_recordings': len(m.active_for(ctx)),
            'compatibility_note': ('Only devices that expose the standard Bluetooth Heart Rate Service are supported. '
                                   'Most smartwatches (Apple Watch, many Samsung/Xiaomi/Huawei models) do not; some offer a '
                                   '"broadcast heart rate" mode that does. Compatibility is verified over GATT on connect.')}


def h_active(ctx, match, query, body):
    return {'items': get_manager().active_for(ctx)}


def h_simulated(ctx, match, query, body):
    """Get or register the caller's own simulated strap. Server-chosen address prefix → SYNTHETIC provenance only."""
    m = get_manager()
    if m.sim_transport is None:
        from ..science_errors import DeviceUnavailable
        raise DeviceUnavailable('The simulated HRS test transport is not enabled in this process', code='simulation_unavailable')
    for d in m.list(ctx, None):
        if is_simulated_address(d.get('hardware_address')):
            return {**d, 'simulated': True, 'data_class': 'synthetic'}
    import uuid
    if not ctx.can('device:use', ctx.astronaut_id):
        from ..science_errors import Forbidden
        raise Forbidden()
    # Registry row is created by Backend №2 (create without device_id); the address prefix is chosen HERE, by the server.
    saved = m._store('upsert_device', ctx, {'hardware_address': SIM_ADDRESS_PREFIX + uuid.uuid4().hex[:12].upper(),
                                            'name': SIM_DEVICE_NAME, 'astronaut_id': ctx.astronaut_id})
    m._store('audit', ctx, 'device.register_simulated', 'device', saved['device_id'], 'success', {})
    return 201, {**m._public(saved), 'simulated': True, 'data_class': 'synthetic'}


def h_adapters(ctx, match, query, body):
    m = _MANAGER
    return {'adapters': registry(BleHrsAdapter(m, m.transport if m else BleakTransport()))}


_ID = r'(?P<device_id>[a-zA-Z0-9_.:-]{1,80})'          # Backend №2 Identifier (UUID for personal devices)
_B = {'auth': 'bearer', 'capability': 'devices-ble'}
# 03A: the device REGISTRY (GET/POST /api/devices) belongs to Backend №2 (api_15.py). Backend №3 serves only the BLE
# lifecycle on devices that already exist in that registry. Registry handlers above remain for the fake-storage
# harness only and are deliberately NOT routed, so there is exactly one POST /api/devices in AETHER.
ROUTES = [
    ('GET', r'^/api/devices/adapters$', h_adapters, {**_B, 'astronaut_scope': None}),
    ('GET', r'^/api/devices/ble-diagnostics$', h_diagnostics, {**_B, 'astronaut_scope': None}),
    ('GET', r'^/api/devices/active$', h_active, {**_B, 'astronaut_scope': None}),
    ('POST', r'^/api/devices/simulated$', h_simulated, {**_B, 'astronaut_scope': None, 'permission': 'device:use'}),
    ('POST', r'^/api/devices/scan$', h_scan, {**_B, 'astronaut_scope': None}),
    ('POST', rf'^/api/devices/{_ID}/connect$', h_connect, {**_B, 'astronaut_scope': 'body', 'permission': 'device:use'}),
    ('POST', rf'^/api/devices/{_ID}/disconnect$', h_disconnect, {**_B, 'astronaut_scope': None, 'resource_check': 'handler'}),
    ('GET', rf'^/api/devices/{_ID}/status$', h_status, {**_B, 'astronaut_scope': None, 'resource_check': 'handler'}),
]
REGISTRY_ROUTES_OWNED_BY_BACKEND2 = [('GET', '/api/devices'), ('POST', '/api/devices'), ('GET', '/api/devices/{id}/sessions')]
