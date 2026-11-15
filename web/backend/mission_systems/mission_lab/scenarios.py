from ..contracts import Scenario, PlanningInput, Crew, Task, Equipment, Baseline, Event, Window

SCENARIOS=['normal','sleep_loss','fatigue_rise','pulse_shift','cognitive_decline',
           'workload_rise','environment','multifactor','missing','corrupt','noise']


def demo(name='normal',seed=67):
    if name not in SCENARIOS:raise ValueError('Unknown scenario')
    crew=[Crew(id=1,name='Alex',role='Commander',skills={'science','maintenance'}),
          Crew(id=2,name='Sam',role='Engineer',skills={'maintenance'}),
          Crew(id=3,name='Robin',role='Researcher',skills={'science'})]
    tasks=[Task(id='inspect',title='Cabin inspection',duration_minutes=60,priority=5,required_skills={'maintenance'},equipment={'toolkit':1},required=True),
           Task(id='repair',title='Preventive maintenance',duration_minutes=90,priority=4,required_skills={'maintenance'},dependencies=['inspect'],equipment={'toolkit':1},physical_load=.8),
           Task(id='samples',title='Collect samples',duration_minutes=60,priority=4,required_skills={'science'},equipment={'lab':1}),
           Task(id='experiment',title='Joint experiment',duration_minutes=90,people=2,required_skills={'science'},dependencies=['samples'],equipment={'lab':1}),
           Task(id='report',title='Research report',duration_minutes=60,required_skills={'science'},dependencies=['experiment']),
           Task(id='inventory',title='Inventory',duration_minutes=45,priority=2)]
    plan=PlanningInput(crew=crew,tasks=tasks,equipment=[Equipment(id='lab'),Equipment(id='toolkit')])
    events=[] if name=='normal' else [Event(minute=360,kind=name,crew_id=None if name=='environment' else 1)]
    return Scenario(id='mars_day_67_'+name,planning=plan,events=events,seed=seed,
                    baselines={1:Baseline(),2:Baseline(heart_rate=70,cognition=88),3:Baseline(heart_rate=62,sleep_hours=8.5)})
