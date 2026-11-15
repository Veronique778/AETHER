from contextlib import closing
import itertools,json,sqlite3,tempfile,unittest,random
from pathlib import Path
from datetime import datetime,timezone,timedelta
try:
    from fastapi.testclient import TestClient
    HAVE_FASTAPI = True
except ImportError:  # integrated build: the stdlib server is used when FastAPI is absent
    TestClient = None
    HAVE_FASTAPI = False
from pydantic import ValidationError
from mission_systems.contracts import *
from mission_systems.co_orbit.scheduler import solve,validate_schedule,metrics,candidates
from mission_systems.co_orbit.optimization import replan,apply_permitted_availability
from mission_systems.mission_lab.generator import generate
from mission_systems.mission_lab.scenarios import demo,SCENARIOS
from mission_systems.mission_lab.simulator import Simulator,effective_plan
from mission_systems.mission_lab.experiments import *
from mission_systems.symbiosis.environment import EnvironmentService,sample_environment
from mission_systems.symbiosis.analysis import trends,relationship
from mission_systems.symbiosis.scenarios import compare_conditions
from mission_systems.storage import Store
create_app = None
if HAVE_FASTAPI:
    from mission_systems.api import create_app
from mission_systems.core_adapter import to_core_measurements


def plan(**changes):
    data=dict(crew=[Crew(id=i,name=str(i),role='engineer',skills={'x'},available=[Window(start=0,end=240)]) for i in (1,2)],
              tasks=[Task(id='a',title='A',duration_minutes=60,earliest=0,deadline=240,required_skills={'x'},equipment={'kit':1}),
                     Task(id='b',title='B',duration_minutes=60,earliest=0,deadline=240,dependencies=['a'],equipment={'kit':1})],
              equipment=[Equipment(id='kit')],horizon_minutes=240,step_minutes=30)
    data.update(changes);return PlanningInput(**data)

def scenario(**updates):
    data=dict(id='test',planning=plan(),duration_minutes=480,sample_minutes=30,noise=0)
    data.update(updates);return Scenario(**data)

class ContractTests(unittest.TestCase):
    def test_invalid_units_nan_timezone(self):
        r=sample_environment(Environment(),datetime.now(timezone.utc))[0].model_dump()
        for key,value in [('unit','F'),('value',float('nan')),('timestamp',datetime.now())]:
            with self.subTest(key=key),self.assertRaises(ValidationError):Reading(**{**r,key:value})
    def test_missing_is_not_zero(self):
        r=sample_environment(Environment(),datetime.now(timezone.utc))[0].model_dump()
        self.assertIsNone(Reading(**{**r,'quality':'missing','value':None}).value)
        with self.assertRaises(ValidationError):Reading(**{**r,'quality':'missing'})
    def test_cycle_and_unknown_dependencies(self):
        for tasks in ([Task(id='a',title='a',duration_minutes=30,dependencies=['b']),Task(id='b',title='b',duration_minutes=30,dependencies=['a'])], [Task(id='a',title='a',duration_minutes=30,dependencies=['missing'])]):
            with self.assertRaises(ValidationError):plan(tasks=tasks)
    def test_duplicate_and_unknown_equipment(self):
        for tasks in ([Task(id='a',title='a',duration_minutes=30)]*2,[Task(id='a',title='a',duration_minutes=30,equipment={'missing':1})]):
            with self.assertRaises(ValidationError):plan(tasks=tasks)
    def test_no_health_fields_in_planning(self):
        with self.assertRaises(ValidationError):Crew(id=1,name='a',role='x',diagnosis='secret')
    def test_utc_conversion(self):
        t=datetime(2035,1,1,12,tzinfo=timezone(timedelta(hours=2)))
        self.assertEqual(sample_environment(Environment(),t)[0].timestamp.hour,10)

