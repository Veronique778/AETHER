import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError
from app import db
from app.persistence import repository as repo
from app.persistence.common import APIError
from app.schemas_15 import HistoryQuery,MeasurementCreate
from helpers_be2_15 import account,measurement

@pytest.fixture(autouse=True)
def database(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'data.db'); db.init_db()


def test_events_are_not_overwritten_and_aggregates_are_separate():
    u,_,_=account()
    a=repo.add_measurements(u,[measurement('1'),measurement('2',value=75.0)])
    assert len(repo.list_measurements(u,HistoryQuery())['items'])==2
    result=repo.aggregates(u,HistoryQuery())['items'][0]
    assert result['mean']==70 and result['sample_count']==2
    repo.aggregates(u,HistoryQuery())
    assert len(repo.list_measurements(u,HistoryQuery())['items'])==2
    with db.connect() as c:
        with pytest.raises(sqlite3.IntegrityError): c.execute('UPDATE raw_measurements SET value=0 WHERE id=?',(a[0]['measurement']['id'],))
        with pytest.raises(sqlite3.IntegrityError): c.execute('DELETE FROM raw_measurements WHERE id=?',(a[0]['measurement']['id'],))


def test_idempotency_conflict_and_correction_history():
    u,_,_=account(); m=measurement()
    original=repo.add_measurements(u,[m])[0]
    assert repo.add_measurements(u,[m])[0]['created'] is False
    with pytest.raises(APIError) as err: repo.add_measurements(u,[{**m,'value':71.0}])
    assert err.value.status==409
    corrected=measurement('correction',value=72.0,supersedes_id=original['measurement']['id'])
    repo.add_measurements(u,[corrected])
    assert repo.aggregates(u,HistoryQuery())['items'][0]['mean']==72
    assert repo.get_measurement(u,original['measurement']['id'])['value']==65
    with pytest.raises(APIError): repo.add_measurements(u,[{**corrected,'idempotency_key':'other'}])


def test_null_and_absent_values_preserved_and_zero_not_missing():
    u,_,_=account(); a=measurement('missing'); a.pop('value')
    b=measurement('null',value=None)
    c=measurement('zero',signal='activity_minutes',unit='min',value=0.0)
    rows=repo.add_measurements(u,[a,b,c])
    assert rows[0]['measurement']['missing'] and rows[1]['measurement']['value'] is None
    assert rows[2]['measurement']['value']==0 and not rows[2]['measurement']['missing']
    aggs=repo.aggregates(u,HistoryQuery())['items']
    assert next(x for x in aggs if x['signal']=='heart_rate')['mean'] is None


def test_utc_normalization_and_day_boundaries():
    u,_,_=account()
    r=repo.add_measurements(u,[measurement(measured_at='2026-11-15T01:00:00+02:00')])[0]['measurement']
    assert r['measured_at']=='2026-11-14T23:00:00.000000Z' and r['received_at'].endswith('Z')
    assert repo.aggregates(u,HistoryQuery())['items'][0]['day']=='2026-11-14'
    with pytest.raises(ValidationError): repo.add_measurements(u,[measurement('naive',measured_at='2026-11-15T01:00:00')])


@pytest.mark.parametrize('change',[{'value':float('nan')},{'value':float('inf')},{'value':True},{'value':1000.0},{'unit':'kg'},
    {'signal':"x' OR 1=1--"},{'origin':'research'},{'origin':'real'},{'astronaut_id':"x' OR 1=1--"},{'secret':'unexpected'}])
def test_validation(change):
    with pytest.raises(ValidationError): MeasurementCreate.model_validate(measurement(**change))


def test_atomic_batch_and_pagination_filters():
    u,_,_=account()
    repo.add_measurements(u,[measurement(str(i),value=60.0+i) for i in range(5)])
    page=repo.list_measurements(u,HistoryQuery(limit=2)); assert len(page['items'])==2
    second=repo.list_measurements(u,HistoryQuery(limit=2,after=page['next_cursor']))
    assert page['items'][0]['id']!=second['items'][0]['id']
    assert not repo.list_measurements(u,HistoryQuery(start='2027-01-01T00:00:00Z'))['items']
    with pytest.raises(APIError): repo.add_measurements(u,[measurement('new'),measurement('0',value=89.0)])
    assert len(repo.list_measurements(u,HistoryQuery())['items'])==5


