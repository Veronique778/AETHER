from pathlib import Path
from app import db,auth
from app.persistence import repository as repo

PASSWORD='Correct-Horse-Planet-42'


def account(name='alice',peer=None):
    result=auth.register(name,PASSWORD,name,peer=peer or name)
    token=auth.login(name,PASSWORD,peer=peer or name)['access_token']
    return auth.authenticate(token),token,result['recovery_code']


def measurement(key='sample-1',**changes):
    result={'idempotency_key':key,'source':'manual form','signal':'heart_rate','value':65.0,'unit':'bpm',
            'measured_at':'2026-11-15T10:00:00+02:00','origin':'manual'}
    result.update(changes)
    return result
