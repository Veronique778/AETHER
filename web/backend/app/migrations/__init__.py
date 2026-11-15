"""Checksummed, atomic, repeatable migrations; never delete a user's database."""
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from app.persistence.common import utcnow, dumps, digest

UNITS = {'heart_rate_bpm':'bpm','sleep_hours':'h','fatigue_1_10':'score','reaction_ms':'ms','activity_minutes':'min'}


def _statements(text):
    buf = ''
    for line in text.splitlines(True):
        buf += line
        if sqlite3.complete_statement(buf):
            yield buf
            buf = ''
    if buf.strip():
        raise RuntimeError('Incomplete migration')


def migrate(c):
    c.execute('BEGIN IMMEDIATE')
    try:
        c.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY,checksum TEXT NOT NULL,applied_at TEXT NOT NULL)')
        for path in sorted(Path(__file__).parent.glob('*.sql')):
            text = path.read_text(encoding='utf-8'); checksum = digest(text)
            old = c.execute('SELECT checksum FROM schema_migrations WHERE version=?',(path.stem,)).fetchone()
            if old:
                if old[0] != checksum:
                    raise RuntimeError('Migration checksum mismatch: '+path.name)
                continue
            for statement in _statements(text): c.execute(statement)
            c.execute('INSERT INTO schema_migrations VALUES(?,?,?)',(path.stem,checksum,utcnow()))
        if not c.execute("SELECT 1 FROM schema_migrations WHERE version='002_legacy_import'").fetchone():
            _legacy(c)
            c.execute('INSERT INTO schema_migrations VALUES(?,?,?)',('002_legacy_import','legacy-import-1',utcnow()))
        if c.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Foreign key violations; source database retained, migration rolled back')
        c.commit()
    except BaseException:
        c.rollback()
        raise


def _legacy(c):
    # Old IDs are preserved as detached demo profiles. No account is created or assigned.
    now = utcnow()
    for r in c.execute('SELECT * FROM astronauts').fetchall():
        c.execute('INSERT INTO astronaut_profiles(id,user_id,display_name,data_class,created_at) VALUES(?,NULL,?,?,?)',
                  (r['id'],r['name'],'legacy_demo',now))
    cols = {r[1] for r in c.execute('PRAGMA table_info(measurements)')}
    if 'source_by_signal' not in cols:
        c.execute("ALTER TABLE measurements ADD COLUMN source_by_signal TEXT NOT NULL DEFAULT '{}'")
    for row in c.execute('SELECT * FROM measurements').fetchall():
        origins = {}
        for signal, unit in UNITS.items():
            origin = row['source']
            if origin not in ('real','manual','research','simulated'):
                # Unknown historical provenance must not become 'real'. Preserve original label.
                raise RuntimeError('Unsupported legacy provenance; original database retained')
            origins[signal] = row['source']
            meta = {'legacy_day':row['day'],'legacy_source':row['source'],
                    'legacy_source_scope':'row_unverified','utc_unknown':True}
            key = f"legacy:{row['astronaut_id']}:{row['day']}:{signal}"
            mid = str(uuid.uuid5(uuid.NAMESPACE_URL,key))
            c.execute('''INSERT INTO raw_measurements(id,astronaut_id,source,signal,value,unit,measured_at,received_at,
              origin,quality,confidence,missing,processing_version,metadata,idempotency_key,payload_hash)
              VALUES(?,?,?,?,?,?,NULL,?,?,?,?,?,?,?,?,?)''',
              (mid,row['astronaut_id'],'legacy-1.4',signal,row[signal],unit,now,origin,'legacy_unverified',None,
               int(row[signal] is None),'legacy-1.4',dumps(meta),key,digest(dumps([row[signal],meta]))))
        c.execute('UPDATE measurements SET source_by_signal=? WHERE astronaut_id=? AND day=?',
                  (dumps(origins),row['astronaut_id'],row['day']))
    cols = {r[1] for r in c.execute('PRAGMA table_info(recovery_sessions)')}
    for name, definition in [('profile_id','TEXT REFERENCES astronaut_profiles(id)'),('mission_id','TEXT REFERENCES missions(id)')]:
        if name not in cols: c.execute(f'ALTER TABLE recovery_sessions ADD COLUMN {name} {definition}')
    c.execute('CREATE INDEX IF NOT EXISTS recovery_profile ON recovery_sessions(profile_id,id)')