class SchedulerTests(unittest.TestCase):
    def test_dependencies_and_resources(self):
        p=plan();r=solve(p)
        self.assertEqual(r['status'],'optimal_on_grid');self.assertEqual(len(r['assignments']),2)
        self.assertEqual(validate_schedule(p,r['assignments']),[])
        a,b=sorted(r['assignments'],key=lambda x:x['task_id']);self.assertGreaterEqual(b['start'],a['end'])
    def test_team_and_skills(self):
        p=plan(tasks=[Task(id='a',title='a',people=2,required_skills={'x'},duration_minutes=60,earliest=0,deadline=240)])
        self.assertEqual(len(solve(p)['assignments'][0]['crew_ids']),2)
        d=p.model_dump();d['crew'][1]['skills']=set();self.assertEqual(solve(PlanningInput(**d))['assignments'],[])
    def test_no_available_crew(self):
        d=plan().model_dump()
        for c in d['crew']:c['available']=[]
        self.assertEqual(solve(PlanningInput(**d))['assignments'],[])
    def test_no_equipment(self):
        d=plan().model_dump();d['equipment'][0]['capacity']=0
        self.assertEqual(solve(PlanningInput(**d))['assignments'],[])
    def test_rest_and_work_limits(self):
        d=plan().model_dump()
        for c in d['crew']:c['rest']=[{'start':0,'end':180}];c['max_work_minutes_per_day']=30
        self.assertEqual(solve(PlanningInput(**d))['assignments'],[])
    def test_non_grid_duration(self):
        a=solve(plan(tasks=[Task(id='a',title='a',duration_minutes=41,earliest=7,deadline=200)]))['assignments'][0]
        self.assertEqual(a['end']-a['start'],41);self.assertEqual(a['start']%30,0)
    def test_priority(self):
        p=plan(crew=[Crew(id=1,name='A',role='x',available=[Window(start=0,end=60)])],tasks=[Task(id=k,title=k,duration_minutes=60,earliest=0,deadline=60,priority=v,required=(k=='urgent')) for k,v in [('low',1),('urgent',5)]])
        self.assertEqual([a['task_id'] for a in solve(p)['assignments']],['urgent'])
        # 1.0: with every task mandatory (default) the two tasks cannot both fit → no valid schedule
        q=plan(crew=[Crew(id=1,name='A',role='x',available=[Window(start=0,end=60)])],tasks=[Task(id=k,title=k,duration_minutes=60,earliest=0,deadline=60,priority=v) for k,v in [('low',1),('urgent',5)]])
        r=solve(q);self.assertFalse(r['valid']);self.assertEqual(r['assignments'],[])
    def test_arbitrary_invalid_schedule(self):
        rows=[Assignment(task_id='a',crew_ids=[1],start=0,end=60),Assignment(task_id='b',crew_ids=[1],start=30,end=90)]
        errors=validate_schedule(plan(),rows)
        for word in ('Equipment','dependency','break'):self.assertTrue(any(word in e for e in errors))
    def test_midnight_daily_limit(self):
        p=plan(crew=[Crew(id=1,name='a',role='x',available=[Window(start=1380,end=1500)],max_work_minutes_per_day=60)],tasks=[Task(id='a',title='a',duration_minutes=120,earliest=1380,deadline=1500)],horizon_minutes=1600)
        self.assertEqual(len(solve(p)['assignments']),1)
    def test_equipment_capacity_two(self):
        p=plan(tasks=[Task(id=x,title=x,duration_minutes=60,earliest=0,deadline=60,equipment={'kit':1}) for x in ('a','b')],equipment=[Equipment(id='kit',capacity=2)])
        self.assertEqual(len(solve(p)['assignments']),2)
    def test_exhaustive_optimum(self):
        p=plan(horizon_minutes=120,step_minutes=60);opts,_=candidates(p);best=0
        for mask in itertools.product((0,1),repeat=len(opts)):
            rows=[a for a,f in zip(opts,mask) if f]
            if not validate_schedule(p,rows):best=max(best,metrics(p,rows)['priority_score'])
        self.assertEqual(solve(p)['metrics']['priority_score'],best)
    def test_replan_changes(self):
        p,r=replan(plan(),task_updates=[{'id':'a','duration_minutes':90},{'id':'c','title':'urgent','priority':5,'duration_minutes':30,'earliest':0,'deadline':120}])
        self.assertEqual(p.tasks[0].duration_minutes,90)
        for result in r['alternatives']:self.assertEqual(validate_schedule(p,result['assignments']),[])
    def test_projection_permission(self):
        p=plan();r=PhantomResult(sample_id='x',unavailable={1:[Window(start=0,end=60)]})
        with self.assertRaises(ValueError):apply_permitted_availability(p,[r])
        r.planning_authorized=True;self.assertEqual(apply_permitted_availability(p,[r]).crew[0].rest[0].end,60)
    def test_empty_tasks(self):self.assertEqual(solve(plan(tasks=[]))['assignments'],[])
    def test_randomized_feasibility(self):
        rng=random.Random(82)
        for _ in range(12):
            ts=[Task(id=str(i),title=str(i),duration_minutes=rng.choice([20,40,60]),earliest=0,deadline=rng.choice([90,120,180]),equipment={'kit':1},priority=rng.randint(1,5)) for i in range(4)]
            p=plan(tasks=ts);self.assertEqual(validate_schedule(p,solve(p)['assignments']),[])

