"""Science storage adapter over Backend №2's REAL persistence (app.persistence.repository + app.auth + app.access_control).

Owner: Backend №3 (package 03A). It does not modify app.persistence, writes no SQL into Backend №2 tables and creates no
second database: every read and write goes through Backend №2's public repository functions, which perform the
object-level authorisation (access_control.profile) inside their own transactions.

Mapping (details: docs/BACKEND_STORAGE_COMPATIBILITY.md, docs/SIGNAL_COMPATIBILITY_MATRIX.md)
    BE3 protocol                       Backend №2 function
    save_measurements                  repository.add_measurements   (one transaction, idempotency_key, 409 on changed payload)
    query_measurements                 repository.list_measurements  (seq cursor `after`, ≤ 500 per page; end made exclusive here)
    create_session / finish_session    repository.create_session / close_session
    get_session / list_sessions        repository.list_devices + device_sessions (owner's devices)
    upsert_device (create only)        repository.create_device      (kind 'ble', external_id = hardware address)
    get_device / list_devices          repository.list_devices        (owner only)
    save_analysis_bundle               repository.save_analysis      (analysis_runs + processed + audit in ONE transaction)
    get_analysis / list_analyses       repository.get_analysis / list_records('analysis_runs'), filtered to PHANTOM models
    audit                              persistence.common.audit       (whitelisted fields only; details are not stored)
    log_record                         no-op: Backend №2's history IS raw_measurements / sensor_sessions / analysis_runs

Known gaps that need Backend №2 (BE2_REQUIRED_CHANGES.md): session end status/metadata, device update/delete/touch,
input_ids > 5000, result > 128 KB, a delegated device-writer credential for recordings longer than the token TTL.
"""
from __future__ import annotations

import json
import math
import sqlite3

from pydantic import ValidationError

from . import identity, signal_compat
from . import signals as reg
from .science_errors import (Conflict, Forbidden, InvalidInput, NotFound, ScienceError, StorageUnavailable,
                             Unauthenticated)

ADAPTER_VERSION = 'be3-be2-adapter-1.5.1'
PHANTOM_MODELS = ('phantom_hr_univariate_1_4',)
VOLATILE = ('analysis_id', 'created_at', 'idempotent_replay', 'idempotency_key')
BE2_INPUT_IDS_MAX = 5000
BE2_RESULT_MAX = 128000
BE2_PAGE_MAX = 500
SOURCE_TYPE_TO_ORIGIN = {'live_sensor': 'real', 'manual': 'manual', 'simulated_demo': 'simulated'}
ORIGIN_TO_SOURCE_TYPE = {'real': 'live_sensor', 'manual': 'manual', 'simulated': 'simulated_demo', 'research': 'research'}


def _be2():
    from app import auth, db                                    # imported lazily: optional dependency (argon2)
    from app import access_control as acl
    from app import schemas_15
    from app.persistence import common, repository
    return auth, db, acl, schemas_15, common, repository


class Be2Error(ScienceError):
    """A Backend №2 APIError carried through unchanged (status, code, detail)."""
    category = 'backend2'

    def __init__(self, status, code, detail):
        super().__init__(detail, code=code, status=status)


def _call(fn, *args, **kw):
    _, _, _, _, common, _ = _be2()
    try:
        return fn(*args, **kw)
    except ScienceError:
        raise
    except common.APIError as exc:
        raise Be2Error(exc.status, exc.code, exc.detail) from None
    except ValidationError as exc:
        e = exc.errors(include_input=False, include_url=False, include_context=False)[0] if exc.errors() else {}
        raise InvalidInput(f"Backend №2 validation failed: {e.get('msg', 'invalid')}",
                           field='.'.join(str(x) for x in e.get('loc', ())) or None) from None
    except sqlite3.OperationalError as exc:
        raise StorageUnavailable(f'Backend №2 storage unavailable ({type(exc).__name__})') from None


