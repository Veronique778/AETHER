"""Historical BE2 provider COMPONENT regressions, with real SQLite.

FixtureProvider is TEST ONLY. It is called directly through service.run, never
registered as a public PHANTOM handler. Actual scientific HTTP integration is in
test_final_bridge_15.py; this file preserves the older provider's storage coverage.
"""
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from jsonschema import Draft202012Validator
from app import db, auth
from app.api_15 import contract
from app.persistence.common import APIError
from app.science_integration import service
from app.storage.api import StorageAPI, normalize_measurement
from test_api_security_15 import client, register
from integration_support_15 import FixtureProvider, admin_account, create_recording
from helpers_be2_15 import measurement


def provider_run(body, token):
    """Internal component result; this helper sends NO HTTP request."""
    from app.api_15 import error_response
    try:
        result=service.run(token,body)
        return (201 if result['created'] else 200),result
    except Exception as exc:
        return error_response(exc)

def check(method, route, status, body):
    schema = contract()['paths'][route][method.lower()]['responses'][str(status)]['content']['application/json']['schema']
    Draft202012Validator(schema).validate(body)

def test_real_storage_100_replay_auth_profile_device_sessions_and_missing_provider(client):
    registered, token = register(client)
    assert client('GET', '/api/profile', token=token)[1]['id'] == registered['user']['astronaut_id']
    session, items, request = create_recording(client, token)
    status, listing = client('GET', '/api/measurements?limit=100', token=token)
    assert status == 200 and len(listing['items']) == 100
    assert all(r['origin'] == 'simulated' and r['measured_at'].endswith('Z') for r in listing['items'])
    status, repeated = client('POST', '/api/measurements/batch', {'measurements': items}, token)
    assert status == 200 and not any(r['created'] for r in repeated['items'])
    check('POST', '/api/measurements/batch', status, repeated)
    status, unavailable = provider_run(request, token)
    assert status == 503 and unavailable['error']['code'] == 'science_not_integrated'
    status, catalog = client('GET', '/api/signals', token=token)
    assert status == 200
    check('GET', '/api/signals', status, catalog)
    for path in ('/api/signals', '/api/phantom-analyses'): assert client('GET', path)[0] == 401
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM raw_measurements WHERE astronaut_id=?', (registered['user']['astronaut_id'],)).fetchone()[0] == 100
        assert c.execute('SELECT COUNT(*) FROM analysis_runs').fetchone()[0] == 0
        assert c.execute('PRAGMA foreign_key_check').fetchone() is None

def test_provider_component_results_reruns_nulls_and_contracts(client, monkeypatch):
    """Storage/route integration with TEST provider, NOT personal PHANTOM validation."""
    monkeypatch.setattr(service, 'PROVIDERS', {'test-fixture': FixtureProvider()})
    registered, token = register(client)
    session, items, request = create_recording(client, token, missing=True)
    before = StorageAPI(token).list_measurements()['items']
    status, result = provider_run(request, token)
    assert status == 201
    run = result['analysis']; rid = run['id']
    assert run['status'] == 'insufficient_data'
    assert run['astronaut_id'] == registered['user']['astronaut_id']
    assert run['processing_version'] == 'TEST-ONLY-NOT-PHANTOM-1'
    assert run['result'] == {'test_only': True, 'sample_count': 100, 'missing_count': 100}
    assert all(p['origin'] == 'simulated' and p['missing'] for p in run['provenance'])
    assert provider_run(request, token)[0] == 200
    assert provider_run({**request, 'input_ids': request['input_ids'][:1]}, token)[0] == 409
    second = provider_run({**request, 'idempotency_key': 'run-2'}, token)[1]['analysis']
    assert second['id'] != rid
    assert StorageAPI(token).get_analysis(rid)==run
    assert StorageAPI(token).list_measurements()['items'] == before
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM record_events').fetchone()[0] == 2
        assert c.execute("SELECT COUNT(*) FROM audit_logs WHERE resource_type='phantom_analysis' AND action='create'").fetchone()[0] == 2
    db.init_db()
    assert StorageAPI(token).get_analysis(rid) == run

