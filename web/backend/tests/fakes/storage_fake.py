"""In-memory (optionally JSON-file backed) fake of the Backend №2 storage API — API Contract 1.5 §2.3.

FOR TESTS ONLY. It is never imported by application code. It reproduces the agreed behaviour so that Backend №3
modules can be tested before `app/storage` exists:

* access isolation: every call checks ctx.can(permission, astronaut_id) and raises Forbidden;
* atomic batches: a batch with one invalid item stores nothing;
* idempotency: (astronaut_id, client_measurement_id) is stored once; replays are counted as duplicates;
* sessions: create / finish, finished sessions cannot receive measurements;
* analyses, devices, record log and audit log;
* failure injection (`fail_next`) to test that callers do not lose or duplicate data;
* `path=` persists everything to a JSON file, so a new FakeStorage(path) behaves like a restarted server.

Backend №2's real implementation must pass tests/test_storage_fake_15.py when FakeStorage is replaced by it
(see INTEGRATION_REQUESTS.md IR-2).
"""
from __future__ import annotations

import copy
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app import signals
from app.science_errors import Conflict, Forbidden, InvalidInput, NotFound, StorageUnavailable


@dataclass(frozen=True)
class FakeContext:
    user_id: str | None = 'u' * 32
    role: str | None = 'crew'
    auth_mode: str = 'required'
    astronaut_ids: frozenset = field(default_factory=frozenset)
    mission_ids: frozenset = field(default_factory=frozenset)

    def can(self, permission: str, astronaut_id: str | None = None, mission_id: str | None = None) -> bool:
        if self.role == 'admin':
            return True
        if astronaut_id is None:
            return self.role is not None
        return astronaut_id in self.astronaut_ids


def _now() -> str:
    return signals.iso_utc(datetime.now(timezone.utc))


