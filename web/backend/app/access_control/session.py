"""Recheck a personal session inside the same transaction as a sensitive action."""
from datetime import datetime, timedelta, timezone
from app import auth
from app.persistence.common import APIError, digest, utcnow


def principal(c, token):
    if not isinstance(token, str) or not 32 <= len(token) <= 128:
        raise APIError(401, 'unauthenticated', 'A valid personal session is required')
    now = utcnow()
    idle = (datetime.now(timezone.utc) - timedelta(seconds=auth.IDLE)).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    row = c.execute('''SELECT u.* FROM users u JOIN auth_sessions s ON s.user_id=u.id
      WHERE s.token_hash=? AND u.active=1 AND s.revoked_at IS NULL
      AND s.expires_at>? AND s.last_seen_at>?''', (digest(token), now, idle)).fetchone()
    if not row:
        raise APIError(401, 'unauthenticated', 'A valid personal session is required')
    c.execute('UPDATE auth_sessions SET last_seen_at=? WHERE token_hash=?', (now, digest(token)))
    return auth.public_user(c, row)
