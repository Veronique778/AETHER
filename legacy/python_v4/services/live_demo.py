"""Offline demonstrator. Every generated reading is labelled synthetic."""
import json, math, random, sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from modules.biometric.ingestion import connect, add, history, import_file
from modules.phantom_engine.explanations import report
from modules.recovery_engine.recovery_lab import save, suggest
from modules.recovery_engine.activities import ZeroGGarden, EarthWindow, OrbitFlow, MindPulse

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'aether_live.db'
CREW='DEMO-01'
SCHEMA='''CREATE TABLE IF NOT EXISTS mission_state (id INTEGER PRIMARY KEY CHECK(id=1), day INTEGER NOT NULL, scenario TEXT NOT NULL, step INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS environment_history (id INTEGER PRIMARY KEY, timestamp TEXT, day INTEGER, temperature_c REAL, humidity_pct REAL, co2_ppm REAL, oxygen_pct REAL, origin TEXT);
CREATE TABLE IF NOT EXISTS crew_tasks (id INTEGER PRIMARY KEY, title TEXT NOT NULL, assigned_to TEXT NOT NULL, status TEXT NOT NULL);'''

class DemoSystem:
 def __init__(self,path=DB):
  self.db=connect(path);self.db.executescript(SCHEMA)
  self.rng=random.Random(13);self.garden=ZeroGGarden();self.orbit=OrbitFlow();self.mind=MindPulse();self.window=EarthWindow()
  if not self.db.execute('SELECT 1 FROM mission_state').fetchone():
   self.db.execute("INSERT INTO mission_state VALUES(1,67,'nominal',0)")
   self.db.executemany('INSERT INTO crew_tasks(title,assigned_to,status) VALUES(?,?,?)',[
    ('Daily medical check','DEMO-01','pending'),('Environmental inspection','DEMO-02','pending'),('Exercise block','DEMO-01','done')]);self.db.commit()
  if not history(self.db,CREW):
   import_file(self.db,ROOT/'examples'/'synthetic_mission.csv')
  if not self.db.execute('SELECT 1 FROM environment_history').fetchone():self._environment(67,0,'nominal')
 def state(self):return dict(self.db.execute('SELECT * FROM mission_state WHERE id=1').fetchone())
 def _environment(self,day,step,scenario):
  t=datetime.now(timezone.utc).isoformat(); drift=min(step,20)
  co2=680+25*math.sin(step/2)+(110*drift if scenario=='cabin_co2' else 0)
  temp=22.1+0.2*math.sin(step/3)+(0.15*drift if scenario=='cabin_co2' else 0)
  self.db.execute('INSERT INTO environment_history(timestamp,day,temperature_c,humidity_pct,co2_ppm,oxygen_pct,origin) VALUES(?,?,?,?,?,?,?)',
    (t,day,round(temp,2),round(44+3*math.sin(step/3),1),round(co2),20.9,'synthetic'))
  self.db.commit()
 def scenario(self,name):
  if name not in ('nominal','sleep_debt','cabin_co2'):raise ValueError('Unknown scenario')
  self.db.execute('UPDATE mission_state SET scenario=?,step=0 WHERE id=1',(name,));self.db.commit()
  return self.state()
 def tick(self):
  s=self.state();step=s['step']+1;day=s['day']+1;scenario=s['scenario'];drift=min(step,16)
  values={
   'resting_hr':(69+ (1.5*drift if scenario=='sleep_debt' else .3*drift if scenario=='cabin_co2' else 0)+self.rng.uniform(-1.8,1.8),'bpm'),
   'heart_rate':(75+(1.2*drift if scenario=='sleep_debt' else 0)+self.rng.uniform(-3,3),'bpm'),
   'sleep_hours':(7.7-(.24*drift if scenario=='sleep_debt' else 0)+self.rng.uniform(-.25,.25),'h'),
   'fatigue':(2.5+(.42*drift if scenario=='sleep_debt' else .1*drift if scenario=='cabin_co2' else 0)+self.rng.uniform(-.35,.35),'score_0_10'),
   'reaction_ms':(235+(12*drift if scenario=='sleep_debt' else 3*drift if scenario=='cabin_co2' else 0)+self.rng.uniform(-9,9),'ms'),
   'activity_minutes':(42-(1.3*drift if scenario=='sleep_debt' else 0)+self.rng.uniform(-5,5),'min'),
   'stress':(3+(.24*drift if scenario=='sleep_debt' else 0)+self.rng.uniform(-.4,.4),'score_0_10'),
   'mood':(7-(.18*drift if scenario=='sleep_debt' else 0)+self.rng.uniform(-.3,.3),'score_0_10'),
  }
  stamp=(datetime.now(timezone.utc)+timedelta(seconds=step)).isoformat()
  for metric,(value,unit) in values.items():
   low,high={'sleep_hours':(0,24),'fatigue':(0,10),'stress':(0,10),'mood':(0,10),'activity_minutes':(0,1440)}.get(metric,(0,9999))
   add(self.db,dict(crew_id=CREW,metric=metric,value=round(max(low,min(high,value)),2),unit=unit,origin='synthetic',timestamp=stamp,context='mission_demo',source_id='AETHER_SCENARIO_V1'))
  self._environment(day,step,scenario)
  self.db.execute('UPDATE mission_state SET day=?,step=? WHERE id=1',(day,step));self.db.commit()
  return self.snapshot()
 def snapshot(self):
  s=self.state();records=history(self.db,CREW);latest={}
  for r in records:latest[r['metric']]=r
  env=dict(self.db.execute('SELECT * FROM environment_history ORDER BY id DESC LIMIT 1').fetchone())
  return {'mission':s,'metrics':latest,'environment':env,'analysis':report(records,CREW),
          'tasks':[dict(r) for r in self.db.execute('SELECT * FROM crew_tasks ORDER BY id')],
          'recovery_suggestions':suggest(self.db,CREW),'origin':'synthetic'}
 def toggle_task(self,task_id):
  self.db.execute("UPDATE crew_tasks SET status=CASE status WHEN 'done' THEN 'pending' ELSE 'done' END WHERE id=?",(task_id,));self.db.commit()
 def recovery(self,activity,before,after):
  now=datetime.now(timezone.utc).isoformat()
  if activity=='Zero-G Garden':result=self.garden.interact()
  elif activity=='Earth Window':result=self.window.finish('Earth view',3,before,after)
  elif activity=='Orbit Flow':
   q=self.orbit.question();result=self.orbit.submit(q,q['answer']);result['question']=q['prompt']
  elif activity=='Mind Pulse':result=self.mind.score(250,4,5)
  else:raise ValueError('Unknown activity')
  save(self.db,CREW,activity,now,now,float(before),float(after),result,origin='synthetic')
  return result
 def close(self):self.db.close()
