import asyncio
import http.client
import json
import threading
from urllib.parse import urlsplit

import pytest
from app import db,security
from helpers_be2_15 import PASSWORD

@pytest.fixture(params=['stdlib','fastapi'])
def client(request,tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'http.db');db.init_db()
    if request.param=='stdlib':
        from app.devserver import serve
        srv=serve(port=0,policy=security.Policy(token='aether-test-token'))
        thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
        def call(method,path,body=None,token=None,headers=None):
            c=http.client.HTTPConnection('127.0.0.1',srv.server_port,timeout=15)
            h={'X-AETHER-Token':'aether-test-token',**(headers or {})}
            if token: h['Authorization']='Bearer '+token
            raw=None
            if body is not None: raw=json.dumps(body).encode();h['Content-Type']='application/json'
            c.request(method,path,body=raw,headers=h);r=c.getresponse();data=r.read();c.close()
            return r.status,json.loads(data) if data else None
        def restart():
            nonlocal srv,thread
            srv.shutdown();srv.server_close();thread.join(timeout=3)
            srv=serve(port=0,policy=security.Policy(token='aether-test-token'))
            thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
        call.restart=restart
        yield call
        srv.shutdown();srv.server_close();thread.join(timeout=3)
    else:
        pytest.importorskip("fastapi",reason="Optional FastAPI surface is not installed")
        from fastapi.testclient import TestClient
        from app.main import app
        from contextlib import ExitStack
        with ExitStack() as stack:
            cli=stack.enter_context(TestClient(app,base_url='http://127.0.0.1',headers={'X-AETHER-Token':'aether-test-token'}))
            def call(method,path,body=None,token=None,headers=None):
                h=headers or {}
                if token: h={**h,'Authorization':'Bearer '+token}
                r=cli.request(method,path,json=body,headers=h)
                return r.status_code,r.json() if r.content else None
            def restart():
                nonlocal cli
                cli.__exit__(None,None,None)
                cli=stack.enter_context(TestClient(app,base_url='http://127.0.0.1',headers={'X-AETHER-Token':'aether-test-token'}))
            call.restart=restart
            yield call


def register(client,name='alice'):
    status,b=client('POST','/api/auth/register',{'login':name,'password':PASSWORD,'display_name':name})
    assert status==201
    status,session=client('POST','/api/auth/login',{'login':name,'password':PASSWORD})
    assert status==200
    return b,session['access_token']


def test_all_target_routes_auth_permissions_and_response_contracts(client):
    for path in ['/api/profile','/api/measurements','/api/devices','/api/missions','/api/analyses','/api/alerts','/api/recovery/sessions']:
        assert client('GET',path)[0]==401
    a,t=register(client); b,other=register(client,'bob')
    assert client('GET','/api/auth/me',token=t)[1]['user']['id']==a['user']['id']
    assert client('PATCH','/api/profile',{'display_name':'Mariana','language':'uk'},t)[1]['display_name']=='Mariana'
    assert client('PATCH','/api/profile',{'role':'administrator'},t)[0]==422
    from helpers_be2_15 import measurement
    status,r=client('POST','/api/measurements',measurement(),t);assert status==201
    rid=r['measurement']['id']
    assert client('POST','/api/measurements',measurement(),t)[0]==200
    assert client('GET','/api/measurements/'+rid,token=other)[0]==404
    assert client('POST','/api/measurements',measurement('foreign',astronaut_id=a['user']['astronaut_id']),other)[0]==404
    for path in ['/api/measurements','/api/measurements/aggregates','/api/measurements/export','/api/recovery/sessions','/api/analyses','/api/alerts']:
        assert client('GET',path+'?astronaut_id='+a['user']['astronaut_id'],token=other)[0]==404
    assert client('GET','/api/measurements/aggregates',token=t)[1]['items'][0]['mean']==65
    assert client('GET','/api/measurements/export',token=t)[1]['rows']==1
    assert client('GET','/api/missions',token=t)[1]['items']==[]
    assert client('POST','/api/missions',{'name':'Unauthorized'},t)[0]==403
    assert client('GET','/api/astronauts/A01/timeline',token=t)[0]==410
    assert client('GET','/api/biosignals/sessions',token=t)[0]==410
    assert client('GET','/api/profile',token=t,headers={'Origin':'https://evil.example'})[0]==403
    assert client('POST','/api/auth/logout',{},t)[1]['logged_out']
    assert client('GET','/api/profile',token=t)[0]==401


