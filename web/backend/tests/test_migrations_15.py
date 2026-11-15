import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from app import db,auth
from app.persistence import backup,repository as repo
from app.persistence.common import APIError
from helpers_be2_15 import account,measurement

@pytest.fixture
def legacy(tmp_path,monkeypatch):
    path=tmp_path/'legacy.db'; monkeypatch.setattr(db,'DB_PATH',path)
    # Standalone fixture of the original 1.4 schema; portable with the patch archives.
    c=sqlite3.connect(path)
    c.executescript('''CREATE TABLE astronauts(id TEXT PRIMARY KEY,name TEXT NOT NULL,role TEXT NOT NULL);
    CREATE TABLE measurements(astronaut_id TEXT NOT NULL,day INTEGER NOT NULL,heart_rate_bpm REAL,sleep_hours REAL,
      fatigue_1_10 REAL,reaction_ms REAL,activity_minutes REAL,source TEXT NOT NULL DEFAULT 'simulated',
      PRIMARY KEY(astronaut_id,day),FOREIGN KEY(astronaut_id) REFERENCES astronauts(id));
    CREATE TABLE recovery_sessions(id INTEGER PRIMARY KEY AUTOINCREMENT,astronaut_id TEXT NOT NULL,activity TEXT NOT NULL,
      before_mood INTEGER NOT NULL,after_mood INTEGER NOT NULL,duration_seconds INTEGER NOT NULL,created_at TEXT NOT NULL DEFAULT(datetime('now')),details TEXT);
    CREATE TABLE experiments(id TEXT PRIMARY KEY,name TEXT NOT NULL,created_at TEXT NOT NULL,payload TEXT NOT NULL);
    CREATE TABLE ms_documents(kind TEXT,id TEXT,payload TEXT,updated_at TEXT,PRIMARY KEY(kind,id));
    CREATE TABLE nasa_fixture(id TEXT PRIMARY KEY,payload TEXT);
    ''')
    c.execute("INSERT INTO astronauts VALUES('A01','Demo','commander')")
    c.execute("INSERT INTO measurements VALUES('A01',67,60,NULL,3,300,0,'simulated')")
    c.execute("INSERT INTO recovery_sessions(astronaut_id,activity,before_mood,after_mood,duration_seconds,details) VALUES('A01','mind-pulse',3,5,60,'{}')")
    c.execute("INSERT INTO experiments VALUES('e','Example','2026-01-01','{}')")
    c.execute("INSERT INTO ms_documents VALUES('run','r','{}','2026-01-01')")
    c.execute("INSERT INTO nasa_fixture VALUES('n','research')")
    c.commit(); c.close()
    return path


def test_legacy_migration_repeatable_preserves_all_history(legacy):
    db.init_db(); db.init_db()
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM raw_measurements').fetchone()[0]==5
        assert c.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0
        for table in ('recovery_sessions','experiments','ms_documents','nasa_fixture'):
            assert c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]==1
        rows=c.execute('SELECT * FROM raw_measurements').fetchall()
        assert all(r['measured_at'] is None and r['origin']=='simulated' for r in rows)
        assert next(r for r in rows if r['signal']=='sleep_hours')['value'] is None
        assert c.execute('SELECT profile_id FROM recovery_sessions').fetchone()[0] is None
        assert not c.execute('PRAGMA foreign_key_check').fetchall()
    u,_,_=account()
    assert repo.list_measurements(u,__import__('app.schemas_15',fromlist=['HistoryQuery']).HistoryQuery())['items']==[]


def test_partial_entry_preserves_each_signals_provenance(legacy):
    db.init_db(); db.add_measurement('A01',67,{'reaction_ms':350.0},'manual')
    row=db.timeline('A01',67)[0]
    assert row['source_by_signal']['reaction_ms']=='manual'
    assert row['source_by_signal']['heart_rate_bpm']=='simulated'
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM raw_measurements').fetchone()[0]==6
        assert c.execute("SELECT COUNT(*) FROM raw_measurements WHERE signal='heart_rate_bpm' AND origin='manual'").fetchone()[0]==0


def test_checksum_tampering_fails_without_data_loss(legacy):
    db.init_db()
    with db.connect() as c: c.execute("UPDATE schema_migrations SET checksum='wrong' WHERE version='001_accounts_events'")
    with pytest.raises(RuntimeError): db.init_db()
    with db.connect() as c: assert c.execute('SELECT COUNT(*) FROM raw_measurements').fetchone()[0]==5


def test_backup_restore_and_token_replay_prevention(legacy,tmp_path,monkeypatch):
    db.init_db(); u,token,recovery=account(); record=repo.add_measurements(u,[measurement()])[0]['measurement']
    saved=tmp_path/'backup.db'; backup.backup(saved)
    auth.logout(u,token)
    restored=tmp_path/'restored.db'; backup.restore(saved,restored)
    monkeypatch.setattr(db,'DB_PATH',restored); db.init_db()
    with pytest.raises(APIError): auth.authenticate(token)
    with pytest.raises(APIError): auth.recover('alice',recovery,'Strong-New-Password-123')
    with db.connect() as c:
        assert c.execute('SELECT value FROM raw_measurements WHERE id=?',(record['id'],)).fetchone()[0]==65
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert c.execute('SELECT COUNT(*) FROM recovery_sessions').fetchone()[0]==1


def test_corrupt_backup_cannot_replace_database(legacy,tmp_path):
    db.init_db(); path=tmp_path/'backup.db'; backup.backup(path)
    with path.open('ab') as out: out.write(b'corrupt')
    with pytest.raises(ValueError): backup.restore(path,tmp_path/'restore.db')
    assert not (tmp_path/'restore.db').exists()
    assert legacy.exists()


def test_crash_rolls_back_partial_transaction(legacy):
    db.init_db()
    script="from app import db;from pathlib import Path;import os,sys;db.DB_PATH=Path(sys.argv[1]);\nwith db.connect() as c:\n c.execute('BEGIN IMMEDIATE');c.execute(\"INSERT INTO missions VALUES('crashed','lost','now')\");os._exit(9)"
    p=subprocess.run([sys.executable,'-c',script,str(legacy)])
    assert p.returncode==9
    with db.connect() as c:
        assert not c.execute("SELECT 1 FROM missions WHERE id='crashed'").fetchone()
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


def test_mission_store_settings_preserve_existing(tmp_path):
    from mission_systems.storage import Store
    s=Store(tmp_path/'missions.db'); s.save('run','1',{'value':1})
    with s.connection() as c:
        assert c.execute('PRAGMA foreign_keys').fetchone()[0]==1
        assert c.execute('PRAGMA journal_mode').fetchone()[0]=='wal'
    assert Store(tmp_path/'missions.db').get('run','1')=={'value':1}
