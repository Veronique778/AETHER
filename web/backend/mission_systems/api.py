"""Local API for the team's frontend, PHANTOM adapter and 3D data binding."""
import os
import secrets
from datetime import datetime
from threading import RLock
from typing import Literal
from fastapi import FastAPI, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import Field, ValidationError
from .contracts import Model, Scenario, PlanningInput, Reading, Environment, PhantomResult, Assignment, Task, Crew
from .storage import Store
from .symbiosis.environment import EnvironmentService
from .symbiosis.analysis import trends,relationship,compare_periods
from .symbiosis.scenarios import compare_conditions
from .co_orbit.optimization import alternatives,replan,compare,commit_if_valid
from .co_orbit.scheduler import validate_schedule
from .mission_lab.scenarios import demo,SCENARIOS
from .mission_lab.simulator import Simulator
from .mission_lab.experiments import phantom_input,experiment_report,compare_runs

class Control(Model):
    action: Literal['start','pause','resume','reset','seek','speed','tick']
    value: float = 0

class ReplanRequest(Model):
    crew_updates: list[dict] = Field(default_factory=list)
    task_updates: list[dict] = Field(default_factory=list)
    equipment_updates: list[dict] = Field(default_factory=list)

class Conditions(Model):
    a: Environment
    b: Environment
    sleep_a: float = Field(default=8,ge=0,le=12)
    sleep_b: float = Field(default=8,ge=0,le=12)
    rest_a: float = Field(default=0,ge=0,le=8)
    rest_b: float = Field(default=0,ge=0,le=8)
    workload: float = Field(default=6,ge=0,le=24)

class Relationship(Model):
    environment: list[Reading]
    physiology: list[Reading]
    env_metric: str
    metric: str
    crew_id: int
    zone_id: str
    lag_minutes: int = Field(default=0,ge=0)

class Periods(Model):
    readings: list[Reading]
    start_a: datetime
    end_a: datetime
    start_b: datetime
    end_b: datetime

class RunComparison(Model):
    a: str
    b: str

class ScheduleComparison(Model):
    plan: PlanningInput
    before: list[Assignment]
    after: list[Assignment]