def test_device_session_analysis_recovery_and_sync_routes(client):
    a,t=register(client)
    _,device=client('POST','/api/devices',{'name':'Sensor','kind':'ble'},t)
    status,s=client('POST','/api/sensor-sessions',{'device_id':device['id'],'source':'Sensor','origin':'real','started_at':'2026-11-15T12:00:00+02:00'},t)
    assert status==201
    from helpers_be2_15 import measurement
    status,r=client('POST','/api/measurements',measurement(origin='real',device_id=device['id'],session_id=s['id']),t); assert status==201
    assert client('GET',f"/api/devices/{device['id']}/sessions",token=t)[1]['items'][0]['id']==s['id']
    status,analysis=client('POST','/api/analyses',{'session_id':s['id'],'idempotency_key':'r1'},t);assert status==201
    assert client('GET','/api/analyses/'+analysis['id'],token=t)[1]['result']['channels']['heart_rate']['samples']==1
    status,recovery=client('POST','/api/recovery/sessions',{'activity':'mind-pulse','before_mood':4,'after_mood':6,'duration_seconds':90},t)
    assert status==201
    assert len(client('GET','/api/recovery/sessions',token=t)[1]['items'])==1
    assert client('GET','/api/sync/status',token=t)[1]['unsent']==1
    assert len(client('GET','/api/sync/pending',token=t)[1]['items'])==1
    assert client('POST',f"/api/sensor-sessions/{s['id']}/close",{},t)[1]['closed']


def test_body_limits_validation_and_no_secret_echo(client):
    _,t=register(client)
    assert client('POST','/api/measurements',{'large':'x'*270000},t)[0]==413
    secret='top-secret-value'
    status,b=client('POST','/api/auth/login',{'login':'alice','password':secret,'extra':secret})
    assert status==422 and secret not in json.dumps(b)
    assert client('GET','/api/measurements?limit=501',token=t)[0]==422
    assert client('GET','/api/measurements?limit=2&limit=3',token=t)[0]==422
    assert client('POST','/api/profile',{},t)[0]==405
    assert client('GET','/api/contract')[1]['openapi']=='3.1.0'


def test_release_cannot_disable_protection_or_use_demo(monkeypatch):
    monkeypatch.setenv('AETHER_DISABLE_TOKEN','1')
    with pytest.raises(ValueError): security.Policy()
    monkeypatch.delenv('AETHER_DISABLE_TOKEN');monkeypatch.setenv('AETHER_RELEASE','1');monkeypatch.setenv('AETHER_LEGACY_DEMO','1')
    with pytest.raises(ValueError): security.Policy()


def test_network_binding_guard(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'bind.db')
    from app.devserver import serve
    with pytest.raises(ValueError): serve('0.0.0.0',0)
    with pytest.raises(ValueError): security.Policy(remote=True,remote_hosts=())
    p=security.Policy(remote=True,remote_hosts=('central.example',),extra_origins=())
    assert security.check(p,'GET','/api/profile',{'host':'central.example'},secure_transport=False)[0]==403
    assert security.check(p,'GET','/api/profile',{'host':'central.example','x-forwarded-proto':'https'},secure_transport=False)[0]==403
    assert security.check(p,'GET','/api/profile',{'host':'evil.example'},secure_transport=True)[0]==421
    assert security.check(p,'GET','/api/profile',{'host':'central.example','origin':'https://central.example'},secure_transport=True) is None


def test_asgi_stream_limit_without_content_length():
    called=[]
    async def app(scope,receive,send): called.append(True)
    mw=security.ASGISecurity(app,security.Policy(token='test'))
    messages=iter([{'type':'http.request','body':b'a'*150000,'more_body':True}, {'type':'http.request','body':b'b'*150000,'more_body':False}])
    sent=[]
    async def receive(): return next(messages)
    async def send(message): sent.append(message)
    asyncio.run(mw({'type':'http','method':'POST','path':'/api/measurements','headers':[(b'host',b'127.0.0.1'),(b'x-aether-token',b'test')]},receive,send))
    assert sent[0]['status']==413 and not called


def test_legacy_demo_switch_cannot_expose_personal_accounts(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'demo.db');db.init_db()
    monkeypatch.setenv('AETHER_LEGACY_DEMO','1')
    from app.api_15 import legacy_allowed
    from helpers_be2_15 import account
    assert legacy_allowed()
    account();assert not legacy_allowed()


def test_loopback_host_parser_rejects_malformed_authority():
    for h in ('localhost:bad','localhost:999999','localhost:0','localhost:80/path','localhost:80@evil','localhost\r\n'):
        assert not security.host_ok(h)


def test_local_asgi_rejects_external_peer_even_with_spoofed_host():
    called=[];sent=[]
    async def app(*args): called.append(True)
    async def receive():return {'type':'http.request','body':b''}
    async def send(m):sent.append(m)
    mw=security.ASGISecurity(app,security.Policy(token='t'))
    asyncio.run(mw({'type':'http','method':'GET','path':'/api/health','client':('192.0.2.1',1234),
                   'headers':[(b'host',b'127.0.0.1')]},receive,send))
    assert sent[0]['status']==403 and not called