class SimulationTests(unittest.TestCase):
    def test_repeatable_seed(self):
        s=scenario(noise=.3);self.assertEqual(generate(s),generate(s));self.assertNotEqual(generate(s),generate(scenario(noise=.3,seed=68)))
    def test_temporal_response_and_origin(self):
        d=generate(scenario(events=[Event(minute=60,kind='sleep_loss',ramp_minutes=60)]))
        vs=[next(r['value'] for r in f['measurements'] if r['metric']=='sleep_hours' and r['crew_id']==1) for f in d['frames']]
        self.assertLess(vs[-1],vs[0]);self.assertLess(abs(vs[4]-vs[3]),1.6)
        self.assertTrue(all(r['origin']=='synthetic' for f in d['frames'] for r in f['measurements']+f['environment']))
    def test_parameter_effect(self):
        a=summarize(generate(scenario(sleep_hours=8)));b=summarize(generate(scenario(sleep_hours=5)))
        self.assertGreater(a['means']['1:cognition'],b['means']['1:cognition'])
    def test_corrupt_data(self):
        d=generate(scenario(events=[Event(minute=0,kind='corrupt',intensity=3,ramp_minutes=0)]))
        bad=[r for f in d['frames'] for r in f['measurements'] if r['quality']=='invalid']
        self.assertTrue(bad);self.assertTrue(all(r['value'] is None for r in bad))
    def test_no_ground_truth_leak(self):
        text=json.dumps(phantom_input(generate(scenario(events=[Event(minute=60,kind='multifactor')]))))
        for word in ('ground_truth','injected_changes','multifactor','events','anomaly'):self.assertNotIn(word,text)
    def test_controls(self):
        s=Simulator(scenario());s.start();s.set_speed(60);s.tick(30);self.assertEqual(s.minute,30)
        s.pause();s.tick(30);self.assertEqual(s.minute,30);s.resume();s.tick(30);self.assertEqual(s.minute,60)
        s.seek(480);self.assertEqual(s.status,'finished');s.seek(0);self.assertEqual(s.status,'paused');s.reset();self.assertEqual(s.status,'ready')
        for v in (-1,float('nan'),500):
            with self.assertRaises(ValueError):s.seek(v)
    def test_invalid_update_is_atomic(self):
        s=Simulator(scenario());before=s.scenario
        with self.assertRaises(ValidationError):s.update({'sleep_hours':99})
        self.assertEqual(s.scenario,before)
    def test_extra_rest_changes_availability(self):self.assertEqual(effective_plan(scenario(extra_rest_hours=2)).crew[0].available[0].end,120)
    def test_persistent_exact_replay(self):
        with tempfile.TemporaryDirectory() as d:
            st=Store(Path(d)/'a.db');s=Simulator(scenario(),st);s.start();s.seek(90);s.save();r=Simulator.restore(st,'test')
            self.assertEqual(r.state(),s.state());self.assertEqual(r.dataset,s.dataset)
    def test_adapter(self):
        s=Simulator(scenario(events=[Event(minute=60,kind='pulse_shift',ramp_minutes=0)]));truth={r['sample_id']:r['anomaly'] for r in s.dataset['ground_truth']}
        class Fixture:
            def analyze(self,p):return [PhantomResult(sample_id=x['sample_id'],anomaly=truth[x['sample_id']]) for x in p['samples']]
        r=s.analyze_with(Fixture())['evaluation']['phantom'];self.assertEqual(r['precision'],1);self.assertEqual(r['recall'],1)
    def test_all_templates(self):
        for name in SCENARIOS:self.assertEqual(len(generate(demo(name))['frames']),49)
    def test_missing_phantom(self):
        r=experiment_report(generate(scenario()));self.assertIsNone(r['phantom']);self.assertEqual(r['phantom_status'],'not_connected')
    def test_bad_predictions(self):
        d=generate(scenario());key=d['ground_truth'][0]['sample_id']
        with self.assertRaises(ValueError):evaluate(d,[PhantomResult(sample_id='bad')])
        with self.assertRaises(ValueError):evaluate(d,[PhantomResult(sample_id=key)]*2)
    def test_confusion_and_abstentions(self):
        d={'ground_truth':[{'sample_id':str(i),'anomaly':a} for i,a in enumerate([True,True,False,False])]}
        r=evaluate(d,[PhantomResult(sample_id='0',anomaly=True),PhantomResult(sample_id='2',anomaly=True),PhantomResult(sample_id='3',anomaly=False)])
        self.assertEqual([r[k] for k in ('tp','fn','fp','tn')],[1,1,1,1]);self.assertEqual(r['recall'],.5);self.assertEqual(r['coverage'],.75)

