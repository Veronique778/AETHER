"""Latest-per-signal endpoint stays accurate after long paginated sensor histories."""
from app import auth
from app.persistence import repository as repo
from test_api_security_15 import client, register
from helpers_be2_15 import measurement


def test_snapshot_recent_usable_and_user_isolated(client):
    assert client('GET', '/api/measurements/latest')[0] == 401
    a, token = register(client, 'snap_a')
    _, other = register(client, 'snap_b')
    me = auth.authenticate(token)
    writes = [measurement(f'old-{i}', value=61 + (i % 10)) for i in range(115)]
    repo.add_measurements(me, writes)
    # The regular history endpoint returns the oldest 100; the snapshot must not.
    assert client('GET', '/api/measurements', token=token)[1]['next_cursor'] is not None
    repo.add_measurements(me, [measurement('recent-good', value=83)])
    repo.add_measurements(me, [measurement('recent-contact-lost', value=150, quality='no_contact')])
    # A late import of an older sample must not override a newer measured timestamp.
    repo.add_measurements(me, [measurement('older-late-import', value=33, measured_at='2026-11-14T10:00:00+02:00')])
    status, result = client('GET', '/api/measurements/latest', token=token)
    assert status == 200
    assert result['source'] == 'authenticated_personal_sqlite'
    assert result['clinical_validation'] is False
    assert {row['signal'] for row in result['items']} == {'heart_rate'}
    assert result['items'][0]['value'] == 83
    assert result['counts']['heart_rate'] == {'samples': 118, 'usable': 117}
    assert client('GET', '/api/measurements/latest', token=other)[1]['items'] == []
    assert client('GET', '/api/measurements/latest', token='bad')[0] == 401
