"""Local OS-operator action: python -m app.auth.admin LOGIN --role administrator.
No remote bootstrap or automatic administrator registration exists.
"""
import argparse
from app import db
from app.persistence.common import audit, utcnow


def set_role(login,role):
    if role not in ('administrator','astronaut'): raise ValueError('Invalid role')
    db.init_db()
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT id FROM users WHERE login=?',(login,)).fetchone()
        if not row: raise ValueError('User not found; register an account first')
        c.execute('UPDATE users SET role=? WHERE id=?',(role,row[0]))
        c.execute('UPDATE auth_sessions SET revoked_at=? WHERE user_id=?',(utcnow(),row[0]))
        audit(c,None,'operator_set_role','user',row[0])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('login'); p.add_argument('--role',choices=['administrator','astronaut'],required=True)
    a=p.parse_args(); set_role(a.login,a.role)
    print('Role updated. Sign in again.')
