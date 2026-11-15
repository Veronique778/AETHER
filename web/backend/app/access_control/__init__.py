"""Explicit object authorization. Administrator is not a medical superuser."""
from app.persistence.common import APIError


def admin(user):
    if user['role'] != 'administrator':
        raise APIError(403,'forbidden','Administrator role required')


def profile(c, user, astronaut_id=None, write=False, mission_id=None, review=False):
    aid = astronaut_id or user['astronaut_id']
    row = c.execute("SELECT * FROM astronaut_profiles WHERE id=? AND data_class='personal'",(aid,)).fetchone()
    if row is None: raise APIError(404,'not_found','Resource not found')
    if row['user_id'] == user['id'] and not review: return aid
    if not write and mission_id:
        grant = c.execute('''SELECT g.can_review FROM medical_access g
          JOIN crew_memberships o ON o.mission_id=g.mission_id AND o.user_id=g.officer_id AND o.role='medical_officer'
          JOIN crew_memberships a ON a.mission_id=g.mission_id AND a.user_id=?
          WHERE g.officer_id=? AND g.astronaut_id=? AND g.mission_id=?''',
          (row['user_id'],user['id'],aid,mission_id)).fetchone()
        if grant and (not review or grant['can_review']): return aid
    # Hide existence as well as contents from other accounts.
    raise APIError(404,'not_found','Resource not found')


def mission(c, user, mission_id):
    if mission_id is not None and not c.execute('SELECT 1 FROM crew_memberships WHERE user_id=? AND mission_id=?',(user['id'],mission_id)).fetchone():
        raise APIError(403,'mission_access','Mission membership required')
