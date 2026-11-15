"""Server-issued personal context; no role or permission is accepted from HTTP."""
from contextlib import contextmanager
from app import auth, db, access_control as acl
from app.access_control.session import principal
from app.persistence.common import APIError


class RequestContext:
    __slots__ = ('_token', 'mission_id', '_principal', '_capture')
    def __init__(self, personal_session_token, *, mission_id=None):
        self._token = personal_session_token
        self._principal = auth.authenticate(personal_session_token)
        self.mission_id = mission_id
        self._capture = {}

    @property
    def user_id(self): return self._principal['id']

    @property
    def astronaut_id(self): return self._principal['astronaut_id']

    @property
    def role(self):
        # Compatibility labels, never authority. All operations recheck database permissions.
        return 'admin' if self._principal['role'] == 'administrator' else 'crew'

    def __repr__(self): return '<RequestContext personal_token=redacted>'

    def can(self, permission, astronaut_id=None):
        if permission not in ('measurement:read','measurement:write','phantom:run','device:use'): return False
        try:
            with db.connect() as c:
                c.execute('BEGIN IMMEDIATE'); user = principal(c,self._token)
                acl.profile(c,user,astronaut_id,write=permission!='measurement:read',mission_id=self.mission_id)
                if permission!='measurement:read': acl.mission(c,user,self.mission_id)
            return True
        except APIError: return False

    @contextmanager
    def analysis_scope(self):
        previous = self._capture; self._capture = {}
        try: yield self
        finally: self._capture = previous


class _RecoveryContext:
    __slots__ = ()
    user_id = None
    role = 'system'
    def can(self, permission, astronaut_id=None):
        return permission in ('measurement:read','measurement:write')
    def __repr__(self): return '<RecoveryContext limited-to-live-sensor-recovery>'


# Identity check, not a caller-provided role string; never issued through HTTP.
SYSTEM_CONTEXT = _RecoveryContext()


def current(c, ctx):
    if type(ctx) is not RequestContext:
        raise APIError(401,'unauthenticated','A server-issued personal RequestContext is required')
    user=principal(c,ctx._token)
    if user['id']!=ctx.user_id: raise APIError(401,'unauthenticated','Invalid request context')
    return user