class Be2Context:
    """RequestContext for the scientific modules, backed by a Backend №2 personal session token.

    The token is re-validated on EVERY call (expiry, idle timeout, revocation, deactivated account). Permissions are
    decided by Backend №2's access_control.profile — the owner may write; a medical officer may read only with an
    explicit medical_access grant for the given mission; an administrator is NOT a medical superuser. There is no
    system context and none can be created from request data."""

    def __init__(self, token: str):
        self._token = token
        self.user                                               # validate now → 401 early

    def __repr__(self):
        return 'Be2Context(<redacted>)'

    @property
    def user(self) -> dict:
        auth, *_ = _be2()
        try:
            return _call(auth.authenticate, self._token)
        except Be2Error as exc:
            raise Unauthenticated(exc.message) from None

    @property
    def user_id(self):
        return self.user['id']

    @property
    def role(self):
        return self.user['role']

    @property
    def astronaut_id(self):
        return self.user['astronaut_id']

    auth_mode = 'required'

    def can(self, permission: str, astronaut_id: str | None = None, mission_id: str | None = None) -> bool:
        _, db, acl, _, common, _ = _be2()
        user = self.user
        write = permission in ('measurement:write', 'device:use', 'phantom:run')
        if astronaut_id is not None and identity.astronaut_kind(astronaut_id) != identity.PERSONAL:
            return False                                        # demo ids are never personal profiles
        try:
            with db.connect() as c:
                acl.profile(c, user, astronaut_id, write=write, mission_id=mission_id)
            return True
        except common.APIError:
            return False


def _iso(v):
    return reg.iso_utc(reg.parse_utc(v)) if v else None


def from_be2_row(r: dict) -> dict:
    """Backend №2 raw_measurements row → BE3 canonical measurement (explicit, never upgrading)."""
    md = dict(r.get('metadata') or {})
    value = r.get('value')
    signal, unit = r.get('signal'), r.get('unit')
    status = 'active'
    try:
        signal, unit, value, md = signal_compat.normalise_signal(signal, unit, value, md, reg.OPERATIONAL)
    except ScienceError:
        status = 'unsupported_signal'                           # kept visible, never analysed
    data_class = signal_compat.from_be2_data_class(r.get('origin'), md)
    quality = signal_compat.from_be2_quality(r.get('quality'), value, md)
    finite = value is not None and isinstance(value, (int, float)) and math.isfinite(float(value))
    md.setdefault('be2_quality', r.get('quality'))
    md.setdefault('be2_origin', r.get('origin'))
    return {'measurement_id': r['id'], 'client_measurement_id': md.get('client_measurement_id'),
            'astronaut_id': r['astronaut_id'], 'mission_id': r.get('mission_id'), 'session_id': r.get('session_id'),
            'device_id': r.get('device_id'), 'signal': signal, 'value': float(value) if finite else None, 'unit': unit,
            'recorded_at': _iso(r.get('measured_at')), 'received_at': _iso(r.get('received_at')),
            'quality': quality, 'valid': finite and quality in reg.VALID_QUALITY, 'missing': value is None,
            'data_class': data_class, 'source': r.get('source'), 'provenance': md,
            'processing_version': r.get('processing_version'), 'status': status,
            'supersedes_id': r.get('supersedes_id')}


def to_be2_item(n: dict) -> dict:
    """Validated BE3 measurement (signals.validate_item output) → Backend №2 MeasurementCreate payload."""
    origin = signal_compat.to_be2_origin(n['data_class'])
    if not n.get('client_measurement_id'):
        raise InvalidInput('client_measurement_id is required (it becomes Backend №2 idempotency_key)',
                           field='client_measurement_id')
    if n.get('recorded_at') is None:
        raise InvalidInput('Backend №2 requires measured_at; rows without a UTC time cannot be stored', field='recorded_at')
    q = signal_compat.to_be2_quality(n['quality'])
    md = dict(n.get('provenance') or {})
    value = n['value']
    lo, hi = signal_compat.BE2_STORAGE[n['signal']][1:]
    if value is not None and not lo <= value <= hi:
        # Backend №2 refuses values outside its storage range; never clip: keep the original, store a null value.
        md['original_value'] = value
        md['storage_note'] = f'value outside Backend №2 storage range {lo}–{hi}; stored as null, flagged rejected'
        value, q = None, 'rejected'
    md.update(data_class=n['data_class'], be3_quality=n['quality'] if value is not None else
              ('out_of_range' if 'original_value' in md else n['quality']), client_measurement_id=n['client_measurement_id'])
    if value is None and q not in ('rejected', 'corrupt', 'no_contact', 'connection_lost'):
        q = 'connection_lost'
    return {'idempotency_key': n['client_measurement_id'], 'source': n['source'], 'signal': n['signal'], 'value': value,
            'unit': n['unit'], 'measured_at': n['recorded_at'], 'origin': origin, 'quality': q,
            'processing_version': (n.get('provenance') or {}).get('processing_version') or ADAPTER_VERSION,
            'metadata': md, 'astronaut_id': n['astronaut_id'], 'mission_id': n.get('mission_id'),
            'device_id': n.get('device_id'), 'session_id': n.get('session_id')}


