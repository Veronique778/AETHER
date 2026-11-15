"""Local end-to-end TLS test with a test-only CA; no external server or personal data."""
import json
import os
import shutil
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path
import pytest
from app import db
from app.persistence import repository as repo,sync
from helpers_be2_15 import account,measurement,PASSWORD


def test_actual_https_receiver_and_certificate_verification(tmp_path,monkeypatch):
    openssl=shutil.which('openssl')
    if not openssl: pytest.skip('OpenSSL executable needed for temporary test certificate')
    key=tmp_path/'test-key.pem';cert=tmp_path/'test-cert.pem'
    subprocess.run([openssl,'req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),
                    '-days','1','-subj','/CN=127.0.0.1','-addext','subjectAltName=IP:127.0.0.1'],check=True,capture_output=True)
    script='''import ssl,sys
from app.devserver import serve
from app.security import Policy
ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.minimum_version=ssl.TLSVersion.TLSv1_2
ctx.load_cert_chain(sys.argv[1],sys.argv[2])
p=Policy(remote=True,remote_hosts=('127.0.0.1',),extra_origins=())
s=serve(port=0,policy=p,tls_context=ctx);p.remote_hosts=(f'127.0.0.1:{s.server_port}',)
print(s.server_port,flush=True);s.serve_forever()
'''
    env={**os.environ,'AETHER_DB_PATH':str(tmp_path/'central.db'),'AETHER_LEGACY_DEMO':'0','AETHER_RELEASE':'1'}
    proc=subprocess.Popen([sys.executable,'-c',script,str(cert),str(key)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        port=int(proc.stdout.readline().strip());url=f'https://127.0.0.1:{port}'
        context=ssl.create_default_context(cafile=str(cert))
        def request(path,data=None,token=None):
            headers={'Content-Type':'application/json'}
            if token:headers['Authorization']='Bearer '+token
            r=urllib.request.Request(url+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
            with urllib.request.urlopen(r,context=context,timeout=10) as response: return json.loads(response.read())
        request('/api/auth/register',{'login':'alice','password':PASSWORD,'display_name':'Alice'})
        remote_token=request('/api/auth/login',{'login':'alice','password':PASSWORD})['access_token']
        monkeypatch.setattr(db,'DB_PATH',tmp_path/'local.db');db.init_db();u,_,_=account()
        repo.add_measurements(u,[measurement()])
        # An untrusted certificate must fail, leaving the outbox intact.
        sync.sync_once(u,url,remote_token)
        assert sync.status(u)['unsent']==1
        event=sync.pending(u)['items'][0];sync.retry(u,event['id'])
        monkeypatch.setenv('SSL_CERT_FILE',str(cert))
        sync.sync_once(u,url,remote_token)
        assert sync.status(u)['unsent']==0
        records=request('/api/measurements',token=remote_token)['items']
        assert len(records)==1 and records[0]['value']==65
    finally:
        proc.terminate();proc.communicate(timeout=10)
