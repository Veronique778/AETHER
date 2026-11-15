from helpers_be2_15 import PASSWORD, measurement
from test_api_security_15 import client, register
from integration_support_15 import admin_account
from test_science_integration_15 import check

def test_admin_users_block_unblock_roles_and_limited_audit(client):
    user, token = register(client); admin, at = admin_account(client)
    assert client('GET', '/api/admin/users', token=token)[0] == 403
    assert client('PATCH', '/api/admin/users/'+admin['id'], {'active': False}, at)[0] == 409
    assert client('PATCH', '/api/admin/users/'+admin['id'], {'role': 'astronaut'}, at)[0] == 409
    status, users = client('GET', '/api/admin/users?limit=1', token=at)
    assert status == 200 and len(users['items']) == 1 and users['next_cursor'] is not None
    check('GET', '/api/admin/users', status, users)
    assert client('GET', '/api/admin/users?mission_id=unexpected', token=at)[0] == 422
    for row in users['items']: assert not {'password_hash', 'recovery_hash', 'token_hash'} & row.keys()
    mid = client('POST', '/api/measurements', measurement(), token)[1]['measurement']['id']
    assert client('GET', '/api/measurements/'+mid, token=at)[0] == 404
    status, blocked = client('PATCH', '/api/admin/users/'+user['user']['id'], {'active': False}, at)
    assert status == 200
    check('PATCH', '/api/admin/users/{id}', status, blocked)
    assert client('GET', '/api/auth/me', token=token)[0] == 401
    assert client('POST', '/api/auth/login', {'login': 'alice', 'password': PASSWORD})[0] == 401
    assert client('PATCH', '/api/admin/users/'+user['user']['id'], {'active': True}, at)[0] == 200
    assert client('GET', '/api/auth/me', token=token)[0] == 401
    _, new_login = client('POST', '/api/auth/login', {'login': 'alice', 'password': PASSWORD})
    assert client('GET', '/api/auth/me', token=new_login['access_token'])[0] == 200
    status, promoted = client('PATCH', '/api/admin/users/'+user['user']['id'], {'role': 'administrator'}, at)
    assert status == 200 and promoted['role'] == 'administrator'
    assert client('GET', '/api/auth/me', token=new_login['access_token'])[0] == 401
    assert client('GET', '/api/admin/audit-logs', token=token)[0] == 401
    status, audit = client('GET', '/api/admin/audit-logs', token=at)
    check('GET', '/api/admin/audit-logs', status, audit)
    assert any(r['action'] == 'set_account' for r in audit['items'])
    assert not any(r['resource_type'] in ('measurement', 'analysis', 'phantom_analysis') for r in audit['items'])
