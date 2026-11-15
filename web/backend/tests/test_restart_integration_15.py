"""Real scientific HTTP processes, abrupt exit and durable SQLite.
The separate old provider rollback test remains explicitly a component test.
"""
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
import pytest
from app import db
from app.storage.api import StorageAPI
from app.persistence import backup
from helpers_be2_15 import PASSWORD, account, measurement
from integration_support_15 import FixtureProvider, create_recording
from test_api_security_15 import register

ROOT = Path(__file__).resolve().parents[1]
START = '''
import sys
port=int(sys.argv[2])
if sys.argv[1]=='stdlib':
 from app.devserver import serve
 serve(port=port).serve_forever()
else:
 import uvicorn
 uvicorn.run('app.main:app',host='127.0.0.1',port=port,log_level='critical',access_log=False)
'''

@contextmanager
def server(kind, path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    env={**os.environ,'AETHER_DB_PATH':str(path),'AETHER_LEGACY_DEMO':'0','AETHER_SESSION_TOKEN':'aether-test-token'}
    proc=subprocess.Popen([sys.executable,'-u','-c',START,kind,str(port)],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    def call(method,path,body=None,token=None):
        conn=http.client.HTTPConnection('127.0.0.1',port,timeout=15)
        headers={'X-AETHER-Token':'aether-test-token'}
        if token: headers['Authorization']='Bearer '+token
        raw=None
        if body is not None: raw=json.dumps(body); headers['Content-Type']='application/json'
        conn.request(method,path,body=raw,headers=headers)
        reply=conn.getresponse(); data=reply.read(); status=reply.status; conn.close()
        return status,json.loads(data) if data else None
    try:
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            assert proc.poll() is None, 'Server startup failed'
            try:
                if call('GET','/api/health')[0]==200: break
            except (ConnectionError, OSError): time.sleep(0.05)
        else: pytest.fail('Server startup timeout')
        yield call,proc
    finally:
        if proc.poll() is None: proc.kill()
        out,err=proc.communicate(timeout=10)
        assert PASSWORD.encode() not in out+err

@pytest.mark.parametrize('kind',['stdlib','fastapi'])
def test_process_restart_100_measurements_and_real_result_history(kind,tmp_path):
    if kind=='fastapi':
        pytest.importorskip('fastapi');pytest.importorskip('uvicorn')
    path=tmp_path/'restart.db'
    with server(kind,path) as (call,proc):
        user,token=register(call)
        session,items,_=create_recording(call,token,origin='manual')
        request={'astronaut_id':user['user']['astronaut_id'],'session_id':session['id'],'data_classes':['manual']}
        status,result=call('POST','/api/phantom-analyses',request,token)
        assert status==201 and result['outcome']=='insufficient_data',result
        assert result['method']['id']=='phantom_hr_univariate_1_4'
        rid=result['analysis_id']
        # A process-owned live session exists but cannot remain live after kill.
        _,device=call('POST','/api/devices',{'name':'recovery strap','kind':'ble','external_id':'CRASH:01'},token)
        _,live=call('POST','/api/sensor-sessions',{'device_id':device['id'],'source':'BLE test','origin':'real',
             'started_at':'2026-01-01T00:00:00Z','metadata':{'source_type':'live_sensor'}},token)
        proc.kill();proc.wait(timeout=10)
    with server(kind,path) as (call,_):
        assert len(call('GET','/api/measurements?limit=100',token=token)[1]['items'])==100
        assert call('GET','/api/phantom-analyses/'+rid,token=token)[1]['analysis_id']==rid
        assert call('GET','/api/analyses',token=token)[1]['items'][0]['id']==rid
        assert call('GET','/api/phantom-analyses',token=token)[1]['items'][0]['analysis_id']==rid
        replay=call('POST','/api/measurements/batch',{'measurements':items},token)
        assert replay[0]==200 and all(not r['created'] for r in replay[1]['items'])
        assert call('POST','/api/phantom-analyses',request,token)[0]==200
        _,other=register(call,'stranger')
        assert call('GET','/api/phantom-analyses/'+rid,token=other)[0]==404
        assert call('POST','/api/sensor-sessions/'+session['id']+'/close',{},token)[0]==200
        rows=call('GET',f"/api/devices/{device['id']}/sessions",token=token)[1]['items']
        assert rows[0]['id']==live['id'] and rows[0]['end_status']=='recovered'


CRASH = '''
import json,os,sys
sys.path.insert(0,'tests')
from integration_support_15 import FixtureProvider
from app.storage.api import StorageAPI
import app.storage.api as adapter_module
payload=json.load(sys.stdin)
api=StorageAPI(payload['token'])
snapshot=api.prepare_analysis(payload['request'])
real_audit=adapter_module.audit
def crash_audit(c,actor,action,resource_type,*args,**kwargs):
 if action=='create' and resource_type=='phantom_analysis': os._exit(73)
 return real_audit(c,actor,action,resource_type,*args,**kwargs)
adapter_module.audit=crash_audit
api.save_analysis(snapshot,FixtureProvider().evaluate(snapshot.measurements()))
'''

def test_abort_inside_write_transaction_and_backup_restore(tmp_path,monkeypatch):
    path=tmp_path/'crash.db';monkeypatch.setattr(db,'DB_PATH',path);db.init_db()
    user,token,_=account();api=StorageAPI(token)
    s=api.create_session({'source':'manual-test','origin':'manual','started_at':'2026-01-01T00:00:00Z'})
    row=api.append_biosignals([measurement(session_id=s['id'])])[0]['measurement']
    request={'session_id':s['id'],'input_ids':[row['id']],'algorithm':'test-fixture','idempotency_key':'crash-run'}
    proc=subprocess.run([sys.executable,'-c',CRASH],input=json.dumps({'token':token,'request':request}),text=True,
           cwd=ROOT,env={**os.environ,'AETHER_DB_PATH':str(path)},capture_output=True,timeout=20)
    assert proc.returncode==73
    db.init_db()
    with db.connect() as c:
        for table in ('analysis_runs','phantom_run_details','record_events'): assert c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert c.execute('PRAGMA foreign_key_check').fetchone() is None
    assert api.get_measurement(row['id'])['value']==65
    snapshot=api.prepare_analysis(request)
    saved,created=api.save_analysis(snapshot,FixtureProvider().evaluate(snapshot.measurements()))
    assert created
    archive=tmp_path/'backup.db';restored=tmp_path/'restored.db'
    backup.backup(archive);backup.restore(archive,restored)
    monkeypatch.setattr(db,'DB_PATH',restored);db.init_db()
    from app import auth
    from app.persistence.common import APIError
    with pytest.raises(APIError): StorageAPI(token).get_analysis(saved['id'])
    fresh=auth.login('alice',PASSWORD)['access_token']
    assert StorageAPI(fresh).get_analysis(saved['id'])==saved
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM record_events').fetchone()[0]==1
