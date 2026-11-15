"""BLE Device Manager (AETHER 1.5, Backend №3) — independent devices, one recording session per device.

Design rules
* One DeviceSlot per device_id, each with its own lock, lifecycle state, session, astronaut and counters. There is no
  global sensor state (1.4's single `ble_sensor.sensor` object remains only behind the deprecated /api/biosignals/sensor/*).
* A session belongs to exactly one astronaut and one device. A busy device refuses a second session (409 device_busy).
  A device registered to astronaut X records only for X (403 / 409 otherwise); re-binding needs PATCH while idle.
* Every sample is stored through the agreed storage adapter (app.science_storage → Backend №2). No table is created here.
* Rows are built only from the slot's own astronaut/session/device — never from the transport callback arguments —
  so records of different astronauts cannot be mixed even if notifications of several devices interleave.
* Persistence: rows are buffered per slot and flushed when ≥ FLUSH_ROWS rows are pending or every FLUSH_INTERVAL_S.
  Maximum data that can be lost by a process crash in normal operation: the pending buffer = < FLUSH_ROWS rows and
  < FLUSH_INTERVAL_S + one tick of data. During a storage outage the buffer grows to MAX_PENDING_ROWS; beyond that new
  samples are DROPPED (counted, marked by a gap row once storage is back) — memory never grows without bound.
* Every row has a deterministic client_measurement_id `<session>:<seq>:hr|rrN|gapN`: a retried flush after a lost
  acknowledgement is de-duplicated by storage; RR values of one notification are stored once each, in order.
* Time: HR `recorded_at` = host receipt time (the HRS packet has no timestamp). RR `recorded_at` = beat-end estimate
  reconstructed backwards from receipt; provenance carries `clock`, `time_uncertainty_s` and `received_host_utc`.
  A host clock that goes backwards is flagged (`clock_regression`), never "corrected".
* Contact rule (02A): contact False → quality 'no_contact' (invalid); contact not supported/reported → at most
  'screened'; contact True → 'good'. `provenance.contact` is written on the HR row AND on every RR row.
* Gaps: no notification for STALE_S while recording → one explicit missing row (value null, quality 'missing') per gap;
  link loss → missing row + automatic reconnection into the same session; nothing is interpolated.
* Recovery: recover_interrupted_sessions() closes sessions left in 'recording' by a crashed process as 'interrupted'.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from .. import identity, signals as reg
from . import hw_lock
from ..science_errors import (Conflict, CorruptedData, DeviceBusy, DeviceUnavailable, Forbidden, InvalidInput, NotFound,
                              RoleForbidden, ScienceError, SensorDisconnected, StorageUnavailable)
from . import hrs
from .lifecycle import ACTIVE, CONTRACT_CONNECTION, State, check
from .runtime import BleScanError, HrsNotSupported, SystemClock, ThreadScheduler, classify_ble_error
from .simulated import SIM_SOURCE, is_simulated_address

PROFILE = 'Bluetooth SIG Heart Rate Service (0x180D / 0x2A37)'
SOURCE = 'BLE Heart Rate Service'
PROCESSING_VERSION = 'aether-devices-1.5.0'
FLUSH_ROWS = 50
FLUSH_INTERVAL_S = 1.0
TICK_S = 1.0
STALE_S = 5.0
MAX_PENDING_ROWS = 20_000
CONNECT_TIMEOUT_S = 20.0
RECONNECT_DELAYS_S = (1.0, 2.0, 4.0, 8.0, 16.0)
BLE_LATENCY_BOUND_S = 0.1         # documented assumption for receipt-time uncertainty (connection interval scale)
DEFAULT_MAX_CONCURRENT = 4        # software limit; the VERIFIED number of simultaneous links is 0 (no hardware test)
AUTH_CHECK_S = 10.0               # a recording re-validates its owner's personal session at least this often
REVOKED_MESSAGE = ('Personal session ended (signed out, expired or revoked); recording stopped and the Bluetooth device '
                   'was released. Rows stored before that moment are kept; nothing is written to another account.')


def transport_data_class(transport) -> str:
    """Server-side provenance of rows produced by `transport`. Fail-safe: a transport that does not declare
    DATA_CLASS = 'real_wearable' (only the production radio transport does) produces 'synthetic' rows."""
    dc = getattr(type(transport), 'DATA_CLASS', None)
    return 'real_wearable' if dc == 'real_wearable' else 'synthetic'


@dataclass
class DeviceSlot:
    device_id: str
    lock: threading.RLock = field(default_factory=threading.RLock)
    state: State = State.DISCONNECTED
    ctx: object = None
    session_id: str | None = None
    astronaut_id: str | None = None
    mission_id: str | None = None
    handle: object = None
    token: int = 0
    seq: int = 0
    gap_seq: int = 0
    pending: list = field(default_factory=list)
    inflight: bool = False
    counters: dict = field(default_factory=dict)
    last_notification_mono: float | None = None
    last_received_at: object = None
    last_flush_mono: float = 0.0
    in_gap: bool = False
    contact_state: str = 'unknown'
    last_hr: int | None = None
    last_quality: str | None = None
    error: str | None = None
    reconnect_attempt: int = 0
    timer: object = None
    started_mono: float | None = None
    dropped_since_flush: int = 0
    hardware_address: str | None = None
    transport: object = None
    data_class: str = 'real_wearable'
    source: str = SOURCE
    hrs_verified: bool = False
    revoked: bool = False
    last_auth_check_mono: float = 0.0
    last_session_id: str | None = None
    last_session_status: str | None = None

    def reset_counters(self):
        self.counters = {k: 0 for k in ('received_notifications', 'hr_samples', 'rr_samples', 'stored_rows', 'duplicate_rows',
                                        'gaps', 'corrupt_packets', 'no_contact_samples', 'dropped_rows', 'reconnects',
                                        'storage_failures', 'clock_regressions')}


class DeviceManager:
    # Production (app.persistence.recording_lifecycle_06.ManagedDeviceManager) sets True: a recording whose owner's
    # personal session ended is stopped and the device released. The 03A base keeps rows pending (BE2 R-6 tests).
    REVOKE_ON_AUTH_END = False

    def __init__(self, storage, transport, *, clock=None, scheduler=None, max_concurrent: int = DEFAULT_MAX_CONCURRENT,
                 reconnect_delays=RECONNECT_DELAYS_S, connect_timeout_s: float = CONNECT_TIMEOUT_S, sim_transport=None):
        self.storage = storage
        self.transport = transport
        self.sim_transport = sim_transport       # explicit SYNTHETIC strap (app.devices.simulated); never a radio fallback
        self.clock = clock or SystemClock()
        self.scheduler = scheduler or ThreadScheduler()
        self.max_concurrent = max_concurrent
        self.reconnect_delays = tuple(reconnect_delays)
        self.connect_timeout_s = connect_timeout_s
        self._slots: dict[str, DeviceSlot] = {}
        self._lock = threading.RLock()
        self._closed = False

    def _hw_owner(self, device_id: str) -> str:
        # per MANAGER instance: a second manager in the same process (e.g. both servers) must not re-enter the lock
        return f'dm:{id(self):x}:{device_id}'

    # ---------------------------------------------------------------- helpers
    def _slot(self, device_id: str) -> DeviceSlot:
        with self._lock:
            s = self._slots.get(device_id)
            if s is None:
                s = self._slots[device_id] = DeviceSlot(device_id)
                s.reset_counters()
            return s

    @staticmethod
    def _need(ctx, astronaut_id):
        if ctx is None or not ctx.can('device:use', astronaut_id):
            raise Forbidden(f'Your account has no access to astronaut {astronaut_id}')

    def _store(self, name, *args, **kw):
        try:
            return getattr(self.storage, name)(*args, **kw)
        except ScienceError:
            raise
        except Exception as exc:
            raise StorageUnavailable(f'Storage failed during {name}: {type(exc).__name__}') from exc

    def _ble(self, transport=None):
        transport = transport or self.transport
        ok, why = transport.availability()
        if not ok:
            code = getattr(transport, 'reason_code', lambda: None)() or 'ble_unavailable'
            raise DeviceUnavailable(why or 'Bluetooth is not available on this computer', code=code)

    def _transport_for(self, hardware_address):
        if is_simulated_address(hardware_address):
            if self.sim_transport is None:
                raise DeviceUnavailable('The simulated HRS test transport is not enabled in this process', code='simulation_unavailable')
            return self.sim_transport
        return self.transport

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for s in self._slots.values() if s.state in ACTIVE)

    # ---------------------------------------------------------------- registry
    def register(self, ctx, body: dict) -> dict:
        addr = (body or {}).get('hardware_address')
        if not isinstance(addr, str) or not 1 <= len(addr) <= 128:
            raise InvalidInput('hardware_address must be 1–128 characters', field='hardware_address')
        name = (body or {}).get('name') or 'HRS monitor'
        if not isinstance(name, str) or not 1 <= len(name) <= 80:
            raise InvalidInput('name must be 1–80 characters', field='name')
        aid = (body or {}).get('astronaut_id')
        if aid is not None:
            identity.validate_astronaut_id(aid, allow_legacy=False)     # real devices belong to personal profiles only
            self._need(ctx, aid)
        elif getattr(ctx, 'role', None) not in ('admin', 'flight_surgeon'):
            raise RoleForbidden('Only an administrator or medical officer may register an unassigned device')
        now = reg.iso_utc(self.clock.now())
        dev = {'device_id': uuid.uuid4().hex, 'kind': 'ble_hrs', 'name': name, 'hardware_address': addr, 'profile': PROFILE,
               'astronaut_id': aid, 'support_status': 'automated_tested', 'hardware_verified': False,
               'signals': ['heart_rate', 'rr_interval'], 'created_at': now, 'last_seen_at': None,
               'registered_by': getattr(ctx, 'user_id', None)}
        saved = self._store('upsert_device', ctx, dev)
        self._store('audit', ctx, 'device.register', 'device', saved['device_id'], 'success', {'astronaut_id': aid})
        return self._public(saved)

    def get(self, ctx, device_id: str) -> dict:
        _check_id(device_id)
        dev = self._store('get_device', ctx, device_id)
        if dev.get('astronaut_id'):
            self._need(ctx, dev['astronaut_id'])
        return self._public(dev)

    def list(self, ctx, astronaut_id: str | None = None) -> list[dict]:
        if astronaut_id is not None:
            identity.validate_astronaut_id(astronaut_id)
            self._need(ctx, astronaut_id)
        return [self._public(d) for d in self._store('list_devices', ctx, astronaut_id)]

    def update(self, ctx, device_id: str, body: dict) -> dict:
        dev = self.get(ctx, device_id)
        slot = self._slot(device_id)
        with slot.lock:
            if slot.state in ACTIVE:
                raise Conflict('Disconnect the device before changing it', code='device_busy')
            patch = {}
            if 'name' in (body or {}):
                if not isinstance(body['name'], str) or not 1 <= len(body['name']) <= 80:
                    raise InvalidInput('name must be 1–80 characters', field='name')
                patch['name'] = body['name']
            if 'astronaut_id' in (body or {}):
                aid = body['astronaut_id']
                if aid is not None:
                    identity.validate_astronaut_id(aid, allow_legacy=False)
                    self._need(ctx, aid)
                patch['astronaut_id'] = aid
            saved = self._store('upsert_device', ctx, {**self._registry(dev), **patch})
        self._store('audit', ctx, 'device.update', 'device', device_id, 'success', {k: v for k, v in patch.items()})
        return self._public(saved)

    def remove(self, ctx, device_id: str) -> dict:
        dev = self.get(ctx, device_id)
        slot = self._slot(device_id)
        with slot.lock:
            if slot.state in ACTIVE:
                raise Conflict('Disconnect the device before removing it', code='device_busy')
            self._store('upsert_device', ctx, {**self._registry(dev), 'removed': True})
        self._store('audit', ctx, 'device.remove', 'device', device_id, 'success', {})
        return {'removed': True, 'device_id': device_id, 'measurements_retained': True}

    @staticmethod
    def _registry(dev: dict) -> dict:
        """Registry fields only — runtime state (connection, lifecycle) is never persisted."""
        return {k: v for k, v in dev.items() if k not in ('connection', 'lifecycle_state')}

    def _public(self, dev: dict) -> dict:
        slot = self._slots.get(dev['device_id'])
        state = slot.state if slot else State.DISCONNECTED
        out = {k: v for k, v in dev.items() if k not in ('removed',)}
        out.update(connection=CONTRACT_CONNECTION[state], lifecycle_state=state.value, hardware_verified=False)
        return out

    # ---------------------------------------------------------------- discovery
    def scan(self, ctx, body: dict | None = None) -> dict:
        self._ble()
        inc = bool((body or {}).get('include_unadvertised', False))
        t = (body or {}).get('timeout_seconds', 7)
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not 1 <= t <= 15:
            raise InvalidInput('timeout_seconds must be 1–15', field='timeout_seconds')
        try:
            found = self.transport.scan(inc, float(t))
        except Exception as exc:
            code, message = classify_ble_error(exc)
            raise DeviceUnavailable(f'Bluetooth scan failed: {message}', code=code) from exc
        known = {d['hardware_address']: d['device_id'] for d in self._store('list_devices', ctx, None)}
        return {'found': [{**f, 'registered_device_id': known.get(f['hardware_address'])} for f in found],
                'scanned_at': reg.iso_utc(self.clock.now()), 'ble_available': True,
                'note': 'Only the standard Heart Rate Service is supported; advertising is not proof — HRS is verified on connect.'}

    # ---------------------------------------------------------------- connect / record
    def connect(self, ctx, device_id: str, body: dict) -> dict:
        if self._closed:
            raise DeviceUnavailable('Device manager is shutting down')
        dev = self.get(ctx, device_id)
        aid, _ = identity.validate_astronaut_id((body or {}).get('astronaut_id'), allow_legacy=False)
        self._need(ctx, aid)
        if dev.get('astronaut_id') is None:
            raise Conflict('Assign the device to an astronaut (PATCH) before recording', code='conflict')
        if dev['astronaut_id'] != aid:
            raise Forbidden(f'Device {device_id} is assigned to another astronaut')
        mission = (body or {}).get('mission_id')
        if mission is not None:
            identity.validate_object_id(mission, 'mission_id')
        if dev.get('kind') not in (None, 'ble_hrs', 'ble'):
            raise InvalidInput('Only Bluetooth devices can be connected', field='device_id', code='device_not_ble')
        transport = self._transport_for(dev['hardware_address'])
        data_class = transport_data_class(transport)
        source = SOURCE if data_class == 'real_wearable' else SIM_SOURCE
        self._ble(transport)
        self.recover_interrupted_sessions(ctx, device_id=device_id)    # close what a crashed process left open
        slot = self._slot(device_id)
        with slot.lock:
            with self._lock:                                   # lock order: slot → manager (never the reverse)
                if slot.state in ACTIVE:
                    raise DeviceBusy(f'Device {device_id} is already in use (session {slot.session_id})')
                if self.active_count() >= self.max_concurrent:
                    raise DeviceBusy(f'Software limit of {self.max_concurrent} simultaneous devices reached '
                                     '(verified hardware limit: not measured)', code='adapter_limit')
                hw_lock.acquire(dev['hardware_address'], self._hw_owner(device_id))        # one physical device, one owner
                if slot.state is State.CONNECTION_FAILED or slot.state is State.UNAVAILABLE:
                    slot.state = check(slot.state, State.DISCONNECTED)
                slot.state = check(slot.state, State.CONNECTING)
                slot.hardware_address = dev['hardware_address']
            slot.reset_counters(); slot.pending = []; slot.seq = slot.gap_seq = 0
            slot.ctx, slot.astronaut_id, slot.mission_id, slot.error = ctx, aid, mission, None
            slot.token += 1; token = slot.token
            slot.contact_state, slot.last_hr, slot.in_gap, slot.reconnect_attempt = 'unknown', None, False, 0
            slot.transport, slot.data_class, slot.source = transport, data_class, source
            slot.hrs_verified, slot.revoked, slot.last_quality = False, False, None
            slot.last_received_at, slot.last_auth_check_mono = None, self.clock.monotonic()
            try:
                slot.session_id = self._store('create_session', ctx, aid,
                                              'live_sensor' if data_class == 'real_wearable' else 'simulated_demo', source,
                                              device_id=device_id, mission_id=mission, metadata={
                                                  'profile': PROFILE, 'processing_version': PROCESSING_VERSION,
                                                  'time_basis': 'host receipt (UTC); RR beat times reconstructed backwards',
                                                  'hardware_validation': 'unverified', 'data_class': data_class,
                                                  'transport': getattr(transport, 'KIND', 'unknown')})
            except ScienceError:
                slot.state = check(slot.state, State.CONNECTION_FAILED)
                hw_lock.release(dev['hardware_address'], self._hw_owner(device_id))
                raise
        try:
            handle = transport.connect(dev['hardware_address'], lambda data: self.on_notification(device_id, token, data),
                                       lambda reason: self.on_disconnect(device_id, token, reason), self.connect_timeout_s)
        except Exception as exc:
            if isinstance(exc, HrsNotSupported):
                err = InvalidInput(f'Unsupported device: {exc}. Only the standard Bluetooth Heart Rate Service is supported.',
                                   field='device_id', code='device_not_hrs')
            elif isinstance(exc, BleScanError):
                err = DeviceUnavailable(exc.message, code=exc.reason_code)
            elif isinstance(exc, (TimeoutError,)) or 'timeout' in type(exc).__name__.lower():
                err = SensorDisconnected('Connection timed out. Wake the strap (moisten the electrodes, wear it) and '
                                         'make sure no other app or phone is connected to it.', code='connection_failed')
            else:
                err = SensorDisconnected(f'Connection failed: {type(exc).__name__}: {exc}'[:300], code='connection_failed')
            with slot.lock:
                slot.state = check(slot.state, State.CONNECTION_FAILED)
                slot.error = err.message[:300]
                sid, slot.session_id = slot.session_id, None
            self._finish(slot, sid, 'connection_failed')
            hw_lock.release(dev['hardware_address'], self._hw_owner(device_id))
            raise err from exc
        with slot.lock:
            slot.handle = handle
            slot.hrs_verified = True              # transport.connect verified GATT 0x180D / 0x2A37 and subscribed
            slot.state = check(slot.state, State.CONNECTED)
            slot.state = check(slot.state, State.RECORDING)
            slot.started_mono = slot.last_notification_mono = slot.last_flush_mono = self.clock.monotonic()
        touch = getattr(self.storage, 'touch_device', None)      # optional: Backend №2 has no device update yet
        if touch is not None:
            touch(ctx, device_id, reg.iso_utc(self.clock.now()))
        self._store('audit', ctx, 'device.connect', 'device', device_id, 'success', {'session_id': slot.session_id, 'astronaut_id': aid})
        self._schedule_tick(slot, token)
        return {'device_id': device_id, 'connection': CONTRACT_CONNECTION[slot.state], 'lifecycle_state': slot.state.value,
                'session_id': slot.session_id, 'astronaut_id': aid, 'recording': True,
                'storage': 'every sample is committed through the storage adapter (session_id)'}

    def _schedule_tick(self, slot, token):
        slot.timer = self.scheduler.call_later(TICK_S, lambda: self._tick(slot.device_id, token))

    def _tick(self, device_id, token):
        slot = self._slots.get(device_id)
        if slot is None or token != slot.token or slot.state not in (State.RECORDING, State.RECONNECTING):
            return
        now = self.clock.monotonic()
        if self.REVOKE_ON_AUTH_END and now - slot.last_auth_check_mono >= AUTH_CHECK_S:
            slot.last_auth_check_mono = now
            if not self._owner_valid(slot):
                self._revoke(slot, token)
                return
        with slot.lock:
            if (slot.state is State.RECORDING and not slot.in_gap and slot.last_notification_mono is not None
                    and now - slot.last_notification_mono > STALE_S):
                self._gap_row(slot, 'no_notifications')
        if slot.pending and now - slot.last_flush_mono >= FLUSH_INTERVAL_S:
            self.flush(device_id)
        if token == slot.token and slot.state in (State.RECORDING, State.RECONNECTING):
            self._schedule_tick(slot, token)

    def _row(self, slot, cid, signal, value, unit, recorded_at, quality, prov) -> dict:
        # data_class/source come from the slot (fixed by the server at connect from the transport), never from packets
        return {'client_measurement_id': cid, 'astronaut_id': slot.astronaut_id, 'mission_id': slot.mission_id,
                'session_id': slot.session_id, 'device_id': slot.device_id, 'signal': signal, 'value': value, 'unit': unit,
                'recorded_at': recorded_at, 'quality': quality, 'data_class': slot.data_class, 'source': slot.source,
                'provenance': prov}

    def _gap_row(self, slot, reason):
        """Explicit missing marker (value null) — the gap is stored, never filled."""
        slot.gap_seq += 1
        slot.in_gap = True
        slot.contact_state = 'unknown'
        slot.counters['gaps'] += 1
        now = self.clock.now()
        self._append(slot, [self._row(slot, f'{slot.session_id}:gap{slot.gap_seq}', 'heart_rate', None, 'bpm', reg.iso_utc(now),
                                      'missing', {'profile': 'HRS', 'event': reason, 'clock': 'host_receipt',
                                                  'contact': None, 'received_host_utc': reg.iso_utc(now)})])

    def _append(self, slot, rows):
        room = MAX_PENDING_ROWS - len(slot.pending)
        if room < len(rows):
            lost = len(rows) - max(0, room)
            slot.counters['dropped_rows'] += lost
            if not slot.dropped_since_flush:
                # first loss of this outage: one explicit marker at the time of the loss (may exceed the cap by 1 row)
                slot.gap_seq += 1
                slot.counters['gaps'] += 1
                now = reg.iso_utc(self.clock.now())
                slot.pending.append(self._row(slot, f'{slot.session_id}:gap{slot.gap_seq}', 'heart_rate', None, 'bpm', now,
                                              'missing', {'profile': 'HRS', 'event': 'rows_dropped_storage_outage',
                                                          'contact': None, 'clock': 'host_receipt', 'received_host_utc': now}))
            slot.dropped_since_flush += lost
            rows = rows[:max(0, room)]
        slot.pending.extend(rows)

    def on_notification(self, device_id: str, token: int, data: bytes) -> None:
        slot = self._slots.get(device_id)
        if slot is None:
            return
        flush = False
        with slot.lock:
            if token != slot.token or slot.state is not State.RECORDING:
                return                                 # late packet of an old connection: ignored, never re-attributed
            received = self.clock.now()
            slot.counters['received_notifications'] += 1
            slot.last_notification_mono = self.clock.monotonic()
            try:
                m = hrs.decode(data)
            except CorruptedData as exc:
                slot.counters['corrupt_packets'] += 1
                slot.error = f'Corrupt HRS packet: {exc.message}'
                return
            regression = slot.last_received_at is not None and received < slot.last_received_at
            if regression:
                slot.counters['clock_regressions'] += 1
            slot.last_received_at = received
            slot.in_gap = False
            slot.seq += 1
            seq = slot.seq
            contact = m.contact
            if contact is False:
                quality = 'no_contact'; slot.contact_state = 'no_contact'; slot.counters['no_contact_samples'] += 1
            elif contact is True:
                quality = 'good'; slot.contact_state = 'contact'
            else:
                quality = 'screened'; slot.contact_state = 'not_reported'
            rec = reg.iso_utc(received)
            base_prov = {'profile': 'HRS', 'contact': contact, 'contact_supported': m.contact_supported,
                         'received_host_utc': rec, 'notification_seq': seq, 'flags': m.flags,
                         'reserved_bits_set': m.reserved_bits_set, 'processing_version': PROCESSING_VERSION}
            if regression:
                base_prov['clock_regression'] = True
            rows = [self._row(slot, f'{slot.session_id}:{seq}:hr', 'heart_rate', float(m.heart_rate_bpm), 'bpm', rec, quality,
                              {**base_prov, 'clock': 'host_receipt', 'hr_format': m.hr_format,
                               'energy_expended_kj': m.energy_expended_kj, 'time_uncertainty_s': BLE_LATENCY_BOUND_S})]
            rr = m.rr_ms
            end = received
            rr_rows = []
            for i in range(len(rr) - 1, -1, -1):     # newest RR ends at receipt; earlier ones are reconstructed backwards
                unc = sum(rr[i + 1:]) / 1000 + BLE_LATENCY_BOUND_S
                rr_rows.append(self._row(slot, f'{slot.session_id}:{seq}:rr{i}', 'rr_interval', rr[i], 'ms', reg.iso_utc(end),
                                         quality, {**base_prov, 'clock': 'receipt-relative beat estimate',
                                                   'conversion': 'raw/1024 s → ms (×1000/1024)', 'rr_raw_1024': m.rr_raw_1024[i],
                                                   'rr_index': i, 'rr_count': len(rr), 'time_uncertainty_s': round(unc, 4)}))
                end = end - timedelta(milliseconds=rr[i])
            rows.extend(reversed(rr_rows))
            slot.counters['hr_samples'] += 1
            slot.counters['rr_samples'] += len(rr)
            slot.last_hr, slot.last_quality = m.heart_rate_bpm, quality
            self._append(slot, rows)
            flush = len(slot.pending) >= FLUSH_ROWS
        if flush:
            self.flush(device_id)

    # ---------------------------------------------------------------- persistence
    def flush(self, device_id: str) -> int:
        """Write pending rows (≤ 500 per atomic batch). On failure the rows stay pending (retried later). Returns rows stored."""
        slot = self._slots.get(device_id)
        if slot is None:
            return 0
        stored = 0
        while True:
            with slot.lock:
                if slot.inflight or not slot.pending:
                    return stored
                batch = slot.pending[:500]
                slot.inflight = True
                ctx = slot.ctx
            try:
                res = self.storage.save_measurements(ctx, batch)
            except Exception as exc:
                with slot.lock:
                    slot.inflight = False
                    slot.counters['storage_failures'] += 1
                    slot.error = f'Storage unavailable; {len(slot.pending)} rows pending ({type(exc).__name__})'
                if self.REVOKE_ON_AUTH_END and getattr(exc, 'status', None) == 401:   # owner signed out / expired / revoked
                    self._revoke(slot, slot.token)
                return stored
            with slot.lock:
                slot.inflight = False
                del slot.pending[:len(batch)]
                slot.counters['stored_rows'] += res.get('saved', 0)
                slot.counters['duplicate_rows'] += res.get('duplicates', 0)
                slot.last_flush_mono = self.clock.monotonic()
                slot.dropped_since_flush = 0
                if slot.error and slot.error.startswith('Storage unavailable'):
                    slot.error = None
                stored += res.get('saved', 0)

    # ---------------------------------------------------------------- link loss / reconnect
    def on_disconnect(self, device_id: str, token: int, reason: str = 'link_lost') -> None:
        slot = self._slots.get(device_id)
        if slot is None:
            return
        with slot.lock:
            if token != slot.token or slot.state is not State.RECORDING:
                return
            slot.state = check(slot.state, State.RECONNECTING)
            slot.handle = None
            slot.error = f'Bluetooth link lost ({reason}); reconnecting automatically'
            self._gap_row(slot, reason)
            slot.reconnect_attempt = 0
        self.flush(device_id)
        self._schedule_reconnect(slot, token)

    def _schedule_reconnect(self, slot, token):
        if slot.reconnect_attempt >= len(self.reconnect_delays):
            self._give_up(slot, token)
            return
        delay = self.reconnect_delays[slot.reconnect_attempt]
        slot.timer = self.scheduler.call_later(delay, lambda: self._reconnect(slot.device_id, token))

    def _reconnect(self, device_id, token):
        slot = self._slots.get(device_id)
        with slot.lock:
            if token != slot.token or slot.state is not State.RECONNECTING:
                return
            slot.reconnect_attempt += 1
            ctx = slot.ctx
        try:
            dev = self._store('get_device', ctx, device_id)
            handle = (slot.transport or self.transport).connect(
                dev['hardware_address'], lambda data: self.on_notification(device_id, token, data),
                lambda reason: self.on_disconnect(device_id, token, reason), self.connect_timeout_s)
        except Exception as exc:
            with slot.lock:
                slot.error = f'Reconnect attempt {slot.reconnect_attempt} failed: {type(exc).__name__}'
            self._schedule_reconnect(slot, token)
            return
        with slot.lock:
            stale = token != slot.token or slot.state is not State.RECONNECTING
            if not stale:
                slot.handle = handle
                slot.state = check(slot.state, State.RECORDING)
                slot.counters['reconnects'] += 1
                slot.error = None
                slot.last_notification_mono = self.clock.monotonic()
        if stale:                                        # user stopped meanwhile: drop the new link
            try:
                (slot.transport or self.transport).disconnect(handle)
            except Exception:
                pass
            return
        self._schedule_tick(slot, token)

    def _give_up(self, slot, token):
        with slot.lock:
            if token != slot.token or slot.state is not State.RECONNECTING:
                return
            slot.state = check(slot.state, State.DISCONNECTING)
            sid = slot.session_id
        self.flush(slot.device_id)
        self._finish(slot, sid, 'saved_after_connection_loss')
        with slot.lock:
            slot.state = check(slot.state, State.DISCONNECTED)
            slot.error = ('Bluetooth link lost; reconnection failed. The recording is stored up to the loss; '
                          'the gap is stored as missing.')

    # ---------------------------------------------------------------- stop / finish
    def disconnect(self, ctx, device_id: str) -> dict:
        dev = self.get(ctx, device_id)
        slot = self._slot(device_id)
        with slot.lock:
            if slot.state not in (State.RECORDING, State.RECONNECTING, State.CONNECTED):
                return {'device_id': device_id, 'connection': CONTRACT_CONNECTION[slot.state],
                        'lifecycle_state': slot.state.value, 'session_id': None, 'stored_samples': 0, 'changed': False}
            self._need(ctx, slot.astronaut_id)
            slot.state = check(slot.state, State.DISCONNECTING)
            slot.token += 1                              # late callbacks of this link are ignored from now on
            handle, slot.handle, sid = slot.handle, None, slot.session_id
            self.scheduler.cancel(slot.timer)
        if handle is not None:
            try:
                (slot.transport or self.transport).disconnect(handle)
            except Exception:
                pass
        self.flush(device_id)
        status = 'saved' if not slot.pending else 'saved_with_unstored_rows'
        self._finish(slot, sid, status)
        with slot.lock:
            slot.state = check(slot.state, State.DISCONNECTED)
        self._store('audit', ctx, 'device.disconnect', 'device', device_id, 'success', {'session_id': sid})
        return {'device_id': device_id, 'connection': 'disconnected', 'lifecycle_state': 'disconnected', 'session_id': sid,
                'stored_samples': slot.counters['stored_rows'], 'pending_rows': len(slot.pending), 'changed': True,
                'session_status': status}

    def _finish(self, slot, sid, status):
        if getattr(slot, 'hardware_address', None) and status != 'connection_failed':
            hw_lock.release(slot.hardware_address, self._hw_owner(slot.device_id))
        if not sid:
            return
        slot.last_session_id, slot.last_session_status = sid, status
        meta = {'counters': dict(slot.counters), 'pending_rows_at_finish': len(slot.pending)}
        try:
            self._store('finish_session', slot.ctx, sid, status, meta)
        except ScienceError as exc:
            slot.error = f'Session could not be finished ({exc.code}); recover_interrupted_sessions will close it'

    def status(self, ctx, device_id: str) -> dict:
        dev = self.get(ctx, device_id)
        slot = self._slot(device_id)
        with slot.lock:
            age = None if slot.last_notification_mono is None or slot.state is State.DISCONNECTED else \
                round(self.clock.monotonic() - slot.last_notification_mono, 3)
            c = dict(slot.counters)
            return {'device_id': device_id, 'connection': CONTRACT_CONNECTION[slot.state], 'lifecycle_state': slot.state.value,
                    'session_id': slot.session_id, 'astronaut_id': slot.astronaut_id if slot.state in ACTIVE else dev.get('astronaut_id'),
                    'last_sample_at': reg.iso_utc(slot.last_received_at) if slot.last_received_at else None,
                    'last_sample_age_seconds': age,
                    # never present the last value as current once the stream is stale (> STALE_S without packets)
                    'heart_rate': slot.last_hr if slot.last_quality in ('good', 'screened') and not slot.in_gap
                    and slot.state is State.RECORDING and age is not None and age <= STALE_S else None,
                    'stale': slot.state is State.RECORDING and age is not None and age > STALE_S,
                    'quality': ('unavailable' if slot.state not in (State.RECORDING,) else 'no_contact' if slot.contact_state == 'no_contact'
                                else 'missing' if slot.in_gap else slot.last_quality or 'awaiting_measurements'),
                    'contact_state': slot.contact_state, 'rr_available': c['rr_samples'] > 0,
                    'received_samples': c['received_notifications'], 'stored_samples': c['stored_rows'],
                    'pending_rows': len(slot.pending), 'dropped_rows': c['dropped_rows'], 'duplicate_rows': c['duplicate_rows'],
                    'reconnect_attempt': slot.reconnect_attempt if slot.state is State.RECONNECTING else 0,
                    'reconnects': c['reconnects'], 'gaps': c['gaps'], 'corrupt_packets': c['corrupt_packets'],
                    'no_contact_samples': c['no_contact_samples'], 'storage_failures': c['storage_failures'],
                    'clock_regressions': c['clock_regressions'],
                    'duration_seconds': round(self.clock.monotonic() - slot.started_mono) if slot.started_mono and slot.state in ACTIVE else 0,
                    'max_unsaved_rows_normal': FLUSH_ROWS - 1, 'max_unsaved_interval_s': FLUSH_INTERVAL_S + TICK_S,
                    'hardware_validation': 'unverified', 'error': slot.error,
                    # 1.5 personal UI fields (server-derived; the client never supplies them)
                    'data_class': slot.data_class if slot.transport is not None else None,
                    'simulated': slot.data_class != 'real_wearable' if slot.transport is not None else None,
                    'hrs_verified': slot.hrs_verified, 'revoked': slot.revoked,
                    'phase': self._phase(slot, age, c),
                    'stale_after_seconds': STALE_S,
                    'last_session_id': slot.last_session_id, 'last_session_status': slot.last_session_status}

    @staticmethod
    def _phase(slot, age, c) -> str:
        """One UI phase per moment. 'connected_awaiting' ≠ 'receiving': a link without notifications is never 'live'."""
        if slot.revoked:
            return 'revoked'
        if slot.state is State.CONNECTING:
            return 'connecting'
        if slot.state is State.RECONNECTING:
            return 'reconnecting'
        if slot.state is State.DISCONNECTING:
            return 'saving'
        if slot.state in (State.CONNECTED, State.RECORDING):
            if c['received_notifications'] == 0:
                return 'connected_awaiting'
            if slot.contact_state == 'no_contact':
                return 'no_contact'
            if slot.in_gap or (age is not None and age > STALE_S):
                return 'signal_lost'
            return 'receiving'
        if slot.state is State.CONNECTION_FAILED:
            return 'connection_failed'
        if slot.state is State.UNAVAILABLE:
            return 'unavailable'
        return 'saved' if slot.last_session_id else 'idle'

    # ---------------------------------------------------------------- owner session validity / sign-out
    @staticmethod
    def _owner_valid(slot) -> bool:
        ctx = slot.ctx
        if ctx is None:
            return False
        try:
            probe = getattr(type(ctx), 'user', None)
            if isinstance(probe, property):
                ctx.user                                  # Be2Context: re-validates the Bearer session
            return True
        except ScienceError as exc:
            return exc.status != 401
        except Exception:
            return True                                  # transient storage errors are handled by flush()

    def _revoke(self, slot, token) -> None:
        """Stop a recording whose owner is no longer signed in. Nothing is written with another identity."""
        with slot.lock:
            if token != slot.token or slot.state not in ACTIVE:
                return
            if slot.state is not State.DISCONNECTING:
                slot.state = check(slot.state, State.DISCONNECTING)
            slot.token += 1
            handle, slot.handle = slot.handle, None
            self.scheduler.cancel(slot.timer)
            lost = len(slot.pending)
            slot.counters['dropped_rows'] += lost
            slot.pending = []
            slot.revoked = True
            slot.error = REVOKED_MESSAGE + (f' {lost} unsaved row(s) were discarded.' if lost else '')
            slot.last_session_id, slot.last_session_status = slot.session_id, 'interrupted'
            slot.ctx = None
            transport = slot.transport or self.transport
        if handle is not None:
            try:
                transport.disconnect(handle)
            except Exception:
                pass
        if slot.hardware_address:
            hw_lock.release(slot.hardware_address, self._hw_owner(slot.device_id))
        with slot.lock:
            slot.state = check(slot.state, State.DISCONNECTED)

    def stop_for_token(self, token: str) -> list[dict]:
        """Called by the logout route BEFORE the personal session is revoked: every recording started with this token
        is stopped at once. Pending rows are flushed while the token is still valid, the strap is released, and the
        production manager closes the session as 'failed' (reason personal_session_expired_or_revoked) — the BE2_06
        contract for a recording whose personal session ended; all committed rows are kept."""
        import hmac
        out = []
        with self._lock:
            slots = list(self._slots.values())
        for slot in slots:
            ctx = slot.ctx
            own = getattr(ctx, '_token', None)
            if slot.state in ACTIVE and isinstance(own, str) and isinstance(token, str) and hmac.compare_digest(own, token):
                if not self.REVOKE_ON_AUTH_END:
                    try:
                        out.append(self.disconnect(ctx, slot.device_id))
                        continue
                    except ScienceError:
                        pass
                self.flush(slot.device_id)
                sid = slot.session_id
                self._revoke(slot, slot.token)
                out.append({'device_id': slot.device_id, 'session_id': sid, 'session_status': slot.last_session_status})
        return out

    def active_for(self, ctx) -> list[dict]:
        """Statuses of active recordings that belong to the caller (used to restore the UI after a reload)."""
        uid = getattr(ctx, 'user_id', None)
        with self._lock:
            ids = [s.device_id for s in self._slots.values()
                   if s.state in ACTIVE and s.ctx is not None and getattr(s.ctx, 'user_id', None) == uid]
        out = []
        for did in ids:
            try:
                out.append(self.status(ctx, did))
            except ScienceError:
                continue
        return out

    # ---------------------------------------------------------------- crash recovery / shutdown
    def recover_interrupted_sessions(self, ctx, device_id: str | None = None) -> list[str]:
        """Close live-sensor sessions left 'recording' by a crashed or killed process.

        Works with the OWNER's context (Backend №2 has no system context): it is called automatically before every
        connect for that device, and may be called at startup with a server-internal context if Backend №2 provides
        one. Only sessions visible to `ctx` are touched; data stored before the crash are kept, nothing is added."""
        closed = []
        system_ctx = ctx
        for s in self._store('list_sessions', system_ctx, 'recording'):
            if s.get('source_type') != 'live_sensor' or (device_id is not None and s.get('device_id') != device_id):
                continue
            with self._lock:
                live = any(sl.session_id == s['session_id'] and sl.state in ACTIVE for sl in self._slots.values())
            if live:
                continue
            self._store('finish_session', system_ctx, s['session_id'], 'interrupted',
                        {'recovered_at': reg.iso_utc(self.clock.now()),
                         'reason': 'process ended while recording; data stored before the crash are kept, nothing was added'})
            closed.append(s['session_id'])
        if closed:
            self._store('audit', system_ctx, 'device.sessions_recovered', 'sensor_session', closed[0], 'success',
                        {'sessions': closed})
        return closed

    def shutdown(self) -> None:
        self._closed = True
        with self._lock:
            slots = list(self._slots.values())
        for slot in slots:
            with slot.lock:
                if slot.state not in ACTIVE:
                    continue
                if slot.state is not State.DISCONNECTING:
                    slot.state = check(slot.state, State.DISCONNECTING)
                slot.token += 1
                handle, slot.handle, sid = slot.handle, None, slot.session_id
                self.scheduler.cancel(slot.timer)
            if handle is not None:
                try:
                    (slot.transport or self.transport).disconnect(handle)
                except Exception:
                    pass
            self.flush(slot.device_id)
            self._finish(slot, sid, 'saved_on_shutdown')
            with slot.lock:
                slot.state = check(slot.state, State.DISCONNECTED)


def _check_id(device_id):
    identity.validate_object_id(device_id, 'device_id')


__all__ = ['DeviceManager', 'NotFound', 'FLUSH_ROWS', 'FLUSH_INTERVAL_S', 'STALE_S', 'MAX_PENDING_ROWS']
