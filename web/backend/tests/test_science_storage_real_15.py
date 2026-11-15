"""Canonical 03A protocol on real SQLite/Argon2; no FakeStorage or dispatcher patch."""
import uuid
import pytest
from app import db, auth, science_storage
from app.persistence import science_storage as factory
from app.science_storage_be2 import Be2Context as RequestContext
from app.science_errors import ScienceError
from tests.helpers_be2_15 import account

@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'real.db');db.init_db()
    a,t,_=account('sciencealice');b,v,_=account('sciencebob')
    return factory(),RequestContext(t),RequestContext(v)

def item(ctx,key='one',**kw):
    return dict(client_measurement_id=key,astronaut_id=ctx.astronaut_id,signal='heart_rate',value=65,unit='bpm',recorded_at='2026-11-15T10:00:00+02:00',quality='good',data_class='manual',source='test manual',**kw)

def test_conformance_and_batch(setup):
    s,a,b=setup
    assert not science_storage.conformance(s)
    assert type(science_storage.resolve()) is type(s)
    rows=[item(a,str(i)) for i in range(120)]
    first=s.save_measurements(a,rows);assert first['saved']==120
    assert s.save_measurements(a,rows)['duplicates']==120
    bad=rows[0].copy();bad['value']=70
    with pytest.raises(ScienceError) as e:s.save_measurements(a,[item(a,'new'),bad])
    assert e.value.status==409
    page=s.query_measurements(a,a.astronaut_id,limit=40);seen=page['items']
    while page['next_cursor']:
        page=s.query_measurements(a,a.astronaut_id,limit=40,cursor=page['next_cursor']);seen+=page['items']
    assert len(seen)==120
    assert seen==sorted(seen,key=lambda r:(r['recorded_at'],r['measurement_id']))
    assert seen[0]['recorded_at']=='2026-11-15T08:00:00.000Z'
    with pytest.raises(ScienceError):s.query_measurements(b,a.astronaut_id)
    db.init_db();assert len(s.query_measurements(a,a.astronaut_id)['items'])==120
    with db.connect() as c: assert not c.execute('PRAGMA foreign_key_check').fetchall()

def test_devices_sessions_recovery(setup):
    s,a,b=setup
    d=s.upsert_device(a,{'astronaut_id':a.astronaut_id,'name':'strap','hardware_address':'AA:01'})
    e=s.upsert_device(b,{'astronaut_id':b.astronaut_id,'name':'strap','hardware_address':'AA:02'})
    sid=s.create_session(a,a.astronaut_id,'live_sensor','BLE HRS',device_id=d['device_id'])
    sid2=s.create_session(b,b.astronaut_id,'live_sensor','BLE HRS',device_id=e['device_id'])
    with pytest.raises(ScienceError):s.get_device(b,d['device_id'])
    with pytest.raises(ScienceError):s.finish_session(b,sid,'saved')
    assert len(s.list_sessions(a,status='recording'))==1
    assert len(s.list_sessions(b,status='recording'))==1
    s.finish_session(a,sid,'interrupted')
    assert s.get_session(a,sid)['status']=='interrupted'
    assert s.get_session(b,sid2)['status']=='recording'
    auth.logout(auth.authenticate(a._token),a._token)
    with pytest.raises(ScienceError) as x:s.list_devices(a)
    assert x.value.status==401

@pytest.mark.parametrize('signal,value,unit,raw_value,raw_unit',[
 ('sleep_duration',7.5,'h',27000,'s'),('rr_interval',900,'ms',900,'ms'),('fatigue',None,'score_1_10',None,'score')])
def test_units_null(setup,signal,value,unit,raw_value,raw_unit):
    s,a,_=setup;row=item(a);row.update(signal=signal,value=value,unit=unit)
    out=s.save_measurements(a,[row])['items'][0]
    assert out['value']==raw_value and out['unit']==raw_unit
    with db.connect() as c:
        r=c.execute('SELECT * FROM raw_measurements WHERE id=?',(out['measurement_id'],)).fetchone()
        assert (r['value'],r['unit'])==(raw_value,raw_unit)
    if value is None:assert out['missing'] and not out['valid']

