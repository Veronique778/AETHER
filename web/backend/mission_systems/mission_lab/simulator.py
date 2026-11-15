"""Deterministic interactive simulation; host UI supplies elapsed real seconds to tick."""
import math
from threading import RLock
from ..contracts import Scenario, PlanningInput
from ..co_orbit.optimization import alternatives,apply_permitted_availability
from .generator import generate
from .experiments import phantom_input,validate_results,experiment_report


def effective_plan(scenario):
    data=scenario.planning.model_dump()
    # Extra rest reserves the end of each person's last availability window per day.
    # Explicit crew.rest is already a hard scheduling constraint.
    reserve=round(scenario.extra_rest_hours*60)
    if reserve:
        for c in data['crew']:
            windows=[]
            for w in c['available']:
                for day in range(w['start']//1440,(w['end']-1)//1440+1):
                    start=max(w['start'],day*1440);end=min(w['end'],(day+1)*1440)
                    if end-start>reserve:windows.append({'start':start,'end':end-reserve})
            c['available']=windows
    return PlanningInput.model_validate(data)


class Simulator:
    def __init__(self, scenario, store=None):
        self.scenario=Scenario.model_validate(scenario);self.store=store;self.lock=RLock()
        self.minute=0.0;self.speed=1.0;self.status='ready';self.phantom_results=None
        self.rebuild()

    def rebuild(self):
        self.plan=effective_plan(self.scenario)
        self.schedules=alternatives(self.plan)
        self.dataset=generate(self.scenario,self.schedules['alternatives'][1])
        self.phantom_results=None

    def start(self):
        with self.lock:
            if self.minute>=self.scenario.duration_minutes:self.minute=0
            self.status='running';return self.state()

    def pause(self):
        with self.lock:
            if self.status=='running':self.status='paused'
            return self.state()

    def resume(self):
        with self.lock:
            if self.status!='paused':raise ValueError('Only a paused simulation can resume')
            self.status='running';return self.state()

    def reset(self):
        with self.lock:
            self.minute=0;self.status='ready';return self.state()

    def set_speed(self,speed):
        if not math.isfinite(speed) or not 0<speed<=10000:raise ValueError('Speed must be in (0,10000]')
        with self.lock:self.speed=speed;return self.state()

    def seek(self,minute):
        if not math.isfinite(minute) or not 0<=minute<=self.scenario.duration_minutes:raise ValueError('Time outside simulation')
        with self.lock:
            self.minute=float(minute)
            if minute==self.scenario.duration_minutes:self.status='finished'
            elif self.status=='finished':self.status='paused'
            return self.state()

    def tick(self,elapsed_seconds):
        if not math.isfinite(elapsed_seconds) or elapsed_seconds<0:raise ValueError('elapsed_seconds must be finite and nonnegative')
        with self.lock:
            if self.status=='running':self.seek(min(self.scenario.duration_minutes,self.minute+elapsed_seconds*self.speed/60))
            return self.state()

    def state(self):
        with self.lock:
            index=min(len(self.dataset['frames'])-1,int(self.minute//self.scenario.sample_minutes))
            return {'scenario_id':self.scenario.id,'status':self.status,'minute':self.minute,
                    'duration_minutes':self.scenario.duration_minutes,'speed':self.speed,
                    'frame':self.dataset['frames'][index],'sample_policy':'Last sample at or before cursor',
                    'phantom_status':'connected' if self.phantom_results is not None else 'not_connected',
                    'schedule':self.schedules['alternatives'][1],
                    'limitations':self.dataset['limitations']}

    def update(self,changes):
        with self.lock:
            # Full nested values required; validation happens before mutation.
            data=self.scenario.model_dump();data.update(changes)
            new=Scenario.model_validate(data)
            replacement=Simulator(new,self.store)
            self.scenario=replacement.scenario;self.plan=replacement.plan
            self.schedules=replacement.schedules;self.dataset=replacement.dataset
            self.phantom_results=None;self.minute=0;self.status='ready'
            return self.state()

    def submit_phantom(self,results):
        with self.lock:
            checked=validate_results(self.dataset,results)
            # Validate permissions before storing or exposing revised plans.
            plan=apply_permitted_availability(self.plan,checked)
            revised=alternatives(plan) if plan!=self.plan else self.schedules
            self.phantom_results=[r.model_dump(mode='json') for r in checked]
            return {'evaluation':experiment_report(self.dataset,self.phantom_results),
                    'proposed_plan':plan.model_dump(mode='json'),'proposed_schedules':revised,
                    'note':'To simulate the proposal, create a new scenario with proposed_plan and compare runs.'}

    def analyze_with(self,adapter):
        return self.submit_phantom(adapter.analyze(phantom_input(self.dataset)))

    def save(self):
        if self.store is None:raise ValueError('No persistent store configured')
        with self.lock:
            payload={'scenario':self.scenario.model_dump(mode='json'),'minute':self.minute,
                     'speed':self.speed,'status':self.status,'phantom_results':self.phantom_results,
                     'schedules':self.schedules,'dataset':self.dataset}
            self.store.save('simulation',self.scenario.id,payload)
            self.store.save('scenario',self.scenario.id,self.scenario)
            self.store.save('planning',self.scenario.id,self.plan)
            self.store.save('schedules',self.scenario.id,self.schedules)
            return self.scenario.id

    @classmethod
    def restore(cls,store,key):
        data=store.get('simulation',key)
        # Restore exact computed data, avoiding differences between solver versions/tie-breaking.
        obj=cls.__new__(cls);obj.scenario=Scenario.model_validate(data['scenario']);obj.store=store;obj.lock=RLock()
        obj.minute=data['minute'];obj.speed=data['speed'];obj.status=data['status']
        obj.plan=effective_plan(obj.scenario);obj.schedules=data['schedules'];obj.dataset=data['dataset'];obj.phantom_results=data['phantom_results']
        return obj