def device_from_be2(d: dict) -> dict:
    ble = d.get('kind') == 'ble'
    return {'device_id': d['id'], 'astronaut_id': d['astronaut_id'], 'name': d['name'],
            'kind': 'ble_hrs' if ble else d.get('kind'), 'hardware_address': d.get('external_id'),
            'created_at': d.get('created_at'), 'registry': 'backend2', 'profile': 'Bluetooth SIG Heart Rate Service (0x180D / 0x2A37)' if ble else None,
            'support_status': 'automated_tested' if ble else 'unsupported', 'hardware_verified': False,
            'signals': ['heart_rate', 'rr_interval'] if ble else [], 'last_seen_at': None}


class Be2ScienceStorage:
    """Implements app.science_storage.REQUIRED on Backend №2. ctx must be a Be2Context."""

    def __init__(self):
        _be2()                                                  # fail at construction if Backend №2 is absent
        self.finished_status: dict[str, str] = {}               # see BE2_REQUIRED_CHANGES R-3 (no status column)

    @staticmethod
    def _user(ctx) -> dict:
        if not isinstance(ctx, Be2Context):
            raise Unauthenticated('A Backend №2 personal session is required')
        return ctx.user

    # ------------------------------------------------------------------ measurements
    def save_measurements(self, ctx, items: list[dict]) -> dict:
        *_, repo = _be2()
        user = self._user(ctx)
        if not isinstance(items, list) or not 1 <= len(items) <= 500:
            raise InvalidInput('items must contain 1–500 measurements', field='items')
        payload = [to_be2_item(reg.validate_item(it, i)) for i, it in enumerate(items)]
        try:
            res = _call(repo.add_measurements, user, payload)
        except Be2Error as exc:
            if exc.code == 'idempotency_conflict':
                raise Conflict(exc.message, code='idempotency_conflict') from None
            raise
        out = [from_be2_row(r['measurement']) for r in res]
        saved = sum(1 for r in res if r['created'])
        return {'saved': saved, 'duplicates': len(res) - saved, 'items': out, 'record_id': None}

    def query_measurements(self, ctx, astronaut_id, signals=None, start=None, end=None, session_id=None,
                           include_invalid=False, limit=1000, cursor=None, mission_id=None, **_ignored) -> dict:
        _, _, _, s, _, repo = _be2()
        user = self._user(ctx)
        identity.validate_astronaut_id(astronaut_id)
        q = {'astronaut_id': astronaut_id, 'mission_id': mission_id, 'session_id': session_id,
             'signal': signals[0] if signals and len(signals) == 1 and signals[0] in signal_compat.BE2_STORAGE else None,
             'start': start, 'end': end, 'limit': min(int(limit or BE2_PAGE_MAX), BE2_PAGE_MAX),
             'after': int(cursor or 0)}
        hq = _call(s.HistoryQuery.model_validate, {k: v for k, v in q.items() if v is not None})
        page = _call(repo.list_measurements, user, hq)
        end_dt = reg.parse_utc(end) if end else None
        items = []
        for r in page['items']:
            m = from_be2_row(r)
            if signals and m['signal'] not in signals:
                continue
            if end_dt is not None and m['recorded_at'] and reg.parse_utc(m['recorded_at']) >= end_dt:
                continue                                        # Backend №2 `end` is inclusive; BE3 intervals are [start, end)
            if not include_invalid and m['status'] != 'active':
                continue
            items.append(m)
        nxt = page.get('next_cursor')
        return {'items': items, 'next_cursor': None if nxt is None else str(nxt)}

    # ------------------------------------------------------------------ sessions
    def create_session(self, ctx, astronaut_id, source_type, source, device_id=None, mission_id=None, metadata=None) -> str:
        *_, common, repo = _be2()
        user = self._user(ctx)
        if astronaut_id != user['astronaut_id']:
            raise Forbidden()                                   # Backend №2 sessions are created by the owner only
        origin = SOURCE_TYPE_TO_ORIGIN.get(source_type)
        if origin is None:
            raise InvalidInput(f'source_type {source_type!r} cannot be stored in the personal store', field='source_type')
        row = _call(repo.create_session, user, {'device_id': device_id, 'mission_id': mission_id, 'source': source,
                                                'origin': origin, 'started_at': common.utcnow(),
                                                'metadata': {**(metadata or {}), 'source_type': source_type}})
        return row['id']

    def finish_session(self, ctx, session_id, status, metadata=None) -> None:
        *_, repo = _be2()
        _call(repo.close_session, self._user(ctx), session_id)
        self.finished_status[session_id] = status

    def _sessions(self, ctx):
        _, _, _, s, _, repo = _be2()
        user = self._user(ctx)
        for d in _call(repo.list_devices, user)['items']:
            after = 0
            while True:
                page = _call(repo.device_sessions, user, d['id'], s.HistoryQuery.model_validate({'after': after, 'limit': 500}))
                for row in page['items']:
                    yield row
                if page['next_cursor'] is None:
                    break
                after = page['next_cursor']

    @staticmethod
    def _session_out(row):
        md = row.get('metadata') or {}
        return {'session_id': row['id'], 'astronaut_id': row['astronaut_id'], 'device_id': row.get('device_id'),
                'mission_id': row.get('mission_id'), 'source': row.get('source'),
                'source_type': md.get('source_type') or ORIGIN_TO_SOURCE_TYPE.get(row.get('origin')),
                'status': 'recording' if row.get('ended_at') is None else 'closed', 'metadata': md,
                'created_at': row.get('started_at'), 'finished_at': row.get('ended_at')}

    def get_session(self, ctx, session_id) -> dict:
        for row in self._sessions(ctx):
            if row['id'] == session_id:
                return self._session_out(row)
        raise NotFound('Resource not found')

    def list_sessions(self, ctx, status=None) -> list[dict]:
        out = [self._session_out(r) for r in self._sessions(ctx)]
        return [x for x in out if status is None or x['status'] == status]

    # ------------------------------------------------------------------ devices (registry owned by Backend №2)
    def list_devices(self, ctx, astronaut_id=None) -> list[dict]:
        *_, repo = _be2()
        user = self._user(ctx)
        if astronaut_id is not None and astronaut_id != user['astronaut_id']:
            return []                                           # Backend №2 lists the caller's own devices only
        return [device_from_be2(d) for d in _call(repo.list_devices, user)['items']]

    def get_device(self, ctx, device_id) -> dict:
        for d in self.list_devices(ctx):
            if d['device_id'] == device_id:
                return d
        raise NotFound('Resource not found')

    def upsert_device(self, ctx, device: dict) -> dict:
        *_, repo = _be2()
        user = self._user(ctx)
        existing = None
        if device.get('device_id'):
            existing = next((d for d in self.list_devices(ctx) if d['device_id'] == device['device_id']), None)
        if existing is not None:
            changed = {k for k in ('name', 'astronaut_id', 'hardware_address') if k in device and device[k] != existing[k]}
            if changed or device.get('removed'):
                raise Conflict('Backend №2 registry has no device update/delete yet (BE2_REQUIRED_CHANGES R-4)',
                               code='device_update_unsupported')
            return existing
        if device.get('astronaut_id') not in (None, user['astronaut_id']):
            raise Forbidden()
        try:
            row = _call(repo.create_device, user, {'name': device.get('name') or 'HRS monitor', 'kind': 'ble',
                                                   'external_id': device.get('hardware_address')})
        except Be2Error as exc:
            if exc.code == 'device_exists':
                raise Conflict('Hardware address already registered for this astronaut', code='device_already_registered') from None
            raise
        return device_from_be2(row)

    # ------------------------------------------------------------------ analyses
    def _stored_result(self, payload: dict) -> dict:
        result = {k: v for k, v in payload.items() if k not in VOLATILE}
        if len(json.dumps(result, allow_nan=False).encode()) > BE2_RESULT_MAX:
            result = {**result, 'windows': [{k: v for k, v in w.items() if k != 'hrv'} for w in result.get('windows', [])],
                      'storage_compaction': 'per-window HRV detail omitted to fit Backend №2 result limit (128 KB)'}
        if len(json.dumps(result, allow_nan=False).encode()) > BE2_RESULT_MAX:
            raise InvalidInput('Analysis result exceeds Backend №2 storage limit (128 KB); analyse a shorter interval',
                               field='to', code='analysis_too_large')
        return result

    @staticmethod
    def _payload(row) -> dict:
        return {**row['result'], 'analysis_id': row['id'], 'created_at': row['created_at'],
                'astronaut_id': row['astronaut_id'], 'mission_id': row.get('mission_id'),
                'storage': {'backend': 'backend2', 'model': row['model'], 'processing_version': row['processing_version'],
                            'input_ids_stored': len(row.get('input_ids') or [])}}

    def save_analysis_bundle(self, ctx, kind, astronaut_id, payload, *, record, audit, idempotency_key, input_ids=None) -> dict:
        *_, common, repo = _be2()
        user = self._user(ctx)
        ids = list(input_ids or [])
        scope = {'input_ids_complete': len(ids) <= BE2_INPUT_IDS_MAX, 'input_count': len(ids)}
        result = self._stored_result({**payload, 'input_scope': scope})
        data = {'astronaut_id': astronaut_id, 'mission_id': payload.get('mission_id'),
                'session_id': (payload.get('input') or {}).get('session_id'), 'model': payload['method']['id'],
                'processing_version': payload['processing_version'], 'idempotency_key': idempotency_key,
                'input_ids': ids if len(ids) <= BE2_INPUT_IDS_MAX else [], 'result': result}
        before = common.utcnow()
        try:
            row = _call(repo.save_analysis, user, data)
        except Be2Error as exc:
            if exc.code == 'idempotency_conflict':
                raise Conflict(exc.message, code='idempotency_conflict') from None
            raise
        return {'analysis_id': row['id'], 'created': row['created_at'] >= before, 'record_id': row['id'],
                'payload': self._payload(row)}

    def get_analysis(self, ctx, analysis_id) -> dict:
        *_, repo = _be2()
        row = _call(repo.get_analysis, self._user(ctx), analysis_id)
        if row['model'] not in PHANTOM_MODELS:
            raise NotFound('Resource not found')               # summary-v1 is not a personal PHANTOM analysis
        return self._payload(row)

    def list_analyses(self, ctx, astronaut_id=None, kind=None, limit=100, cursor=None, mission_id=None) -> dict:
        _, _, _, s, _, repo = _be2()
        q = {'astronaut_id': astronaut_id, 'mission_id': mission_id, 'limit': min(int(limit), BE2_PAGE_MAX),
             'after': int(cursor or 0)}
        page = _call(repo.list_records, self._user(ctx), s.HistoryQuery.model_validate({k: v for k, v in q.items() if v is not None}),
                     'analysis_runs')
        items = [self._payload(r) for r in page['items'] if r['model'] in PHANTOM_MODELS]
        nxt = page.get('next_cursor')
        return {'items': items, 'next_cursor': None if nxt is None else str(nxt)}

    # ------------------------------------------------------------------ history / audit
    def log_record(self, ctx, kind, ref_ids, astronaut_id, data_class, summary):
        return None        # Backend №2 history = raw_measurements / sensor_sessions / analysis_runs (no separate log)

    def audit(self, ctx, action, target_kind, target_id, outcome, details=None) -> None:
        _, db, _, _, common, _ = _be2()
        user = self._user(ctx)
        with db.connect() as c:                                 # Backend №2's whitelisted audit helper; details dropped
            common.audit(c, user['id'], action, target_kind, target_id, 'ok' if outcome == 'success' else outcome)
