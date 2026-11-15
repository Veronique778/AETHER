"""FastAPI entry point (primary server). Logic lives in app.service."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from . import db, security, service
from .mission_engine import ConditionCompare, ReplanRequest, CoorbitApply, CoorbitReject, EngineCompare, EngineControl, EngineRunRequest
from .science.hazards import MissionProfile
from .schemas import RadiationRequest, Experiment, Measurement, PlanRequest, ProjectionRequest, RecoverySession, SimulationRequest


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    from .persistence.science_lifecycle import start, stop
    start()
    try: yield
    finally: stop()


app = FastAPI(title='AETHER API', version=service.API_VERSION, lifespan=lifespan,
              description='Research demonstrator with synthetic test data.')
# 1.4: the same Host/Origin/session-token policy as app.devserver (see app/security.py).
# CORS is emitted only for allow-listed developer origins; CORS is not treated as authentication.
POLICY = security.Policy()
from .api_15 import PersonalAPI
app.add_middleware(PersonalAPI)
app.add_middleware(security.ASGISecurity, policy=POLICY)


@app.get('/api/session')
def session_bootstrap():
    """Token bootstrap for the Vite dev UI; the middleware has already checked Host/Origin."""
    return security.session_payload(POLICY)


def call(fn, *args):
    try:
        return fn(*args)
    except service.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except service.BadRequest as exc:
        raise HTTPException(400, str(exc)) from exc
    except service.Unavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get('/api/health')
def health():
    return service.health()


@app.get('/api/astronauts')
def get_astronauts():
    return service.get_astronauts()


@app.get('/api/astronauts/{astronaut_id}/timeline')
def get_timeline(astronaut_id: str, day: int = Query(67, ge=1)):
    return call(service.get_timeline, astronaut_id, day)


@app.post('/api/astronauts/{astronaut_id}/measurements')
def post_measurement(astronaut_id: str, measurement: Measurement):
    return call(service.post_measurement, astronaut_id, measurement)


@app.get('/api/phantom/{astronaut_id}')
def phantom(astronaut_id: str, day: int = Query(67, ge=1)):
    return call(service.phantom, astronaut_id, day)


@app.get('/api/phantom/{astronaut_id}/history')
def phantom_history(astronaut_id: str, day: int = Query(67, ge=1), start: int = Query(41, ge=1)):
    return call(service.phantom_history, astronaut_id, day, start)


@app.get('/api/phantom/{astronaut_id}/correlations')
def phantom_correlations(astronaut_id: str, day: int = Query(67, ge=1), window: int = Query(30, ge=8, le=365)):
    return call(service.phantom_correlations, astronaut_id, day, window)


@app.get('/api/symbiosis')
def symbiosis(day: int = Query(67, ge=1)):
    return service.symbiosis(day)


@app.get('/api/symbiosis/history')
def symbiosis_history(zone: str = 'habitat', start: int = Query(1, ge=1), end: int = Query(67, ge=1)):
    return call(service.symbiosis_history, zone, start, end)


@app.get('/api/ship')
def ship(day: int = Query(67, ge=1), hour: float = Query(10.0, ge=0, lt=24)):
    return service.ship(day, hour)


@app.get('/api/co-orbit')
def co_orbit(reduce_a01: bool = False):
    return service.co_orbit(reduce_a01)


@app.get('/api/co-orbit/calendar')
def co_orbit_calendar(day: int = Query(67, ge=1)):
    return service.co_orbit_calendar(day)


@app.post('/api/co-orbit/plan')
def co_orbit_plan(payload: PlanRequest):
    return call(service.co_orbit_plan, payload)


@app.get('/api/mission-lab/scenarios')
def scenarios():
    return service.scenarios()


@app.post('/api/mission-lab/run')
def simulate(payload: SimulationRequest):
    return call(service.simulate, payload)


@app.post('/api/mission-lab/project')
def projection(payload: ProjectionRequest):
    return call(service.projection, payload)


@app.post('/api/recovery/sessions')
def save_recovery(payload: RecoverySession):
    return call(service.save_recovery, payload)


@app.get('/api/recovery/sessions/{astronaut_id}')
def get_recovery(astronaut_id: str):
    return call(service.get_recovery, astronaut_id)


@app.get('/api/human-systems/{astronaut_id}/quality')
def human_systems_quality(astronaut_id: str, day: int = Query(67, ge=1), window: int = Query(14, ge=3, le=365)):
    from .human_systems import summary
    try:
        return summary(astronaut_id, day, window)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


# NASA OSDR research data are kept separate from astronaut demo telemetry.
@app.get('/api/nasa/catalog')
def nasa_catalog(term: str = 'human physiology', refresh: bool = False):
    from .nasa_research import catalog
    return catalog(term, refresh)

@app.get('/api/nasa/studies/{study_id}/files')
def nasa_files(study_id: int):
    from .nasa_research import files
    try: return files(study_id)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    except Exception as exc: raise HTTPException(503, 'NASA API is unavailable') from exc

@app.post('/api/nasa/analyze-csv')
def nasa_analyze_csv(payload: dict):
    from .nasa_research import summarize_csv
    try: return summarize_csv(str(payload.get('csv', '')), str(payload.get('column', '')))
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc



@app.get('/api/nasa/imports')
def nasa_verified_imports():
    from .nasa_research import imports
    return imports()

@app.post('/api/nasa/verified-csv')
def nasa_verified_csv(payload: dict):
    from .nasa_research import verified_csv
    try:
        return verified_csv(int(payload.get('study_id', 0)),
                            str(payload.get('filename', '')),
                            str(payload.get('column', '')),
                            str(payload.get('label_column', '')))
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(503, 'NASA OSDR data service unavailable') from exc


@app.post('/api/nasa/local-csv')
def nasa_local_csv(payload: dict):
    from .nasa_research import local_csv
    try:
        return local_csv(int(payload.get('study_id', 0)), str(payload.get('filename', '')),
                         str(payload.get('content', '')), str(payload.get('column', '')),
                         str(payload.get('label_column', '')))
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get('/api/nasa/studies/{study_id}')
def nasa_study(study_id: int):
    from .nasa_research import study_metadata
    return study_metadata(study_id)


@app.get('/api/nasa/reference-context')
def nasa_reference_context():
    from .nasa_research import reference_context
    return reference_context()


@app.get('/api/connectors')
def data_connectors():
    from .connectors import registry
    return registry()


# ---- v0.8 integration: former pending contracts + Mission Systems engine
@app.get('/api/symbiosis/crew-association')
def crew_association(day: int = Query(67, ge=1), zone: str = 'habitat'):
    return call(service.crew_association, day, zone)


@app.get('/api/recovery/biofeedback')
def biofeedback(astronaut_id: str = 'A01'):
    return call(service.biofeedback, astronaut_id)


@app.get('/api/mission-lab/experiments')
def list_experiments():
    return service.list_experiments()


@app.post('/api/mission-lab/experiments')
def save_experiment(payload: Experiment):
    return call(service.save_experiment, payload)


@app.delete('/api/mission-lab/experiments/{exp_id}')
def delete_experiment(exp_id: str):
    return call(service.delete_experiment, exp_id)


@app.get('/api/engine/status')
def engine_status():
    return service.engine_status()


@app.get('/api/engine/templates')
def engine_templates():
    return call(service.engine_templates)


@app.get('/api/engine/runs')
def engine_runs():
    return call(service.engine_runs)


@app.post('/api/engine/runs')
def engine_run(payload: EngineRunRequest):
    return call(service.engine_run, payload)


@app.get('/api/engine/runs/{run_id}')
def engine_get(run_id: str):
    return call(service.engine_get, run_id)


@app.post('/api/engine/runs/{run_id}/control')
def engine_control(run_id: str, payload: EngineControl):
    return call(service.engine_control, run_id, payload)


@app.get('/api/engine/runs/{run_id}/evaluation')
def engine_evaluation(run_id: str):
    return call(service.engine_evaluation, run_id)


@app.post('/api/engine/compare')
def engine_compare(payload: EngineCompare):
    return call(service.engine_compare, payload)



@app.get('/api/engine/plan-profiles')
def engine_plan_profiles():
    return service.engine_plan_profiles()


@app.get('/api/engine/runs/{run_id}/coorbit')
def engine_coorbit(run_id: str):
    return call(service.engine_coorbit, run_id)


@app.post('/api/engine/runs/{run_id}/coorbit/apply')
def engine_coorbit_apply(run_id: str, payload: CoorbitApply):
    return call(service.engine_coorbit_apply, run_id, payload)


@app.get('/api/engine/runs/{run_id}/environment')
def engine_environment(run_id: str, cabin_pressure_mmhg: float = Query(760.0, ge=200, le=800)):
    return call(service.engine_environment, run_id, cabin_pressure_mmhg)


@app.post('/api/engine/runs/{run_id}/coorbit/reject')
def engine_coorbit_reject(run_id: str, payload: CoorbitReject):
    return call(service.engine_coorbit_reject, run_id, payload)



@app.get('/api/phantom2/{astronaut_id}')
def phantom2_daily(astronaut_id: str, day: int = Query(67, ge=1)):
    return call(service.phantom2_daily, astronaut_id, day)



@app.get('/api/science/evidence')
def science_evidence():
    return service.science_evidence()


@app.get('/api/science/hazards')
def science_hazards():
    return service.science_hazards()


@app.post('/api/science/graph')
def science_graph(payload: MissionProfile):
    return call(service.science_graph, payload)


@app.get('/api/science/radiation/presets')
def science_radiation_presets():
    return service.science_radiation_presets()


@app.post('/api/science/radiation')
def science_radiation(payload: RadiationRequest):
    return call(service.science_radiation, payload)



@app.get('/api/engine/runs/{run_id}/symbiosis')
def engine_symbiosis(run_id: str, env_metric: str = 'co2', metric: str = 'fatigue', crew_id: int = Query(1, ge=1)):
    return call(service.engine_symbiosis, run_id, env_metric, metric, crew_id)


@app.post('/api/symbiosis/compare-conditions')
def symbiosis_compare_conditions(payload: ConditionCompare):
    return call(service.symbiosis_compare_conditions, payload)


@app.post('/api/engine/runs/{run_id}/replan')
def engine_replan(run_id: str, payload: ReplanRequest):
    return call(service.engine_replan, run_id, payload)


# Additive 1.1 routes; shared implementation preserves both servers' behavior.
from fastapi import Request
from .bio_api import dispatch as bio_dispatch
from urllib.parse import parse_qs

@app.api_route('/api/biosignals/{tail:path}', methods=['GET','POST','DELETE'])
async def biosignal_api(tail: str, request: Request):
    # Host/Origin/token are enforced by security.ASGISecurity for every /api route.
    raw=await request.body()
    if len(raw)>16384: raise HTTPException(413,'Request body exceeds limit')
    try:
        import json
        from starlette.concurrency import run_in_threadpool
        payload=json.loads(raw) if raw else {}
        if not isinstance(payload,dict): raise ValueError('Expected JSON object')
        return await run_in_threadpool(bio_dispatch,request.method,'/api/biosignals/'+tail,payload,parse_qs(request.url.query))
    except (ValueError,OSError,KeyError) as exc:
        raise HTTPException(400,str(exc)) from exc