def test_concurrent_writes_and_bulk_load():
    u,_,_=account()
    def write(i): return repo.add_measurements(u,[measurement(f'{i}-{j}',value=60.0) for j in range(100)])
    with ThreadPoolExecutor(8) as pool: results=list(pool.map(write,range(10)))
    assert sum(len(x) for x in results)==1000
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM raw_measurements WHERE astronaut_id=?',(u['astronaut_id'],)).fetchone()[0]==1000
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not c.execute('PRAGMA foreign_key_check').fetchall()
    assert repo.aggregates(u,HistoryQuery())['items'][0]['sample_count']==1000


def test_restart_in_separate_process():
    u,_,_=account(); mid=repo.add_measurements(u,[measurement()])[0]['measurement']['id']
    script="from app import db; from pathlib import Path; import sys; db.DB_PATH=Path(sys.argv[1]); db.init_db();\nwith db.connect() as c: print(c.execute('SELECT value FROM raw_measurements WHERE id=?',(sys.argv[2],)).fetchone()[0])"
    out=subprocess.check_output([sys.executable,'-c',script,str(db.DB_PATH),mid],text=True)
    assert out.strip()=='65.0'


def test_fk_wal_and_busy_timeout_every_connection():
    for _ in range(2):
        with db.connect() as c:
            assert c.execute('PRAGMA foreign_keys').fetchone()[0]==1
            assert c.execute('PRAGMA journal_mode').fetchone()[0]=='wal'
            assert c.execute('PRAGMA busy_timeout').fetchone()[0]>=15000
            with pytest.raises(sqlite3.IntegrityError): c.execute("INSERT INTO devices VALUES('x','missing','x','ble',NULL,'now')")


def test_export_neutralizes_formula_and_preserves_null():
    u,_,_=account(); repo.add_measurements(u,[measurement(source='=HYPERLINK("bad")',value=None)])
    text=repo.export_measurements(u,HistoryQuery())['csv']
    assert "'=HYPERLINK" in text


def test_session_context_and_analysis_history():
    u,_,_=account(); d=repo.create_device(u,{'name':'Band','kind':'ble'})
    s=repo.create_session(u,{'device_id':d['id'],'source':'Band','origin':'real','started_at':'2026-11-15T00:00:00Z'})
    m=measurement(origin='real',session_id=s['id'],device_id=d['id'])
    r=repo.add_measurements(u,[m])[0]['measurement']
    for key in ('first','second'): repo.run_summary(u,{'session_id':s['id'],'idempotency_key':key})
    assert len(repo.list_records(u,HistoryQuery(),'analysis_runs')['items'])==2
    assert repo.get_measurement(u,r['id'])['value']==65
    repo.close_session(u,s['id']); assert repo.device_sessions(u,d['id'],HistoryQuery())['items'][0]['ended_at']


def test_outbox_inserted_atomically_and_origin_groups_separate():
    u,_,_=account(); repo.add_measurements(u,[measurement('manual'),measurement('sim',origin='simulated')])
    assert len(repo.aggregates(u,HistoryQuery())['items'])==2
    with db.connect() as c: assert c.execute('SELECT COUNT(*) FROM sync_events WHERE user_id=?',(u['id'],)).fetchone()[0]==2


def test_internal_adapter_validates_session_and_persists_derived_outputs():
    from app.persistence.internal_api import InternalAPI
    from app import auth
    u,t,_=account();api=InternalAPI(t)
    s=api.create_session({'source':'form','origin':'manual','started_at':'2026-01-01T00:00:00Z'})
    m=api.append_biosignals([measurement(session_id=s['id'])])[0]['measurement']
    run=api.save_analysis({'session_id':s['id'],'model':'external-model','processing_version':'v1',
          'idempotency_key':'analysis-v1','input_ids':[m['id']],'result':{'score':0.2}},
          processed=[{'raw_id':m['id'],'signal':'normalized_hr','value':0.2,'unit':'z'}])
    alert=api.create_alert({'analysis_id':run['id'],'severity':'info','message':'Review requested'})
    assert alert['astronaut_id']==u['astronaut_id'] and t not in repr(api)
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM processed_measurements').fetchone()[0]==1
    auth.logout(u,t)
    with pytest.raises(APIError): api.append_biosignals([measurement('revoked')])
