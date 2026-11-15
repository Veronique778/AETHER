import asyncio
import io
import math
import zipfile
from types import SimpleNamespace
import pytest
from app import db, biosignals as bio, mmash
from app.ble_sensor import Sensor, decode, HRS

@pytest.fixture(autouse=True)
def local_db(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'test.sqlite3');db.init_db();bio.init()

@pytest.fixture
def dataset(tmp_path):
    root=tmp_path/'DataPaper'/'user_1';root.mkdir(parents=True)
    (root/'RR.csv').write_text(',ibi_s,day,time\n1,0.8,1,23:59:59\n2,0.81,2,00:00:00\n3,,2,00:00:01\n4,30,2,00:00:02\n5,bad,2,00:00:03\n6,0.82,1,23:59:58\n')
    (root/'sleep.csv').write_text('In Bed Date,In Bed Time,Out Bed Date,Out Bed Time,Total Sleep Time (TST),Efficiency,Wake After Sleep Onset (WASO),Sleep Fragmentation Index\n1,23:00,2,07:00,400,83,40,12\n')
    return tmp_path/'DataPaper'

def test_original_schema_day_units_missing_provenance(dataset):
    assert mmash.inspect(dataset)['participants']==['user_1']
    s=mmash.import_mmash(dataset,'user_1',True)
    assert s['participant']=='MMASH:user_1' and s['source_type']=='research'
    with db.connect() as c:
        r=c.execute("SELECT * FROM bio_measurements WHERE signal='rr_interval' ORDER BY id").fetchall()
        assert r[0]['value']==800 and r[1]['t']-r[0]['t']==1
        assert r[0]['timestamp_utc'] is None and r[0]['timezone'] is None
        assert r[2]['value'] is None and r[2]['missing']
        assert not r[3]['valid'] and not r[-1]['valid']
        assert 'RR.csv' in r[0]['provenance']
    assert s['metadata']['corrupt_rows']==1
    assert s['metadata']['out_of_order_rows']==1
    a=bio.analyze(s['id']); assert a['outcome']=='insufficient_data'
    assert 'fatigue' in a['missing_channels']
    assert a['baseline_hr_bpm'] is None
    assert bio.points(s['id'])
    assert 'session_id' in bio.csv_page(s['id'])['csv']
    # Restart-like new DB connection, then actual deletion, including stored analysis.
    assert bio.session(s['id'])['channels']
    before=db.timeline('A01');bio.delete(s['id']);assert db.timeline('A01')==before
    for table in ('bio_measurements','bio_analysis','bio_sessions'):
        with db.connect() as c: assert c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0

def test_consent_schema_and_rollback(dataset):
    with pytest.raises(ValueError): mmash.import_mmash(dataset,'user_1',False)
    with pytest.raises(ValueError): mmash.import_mmash(dataset,'user_99',True)
    (dataset/'user_1'/'RR.csv').write_text('fake,columns\n1,2\n')
    with pytest.raises(ValueError,match='expected columns'): mmash.import_mmash(dataset,'user_1',True)
    assert not bio.sessions()

@pytest.mark.parametrize('name',['../secret.csv','/absolute.csv','C:/escape.csv','x/../../escape.csv'])
def test_zip_traversal(tmp_path,name):
    z=tmp_path/'bad.zip'
    with zipfile.ZipFile(z,'w') as f:f.writestr(name,'x')
    with pytest.raises(ValueError,match='Unsafe'): mmash.inspect(z)

def test_zip_import(dataset,tmp_path):
    z=tmp_path/'data.zip'
    with zipfile.ZipFile(z,'w') as f:
        for p in dataset.rglob('*.csv'): f.write(p,p.relative_to(dataset))
    assert mmash.import_mmash(z,'user_1',True)['channels']

@pytest.mark.parametrize('day,time', [('nan','00:00'),('1','24:00'),('1','12:60'),('1','12:00:60'),('-1','00:00')])
def test_bad_clocks(day,time):
    with pytest.raises(ValueError):mmash.clock(day,time)

def test_hrv_known_rr_sequence():
    rows=[(i*1.0,1000+(10 if i%2 else 0),True) for i in range(300)]
    f=bio.rr_features(rows)
    assert f['rmssd_ms']==pytest.approx(10)
    assert f['sdnn_ms']==pytest.approx(5.008354,rel=1e-6)
    assert bio.rr_features(rows[:10])['rmssd_ms'] is None
    assert bio.rr_features([(t,v,False) for t,v,_ in rows])['sdnn_ms'] is None

def test_hr_samples_never_hrv_and_fixed_baseline():
    sid=bio.create('fixture','research','synthetic unit-test fixture')
    rows=[bio.measurement(t,'heart_rate',60 if t<3600 else 90,'bpm') for t in range(0,4200,5)]
    bio.append(sid,rows);bio.finish(sid)
    a=bio.analyze(sid)
    assert a['baseline_hr_bpm']==60 and a['outcome']=='flag'
    assert a['flag_rate']==1 and all(w['hrv'] is None for w in a['windows'])
    assert a['noise_scale_bpm']==3
    assert len(a['windows'])==14