class EnvironmentTests(unittest.TestCase):
    def test_history_transaction_stale(self):
        with tempfile.TemporaryDirectory() as d:
            service=EnvironmentService(Store(Path(d)/'a.db'));now=datetime(2035,1,1,tzinfo=timezone.utc);rows=sample_environment(Environment(),now)
            service.ingest(rows);service.ingest(rows);self.assertEqual(len(service.history('habitat')),4)
            with self.assertRaises(ValueError):service.ingest([sample_environment(Environment(),now+timedelta(hours=1))[0],rows[0].model_copy(update={'value':24})])
            self.assertEqual(len(service.history('habitat')),4)
            self.assertTrue(all(r['quality']=='stale' for r in service.state('habitat',as_of=now+timedelta(hours=3))['readings']))
    def test_preserves_core_tables(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.db'
            with closing(sqlite3.connect(p)) as c, c:c.execute('CREATE TABLE crew(id INTEGER,name TEXT)');c.execute("INSERT INTO crew VALUES(1,'existing')")
            with self.assertRaises(sqlite3.ProgrammingError): c.execute('SELECT 1')
            Store(p)
            with closing(sqlite3.connect(p)) as c, c:self.assertEqual(c.execute('SELECT name FROM crew').fetchone()[0],'existing')
            with self.assertRaises(sqlite3.ProgrammingError): c.execute('SELECT 1')
    def test_trend_correlation(self):
        env=[];phys=[];base=datetime(2035,1,1,tzinfo=timezone.utc)
        for i in range(4):
            env.append(Reading(metric='co2',value=800+i*100,unit='ppm',timestamp=base+timedelta(hours=i),origin='synthetic',source_id='x',zone_id='hab'))
            phys.append(Reading(metric='cognition',value=90-i*2,unit='score_0_100',timestamp=base+timedelta(hours=i),origin='synthetic',source_id='x',crew_id=1))
        self.assertAlmostEqual(trends(env)[0]['slope_per_hour'],100)
        r=relationship(env,phys,env_metric='co2',metric='cognition',crew_id=1,zone_id='hab');self.assertAlmostEqual(r['pearson_r'],-1);self.assertFalse(r['causal'])
        phys[0].origin='real'
        with self.assertRaises(ValueError):relationship(env,phys,env_metric='co2',metric='cognition',crew_id=1,zone_id='hab')
    def test_insufficient_correlation(self):self.assertIsNone(relationship([],[],env_metric='co2',metric='cognition',crew_id=1,zone_id='hab')['pearson_r'])
    def test_conditions_uncertainty(self):
        r=compare_conditions(Environment(temperature=28,night_light=100),Environment(),sleep_a=5,sleep_b=8)
        self.assertGreater(r['delta']['sleep_quality'],0);self.assertFalse(r['actuation']);self.assertIn('sensitivity_range_b',r)
    def test_core_bridge(self):
        r=sample_environment(Environment(),datetime.now(timezone.utc))[0];bad=r.model_copy(update={'quality':'invalid','value':None})
        result=to_core_measurements([r,bad]);self.assertEqual(len(result['items']),1);self.assertEqual(len(result['rejected']),1)
        self.assertEqual(result['items'][0]['metadata']['zone_id'],'habitat')

@unittest.skipUnless(HAVE_FASTAPI, "FastAPI not installed")
class APITests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.client=TestClient(create_app(Path(self.temp.name)/'a.db'))
    def tearDown(self):self.client.close();self.temp.cleanup()
    def test_contract_errors(self):
        self.assertEqual(self.client.get('/v1/health').status_code,200);self.assertEqual(self.client.get('/v1/simulations/missing').status_code,404)
        self.assertEqual(self.client.post('/v1/simulations',json={'bad':'data'}).status_code,422);self.assertEqual(self.client.get('/openapi.json').status_code,200)
    def test_end_to_end(self):
        s=scenario();prefix='/v1/simulations/'+s.id
        self.assertEqual(self.client.post('/v1/simulations',json=s.model_dump(mode='json')).status_code,200)
        for action,v in [('start',0),('speed',60),('tick',30),('pause',0),('resume',0),('seek',90),('reset',0)]:self.assertEqual(self.client.post(prefix+'/control',json={'action':action,'value':v}).status_code,200)
        for endpoint in ('dataset','phantom-input','evaluation'):self.assertEqual(self.client.get(prefix+'/'+endpoint).status_code,200)
        body=s.model_dump(mode='json');body['sleep_hours']=6;self.assertEqual(self.client.put(prefix,json=body).status_code,200)
        body['id']='comparison';self.assertEqual(self.client.post('/v1/simulations',json=body).status_code,200)
        self.assertEqual(self.client.post('/v1/experiments/compare',json={'a':s.id,'b':'comparison'}).status_code,200)
    def test_manual_schedule_and_replan(self):
        self.assertEqual(self.client.put('/v1/plans/test',json=plan().model_dump(mode='json')).status_code,200)
        r=self.client.post('/v1/plans/test/replan',json={'equipment_updates':[{'id':'kit','capacity':0}]})
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['schedules']['alternatives'][0]['assignments'],[])
        self.assertEqual(self.client.put('/v1/plans/test/schedule',json=[{'task_id':'a','crew_ids':[1],'start':0,'end':60}]).status_code,422)
    def test_token(self):
        client=TestClient(create_app(Path(self.temp.name)/'secure.db',api_token='test-only'))
        self.assertEqual(client.get('/v1/health').status_code,401);self.assertEqual(client.get('/v1/health',headers={'X-Aether-Token':'test-only'}).status_code,200);client.close()

if __name__=='__main__':unittest.main()
