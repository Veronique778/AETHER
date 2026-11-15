"""HTTP parity for the new verified NASA import and local history endpoints."""
import json
import threading
import urllib.request
import pytest

from app import nasa_research as nasa, db


@pytest.fixture
def nasa_source(monkeypatch, tmp_path):
    monkeypatch.setattr(nasa, 'IMPORT_HISTORY', tmp_path / 'history.json')
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'db.sqlite3')
    monkeypatch.setattr(nasa, 'files', lambda sid: {'source': f'https://osdr.nasa.gov/osdr/data/osd/files/{sid}',
      'files': [{'name': 'published.csv', 'download_url': 'https://osdr.nasa.gov/research/published.csv', 'restricted':False}]})
    monkeypatch.setattr(nasa, '_download_verified_csv', lambda _: b'channel,hr\n1,70\n2,80\n')
    monkeypatch.setattr(nasa, 'study_metadata', lambda sid: {'accession': f'OSD-{sid}', 'available': False})


def test_fastapi_verified_nasa_endpoint(nasa_source):
    pytest.importorskip('fastapi', reason='FastAPI not installed in this environment')
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, base_url='http://127.0.0.1', headers={'X-AETHER-Token': 'aether-test-token'}) as client:
        inspected=client.post('/api/nasa/verified-csv',json={'study_id':48,'filename':'published.csv'})
        assert inspected.status_code==200, inspected.text
        assert inspected.json()['columns']==['channel','hr']
        done=client.post('/api/nasa/verified-csv',json={'study_id':48,'filename':'published.csv','column':'hr'})
        assert done.status_code==200, done.text
        assert done.json()['summary']['mean']==75
        saved=client.get('/api/nasa/imports')
        assert saved.status_code==200
        assert len(saved.json()['imports'])==1


def test_stdlib_verified_nasa_endpoint(nasa_source):
    from app.devserver import serve
    srv=serve(port=0)
    thread=threading.Thread(target=srv.serve_forever,daemon=True)
    thread.start()
    try:
        url=f'http://127.0.0.1:{srv.server_port}'
        payload=json.dumps({'study_id':48,'filename':'published.csv','column':'hr'}).encode('utf-8')
        with urllib.request.urlopen(urllib.request.Request(url+'/api/nasa/verified-csv',data=payload,
             headers={'Content-Type':'application/json'}),timeout=4) as res:
            assert json.load(res)['summary']['mean']==75
        with urllib.request.urlopen(url+'/api/nasa/imports',timeout=4) as res:
            assert len(json.load(res)['imports'])==1
    finally:
        srv.shutdown();srv.server_close();thread.join(timeout=3)
