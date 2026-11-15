"""Production dispatcher, canonical SQLite, real Argon2, real BE3 calculations; mock BLE transport only."""
from datetime import datetime,timedelta,timezone
import pytest
from test_api_security_15 import client,register
from app import db


def test_two_user_ble_phantom_and_restart(client):
    from app.devices import api
    from fakes.ble_mock import MockTransport,ManualClock,ManualScheduler
    manager=api.get_manager()
    transport=MockTransport();clock=ManualClock(datetime.now(timezone.utc)-timedelta(hours=3))
    manager.transport=transport;manager.clock=clock;manager.scheduler=ManualScheduler(clock)
    accounts=[register(client,'alice'),register(client,'bob')];results=[]
    for index,(registered,token) in enumerate(accounts):
        aid=registered['user']['astronaut_id'];address=f'TEST:BLE:{index}';transport.add(address)
        code,device=client('POST','/api/devices',{'name':'test strap','kind':'ble','external_id':address},token)
        assert code==201,device
        did=device['id']
        code,session=client('POST',f'/api/devices/{did}/connect',{'astronaut_id':aid},token)
        assert code==200,session
        for n in range(2700):
            manager.scheduler.advance(2)
            transport.link(address).hr(62 if n<1800 or index else 90,(1024,),True)
        code,off=client('POST',f'/api/devices/{did}/disconnect',{},token)
        assert code==200 and off['pending_rows']==0,off
        sid=session['session_id']
        with db.connect() as c:
            rows=c.execute('SELECT written_via,origin,quality FROM raw_measurements WHERE astronaut_id=?',(aid,)).fetchall()
            assert len(rows)==5400
            assert all(tuple(r)==('device_manager','real','screened') for r in rows)
        body={'astronaut_id':aid,'session_id':sid}
        code,result=client('POST','/api/phantom-analyses',body,token)
        assert code==201,result
        assert result['outcome']==('flag' if index==0 else 'no_flag')
        assert result['storage']['input_count']==5400 and result['storage']['input_ids_stored']==5400
        assert result['input']['data_classes']==['real_wearable']
        code,replay=client('POST','/api/phantom-analyses',body,token)
        assert code==200 and replay['analysis_id']==result['analysis_id'],replay
        results.append(result)
    assert results[0]['analysis_id']!=results[1]['analysis_id']
    assert client('GET','/api/phantom-analyses/'+results[1]['analysis_id'],token=accounts[0][1])[0]==404
    # Reopen all connections and reapply migrations to the same persisted database.
    # Full process restart is separately exercised by the subprocess regression suite.
    client.restart()
    db.init_db()
    for (_,token),result in zip(accounts,results):
        code,stored=client('GET','/api/phantom-analyses/'+result['analysis_id'],token=token)
        assert code==200 and stored['input']['measurement_digest']==result['input']['measurement_digest']
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM analysis_evidence').fetchone()[0]==2
        assert c.execute("SELECT COUNT(*) FROM science_records WHERE kind='phantom_analysis'").fetchone()[0]==2
        assert not c.execute('PRAGMA foreign_key_check').fetchall()

@pytest.mark.parametrize('metadata',[{'data_class':'real_wearable'},{'contact':True},{'be3_quality':'good'},{'nested':{'contact':True}},{'written_via':'device_manager'}])
def test_public_provenance_forgery(client,metadata):
    _,token=register(client)
    from helpers_be2_15 import measurement
    code,body=client('POST','/api/measurements',measurement(metadata=metadata),token)
    assert code==422 and body['error']['code']=='reserved_provenance'


def test_registry_owner_and_soft_removal(client):
    a,t=register(client,'alice');_,other=register(client,'bob')
    code,d=client('POST','/api/devices',{'name':'strap','kind':'ble','external_id':'REG:01'},t)
    did=d['id'];assert code==201
    assert client('PATCH',f'/api/devices/{did}',{'name':'stolen'},other)[0]==404
    assert client('PATCH',f'/api/devices/{did}',{'astronaut_id':a['user']['astronaut_id']},t)[0]==422
    assert client('PATCH',f'/api/devices/{did}',{'name':'renamed'},t)[0]==200
    assert client('DELETE',f'/api/devices/{did}',token=other)[0]==404
    assert client('DELETE',f'/api/devices/{did}',token=t)[0]==200
    assert client('GET','/api/devices',token=t)[1]['items']==[]
    with db.connect() as c:assert c.execute('SELECT 1 FROM devices WHERE id=?',(did,)).fetchone()


