import json,sqlite3
SCHEMA='''CREATE TABLE IF NOT EXISTS recovery_sessions(id INTEGER PRIMARY KEY, crew_id TEXT, activity TEXT, started_at TEXT, ended_at TEXT, before_score REAL, after_score REAL, result_json TEXT, origin TEXT);'''
def save(db,crew_id,activity,started_at,ended_at,before_score,after_score,result,origin='manual'):
 db.executescript(SCHEMA)
 if not 0<=before_score<=10 or not 0<=after_score<=10:raise ValueError('Scores must be 0-10')
 db.execute('INSERT INTO recovery_sessions(crew_id,activity,started_at,ended_at,before_score,after_score,result_json,origin) VALUES(?,?,?,?,?,?,?,?)',(crew_id,activity,started_at,ended_at,before_score,after_score,json.dumps(result),origin));db.commit()
def suggest(db,crew_id):
 db.executescript(SCHEMA)
 rows=db.execute('SELECT activity,COUNT(*) AS n,AVG(after_score-before_score) AS change FROM recovery_sessions WHERE crew_id=? GROUP BY activity HAVING n>=2 ORDER BY change DESC',(crew_id,)).fetchall()
 return [{'activity':r[0],'sessions':r[1],'mean_self_report_change':round(r[2],2),'caution':'Not evidence of therapeutic efficacy'} for r in rows]
