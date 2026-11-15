"""Mission administration and explicit medical assignments."""
from app import db
from app import access_control as acl
from .common import APIError, audit, uid, utcnow


def list_missions(user):
    with db.connect() as c:
        if user['role']=='administrator': rows=c.execute('SELECT * FROM missions ORDER BY created_at').fetchall()
        else: rows=c.execute('SELECT m.* FROM missions m JOIN crew_memberships x ON m.id=x.mission_id WHERE x.user_id=? ORDER BY m.created_at',(user['id'],)).fetchall()
        audit(c,user['id'],'list','mission')
        return {'items':[dict(r) for r in rows]}


def create_mission(user,d):
    acl.admin(user)
    with db.connect() as c:
        mid=uid(); c.execute('INSERT INTO missions VALUES(?,?,?)',(mid,d['name'],utcnow()))
        audit(c,user['id'],'create','mission',mid)
        return dict(c.execute('SELECT * FROM missions WHERE id=?',(mid,)).fetchone())


def crew(user,mid):
    with db.connect() as c:
        if user['role']!='administrator': acl.mission(c,user,mid)
        if not c.execute('SELECT 1 FROM missions WHERE id=?',(mid,)).fetchone(): raise APIError(404,'not_found','Mission not found')
        rows=c.execute('''SELECT p.id AS astronaut_id,p.display_name,x.user_id,x.role FROM crew_memberships x
          JOIN astronaut_profiles p ON p.user_id=x.user_id WHERE x.mission_id=? ORDER BY p.id''',(mid,)).fetchall()
        audit(c,user['id'],'list','crew',mid)
        return {'items':[dict(r) for r in rows]}


def membership(user,mid,d):
    acl.admin(user)
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM missions WHERE id=?',(mid,)).fetchone() or not c.execute('SELECT 1 FROM users WHERE id=?',(d['user_id'],)).fetchone():
            raise APIError(404,'not_found','Mission or user not found')
        c.execute('INSERT INTO crew_memberships VALUES(?,?,?) ON CONFLICT(mission_id,user_id) DO UPDATE SET role=excluded.role',(mid,d['user_id'],d['role']))
        if d['role']!='medical_officer': c.execute('DELETE FROM medical_access WHERE mission_id=? AND officer_id=?',(mid,d['user_id']))
        audit(c,user['id'],'set_membership','mission',mid)
    return {'saved':True}


def remove_member(user,mid,member_id):
    acl.admin(user)
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('DELETE FROM medical_access WHERE mission_id=? AND (officer_id=? OR astronaut_id IN (SELECT id FROM astronaut_profiles WHERE user_id=?))',(mid,member_id,member_id))
        c.execute('DELETE FROM crew_memberships WHERE mission_id=? AND user_id=?',(mid,member_id))
        audit(c,user['id'],'remove_membership','mission',mid)
    return {'removed':True}


def grant(user,mid,d):
    acl.admin(user)
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        officer=c.execute("SELECT 1 FROM crew_memberships WHERE mission_id=? AND user_id=? AND role='medical_officer'",(mid,d['officer_id'])).fetchone()
        member=c.execute('''SELECT 1 FROM crew_memberships x JOIN astronaut_profiles p ON x.user_id=p.user_id
          WHERE x.mission_id=? AND p.id=?''',(mid,d['astronaut_id'])).fetchone()
        if not officer or not member: raise APIError(422,'assignment_invalid','Both users must be mission members; reviewer must be a medical officer')
        c.execute('INSERT INTO medical_access VALUES(?,?,?,?) ON CONFLICT(mission_id,officer_id,astronaut_id) DO UPDATE SET can_review=excluded.can_review',
                  (mid,d['officer_id'],d['astronaut_id'],int(d['can_review'])))
        audit(c,user['id'],'grant_medical_access','profile',d['astronaut_id'])
    return {'granted':True}


def revoke(user,mid,officer_id,astronaut_id):
    acl.admin(user)
    with db.connect() as c:
        c.execute('DELETE FROM medical_access WHERE mission_id=? AND officer_id=? AND astronaut_id=?',(mid,officer_id,astronaut_id))
        audit(c,user['id'],'revoke_medical_access','profile',astronaut_id)
    return {'revoked':True}
