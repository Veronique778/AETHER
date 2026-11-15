"""Database-backed Argon2id authentication. Opaque bearer tokens, no implicit cookies."""
import secrets
import time
from datetime import datetime, timedelta, timezone
from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError, InvalidHashError
from app import db
from app.persistence.common import APIError, audit, digest, uid, utcnow

HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, type=Type.ID)
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))
TTL = 12 * 3600
IDLE = 30 * 60


def password_hash(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise APIError(422,'password_policy','Password must contain 12–128 characters')
    return HASHER.hash(password)


def verify(encoded, password):
    try:
        return HASHER.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def public_user(c, user):
    profile = c.execute('SELECT id FROM astronaut_profiles WHERE user_id=?',(user['id'],)).fetchone()
    return {'id':user['id'],'login':user['login'],'role':user['role'],'astronaut_id':profile[0]}


def rate_limit(action, peer, login=''):
    """Persisted limits across restarts; hashed identifiers, never passwords/tokens."""
    now = time.time()
    keys = [(digest(action+':peer:'+peer),30)]
    if login: keys.append((digest(action+':login:'+login.lower()),5))
    blocked = False
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('DELETE FROM auth_limits WHERE window_start<?',(now-3600,))
        for key, maximum in keys:
            old = c.execute('SELECT * FROM auth_limits WHERE key_hash=?',(key,)).fetchone()
            attempts = old['attempts']+1 if old and now-old['window_start']<900 else 1
            start = old['window_start'] if old and now-old['window_start']<900 else now
            c.execute('INSERT INTO auth_limits VALUES(?,?,?) ON CONFLICT(key_hash) DO UPDATE SET window_start=excluded.window_start,attempts=excluded.attempts',
                      (key,start,attempts))
            blocked |= attempts > maximum
    if blocked: raise APIError(429,'rate_limited','Too many attempts; retry after 15 minutes')


def register(login, password, display_name, language='uk', peer='local'):
    rate_limit('register',peer)
    hashed = password_hash(password)
    recovery = secrets.token_urlsafe(32)
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM users WHERE login=?',(login,)).fetchone():
            raise APIError(409,'login_taken','Login is already in use')
        user_id, profile_id = uid(), uid()
        c.execute('INSERT INTO users(id,login,password_hash,recovery_hash,created_at) VALUES(?,?,?,?,?)',
                  (user_id,login.lower(),hashed,digest(recovery),utcnow()))
        c.execute('INSERT INTO astronaut_profiles(id,user_id,display_name,language,data_class,created_at) VALUES(?,?,?,?,?,?)',
                  (profile_id,user_id,display_name,language,'personal',utcnow()))
        audit(c,user_id,'register','user',user_id)
        return {'user':public_user(c,c.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()),
                'recovery_code':recovery}


def login(login, password, peer='local'):
    rate_limit('login',peer,login)
    with db.connect() as c:
        user = c.execute('SELECT * FROM users WHERE login=?',(login,)).fetchone()
    valid = verify(user['password_hash'] if user else DUMMY_HASH,password)
    if not valid or not user or not user['active']:
        with db.connect() as c: audit(c,None,'login','user',outcome='denied')
        raise APIError(401,'invalid_credentials','Invalid login or password')
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc)+timedelta(seconds=TTL)).isoformat(timespec='microseconds').replace('+00:00','Z')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        fresh = c.execute('SELECT * FROM users WHERE id=?',(user['id'],)).fetchone()
        if not fresh['active'] or fresh['password_hash'] != user['password_hash']:
            raise APIError(401,'invalid_credentials','Invalid login or password')
        c.execute('INSERT INTO auth_sessions VALUES(?,?,?,?,?,NULL)',(digest(token),user['id'],utcnow(),expires,utcnow()))
        c.execute('DELETE FROM auth_limits WHERE key_hash=?',(digest('login:login:'+login.lower()),))
        audit(c,user['id'],'login','user',user['id'])
        return {'access_token':token,'token_type':'Bearer','expires_at':expires,'idle_timeout_seconds':IDLE,'user':public_user(c,fresh)}


def authenticate(token):
    if not isinstance(token,str) or not 32 <= len(token) <= 128:
        raise APIError(401,'unauthenticated','A valid personal session is required')
    now = utcnow(); idle_before = (datetime.now(timezone.utc)-timedelta(seconds=IDLE)).isoformat(timespec='microseconds').replace('+00:00','Z')
    user = None
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('UPDATE auth_sessions SET revoked_at=? WHERE revoked_at IS NULL AND (expires_at<=? OR last_seen_at<=?)', (now,now,idle_before))
        row = c.execute('''SELECT u.*,s.token_hash FROM users u JOIN auth_sessions s ON s.user_id=u.id
                          WHERE s.token_hash=? AND s.revoked_at IS NULL AND u.active=1''',(digest(token),)).fetchone()
        if row:
            user = public_user(c,row)
            c.execute('UPDATE auth_sessions SET last_seen_at=? WHERE token_hash=?',(now,row['token_hash']))
    if user is None: raise APIError(401,'unauthenticated','A valid personal session is required')
    return user


def logout(user, token):
    with db.connect() as c:
        c.execute('UPDATE auth_sessions SET revoked_at=? WHERE token_hash=? AND user_id=?',(utcnow(),digest(token),user['id']))
        audit(c,user['id'],'logout','user',user['id'])
    return {'logged_out':True}


def change_password(user, current_password, new_password, peer='local'):
    rate_limit('change-password',peer,user['login'])
    hashed = password_hash(new_password)
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        old = c.execute('SELECT password_hash FROM users WHERE id=?',(user['id'],)).fetchone()[0]
        if not verify(old,current_password): raise APIError(401,'invalid_credentials','Invalid current password')
        recovery = secrets.token_urlsafe(32)
        c.execute('UPDATE users SET password_hash=?,recovery_hash=? WHERE id=?',(hashed,digest(recovery),user['id']))
        c.execute('UPDATE auth_sessions SET revoked_at=? WHERE user_id=?',(utcnow(),user['id']))
        audit(c,user['id'],'change_password','user',user['id'])
    return {'changed':True,'login_required':True,'recovery_code':recovery}


def recover(login, recovery_code, new_password, peer='local'):
    rate_limit('recover',peer,login)
    hashed = password_hash(new_password)
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        user = c.execute('SELECT * FROM users WHERE login=?',(login,)).fetchone()
        if not user or not user['active'] or not secrets.compare_digest(user['recovery_hash'],digest(recovery_code)):
            raise APIError(401,'invalid_recovery','Invalid recovery credentials')
        replacement = secrets.token_urlsafe(32)
        c.execute('UPDATE users SET password_hash=?,recovery_hash=? WHERE id=?',(hashed,digest(replacement),user['id']))
        c.execute('UPDATE auth_sessions SET revoked_at=? WHERE user_id=?',(utcnow(),user['id']))
        audit(c,user['id'],'recover','user',user['id'])
    return {'changed':True,'login_required':True,'recovery_code':replacement}