def test_logout_stops_recording_preserves_commits(client):
    from app.devices import api
    from fakes.ble_mock import MockTransport,ManualClock,ManualScheduler
    a,t=register(client);aid=a['user']['astronaut_id'];m=api.get_manager()
    transport=MockTransport();transport.add('EXP:01');clock=ManualClock(datetime.now(timezone.utc)-timedelta(hours=1))
    m.transport=transport;m.clock=clock;m.scheduler=ManualScheduler(clock)
    _,d=client('POST','/api/devices',{'name':'strap','kind':'ble','external_id':'EXP:01'},t)
    code,s=client('POST',f"/api/devices/{d['id']}/connect",{'astronaut_id':aid},t);assert code==200,s
    transport.link('EXP:01').hr(60,(1024,),True);m.flush(d['id'])
    assert client('POST','/api/auth/logout',{},t)[0]==200
    m.flush(d['id'])
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM raw_measurements WHERE astronaut_id=?',(aid,)).fetchone()[0]==2
        assert c.execute('SELECT status FROM session_end_states WHERE session_id=?',(s['session_id'],)).fetchone()[0]=='failed'
    assert m._slots[d['id']].state.value=='disconnected'
    client.restart()
    with db.connect() as c:assert c.execute('SELECT status FROM session_end_states WHERE session_id=?',(s['session_id'],)).fetchone()[0]=='failed'


def test_atomic_bundle_failure_replay_concurrency(client):
    from concurrent.futures import ThreadPoolExecutor
    a,t=register(client);aid=a['user']['astronaut_id']
    _,session=client('POST','/api/sensor-sessions',{'source':'manual','origin':'manual','started_at':'2026-11-01T00:00:00Z'},t)
    sid=session['id']
    from helpers_be2_15 import measurement
    code,_=client('POST','/api/measurements',measurement(session_id=sid),t);assert code==201
    body={'astronaut_id':aid,'session_id':sid,'data_classes':['manual']}
    for table in ('analysis_evidence','science_records','audit_logs'):
        with db.connect() as c:
            condition=" WHEN NEW.resource_type='analysis'" if table=='audit_logs' else ''
            c.execute(f"CREATE TRIGGER fail_bundle BEFORE INSERT ON {table}{condition} BEGIN SELECT RAISE(ABORT,'injected'); END")
        code,result=client('POST','/api/phantom-analyses',body,t)
        assert code==503,result
        with db.connect() as c:
            assert c.execute('SELECT COUNT(*) FROM analysis_runs').fetchone()[0]==0
            assert c.execute('SELECT COUNT(*) FROM analysis_evidence').fetchone()[0]==0
            assert c.execute('SELECT COUNT(*) FROM science_records').fetchone()[0]==0
            c.execute('DROP TRIGGER fail_bundle')
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies=list(pool.map(lambda _:client('POST','/api/phantom-analyses',body,t),range(4)))
    assert sorted(code for code,_ in replies)==[200,200,200,201],replies
    assert len({r['analysis_id'] for _,r in replies})==1
    assert all(r['outcome']=='insufficient_data' for _,r in replies)
    client.restart()
    code,result=client('POST','/api/phantom-analyses',body,t)
    assert code==200 and result['idempotent_replay']


def test_contract_and_capabilities(client):
    from jsonschema import Draft202012Validator
    _,t=register(client)
    code,contract=client('GET','/api/contract');assert code==200
    assert '/api/phantom-analyses' in contract['paths']
    for path in ('/api/signals','/api/phantom-analyses'):
        code,body=client('GET',path,token=t);assert code==200
        Draft202012Validator(contract['paths'][path]['get']['responses']['200']['content']['application/json']['schema']).validate(body)
    code,health=client('GET','/api/health');assert code==200
    Draft202012Validator(contract['paths']['/api/health']['get']['responses']['200']['content']['application/json']['schema']).validate(health)
    assert health['feature_status']['phantom']['available']
    assert not health['feature_status']['ble']['hardware_verified']


