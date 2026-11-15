"""Test-only provider. Does not execute or validate PHANTOM mathematics."""
from app.auth.admin import set_role
from helpers_be2_15 import PASSWORD, measurement

class FixtureProvider:
    def evaluate(self, rows):
        return {'algorithm_version': 'TEST-ONLY-NOT-PHANTOM-1',
                'status': 'insufficient_data' if all(r['value'] is None for r in rows) else 'ok',
                'result': {'test_only': True, 'sample_count': len(rows), 'missing_count': sum(r['value'] is None for r in rows)}}

def admin_account(client, name='operator'):
    from test_api_security_15 import register
    details, _ = register(client, name)
    set_role(name, 'administrator')
    status, logged = client('POST', '/api/auth/login', {'login': name, 'password': PASSWORD})
    assert status == 200
    return details['user'], logged['access_token']

def create_recording(client, token, count=100, origin='simulated', mission_id=None, missing=False):
    status, device = client('POST', '/api/devices', {'name': 'Explicit test sensor', 'kind': 'other'}, token)
    assert status == 201
    status, session = client('POST', '/api/sensor-sessions', {'device_id': device['id'], 'mission_id': mission_id,
                'source': 'automated-test-fixture', 'origin': origin, 'started_at': '2026-01-01T00:00:00Z'}, token)
    assert status == 201
    items = [measurement('test-'+str(i), origin=origin, device_id=device['id'], session_id=session['id'], mission_id=mission_id,
                 source='automated-test-fixture', value=None if missing else float(60+i%20)) for i in range(count)]
    status, saved = client('POST', '/api/measurements/batch', {'measurements': items}, token)
    assert status == 200
    request = {'session_id': session['id'], 'algorithm': 'test-fixture', 'idempotency_key': 'run-1',
               'input_ids': [r['measurement']['id'] for r in saved['items']], 'allowed_origins': [origin]}
    return session, items, request