class FakeStorage:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.lock = threading.RLock()
        self.fail_next: str | None = None          # name of the next method that must raise StorageUnavailable
        self.calls: list[str] = []
        self.db = {'measurements': {}, 'keys': {}, 'sessions': {}, 'analyses': {}, 'devices': {}, 'records': [], 'audit': []}
        if self.path and self.path.exists():
            self.db = json.loads(self.path.read_text(encoding='utf-8'))

    # ------------------------------------------------------------------ helpers
    def _enter(self, name: str):
        self.calls.append(name)
        if self.fail_next == name:
            self.fail_next = None
            raise StorageUnavailable(f'storage unavailable during {name} (injected)')

    def _flush(self):
        if self.path:
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.db), encoding='utf-8')
            tmp.replace(self.path)            # atomic replace: a crash never leaves half a file

    @staticmethod
    def _need(ctx, permission, astronaut_id):
        if not ctx.can(permission, astronaut_id):
            raise Forbidden(f'No access to astronaut {astronaut_id}')

    # ------------------------------------------------------------------ measurements
    def save_measurements(self, ctx, items: list[dict]) -> dict:
        with self.lock:
            self._enter('save_measurements')
            if not isinstance(items, list) or not 1 <= len(items) <= 500:
                raise InvalidInput('items must contain 1–500 measurements', field='items')
            normalised = [signals.validate_item(it, i) for i, it in enumerate(items)]   # raises → nothing stored
            for i, it in enumerate(normalised):
                self._need(ctx, 'measurement:write', it['astronaut_id'])
                sid = it.get('session_id')
                if sid:
                    s = self.db['sessions'].get(sid)
                    if s is None:
                        raise NotFound(f'Unknown session {sid}', field=f'items[{i}].session_id')
                    if s['astronaut_id'] != it['astronaut_id']:
                        raise Forbidden('Session belongs to another astronaut', field=f'items[{i}].session_id')
                    if s['status'] != 'recording':
                        raise Conflict(f'Session {sid} is {s["status"]}; it no longer accepts measurements')
            # 03A (conformance suite): Backend №2 inserts a batch in ONE transaction — a conflicting row anywhere in the
            # batch stores nothing. Check every key first, then write.
            for it in normalised:
                key = f"{it['astronaut_id']}|{it.get('client_measurement_id')}" if it.get('client_measurement_id') else None
                if key and key in self.db['keys']:
                    old = self.db['measurements'][self.db['keys'][key]]
                    same = all(old.get(f) == it.get(f) for f in ('signal', 'value', 'unit', 'recorded_at', 'quality',
                                                                 'data_class', 'session_id', 'device_id', 'mission_id'))
                    if not same or (old.get('provenance') or {}) != (it.get('provenance') or {}):
                        raise Conflict('Idempotency key was used with different content', code='idempotency_conflict')
            saved, dup, out = 0, 0, []
            for it in normalised:
                key = f"{it['astronaut_id']}|{it.get('client_measurement_id')}" if it.get('client_measurement_id') else None
                if key and key in self.db['keys']:
                    old = self.db['measurements'][self.db['keys'][key]]
                    same = all(old.get(f) == it.get(f) for f in ('signal', 'value', 'unit', 'recorded_at', 'quality',
                                                                 'data_class', 'session_id', 'device_id', 'mission_id'))
                    if not same or (old.get('provenance') or {}) != (it.get('provenance') or {}):
                        # Backend №2 raw_measurements behaviour: same key + different content → 409
                        raise Conflict('Idempotency key was used with different content', code='idempotency_conflict')
                    dup += 1
                    out.append(copy.deepcopy(old))
                    continue
                mid = uuid.uuid4().hex
                rec = {'measurement_id': mid, 'client_measurement_id': it.get('client_measurement_id'),
                       'astronaut_id': it['astronaut_id'], 'mission_id': it.get('mission_id'), 'session_id': it.get('session_id'),
                       'device_id': it.get('device_id'), 'signal': it['signal'], 'value': it['value'], 'unit': it['unit'],
                       'recorded_at': it['recorded_at'], 'received_at': _now(), 'original_timestamp': it.get('original_timestamp'),
                       'timezone': it.get('timezone'), 'mission_day': it.get('mission_day'), 'sampling_hz': it.get('sampling_hz'),
                       'quality': it['quality'], 'valid': it['valid'], 'missing': it['missing'], 'data_class': it['data_class'],
                       'source': it['source'], 'provenance': it.get('provenance') or {}, 'processing_version': 'fake-storage',
                       'created_by': ctx.user_id, 'status': 'active', 'invalidated_reason': None}
                self.db['measurements'][mid] = rec
                if key:
                    self.db['keys'][key] = mid
                saved += 1
                out.append(copy.deepcopy(rec))
            rid = self.log_record(ctx, 'measurement_batch', [r['measurement_id'] for r in out], normalised[0]['astronaut_id'],
                                  normalised[0]['data_class'], f'{saved} measurements ({dup} duplicates)')
            self._flush()
            return {'saved': saved, 'duplicates': dup, 'items': out, 'record_id': rid}

    def query_measurements(self, ctx, astronaut_id: str, signals_: list[str] | None = None, start: str | None = None,
                           end: str | None = None, session_id: str | None = None, include_invalid: bool = False,
                           limit: int = 1000, cursor: str | None = None, **kw) -> dict:
        signals_ = kw.pop('signals', signals_)
        with self.lock:
            self._enter('query_measurements')
            self._need(ctx, 'measurement:read', astronaut_id)
            t0 = signals.parse_utc(start, 'from') if start else None
            t1 = signals.parse_utc(end, 'to') if end else None
            rows = []
            for r in self.db['measurements'].values():
                if r['astronaut_id'] != astronaut_id:
                    continue
                if signals_ and r['signal'] not in signals_:
                    continue
                if session_id and r['session_id'] != session_id:
                    continue
                if not include_invalid and r['status'] != 'active':
                    continue
                if kw.get('mission_id') and r.get('mission_id') != kw['mission_id']:
                    continue
                if t0 or t1:
                    if r['recorded_at'] is None:
                        continue
                    t = signals.parse_utc(r['recorded_at'])
                    if (t0 and t < t0) or (t1 and t >= t1):
                        continue
                rows.append(r)
            rows.sort(key=lambda r: (r['recorded_at'] or '', r['measurement_id']))
            off = int(cursor or 0)
            page = rows[off:off + limit]
            nxt = str(off + limit) if off + limit < len(rows) else None
            return {'items': copy.deepcopy(page), 'next_cursor': nxt}

    def invalidate(self, ctx, measurement_id: str, reason: str) -> dict:
        with self.lock:
            r = self.db['measurements'].get(measurement_id)
            if r is None:
                raise NotFound('Unknown measurement')
            self._need(ctx, 'measurement:write', r['astronaut_id'])
            if r['status'] == 'invalidated':
                raise Conflict('Already invalidated')
            r.update(status='invalidated', invalidated_reason=reason)
            self._flush()
            return copy.deepcopy(r)

    # ------------------------------------------------------------------ sessions
    def create_session(self, ctx, astronaut_id, source_type, source, device_id=None, mission_id=None, metadata=None) -> str:
        with self.lock:
            self._enter('create_session')
            if astronaut_id is not None:
                self._need(ctx, 'measurement:write', astronaut_id)
            sid = uuid.uuid4().hex
            self.db['sessions'][sid] = {'session_id': sid, 'astronaut_id': astronaut_id, 'source_type': source_type,
                                        'source': source, 'device_id': device_id, 'mission_id': mission_id,
                                        'metadata': metadata or {}, 'status': 'recording', 'created_at': _now(),
                                        'finished_at': None, 'created_by': ctx.user_id}
            self._flush()
            return sid

    def finish_session(self, ctx, session_id, status, metadata=None) -> None:
        with self.lock:
            self._enter('finish_session')
            s = self.db['sessions'].get(session_id)
            if s is None:
                raise NotFound('Unknown session')
            s.update(status=status, finished_at=_now())
            if metadata:
                s['metadata'] = {**s['metadata'], **metadata}
            self._flush()

    def get_session(self, ctx, session_id) -> dict:
        s = self.db['sessions'].get(session_id)
        if s is None:
            raise NotFound('Unknown session')
        if s['astronaut_id']:
            self._need(ctx, 'measurement:read', s['astronaut_id'])
        return copy.deepcopy(s)

    def list_sessions(self, ctx, status: str | None = None) -> list[dict]:
        """Amendment A-3 (not yet in contract §2.3): needed for crash recovery of 'recording' sessions."""
        return [copy.deepcopy(s) for s in self.db['sessions'].values()
                if (status is None or s['status'] == status) and (s['astronaut_id'] is None or ctx.can('measurement:read', s['astronaut_id']))]

    # ------------------------------------------------------------------ analyses
    def save_analysis(self, ctx, kind, astronaut_id, payload) -> str:
        with self.lock:
            self._enter('save_analysis')
            self._need(ctx, 'phantom:run', astronaut_id)
            aid = payload.get('analysis_id') or uuid.uuid4().hex
            self.db['analyses'][aid] = {'analysis_id': aid, 'kind': kind, 'astronaut_id': astronaut_id,
                                        'created_at': payload.get('created_at') or _now(), 'created_by': ctx.user_id,
                                        'payload': copy.deepcopy({**payload, 'analysis_id': aid})}
            self._flush()
            return aid

    def save_analysis_bundle(self, ctx, kind, astronaut_id, payload, *, record: dict, audit: dict, idempotency_key: str,
                             input_ids: list | None = None) -> dict:
        """Amendment A-11 / IR-11: analysis + history record + audit event in ONE transaction, idempotent on
        `idempotency_key` (= analysis_id). Returns {'analysis_id', 'created', 'record_id', 'payload'}.
        Failure points for tests (`fail_next`): 'save_analysis_bundle' (before anything), 'bundle:after_analysis',
        'bundle:after_record' (both roll back), 'bundle:after_commit' (data committed, then the call fails — lost ack)."""
        with self.lock:
            self._enter('save_analysis_bundle')
            self._need(ctx, 'phantom:run', astronaut_id)
            if not isinstance(idempotency_key, str) or len(idempotency_key) != 32:
                raise InvalidInput('idempotency_key must be 32 hex characters')
            existing = self.db['analyses'].get(idempotency_key)
            if existing is not None:
                if existing['astronaut_id'] != astronaut_id:
                    raise Conflict('idempotency_key already used for another astronaut')
                volatile = ('analysis_id', 'created_at', 'created_by', 'idempotent_replay', 'idempotency_key')
                if {k: v for k, v in existing['payload'].items() if k not in volatile} != \
                        {k: v for k, v in payload.items() if k not in volatile}:
                    raise Conflict('Analysis key already used with different content', code='idempotency_conflict')
                return {'analysis_id': idempotency_key, 'created': False, 'record_id': existing.get('record_id'),
                        'payload': copy.deepcopy(existing['payload'])}
            snapshot = copy.deepcopy(self.db)
            try:
                self.db['analyses'][idempotency_key] = {
                    'analysis_id': idempotency_key, 'kind': kind, 'astronaut_id': astronaut_id,
                    'created_at': payload.get('created_at') or _now(), 'created_by': ctx.user_id,
                    'payload': copy.deepcopy({**payload, 'analysis_id': idempotency_key})}
                self._enter('bundle:after_analysis')
                rid = self.log_record(ctx, record['kind'], record['ref_ids'], record['astronaut_id'], record['data_class'],
                                      record['summary'])
                self.db['analyses'][idempotency_key]['record_id'] = rid
                self._enter('bundle:after_record')
                self.audit(ctx, audit['action'], audit['target_kind'], audit['target_id'], audit['outcome'], audit.get('details'))
            except Exception:
                self.db = snapshot                    # rollback: nothing of the three is visible
                raise
            self._flush()                             # commit
            self._enter('bundle:after_commit')
            return {'analysis_id': idempotency_key, 'created': True, 'record_id': rid,
                    'payload': copy.deepcopy(self.db['analyses'][idempotency_key]['payload'])}

    def get_analysis(self, ctx, analysis_id) -> dict:
        with self.lock:
            self._enter('get_analysis')
            a = self.db['analyses'].get(analysis_id)
            if a is None:
                raise NotFound('Unknown analysis')
            self._need(ctx, 'measurement:read', a['astronaut_id'])
            return copy.deepcopy(a['payload'])

    def list_analyses(self, ctx, astronaut_id=None, kind=None, limit=100, cursor=None) -> dict:
        with self.lock:
            self._enter('list_analyses')
            if astronaut_id:
                self._need(ctx, 'measurement:read', astronaut_id)
            rows = [a for a in self.db['analyses'].values()
                    if (astronaut_id is None or a['astronaut_id'] == astronaut_id) and (kind is None or a['kind'] == kind)
                    and ctx.can('measurement:read', a['astronaut_id'])]
            rows.sort(key=lambda a: (a['created_at'], a['analysis_id']), reverse=True)   # stable total order
            off = int(cursor or 0)
            page = rows[off:off + limit]
            return {'items': [copy.deepcopy(a['payload']) for a in page],
                    'next_cursor': str(off + limit) if off + limit < len(rows) else None}

    # ------------------------------------------------------------------ devices
    def upsert_device(self, ctx, device: dict) -> dict:
        with self.lock:
            self._enter('upsert_device')
            if device.get('astronaut_id'):
                self._need(ctx, 'device:use', device['astronaut_id'])
            did = device.get('device_id') or uuid.uuid4().hex
            for other in self.db['devices'].values():
                # Backend №2 devices: UNIQUE(astronaut_id, external_id) — the same strap may be registered by two
                # astronauts; the Device Manager's hardware lock prevents simultaneous use.
                if (other['hardware_address'] == device.get('hardware_address') and other['device_id'] != did
                        and other.get('astronaut_id') == device.get('astronaut_id') and not other.get('removed')):
                    raise Conflict('Hardware address already registered', code='device_already_registered')
            rec = {**self.db['devices'].get(did, {}), **device, 'device_id': did}
            rec.setdefault('created_at', _now())
            self.db['devices'][did] = rec
            self._flush()
            return copy.deepcopy(rec)

    def touch_device(self, ctx, device_id, last_seen_at) -> None:
        d = self.db['devices'].get(device_id)
        if d is not None:
            d['last_seen_at'] = last_seen_at
            self._flush()

    def get_device(self, ctx, device_id) -> dict:
        d = self.db['devices'].get(device_id)
        if d is None or d.get('removed'):
            raise NotFound('Unknown device')
        if d.get('astronaut_id'):
            self._need(ctx, 'device:use', d['astronaut_id'])
        return copy.deepcopy(d)

    def list_devices(self, ctx, astronaut_id=None) -> list[dict]:
        return [copy.deepcopy(d) for d in self.db['devices'].values() if not d.get('removed')
                and (astronaut_id is None or d.get('astronaut_id') == astronaut_id)
                and (d.get('astronaut_id') is None or ctx.can('device:use', d['astronaut_id']))]

    # ------------------------------------------------------------------ history / audit
    def log_record(self, ctx, kind, ref_ids, astronaut_id, data_class, summary) -> str:
        rid = uuid.uuid4().hex
        self.db['records'].append({'record_id': rid, 'kind': kind, 'ref_ids': list(ref_ids), 'astronaut_id': astronaut_id,
                                   'data_class': data_class, 'summary': summary, 'created_at': _now(), 'created_by': ctx.user_id})
        return rid

    def audit(self, ctx, action, target_kind, target_id, outcome, details=None) -> None:
        details = details or {}
        assert not any(k in details for k in ('password', 'token', 'access_token')), 'secrets must never reach the audit log'
        self.db['audit'].append({'event_id': uuid.uuid4().hex, 'at': _now(), 'actor_user_id': ctx.user_id, 'action': action,
                                 'target_kind': target_kind, 'target_id': target_id, 'outcome': outcome, 'details': details})