@pytest.mark.parametrize('packet,hr,contact,rr',[(bytes([0,72]),72,None,[]),(bytes([1,44,1]),300,None,[]),(bytes([22,60,0,4]),60,True,[1000]),(bytes([4,70]),70,False,[]),(bytes([24,65,7,0,0,2]),65,None,[500])])
def test_ble_decoding(packet,hr,contact,rr):
    p=decode(packet);assert p['heart_rate']==hr and p['contact']==contact and p['rr_ms']==rr

@pytest.mark.parametrize('packet',[b'',bytes([1,2]),bytes([16,60]),bytes([16,60,1]),bytes([8,60,1]),bytes([0,60,1])])
def test_ble_malformed(packet):
    with pytest.raises(ValueError):decode(packet)

class FakeClient:
    def __init__(self,device,disconnected_callback):self.callback=disconnected_callback;self.is_connected=False;self.notify=None
    async def connect(self):self.is_connected=True
    async def start_notify(self,characteristic,notify):self.notify=notify
    async def disconnect(self):self.is_connected=False;self.callback(self)

def test_ble_transport_end_to_end():
    async def scan():return {'test':(SimpleNamespace(name='TEST ONLY'),SimpleNamespace(service_uuids=[HRS]))}
    sensor=Sensor(FakeClient,scan,reconnect_delays=())
    try:
        assert sensor.call(sensor.scan())[0]['id']=='test'
        status=sensor.call(sensor.connect('test')); sid=status['session_id']; token=sensor.token
        sensor.client.notify(None,bytes([22,60,0,4]))
        assert sensor.status()['heart_rate']==60
        assert bio.session(sid)['source_type']=='live_sensor'
        assert bio.points(sid) and bio.analyze(sid)['outcome']=='insufficient_data'
        sensor.call(sensor.disconnect());assert sensor.status()['heart_rate'] is None
        count=bio.session(sid)['channels'][0]['total']
        sensor.notification(bytes([0,99]),token)
        assert bio.session(sid)['channels'][0]['total']==count
        sensor.call(sensor.connect('test'));assert sensor.state['session_id']!=sid
        sensor.notification(bytes([0,99]),token);assert sensor.status()['heart_rate'] is None
        sensor.client.notify(None,bytes([4,60]));assert sensor.status()['quality']=='no_contact'
        sensor.disconnected(sensor.token);assert sensor.status()['connection']=='disconnected'
    finally:
        sensor.call(sensor.disconnect());sensor.loop.call_soon_threadsafe(sensor.loop.stop)

def test_unavailable_sensor():
    async def broken():raise OSError('no radio')
    sensor=Sensor(scanner=broken)
    try:
        assert sensor.call(sensor.scan())==[]
        assert sensor.status()['connection']=='unavailable' and sensor.status()['heart_rate'] is None
    finally:sensor.loop.call_soon_threadsafe(sensor.loop.stop)

def test_api_parity_and_privacy(dataset):
    pytest.importorskip('fastapi', reason='FastAPI not installed in this environment')
    from fastapi.testclient import TestClient
    from app.main import app
    from app.devserver import serve
    import threading,urllib.request,json
    server=serve(port=0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        url='http://127.0.0.1:'+str(server.server_port)
        with TestClient(app, base_url='http://127.0.0.1', headers={'X-AETHER-Token': 'aether-test-token'}) as client:
            body={'path':str(dataset),'participant':'user_1','confirmed':True}
            r=client.post('/api/biosignals/mmash/import',json=body); assert r.status_code==200,r.text
            sid=r.json()['id']
            request=urllib.request.Request(url+'/api/biosignals/sessions/'+sid+'/analysis',data=b'{}',headers={'Content-Type':'application/json'})
            a=json.load(urllib.request.urlopen(request))
            assert a==client.get('/api/biosignals/sessions/'+sid+'/analysis').json()
            assert client.get('/api/biosignals/sessions',headers={'Origin':'https://evil.example'}).status_code==403
            assert client.post('/api/biosignals/mmash/import',json={'confirmed':False}).status_code==400
            assert client.delete('/api/biosignals/sessions/'+sid).status_code==200
    finally:server.shutdown();server.server_close()


def test_broad_ble_scan_does_not_treat_unverified_devices_as_compatible():
    """Unadvertised BLE is only a candidate; GATT must confirm profile."""
    async def scan():
        return {
            'generic': (SimpleNamespace(name='Watch'), SimpleNamespace(service_uuids=[])),
            'known': (SimpleNamespace(name='Chest strap'), SimpleNamespace(service_uuids=[HRS])),
        }
    sensor = Sensor(FakeClient, scan)
    try:
        narrow = sensor.call(sensor.scan(include_unadvertised=False))
        assert [x['id'] for x in narrow] == ['known']
        broad = sensor.call(sensor.scan(include_unadvertised=True))
        assert [x['id'] for x in broad] == ['known', 'generic']
        assert broad[-1]['advertised_hrs'] is False
        bad = sensor.call(sensor.connect('generic'))
        assert bad['connection'] == 'disconnected'
        assert 'does not expose' in bad['error']
        assert not bio.sessions()
    finally:
        sensor.loop.call_soon_threadsafe(sensor.loop.stop)
