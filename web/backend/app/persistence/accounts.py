"""Administrative metadata only; no medical payloads, hashes or tokens."""
from app import db, access_control as acl
from app.access_control.session import principal
from app.persistence.common import APIError, audit, utcnow
from app.schemas_integration import AccountPatch

ADMIN_ACTIONS = ('create', 'set_membership', 'remove_membership', 'grant_medical_access',
                 'revoke_medical_access', 'set_account', 'list_accounts', 'read_admin_audit')


def list_users(token, q):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE'); user = principal(c, token); acl.admin(user)
        rows = c.execute('''SELECT u.rowid AS seq,u.id,u.login,u.role,u.active,u.created_at,
          p.id AS astronaut_id,p.display_name FROM users u JOIN astronaut_profiles p ON p.user_id=u.id
          WHERE u.rowid>? ORDER BY u.rowid LIMIT ?''', (q.after, q.limit + 1)).fetchall()
        items = [{**dict(r), 'active': bool(r['active'])} for r in rows[:q.limit]]
        audit(c, user['id'], 'list_accounts', 'user')
        return {'items': items, 'next_cursor': items[-1]['seq'] if len(rows) > q.limit else None}


def patch_user(token, user_id, data):
    data = AccountPatch.model_validate(data).model_dump(exclude_none=True)
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE'); actor = principal(c, token); acl.admin(actor)
        old = c.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        if not old: raise APIError(404, 'not_found', 'User not found')
        active = data.get('active', bool(old['active'])); role = data.get('role', old['role'])
        if actor['id'] == user_id and (not active or role != 'administrator'):
            raise APIError(409, 'self_lockout', 'Another administrator must change your access')
        if old['active'] and old['role'] == 'administrator' and (not active or role != 'administrator'):
            others = c.execute("SELECT COUNT(*) FROM users WHERE role='administrator' AND active=1 AND id<>?", (user_id,)).fetchone()[0]
            if not others: raise APIError(409, 'last_administrator', 'Keep at least one active administrator')
        c.execute('UPDATE users SET active=?,role=? WHERE id=?', (int(active), role, user_id))
        if not active or role != old['role']:
            c.execute('UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL', (utcnow(), user_id))
        # Blocking also removes this account's medical grants: unblocking cannot resurrect them.
        if not active:
            c.execute('DELETE FROM medical_access WHERE officer_id=?', (user_id,))
        audit(c, actor['id'], 'set_account', 'user', user_id)
        return {'id': user_id, 'active': active, 'role': role}


def audit_history(token, q):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE'); user = principal(c, token); acl.admin(user)
        # Strict action/resource allowlist prevents access to clinical read/write audit trails.
        rows = c.execute('''SELECT rowid AS seq,* FROM audit_logs WHERE rowid>? AND (
          (resource_type='mission' AND action IN ('create','set_membership','remove_membership')) OR
          (resource_type='profile' AND action IN ('grant_medical_access','revoke_medical_access')) OR
          (resource_type='user' AND action IN ('set_account','list_accounts','read_admin_audit')))
          ORDER BY rowid LIMIT ?''', (q.after, q.limit + 1)).fetchall()
        items = [dict(r) for r in rows[:q.limit]]
        audit(c, user['id'], 'read_admin_audit', 'user')
        return {'items': items, 'next_cursor': items[-1]['seq'] if len(rows) > q.limit else None}