def test_device_database_outage_retry_contact_quality(client):
    from app.devices import api
    from fakes.ble_mock import MockTransport,ManualClock,ManualScheduler
    a,t=register(client);aid=a['user']['astronaut_id'];m=api.get_manager()
    tr=MockTransport();tr.add('DB:01');clock=ManualClock(datetime.now(timezone.utc)-timedelta(hours=1))
    m.transport=tr;m.clock=clock;m.scheduler=ManualScheduler(clock)
    _,d=client('POST','/api/devices',{'name':'strap','kind':'ble','external_id':'DB:01'},t)
    code,s=client('POST',f"/api/devices/{d['id']}/connect",{'astronaut_id':aid},t);assert code==200
    with db.connect() as c:c.execute("CREATE TRIGGER fail_raw BEFORE INSERT ON raw_measurements BEGIN SELECT RAISE(ABORT,'injected'); END")
    tr.link('DB:01').hr(60,(1024,),False)
    assert m.flush(d['id'])==0 and len(m._slots[d['id']].pending)==2
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM raw_measurements WHERE astronaut_id=?',(aid,)).fetchone()[0]==0
        c.execute('DROP TRIGGER fail_raw')
    assert m.flush(d['id'])==2
    assert m.flush(d['id'])==0
    with db.connect() as c:
        rows=c.execute('SELECT quality,written_via FROM raw_measurements WHERE astronaut_id=?',(aid,)).fetchall()
        assert len(rows)==2 and all(tuple(r)==('no_contact','device_manager') for r in rows)
    assert client('POST',f"/api/devices/{d['id']}/disconnect",{},t)[0]==200


def test_public_source_and_device_do_not_attest_wearable(client):
    from helpers_be2_15 import measurement
    from app.persistence import science_storage
    from app.science_storage_be2 import Be2Context
    a,t=register(client,'alice');b,v=register(client,'bob')
    _,d=client('POST','/api/devices',{'name':'strap','kind':'ble','external_id':'SPOOF:01'},v)
    _,foreign_session=client('POST','/api/sensor-sessions',{'device_id':d['id'],'source':'BLE','origin':'real','started_at':'2026-01-01T00:00:00Z'},v)
    assert client('POST','/api/measurements',measurement(device_id=d['id'],session_id=foreign_session['id'],origin='real',source='authenticated device manager'),t)[0]==404
    _,own=client('POST','/api/devices',{'name':'strap','kind':'ble','external_id':'SPOOF:02'},t)
    _,own_session=client('POST','/api/sensor-sessions',{'device_id':own['id'],'source':'BLE','origin':'real','started_at':'2026-01-01T00:00:00Z'},t)
    code,saved=client('POST','/api/measurements',measurement(device_id=own['id'],session_id=own_session['id'],origin='real',source='authenticated device manager'),t)
    assert code==201
    row=science_storage().query_measurements(Be2Context(t),a['user']['astronaut_id'])['items'][0]
    assert row['data_class']=='real_unclassified'
    assert row['provenance'].get('contact') is not True
    assert row['measurement_id']==saved['measurement']['id']


def test_actual_phantom_medical_access_revocation(client):
    from integration_support_15 import admin_account
    from helpers_be2_15 import measurement
    a,t=register(client,'alice');officer,med=register(client,'medic');_,admin=admin_account(client)
    _,mission=client('POST','/api/missions',{'name':'ACL mission'},admin);mid=mission['id']
    for person,role in [(a['user'],'astronaut'),(officer['user'],'medical_officer')]:
        assert client('POST',f'/api/missions/{mid}/crew',{'user_id':person['id'],'role':role},admin)[0]==200
    _,session=client('POST','/api/sensor-sessions',{'source':'manual','origin':'manual','mission_id':mid,'started_at':'2026-01-01T00:00:00Z'},t)
    assert client('POST','/api/measurements',measurement(session_id=session['id'],mission_id=mid),t)[0]==201
    request={'astronaut_id':a['user']['astronaut_id'],'session_id':session['id'],'mission_id':mid,'data_classes':['manual']}
    code,run=client('POST','/api/phantom-analyses',request,t);assert code==201,run
    path='/api/phantom-analyses/'+run['analysis_id']
    assert client('GET',path,token=admin)[0]==404
    assert client('GET',path,token=med)[0]==404
    grant={'officer_id':officer['user']['id'],'astronaut_id':a['user']['astronaut_id'],'can_review':True}
    assert client('POST',f'/api/missions/{mid}/medical-access',grant,admin)[0]==200
    assert client('GET',path,token=med)[0]==200
    assert client('POST','/api/phantom-analyses',request,med)[0]==404
    assert client('DELETE',f"/api/missions/{mid}/medical-access/{officer['user']['id']}/{a['user']['astronaut_id']}",token=admin)[0]==200
    assert client('GET',path,token=med)[0]==404