def test_database_failure_rolls_back(setup):
    s,a,_=setup
    with db.connect() as c:c.execute("CREATE TRIGGER fail_science BEFORE INSERT ON raw_measurements BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(ScienceError) as e:s.save_measurements(a,[item(a)])
    assert e.value.status==503
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM raw_measurements WHERE astronaut_id=?',(a.astronaut_id,)).fetchone()[0]==0
        c.execute('DROP TRIGGER fail_science')
    assert s.save_measurements(a,[item(a)])['saved']==1

def test_demo_and_forged_context_rejected(setup):
    s,a,_=setup
    from types import SimpleNamespace
    with pytest.raises(ScienceError):s.list_devices(SimpleNamespace(user_id=a.user_id,role='admin'))
    with pytest.raises(ScienceError):s.query_measurements(a,'A01')

def test_shared_dispatch_uuid_supported(setup):
    from app.api_15 import dispatch
    import json
    s,a,b=setup
    h={'authorization':'Bearer '+a._token,'content-type':'application/json'}
    status,result=dispatch('GET','/api/signals',h,b'',{})
    assert status==200
    status,result=dispatch('POST','/api/phantom-analyses',h,json.dumps({'astronaut_id':a.astronaut_id,'from':'2026-11-15T08:00:00Z','to':'2026-11-15T09:00:00Z','data_classes':['manual']}).encode(),{})
    assert status==201 and result['outcome']=='insufficient_data'
    status,_=dispatch('POST','/api/phantom-analyses',h,json.dumps({'astronaut_id':b.astronaut_id,'from':'2026-11-15T08:00:00Z','to':'2026-11-15T09:00:00Z'}).encode(),{})
    assert status==404

@pytest.mark.parametrize('failure_table',['science_records','analysis_evidence','audit_logs'])
def test_atomic_analysis_failure_and_restart(setup,failure_table):
    from app import phantom_analyses as p
    s,a,b=setup
    s.save_measurements(a,[item(a)])
    request={'astronaut_id':a.astronaut_id,'from':'2026-11-15T08:00:00Z','to':'2026-11-15T09:30:00Z','data_classes':['manual']}
    with db.connect() as c:c.execute(f"CREATE TRIGGER fail_bundle BEFORE INSERT ON {failure_table} BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(ScienceError):p.run(a,request,s)
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM analysis_runs').fetchone()[0]==0
        assert c.execute("SELECT COUNT(*) FROM science_records WHERE kind='phantom_analysis'").fetchone()[0]==0
        c.execute('DROP TRIGGER fail_bundle')
    _,result=p.run(a,request,s)
    assert result['outcome']=='insufficient_data'
    rid=result['analysis_id']
    assert p.run(a,request,s)[1]['analysis_id']==rid
    db.init_db();assert s.get_analysis(a,rid)['analysis_id']==rid
    with pytest.raises(ScienceError):s.get_analysis(b,rid)

def test_manager_startup_recovers_real_sqlite(setup):
    from app.persistence import science_lifecycle as lifecycle
    s,a,_=setup
    d=s.upsert_device(a,{'astronaut_id':a.astronaut_id,'name':'strap','hardware_address':'AA:03'})
    sid=s.create_session(a,a.astronaut_id,'live_sensor','BLE',device_id=d['device_id'])
    # Other legacy server tests may leave a process-level manager acquired.
    # Isolate this startup test from that unrelated server's lifecycle.
    while lifecycle._USERS: lifecycle.stop()
    lifecycle.start()
    try:assert s.get_session(a,sid)['status']=='recovered'
    finally:lifecycle.stop()

@pytest.mark.parametrize('after,expected',[(62,'no_flag'),(90,'flag')])
def test_real_science_computation_from_personal_sqlite(setup,after,expected):
    from collections import Counter
    from datetime import datetime,timedelta,timezone
    from app import phantom_analyses as p
    s,a,_=setup;start=datetime(2026,11,15,8,tzinfo=timezone.utc)
    rows=[]
    for i in range(540):
        row=item(a,str(i));row.update(value=62 if i<360 else after,recorded_at=(start+timedelta(seconds=10*i)).isoformat())
        rows.append(row)
    s.save_measurements(a,rows[:500]);s.save_measurements(a,rows[500:])
    data=s.query_measurements(a,a.astronaut_id)['items']
    req={'from':start,'to':start+timedelta(minutes=90),'baseline_mode':'first_hour'}
    counter=Counter();screened=p._screen(data,a.astronaut_id,['manual'],counter)
    result=p.compute(req,screened,None,counter)
    assert result['outcome']==expected

def test_real_ble_parser_manager_flush_component(setup):
    """Only BLE hardware/clock are simulated; normal connect/parser/persistence path."""
    from app.persistence.recording_lifecycle_06 import ManagedDeviceManager
    from tests.fakes.ble_mock import MockTransport,ManualClock,ManualScheduler
    s,a,_=setup;clock=ManualClock();scheduler=ManualScheduler(clock)
    transport=MockTransport();transport.add('TEST:04')
    manager=ManagedDeviceManager(s,transport,clock=clock,scheduler=scheduler)
    d=s.upsert_device(a,{'astronaut_id':a.astronaut_id,'name':'test strap','hardware_address':'TEST:04'})
    session=manager.connect(a,d['device_id'],{'astronaut_id':a.astronaut_id})
    for _ in range(60):
        transport.link('TEST:04').hr(60,(1024,),True);scheduler.advance(1)
    manager.flush(d['device_id'])
    rows=s.query_measurements(a,a.astronaut_id,session_id=session['session_id'])['items']
    assert len(rows)==120
    assert {r['value'] for r in rows if r['signal']=='rr_interval'}=={1000.0}
    assert all(r['quality']=='good' and r['provenance']['contact'] is True for r in rows)
    manager.shutdown();assert s.get_session(a,session['session_id'])['status']=='saved'


def test_order_filter_cursor_null_and_history(setup):
    s,a,b=setup
    rows=[]
    for i in range(12):
        row=item(a,str(i));row['recorded_at']=f'2026-11-15T08:{11-i:02}:00Z'
        if i%2:row.update(signal='rr_interval',value=1000,unit='ms')
        rows.append(row)
    s.save_measurements(a,rows)
    page=s.query_measurements(a,a.astronaut_id,signals=['heart_rate'],limit=2);seen=page['items']
    while page['next_cursor']:
        page=s.query_measurements(a,a.astronaut_id,signals=['heart_rate'],limit=2,cursor=page['next_cursor']);seen+=page['items']
    assert len(seen)==6 and seen==sorted(seen,key=lambda r:(r['recorded_at'],r['measurement_id']))
    with pytest.raises(ScienceError):s.query_measurements(a,a.astronaut_id,cursor=str(uuid.uuid4()))
    with pytest.raises(ScienceError):s.log_record(b,'measurement',[seen[0]['measurement_id']],a.astronaut_id,'manual','secret')
    rid=s.log_record(a,'measurement',[seen[0]['measurement_id']],a.astronaut_id,'manual','private free text')
    with db.connect() as c:
        row=c.execute('SELECT * FROM science_records WHERE record_id=?',(rid,)).fetchone()
        assert row['summary']=='measurement recorded'
    with pytest.raises(ScienceError):s.finish_session(a,str(uuid.uuid4()),'arbitrary state')


def test_second_surface_reuses_lifecycle_manager(setup):
    from app.persistence import science_lifecycle as lifecycle
    from app.devices import api
    while lifecycle._USERS:lifecycle.stop()
    lifecycle.start()
    first=lifecycle._MANAGER
    try:
        api.set_manager(None)  # Simulate an external consumer releasing its binding.
        lifecycle.start()
        assert api.get_manager() is first
        assert type(first).__name__=='ManagedDeviceManager'
        lifecycle.stop()
        assert api.get_manager() is first
    finally:
        lifecycle.stop()


def test_writer_class_and_conflict_type(setup):
    from app.science_errors import Conflict
    s,a,_=setup
    m=item(a,'manual');synthetic=item(a,'synthetic');synthetic['data_class']='synthetic'
    s.save_measurements(a,[m,synthetic])
    with db.connect() as c:
        rows=c.execute('SELECT origin,written_via FROM raw_measurements WHERE astronaut_id=? ORDER BY origin',(a.astronaut_id,)).fetchall()
        assert [tuple(r) for r in rows]==[('manual','api'),('simulated','synthetic_generator')]
    with pytest.raises(Conflict) as exc:s.save_measurements(a,[{**m,'value':70}])
    assert exc.value.status==409