def test_idor_input_ownership_provenance_and_medical_revocation(client, monkeypatch):
    monkeypatch.setattr(service, 'PROVIDERS', {'test-fixture': FixtureProvider()})
    owner, token = register(client); stranger, other = register(client, 'stranger')
    officer, med = register(client, 'officer'); admin, at = admin_account(client)
    mid = client('POST', '/api/missions', {'name': 'Test mission'}, at)[1]['id']
    for u, role in [(owner['user'], 'astronaut'), (officer['user'], 'medical_officer')]:
        assert client('POST', f'/api/missions/{mid}/crew', {'user_id': u['id'], 'role': role}, at)[0] == 200
    session, _, request = create_recording(client, token, count=3, mission_id=mid)
    assert provider_run(request, other)[0] == 404
    assert provider_run({**request, 'astronaut_id': 'A01'}, token)[0] == 404
    assert provider_run({**request, 'mission_id': 'wrong'}, token)[0] == 422
    assert provider_run({**request, 'allowed_origins': ['real']}, token)[0] == 422
    foreign = client('POST', '/api/measurements', measurement('foreign'), other)[1]['measurement']['id']
    assert provider_run({**request, 'input_ids': [*request['input_ids'], foreign]}, token)[0] == 404
    rid = provider_run(request, token)[1]['analysis']['id']
    for wrong in (other, med, at):
        with pytest.raises(APIError):StorageAPI(wrong).get_analysis(rid)
    grant = {'officer_id': officer['user']['id'], 'astronaut_id': owner['user']['astronaut_id'], 'can_review': True}
    assert client('POST', f'/api/missions/{mid}/medical-access', grant, at)[0] == 200
    assert StorageAPI(med).get_analysis(rid)['id']==rid
    assert provider_run(request, med)[0] == 404
    aid = owner['user']['astronaut_id']
    assert StorageAPI(med).get_analysis(rid)['id']==rid
    assert client('DELETE', f"/api/missions/{mid}/medical-access/{officer['user']['id']}/{aid}", token=at)[0] == 200
    with pytest.raises(APIError):StorageAPI(med).get_analysis(rid)
    assert client('GET', f'/api/analyses?astronaut_id={aid}&mission_id={mid}', token=med)[0] == 404

def test_transaction_rollback_actual_sql_trigger_and_safe_retry(client, monkeypatch):
    monkeypatch.setattr(service, 'PROVIDERS', {'test-fixture': FixtureProvider()})
    _, token = register(client); session, _, request = create_recording(client, token, count=2)
    with db.connect() as c:
        c.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON audit_logs WHEN NEW.resource_type='phantom_analysis' BEGIN SELECT RAISE(ABORT,'test-db-failure'); END;")
    status, body = provider_run(request, token)
    assert status == 409 and 'test-db-failure' not in json.dumps(body)
    with db.connect() as c:
        for table in ('analysis_runs', 'phantom_run_details', 'record_events'): assert c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] == 0
        c.execute('DROP TRIGGER fail_audit')
    assert provider_run(request, token)[0] == 201
    with db.connect() as c:
        c.execute("CREATE TRIGGER fail_sample BEFORE INSERT ON raw_measurements WHEN NEW.idempotency_key='fail' BEGIN SELECT RAISE(ABORT,'test-db-failure'); END;")
    status, _ = client('POST', '/api/measurements/batch', {'measurements': [measurement('before-fail'), measurement('fail')]}, token)
    assert status == 409
    with db.connect() as c: assert c.execute("SELECT COUNT(*) FROM raw_measurements WHERE idempotency_key='before-fail'").fetchone()[0] == 0

def test_provider_revalidation_concurrent_idempotency_and_bad_result(client, monkeypatch):
    _, token = register(client); _, _, request = create_recording(client, token, count=2)
    monkeypatch.setattr(service, 'PROVIDERS', {'test-fixture': FixtureProvider()})
    with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(lambda _: service.run(token, request), range(8)))
    assert sum(r['created'] for r in results) == 1
    assert len({r['analysis']['id'] for r in results}) == 1
    class BadProvider:
        def evaluate(self, rows): return {'secret': 'do-not-echo'}
    monkeypatch.setattr(service, 'PROVIDERS', {'test-fixture': BadProvider()})
    status, bad = provider_run({**request, 'idempotency_key': 'bad'}, token)
    assert status == 502 and 'do-not-echo' not in json.dumps(bad)
    class LogoutDuringCompute(FixtureProvider):
        def evaluate(self, rows):
            auth.logout(auth.authenticate(token), token)
            return super().evaluate(rows)
    monkeypatch.setattr(service, 'PROVIDERS', {'test-fixture': LogoutDuringCompute()})
    assert provider_run({**request, 'idempotency_key': 'revoked'}, token)[0] == 401
    with db.connect() as c: assert c.execute('SELECT COUNT(*) FROM analysis_runs').fetchone()[0] == 1

