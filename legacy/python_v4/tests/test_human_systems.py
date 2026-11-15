import unittest,sqlite3
from datetime import datetime,timezone
from modules.biometric.validation import validate
from modules.biometric.ingestion import connect,add,history
from modules.phantom_engine.baseline import baseline
from modules.phantom_engine.anomalies import analyze
from modules.recovery_engine.activities import OrbitFlow,MindPulse
from modules.recovery_engine.recovery_lab import save,suggest
NOW=datetime.now(timezone.utc).isoformat()
def record(metric,value,unit='bpm'):
 return {'crew_id':'T1','metric':metric,'value':value,'unit':unit,'origin':'synthetic','timestamp':NOW,'source_id':'test'}
class HumanSystemsTests(unittest.TestCase):
 def test_validation(self):
  self.assertEqual(validate(record('heart_rate',75))['value'],75)
  with self.assertRaises(ValueError):validate(record('heart_rate',999))
 def test_storage(self):
  with connect(':memory:') as db:
   add(db,record('heart_rate',70));self.assertEqual(len(history(db,'T1')),1)
 def test_baseline(self):
  self.assertEqual(baseline([record('resting_hr',70) for _ in range(6)],'resting_hr')['median'],70)
 def test_multifactor(self):
  records=[]
  for i in range(10):
   for m,v,u in [('resting_hr',70+i%2,'bpm'),('sleep_hours',8-i%2*.1,'h'),('fatigue',2+i%2,'score_0_10'),('reaction_ms',250+i%2*5,'ms')]:
    row=record(m,v,u);row['timestamp']=f'2026-10-{i+1:02d}T12:00:00+00:00';records.append(row)
  for m,v,u in [('resting_hr',88,'bpm'),('sleep_hours',5,'h'),('fatigue',8,'score_0_10'),('reaction_ms',400,'ms')]:
   row=record(m,v,u);row['timestamp']='2026-10-20T12:00:00+00:00';records.append(row)
  self.assertTrue(any(a['type']=='multifactor' for a in analyze(records)['alerts']))
 def test_games(self):
  g=OrbitFlow();q=g.question();self.assertTrue(g.submit(q,q['answer'])['correct'])
  self.assertEqual(MindPulse().score(200,3,4)['accuracy'],.75)
 def test_recovery(self):
  db=sqlite3.connect(':memory:')
  for _ in range(2):save(db,'T1','earth_window',NOW,NOW,4,7,{},'synthetic')
  self.assertEqual(suggest(db,'T1')[0]['activity'],'earth_window')
if __name__=='__main__':unittest.main()
