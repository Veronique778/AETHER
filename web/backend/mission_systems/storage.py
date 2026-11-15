"""Namespaced, additive SQLite migration. Does not touch the original CORE tables."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone
from .contracts import Reading

class Store:
    def __init__(self, path=None):
        self.path = Path(path or Path(__file__).resolve().parents[1] / 'aether.db')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS ms_migrations(version INTEGER PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS ms_documents(
                    kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL, PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS ms_readings(
                    id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, metric TEXT NOT NULL,
                    zone_id TEXT NOT NULL, source_id TEXT NOT NULL, origin TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE(timestamp,metric,zone_id,source_id));
                CREATE INDEX IF NOT EXISTS ms_reading_history ON ms_readings(zone_id,timestamp);
                INSERT OR IGNORE INTO ms_migrations VALUES(1);
            ''')

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def save(self, kind, key, data):
        payload = data.model_dump(mode='json') if hasattr(data, 'model_dump') else data
        text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        with self.connection() as c:
            c.execute('INSERT INTO ms_documents VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at',
                      (kind, key, text, datetime.now(timezone.utc).isoformat()))
        return key

    def get(self, kind, key):
        with self.connection() as c:
            row = c.execute('SELECT payload FROM ms_documents WHERE kind=? AND id=?', (kind, key)).fetchone()
        if row is None:
            raise KeyError(f'{kind}/{key} not found')
        return json.loads(row[0])

    def list(self, kind):
        with self.connection() as c:
            return [json.loads(r[0]) for r in c.execute('SELECT payload FROM ms_documents WHERE kind=? ORDER BY id', (kind,))]

    def readings(self, readings):
        # Validate the complete batch before starting a transaction.
        values = [Reading.model_validate(r) for r in readings]
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            for r in values:
                if r.zone_id is None or r.metric not in ('temperature','humidity','co2','light'):
                    raise ValueError('Environment store requires a zone and environment metric')
                payload = r.model_dump_json()
                key = (r.timestamp.isoformat(),r.metric,r.zone_id,r.source_id)
                row = c.execute('SELECT payload FROM ms_readings WHERE timestamp=? AND metric=? AND zone_id=? AND source_id=?',key).fetchone()
                if row and row[0] != payload:
                    raise ValueError('Conflicting measurement; use a new source_id for a corrected revision')
                c.execute('INSERT OR IGNORE INTO ms_readings(timestamp,metric,zone_id,source_id,origin,payload) VALUES(?,?,?,?,?,?)',(*key,r.origin,payload))
        return len(values)

    def history(self, zone_id, start=None, end=None, origin=None, limit=10000):
        sql = 'SELECT payload FROM ms_readings WHERE zone_id=?'; args = [zone_id]
        for col, op, val in [('timestamp','>=',start),('timestamp','<=',end),('origin','=',origin)]:
            if val is not None:
                sql += f' AND {col}{op}?';args.append(val.astimezone(timezone.utc).isoformat() if hasattr(val,'isoformat') else val)
        sql += ' ORDER BY timestamp,id LIMIT ?';args.append(limit)
        with self.connection() as c:
            return [json.loads(r[0]) for r in c.execute(sql,args)]
