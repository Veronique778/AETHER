import time
from pathlib import Path
import pytest
from app import db
from app.persistence import sync,repository as repo
from app.persistence.common import APIError
from app.schemas_15 import HistoryQuery
from helpers_be2_15 import account,measurement

@pytest.fixture(autouse=True)
def database(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'local.db'); db.init_db()


def test_disconnection_retry_and_duplicate_ack_loss(tmp_path,monkeypatch):
    local=Path(db.DB_PATH); a,_,_=account('alice')
    repo.add_measurements(a,[measurement()])
    def offline(*args): raise OSError('private payload MUST NOT be logged')
    assert sync.sync_once(a,'https://central.example','secret',offline)
    assert sync.status(a)['unsent']==1
    event=sync.pending(a)['items'][0]
    assert sync.history(a)['items'][0]['error_code']=='transport_error'
    sync.retry(a,event['id'])
    central=tmp_path/'central.db'; monkeypatch.setattr(db,'DB_PATH',central); db.init_db(); b,_,_=account('alice')
    monkeypatch.setattr(db,'DB_PATH',local)
    attempts=[]
    def deliver(url,token,payload):
        monkeypatch.setattr(db,'DB_PATH',central)
        try: result=sync.receive(b,payload)
        finally: monkeypatch.setattr(db,'DB_PATH',local)
        attempts.append(result)
        if len(attempts)==1: raise OSError('lost acknowledgement')
        return result
    sync.sync_once(a,'https://central.example','secret',deliver)
    sync.retry(a,event['id']); sync.sync_once(a,'https://central.example','secret',deliver)
    assert sync.status(a)['unsent']==0
    assert attempts[0]['accepted'][0]['created'] is True and attempts[1]['accepted'][0]['created'] is False
    monkeypatch.setattr(db,'DB_PATH',central)
    assert len(repo.list_measurements(b,HistoryQuery())['items'])==1
    assert sync.status(b)['unsent']==0


def test_sync_conflicts_recorded_and_not_silently_overwritten():
    u,_,_=account(); repo.add_measurements(u,[measurement()])
    def conflict(*args): raise APIError(409,'conflict','sensitive information')
    sync.sync_once(u,'https://central.example','secret',conflict)
    assert sync.status(u)['counts']['conflict']==1
    assert 'sensitive' not in str(sync.history(u))


def test_expired_worker_lease_recovers_and_others_cannot_claim():
    a,_,_=account('alice'); b,_,_=account('bob'); repo.add_measurements(a,[measurement()])
    assert sync._claim(b) is None
    first=sync._claim(a); assert sync._claim(a) is None
    with db.connect() as c: c.execute('UPDATE sync_events SET lease_until=0')
    second=sync._claim(a); assert first[0]['id']==second[0]['id'] and first[1]!=second[1]
    sync._finish(first[0],first[1],'sent')
    assert sync.status(a)['counts']['sending']==1
    sync._finish(second[0],second[1],'sent'); assert sync.status(a)['unsent']==0


def test_receiver_rejects_foreign_ownership():
    a,_,_=account('alice'); b,_,_=account('bob')
    item=measurement(id='remote-1',astronaut_id=a['astronaut_id'])
    with pytest.raises(APIError): sync.receive(b,{'events':[{'measurement':item}]})


@pytest.mark.parametrize('url',['http://server','https://user:pass@server','https://server?token=secret','file:///tmp/x'])
def test_remote_transport_requires_https_no_credentials(url):
    with pytest.raises(ValueError): sync.send_https(url,'secret',{})


def test_real_device_and_session_synced(tmp_path,monkeypatch):
    local=Path(db.DB_PATH); a,_,_=account(); d=repo.create_device(a,{'name':'Band','kind':'ble'})
    s=repo.create_session(a,{'source':'Band','origin':'real','device_id':d['id'],'started_at':'2026-01-01T00:00:00Z'})
    repo.add_measurements(a,[measurement(origin='real',device_id=d['id'],session_id=s['id'])])
    event,claim,payload=sync._claim(a)
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'central.db');db.init_db(); b,_,_=account()
    sync.receive(b,payload); sync.receive(b,payload)
    assert repo.list_devices(b)['items'][0]['id']==d['id']
    assert len(repo.device_sessions(b,d['id'],HistoryQuery())['items'])==1
    assert len(repo.list_measurements(b,HistoryQuery())['items'])==1


def test_mission_mapping_is_explicit_and_does_not_change_local_records(tmp_path,monkeypatch):
    from app.persistence import missions
    local=Path(db.DB_PATH);a,_,_=account()
    a['role']='administrator'
    first=missions.create_mission(a,{'name':'local'})['id']
    missions.membership(a,first,{'user_id':a['id'],'role':'astronaut'})
    repo.add_measurements(a,[measurement(mission_id=first)])
    central=tmp_path/'central.db';monkeypatch.setattr(db,'DB_PATH',central);db.init_db();b,_,_=account()
    b['role']='administrator';second=missions.create_mission(b,{'name':'central'})['id']
    missions.membership(b,second,{'user_id':b['id'],'role':'astronaut'})
    monkeypatch.setattr(db,'DB_PATH',local)
    def deliver(url,token,payload):
        monkeypatch.setattr(db,'DB_PATH',central)
        try:return sync.receive(b,payload)
        finally:monkeypatch.setattr(db,'DB_PATH',local)
    sync.sync_once(a,'https://central.example','token',deliver,mission_map={first:second})
    assert sync.status(a)['unsent']==0
    assert repo.list_measurements(a,HistoryQuery())['items'][0]['mission_id']==first
    monkeypatch.setattr(db,'DB_PATH',central)
    assert repo.list_measurements(b,HistoryQuery())['items'][0]['mission_id']==second