def test_alias_adapter_missing_values_session_close_and_no_sensitive_audit(client, caplog):
    _, token = register(client); session, items, request = create_recording(client, token, count=1)
    d = measurement('alias', value=None)
    for source, alias in [('origin', 'data_class'), ('measured_at', 'recorded_at'), ('idempotency_key', 'client_measurement_id')]: d[alias] = d.pop(source)
    adapter = StorageAPI(token)
    assert token not in repr(adapter)
    saved = adapter.append_biosignals([d])[0]['measurement']
    assert saved['value'] is None and saved['missing'] and saved['origin'] == 'manual'
    with pytest.raises(APIError): normalize_measurement({**d, 'origin': 'real'})
    assert client('POST', '/api/measurements', d, token)[0] == 422
    assert adapter.get_session(session['id'])['ended_at'] is None
    assert adapter.close_session(session['id'])['closed']
    later = {**items[0], 'idempotency_key': 'after-close', 'measured_at': '2099-01-01T00:00:00Z'}
    assert client('POST', '/api/measurements', later, token)[0] == 409
    assert client('POST', '/api/measurements', items[0], token)[0] == 200
    assert client('POST', '/api/measurements', {**items[0], 'idempotency_key': 'delayed'}, token)[0] == 201
    with db.connect() as c: text = json.dumps([dict(r) for r in c.execute('SELECT * FROM audit_logs')])
    from helpers_be2_15 import PASSWORD
    for secret in (token, PASSWORD, 'automated-test-fixture', 'Correct-Horse'): assert secret not in text and secret not in caplog.text

def test_contract_schemas_and_migration_repeatability(client):
    for methods in contract()['paths'].values():
        for op in methods.values():
            for resp in op['responses'].values(): Draft202012Validator.check_schema(resp['content']['application/json']['schema'])
    with db.connect() as conn: before = conn.execute('SELECT COUNT(*) FROM raw_measurements').fetchone()[0]
    db.init_db(); db.init_db()
    with db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM raw_measurements').fetchone()[0] == before
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE version='003_science_integration'").fetchone()[0] == 1
        assert conn.execute('PRAGMA foreign_key_check').fetchone() is None

def test_personal_phantom_backend3_protocol_available():
    from app import science_storage
    from app.persistence import science_storage as factory
    assert not science_storage.conformance(factory())

def test_actual_database_open_failure_maps_to_503_without_partial_write(client, tmp_path, monkeypatch):
    _, token = register(client)
    directory = tmp_path / 'not-a-database'; directory.mkdir()
    with monkeypatch.context() as patch:
        patch.setattr(db, 'DB_PATH', directory)
        status, body = client('POST', '/api/measurements/batch', {'measurements': [measurement('unavailable')]}, token)
        assert status == 503 and body['error']['code'] == 'storage_unavailable'
        assert str(directory) not in json.dumps(body)
        check('POST', '/api/measurements/batch', status, body)
    assert client('POST', '/api/measurements/batch', {'measurements': [measurement('unavailable')]}, token)[0] == 200
    assert len(client('GET', '/api/measurements', token=token)[1]['items']) == 1


def test_persisted_runs_events_and_raw_are_immutable(client, monkeypatch):
    import sqlite3
    monkeypatch.setattr(service, 'PROVIDERS', {'test-fixture': FixtureProvider()})
    _, token = register(client); _, _, request = create_recording(client, token, count=1)
    rid = provider_run(request, token)[1]['analysis']['id']
    for sql, arg in [("UPDATE analysis_runs SET processing_version='tampered' WHERE id=?", rid),
                     ('DELETE FROM phantom_run_details WHERE analysis_id=?', rid),
                     ('DELETE FROM record_events WHERE analysis_id=?', rid),
                     ('UPDATE raw_measurements SET value=0 WHERE id=?', request['input_ids'][0])]:
        with pytest.raises(sqlite3.IntegrityError):
            with db.connect() as c: c.execute(sql, (arg,))
    assert StorageAPI(token).get_analysis(rid)['processing_version'] == 'TEST-ONLY-NOT-PHANTOM-1'
