import tempfile,unittest
from pathlib import Path
from services.live_demo import DemoSystem
class LiveDemoTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.app=DemoSystem(Path(self.tmp.name)/'test.db')
 def tearDown(self):self.app.close();self.tmp.cleanup()
 def test_initial_seed_and_provenance(self):
  s=self.app.snapshot();self.assertEqual(s['mission']['day'],67)
  self.assertEqual(s['origin'],'synthetic')
  self.assertEqual(s['metrics']['resting_hr']['origin'],'synthetic')
 def test_scenario_updates_and_phantom(self):
  self.app.scenario('sleep_debt')
  for _ in range(8):self.app.tick()
  s=self.app.snapshot();self.assertEqual(s['mission']['day'],75)
  self.assertGreater(len(s['analysis']['alerts']),0)
 def test_environment_and_tasks(self):
  self.app.scenario('cabin_co2')
  for _ in range(3):self.app.tick()
  self.assertGreater(self.app.snapshot()['environment']['co2_ppm'],680)
  self.app.toggle_task(1);self.assertEqual(self.app.snapshot()['tasks'][0]['status'],'done')
 def test_recovery_persistence(self):
  self.app.recovery('Mind Pulse',5,6)
  n=self.app.db.execute('SELECT count(*) FROM recovery_sessions').fetchone()[0]
  self.assertEqual(n,1)
if __name__=='__main__':unittest.main()
