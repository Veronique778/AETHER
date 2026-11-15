"""Standalone synthetic ingestion benchmark; no personal database is used.
Run from web/backend: python tests/benchmark_storage_15.py
"""
import json
import secrets
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import auth,db
from app.persistence import repository as repo
from app.schemas_15 import HistoryQuery


def main():
    previous=db.DB_PATH
    with tempfile.TemporaryDirectory(prefix='aether-synthetic-benchmark-') as directory:
        try:
            db.DB_PATH=Path(directory)/'load.db';db.init_db()
            password=secrets.token_urlsafe(24)
            auth.register('synthetic_benchmark',password,'Synthetic benchmark')
            token=auth.login('synthetic_benchmark',password)['access_token'];user=auth.authenticate(token)
            device=repo.create_device(user,{'name':'Synthetic sensor','kind':'other'})
            session=repo.create_session(user,{'device_id':device['id'],'source':'load-test','origin':'simulated','started_at':'2026-11-15T00:00:00Z'})
            def batch(n):
                rows=[{'idempotency_key':f'batch-{n}-sample-{j}','source':'load-test','signal':'heart_rate',
                       'value':65.0,'unit':'bpm','measured_at':'2026-11-15T00:00:01Z','origin':'simulated',
                       'device_id':device['id'],'session_id':session['id']} for j in range(1000)]
                return sum(r['created'] for r in repo.add_measurements(user,rows))
            start=time.perf_counter()
            with ThreadPoolExecutor(8) as pool: total=sum(pool.map(batch,range(50)))
            elapsed=time.perf_counter()-start
            # Repeat one complete batch: no duplication in raw or outbox.
            assert batch(0)==0
            with db.connect() as c:
                raw=c.execute('SELECT COUNT(*) FROM raw_measurements WHERE astronaut_id=?',(user['astronaut_id'],)).fetchone()[0]
                queued=c.execute('SELECT COUNT(*) FROM sync_events WHERE user_id=?',(user['id'],)).fetchone()[0]
                assert not c.execute('PRAGMA foreign_key_check').fetchall()
                assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert total==raw==queued==50000
            assert repo.aggregates(user,HistoryQuery())['items'][0]['sample_count']==50000
            print(json.dumps({'samples':total,'threads':8,'batch_size':1000,'seconds':round(elapsed,3),
                              'samples_per_second':round(total/elapsed,1),'raw_count':raw,'outbox_count':queued,
                              'duplicate_batch_created':0,'integrity':'ok','foreign_keys':'ok'}))
        finally: db.DB_PATH=previous

if __name__=='__main__':main()
