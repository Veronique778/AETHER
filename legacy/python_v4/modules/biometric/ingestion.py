"""CSV/JSON ingestion and SQLite persistence, no fabricated missing values."""
import csv,json,sqlite3
from pathlib import Path
from .validation import validate
SCHEMA='''CREATE TABLE IF NOT EXISTS biometric_records (id INTEGER PRIMARY KEY, crew_id TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL, origin TEXT NOT NULL, timestamp TEXT NOT NULL, context TEXT NOT NULL, source_id TEXT NOT NULL, quality TEXT NOT NULL); CREATE INDEX IF NOT EXISTS idx_biometric ON biometric_records(crew_id,metric,timestamp);'''
def connect(path):
 db=sqlite3.connect(str(path));db.row_factory=sqlite3.Row;db.executescript(SCHEMA);return db
def add(db,record):
 x=validate(record)
 if not x.get('crew_id'): raise ValueError('crew_id required')
 cols=('crew_id','metric','value','unit','origin','timestamp','context','source_id','quality')
 db.execute('INSERT INTO biometric_records ('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+')',tuple(x[c] for c in cols));db.commit();return x
def history(db,crew_id,metric=None):
 q='SELECT * FROM biometric_records WHERE crew_id=?';args=[crew_id]
 if metric: q+=' AND metric=?';args.append(metric)
 return [dict(row) for row in db.execute(q+' ORDER BY timestamp',args)]
def import_file(db,path):
 p=Path(path)
 if p.suffix.lower()=='.csv':
  with p.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
 elif p.suffix.lower()=='.json': rows=json.loads(p.read_text(encoding='utf8'))
 else: raise ValueError('Only CSV and JSON supported')
 if not isinstance(rows,list):raise ValueError('Expected list of records')
 return [add(db,row) for row in rows]
