import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from app import auth,db
from app.persistence.common import APIError,digest
from helpers_be2_15 import account,PASSWORD

@pytest.fixture(autouse=True)
def database(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'auth.db'); db.init_db()


def test_register_hash_unique_profile_and_no_demo_assignment():
    u,t,code=account()
    with db.connect() as c:
        raw=c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone()
        assert raw['password_hash'].startswith('$argon2id$') and PASSWORD not in raw['password_hash']
        assert code not in raw['recovery_hash'] and c.execute('SELECT token_hash FROM auth_sessions').fetchone()[0]!=t
        assert c.execute('SELECT COUNT(*) FROM raw_measurements WHERE astronaut_id=?',(u['astronaut_id'],)).fetchone()[0]==0
        assert c.execute("SELECT COUNT(*) FROM astronaut_profiles WHERE user_id IS NULL").fetchone()[0]==4
    with pytest.raises(APIError) as err: auth.register('ALICE',PASSWORD,'second')
    assert err.value.status==409


def test_logout_expiration_and_revocation():
    u,t,_=account(); auth.logout(u,t)
    with pytest.raises(APIError): auth.authenticate(t)
    t=auth.login('alice',PASSWORD)['access_token']
    with db.connect() as c: c.execute("UPDATE auth_sessions SET expires_at='2000-01-01T00:00:00.000000Z' WHERE token_hash=?",(digest(t),))
    with pytest.raises(APIError): auth.authenticate(t)
    with db.connect() as c: assert c.execute('SELECT revoked_at FROM auth_sessions WHERE token_hash=?',(digest(t),)).fetchone()[0]


def test_idle_timeout_and_restart():
    u,t,_=account(); db.init_db(); assert auth.authenticate(t)['id']==u['id']
    with db.connect() as c: c.execute("UPDATE auth_sessions SET last_seen_at='2000-01-01T00:00:00.000000Z'")
    with pytest.raises(APIError): auth.authenticate(t)


def test_password_change_revokes_all_sessions_and_recovery():
    u,t,code=account(); other=auth.login('alice',PASSWORD)['access_token']
    result=auth.change_password(u,PASSWORD,'A-New-Strong-Password-15')
    for token in (t,other):
        with pytest.raises(APIError): auth.authenticate(token)
    with pytest.raises(APIError): auth.login('alice',PASSWORD)
    assert auth.login('alice','A-New-Strong-Password-15')['access_token']
    with pytest.raises(APIError): auth.recover('alice',code,PASSWORD)
    assert result['recovery_code']!=code


def test_recovery_single_use_and_all_sessions_revoked():
    u,t,code=account(); result=auth.recover('alice',code,'Replacement-Password-2026')
    with pytest.raises(APIError): auth.authenticate(t)
    with pytest.raises(APIError): auth.recover('alice',code,PASSWORD)
    assert result['recovery_code']!=code
    assert auth.login('alice','Replacement-Password-2026')['user']['id']==u['id']


def test_rate_limit_persists_across_reinitialization():
    for _ in range(5):
        with pytest.raises(APIError) as err: auth.login('missing','wrong',peer='ip')
        assert err.value.status==401
    db.init_db()
    with pytest.raises(APIError) as err: auth.login('missing','wrong',peer='ip')
    assert err.value.status==429


def test_concurrent_registration_uniqueness():
    def register(_):
        try: auth.register('same',PASSWORD,'Same'); return 201
        except APIError as e: return e.status
    with ThreadPoolExecutor(4) as pool: statuses=list(pool.map(register,range(4)))
    assert statuses.count(201)==1 and statuses.count(409)==3


def test_sensitive_data_not_in_audit_or_logs(capsys,caplog):
    u,t,code=account(); auth.logout(u,t)
    with db.connect() as c: text=json.dumps([dict(r) for r in c.execute('SELECT * FROM audit_logs')])
    text+=capsys.readouterr().out+capsys.readouterr().err+caplog.text
    assert all(secret not in text for secret in (PASSWORD,t,code))


def test_weak_password_rejected():
    with pytest.raises(APIError) as err: auth.register('weak','1234','Weak')
    assert err.value.status==422


def test_disabled_user_cannot_login_or_recover():
    u,t,code=account()
    with db.connect() as c: c.execute('UPDATE users SET active=0 WHERE id=?',(u['id'],))
    for fn,args in [(auth.authenticate,(t,)),(auth.login,('alice',PASSWORD)),(auth.recover,('alice',code,PASSWORD))]:
        with pytest.raises(APIError): fn(*args)
