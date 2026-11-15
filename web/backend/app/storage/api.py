"""Proposed, token-bound science adapter over the canonical personal database.

No global current user, demo fallback, legacy-ID conversion or science algorithms.
Exact Backend #3 call compatibility still requires his source package and review.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import json
from app import db, access_control as acl
from app.access_control.session import principal
from app.persistence import repository as repo
from app.persistence.common import APIError, audit, digest, dumps, uid, utcnow
from app.schemas_15 import HistoryQuery, MeasurementCreate, SessionCreate
from app.schemas_integration import PhantomRequest, PhantomQuery, ScienceResult


@dataclass(frozen=True)
class Snapshot:
    request_json: str
    input_json: str
    fingerprint: str

    def measurements(self):
        """Fresh copy: a scientific function cannot modify the stored snapshot."""
        return json.loads(self.input_json)


def normalize_measurement(data):
    """Opt-in internal aliases only. Never change the existing HTTP request shape."""
    d = dict(data)
    for alias, canonical in [('data_class', 'origin'), ('recorded_at', 'measured_at'),
                             ('client_measurement_id', 'idempotency_key')]:
        if alias in d:
            if canonical in d and d[canonical] != d[alias]:
                raise APIError(422, 'alias_conflict', 'Conflicting measurement field aliases')
            d[canonical] = d.pop(alias)
    return MeasurementCreate.model_validate(d).model_dump()


def _scope(c, user, request):
    d = PhantomRequest.model_validate(request).model_dump()
    session = repo.session_row(c, user, d['session_id'], write=True)
    aid = acl.profile(c, user, d['astronaut_id'], write=True)
    if aid != session['astronaut_id']:
        raise APIError(404, 'not_found', 'Session not found in analysis scope')
    if d['mission_id'] is not None and d['mission_id'] != session['mission_id']:
        raise APIError(422, 'session_mismatch', 'Mission differs from session')
    acl.mission(c, user, session['mission_id'])
    d.update(astronaut_id=aid, mission_id=session['mission_id'])
    # Set semantics for idempotency; order is the original durable measurement sequence.
    d['allowed_origins'] = sorted(d['allowed_origins'])
    rows = []
    for mid in d['input_ids']:
        r = c.execute('SELECT * FROM raw_measurements WHERE id=?', (mid,)).fetchone()
        if not r or (r['astronaut_id'], r['session_id'], r['mission_id']) != (aid, session['id'], session['mission_id']):
            raise APIError(404, 'not_found', 'Input record not found in analysis scope')
        if r['origin'] not in d['allowed_origins']:
            raise APIError(422, 'origin_not_allowed', 'Explicit consent to input provenance is required')
        rows.append(repo.rowdict(r))
    rows.sort(key=lambda r: r['seq'])
    d['input_ids'] = [r['id'] for r in rows]
    return d, rows


def _run(c, run_id):
    row = c.execute('''SELECT a.*,p.status,p.provenance FROM analysis_runs a
      JOIN phantom_run_details p ON p.analysis_id=a.id WHERE a.id=?''', (run_id,)).fetchone()
    if not row: raise APIError(404, 'not_found', 'Analysis not found')
    value = repo.rowdict(row)
    value['provenance'] = json.loads(value['provenance'])
    return value


def _existing(c, d):
    old = c.execute('''SELECT a.id,p.request_hash FROM analysis_runs a
      LEFT JOIN phantom_run_details p ON p.analysis_id=a.id
      WHERE a.astronaut_id=? AND a.idempotency_key=?''', (d['astronaut_id'], d['idempotency_key'])).fetchone()
    if old:
        if old['request_hash'] != digest(dumps(d)):
            raise APIError(409, 'idempotency_conflict', 'Analysis key was used with different content')
        return _run(c, old['id'])
    return None


class StorageAPI:
    def __init__(self, token):
        self.__token = token

    def __repr__(self):
        return '<StorageAPI personal-session=redacted>'

    @contextmanager
    def _transaction(self):
        with db.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            yield c, principal(c, self.__token)

    def create_session(self, data):
        d = SessionCreate.model_validate(data).model_dump()
        with self._transaction() as (c, user):
            return repo._create_session(c, user, d)

    def get_session(self, session_id):
        with self._transaction() as (c, user):
            row = repo.session_row(c, user, session_id)
            audit(c, user['id'], 'read', 'sensor_session', session_id)
            return repo.rowdict(row)

    def close_session(self, session_id):
        with self._transaction() as (c, user):
            repo.session_row(c, user, session_id, write=True)
            c.execute('UPDATE sensor_sessions SET ended_at=COALESCE(ended_at,?) WHERE id=?', (utcnow(), session_id))
            audit(c, user['id'], 'close', 'sensor_session', session_id)
            return {'closed': True}

    def append_biosignals(self, items):
        if not isinstance(items, list) or not 1 <= len(items) <= 1000:
            raise APIError(422, 'batch_size', 'Batch must contain 1–1000 measurements')
        validated = [normalize_measurement(d) for d in items]
        with self._transaction() as (c, user):
            return [repo._insert(c, user, d) for d in validated]

    def get_measurement(self, measurement_id):
        with self._transaction() as (c, user):
            r = c.execute('SELECT * FROM raw_measurements WHERE id=?', (measurement_id,)).fetchone()
            if not r: raise APIError(404, 'not_found', 'Resource not found')
            acl.profile(c, user, r['astronaut_id'], mission_id=r['mission_id'])
            audit(c, user['id'], 'read', 'measurement', measurement_id)
            return repo.rowdict(r)

    def list_measurements(self, query=None):
        q = HistoryQuery.model_validate(query or {})
        with self._transaction() as (c, user):
            aid, where, args = repo._where(c, user, q)
            rows = c.execute('SELECT * FROM raw_measurements WHERE ' + ' AND '.join(where) + ' AND seq>? ORDER BY seq LIMIT ?',
                             (*args, q.after, q.limit + 1)).fetchall()
            audit(c, user['id'], 'list', 'measurement', aid)
            return repo.page(rows, q.limit)

    def prepare_analysis(self, request):
        """Authoritative explicit inputs. Missing values and quality are not imputed."""
        with self._transaction() as (c, user):
            d, rows = _scope(c, user, request)
            audit(c, user['id'], 'read_inputs', 'sensor_session', d['session_id'])
            encoded = dumps(rows)
            return Snapshot(dumps(d), encoded, digest(encoded))

    def find_analysis(self, snapshot):
        with self._transaction() as (c, user):
            d, _ = _scope(c, user, json.loads(snapshot.request_json))
            result = _existing(c, d)
            if result: audit(c, user['id'], 'read', 'analysis', result['id'])
            return result

    def save_analysis(self, snapshot, result):
        """Atomically persist run + provenance + record event + audit; no raw edits."""
        result = ScienceResult.model_validate(result).model_dump()
        with self._transaction() as (c, user):
            d, rows = _scope(c, user, json.loads(snapshot.request_json))
            if digest(dumps(rows)) != snapshot.fingerprint:
                raise APIError(409, 'snapshot_changed', 'Analysis input snapshot changed')
            old = _existing(c, d)
            if old:
                return old, False
            rid = uid(); now = utcnow()
            provenance = [{'id': r['id'], 'origin': r['origin'], 'source': r['source'],
                           'quality': r['quality'], 'missing': r['missing'],
                           'processing_version': r['processing_version']} for r in rows]
            c.execute('INSERT INTO analysis_runs VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (rid, d['astronaut_id'], d['mission_id'], d['session_id'], d['algorithm'], result['algorithm_version'],
                       now, dumps(result['result']), dumps(d['input_ids']), d['idempotency_key']))
            c.execute('INSERT INTO phantom_run_details VALUES(?,?,?,?,?)',
                      (rid, result['status'], digest(dumps(d)), dumps(provenance), user['id']))
            c.execute('INSERT INTO record_events(id,astronaut_id,analysis_id,actor_id,event_type,created_at) VALUES(?,?,?,?,?,?)',
                      (uid(), d['astronaut_id'], rid, user['id'], 'phantom_analysis_saved', now))
            audit(c, user['id'], 'create', 'phantom_analysis', rid)
            return _run(c, rid), True

    def get_analysis(self, analysis_id):
        with self._transaction() as (c, user):
            r = _run(c, analysis_id)
            acl.profile(c, user, r['astronaut_id'], mission_id=r['mission_id'])
            audit(c, user['id'], 'read', 'analysis', analysis_id)
            return r

    def list_analyses(self, query=None):
        q = PhantomQuery.model_validate(query or {})
        with self._transaction() as (c, user):
            aid = acl.profile(c, user, q.astronaut_id, mission_id=q.mission_id)
            where = ['a.astronaut_id=?', 'a.rowid>?']; args = [aid, q.after]
            for k in ('mission_id', 'session_id'):
                value = getattr(q, k)
                if value is not None: where.append('a.' + k + '=?'); args.append(value)
            rows = c.execute('SELECT a.rowid AS seq,a.id FROM analysis_runs a JOIN phantom_run_details p ON p.analysis_id=a.id WHERE ' +
                             ' AND '.join(where) + ' ORDER BY a.rowid LIMIT ?', (*args, q.limit + 1)).fetchall()
            items = [{'seq': r['seq'], **_run(c, r['id'])} for r in rows[:q.limit]]
            audit(c, user['id'], 'list', 'phantom_analysis', aid)
            return {'items': items, 'next_cursor': items[-1]['seq'] if len(rows) > q.limit else None}