def create_app(db_path=None,api_token=None):
    store=Store(db_path);env=EnvironmentService(store);sims={};lock=RLock()
    token=api_token if api_token is not None else os.getenv('AETHER_API_TOKEN')
    def authorize(x_aether_token: str | None = Header(default=None)):
        if token and (not x_aether_token or not secrets.compare_digest(token,x_aether_token)):
            raise HTTPException(401,'Invalid API token')
    app=FastAPI(title='AETHER Mission Systems',version='1.0.0',dependencies=[Depends(authorize)],
                description='SYMBIOSIS, CO-ORBIT and MISSION LAB. Local research simulation; synthetic data clearly labeled.')
    app.state.store=store

    @app.exception_handler(ValueError)
    async def invalid(request,exc):return JSONResponse(status_code=422,content={'detail':str(exc)})
    @app.exception_handler(KeyError)
    async def missing(request,exc):return JSONResponse(status_code=404,content={'detail':str(exc)})

    def simulation(key):
        with lock:
            if key not in sims:sims[key]=Simulator.restore(store,key)
            return sims[key]

    @app.get('/v1/health')
    def health():return {'status':'ok','api_version':'1.0','mode':'local','token_enabled':bool(token)}

    @app.get('/v1/templates')
    def templates():return {'templates':SCENARIOS}

    @app.get('/v1/templates/{name}')
    def template(name:str):return demo(name).model_dump(mode='json')

    @app.post('/v1/environment/readings')
    def ingest(readings:list[Reading]):return {'accepted':env.ingest(readings)}

    @app.get('/v1/environment/{zone}/history')
    def history(zone:str,start:datetime|None=None,end:datetime|None=None,
                origin:Literal['real','synthetic','estimated']|None=None,limit:int=Query(default=10000,ge=1,le=100000)):
        for value in (start,end):
            if value and value.tzinfo is None:raise ValueError('Timezone required')
        if start and end and start>end:raise ValueError('Invalid time range')
        return env.history(zone,start=start,end=end,origin=origin,limit=limit)

    @app.get('/v1/environment/{zone}/state')
    def state(zone:str,as_of:datetime|None=None,stale_minutes:int=Query(default=120,ge=0),origin:Literal['real','synthetic','estimated']|None=None):
        return env.state(zone,as_of=as_of,stale_minutes=stale_minutes,origin=origin)

    @app.post('/v1/environment/trends')
    def trend(readings:list[Reading]):return trends(readings)

    @app.post('/v1/environment/relationship')
    def relation(body:Relationship):return relationship(**body.model_dump())

    @app.post('/v1/environment/periods')
    def periods(body:Periods):return compare_periods(**body.model_dump())

    @app.post('/v1/environment/compare')
    def conditions(body:Conditions):
        args=body.model_dump(exclude={'a','b'})
        return compare_conditions(body.a,body.b,**args)

    @app.put('/v1/plans/{key}')
    def save_plan(key:str,plan:PlanningInput):
        store.save('planning',key,plan);return plan

    @app.get('/v1/plans/{key}')
    def get_plan(key:str):return store.get('planning',key)

    @app.put('/v1/plans/{key}/tasks/{task_id}')
    def edit_task(key:str,task_id:str,task:Task):
        if task.id!=task_id:raise ValueError('Task id mismatch')
        plan=PlanningInput.model_validate(store.get('planning',key))
        updated,result=replan(plan,task_updates=[task.model_dump()])
        return {**result,**commit_if_valid(store,key,updated,result)}

    @app.put('/v1/plans/{key}/crew/{crew_id}')
    def edit_crew(key:str,crew_id:int,crew:Crew):
        if crew.id!=crew_id:raise ValueError('Crew id mismatch')
        plan=PlanningInput.model_validate(store.get('planning',key))
        updated,result=replan(plan,crew_updates=[crew.model_dump()])
        return {**result,**commit_if_valid(store,key,updated,result)}

    @app.post('/v1/plans/{key}/optimize')
    def optimize(key:str):
        plan=PlanningInput.model_validate(store.get('planning',key))
        result=alternatives(plan)
        return {**result,**commit_if_valid(store,key,plan,result)}

    @app.post('/v1/plans/{key}/replan')
    def recalculate(key:str,body:ReplanRequest):
        plan=PlanningInput.model_validate(store.get('planning',key))
        updated,result=replan(plan,**body.model_dump())
        state=commit_if_valid(store,key,updated,result)
        return {'plan':updated if state['persisted'] else plan,'proposed_plan':updated,'schedules':result,**state}

    @app.put('/v1/plans/{key}/schedule')
    def manual_schedule(key:str,assignments:list[Assignment]):
        plan=PlanningInput.model_validate(store.get('planning',key))
        violations=validate_schedule(plan,assignments,require_all_required=True)
        if violations:raise ValueError('; '.join(violations))
        result=[a.model_dump() for a in assignments];store.save('manual_schedule',key,result);return result

    @app.get('/v1/plans/{key}/schedules')
    def schedules(key:str):return store.get('schedules',key)

    @app.post('/v1/plans/compare')
    def compare_schedules(body:ScheduleComparison):return compare(body.plan,body.before,body.after)

    @app.post('/v1/simulations')
    def create_simulation(scenario:Scenario):
        with lock:
            sim=Simulator(scenario,store);sim.save();sims[scenario.id]=sim
        env.ingest([r for frame in sim.dataset['frames'] for r in frame['environment']])
        return sim.state()

    @app.get('/v1/simulations')
    def list_simulations():return store.list('scenario')

    @app.get('/v1/simulations/{key}')
    def get_simulation(key:str):return simulation(key).state()

    @app.put('/v1/simulations/{key}')
    def update_simulation(key:str,scenario:Scenario):
        if scenario.id!=key:raise ValueError('Scenario id must match URL')
        sim=simulation(key);sim.update(scenario.model_dump());sim.save()
        env.ingest([r for frame in sim.dataset['frames'] for r in frame['environment']])
        return sim.state()

    @app.post('/v1/simulations/{key}/control')
    def control(key:str,body:Control):
        sim=simulation(key)
        methods={'start':sim.start,'pause':sim.pause,'resume':sim.resume,'reset':sim.reset,
                 'seek':sim.seek,'speed':sim.set_speed,'tick':sim.tick}
        with sim.lock:
            result=methods[body.action](body.value) if body.action in ('seek','speed','tick') else methods[body.action]()
            sim.save()
        return result

    @app.get('/v1/simulations/{key}/dataset')
    def dataset(key:str):return simulation(key).dataset

    @app.get('/v1/simulations/{key}/phantom-input')
    def input_for_phantom(key:str):return phantom_input(simulation(key).dataset)

    @app.post('/v1/simulations/{key}/phantom-results')
    def receive_phantom(key:str,results:list[PhantomResult]):
        sim=simulation(key);report=sim.submit_phantom(results);sim.save();return report

    @app.get('/v1/simulations/{key}/evaluation')
    def evaluation(key:str):
        sim=simulation(key);return experiment_report(sim.dataset,sim.phantom_results)

    @app.post('/v1/experiments/compare')
    def experiment_comparison(body:RunComparison):return compare_runs(simulation(body.a),simulation(body.b))

    return app
