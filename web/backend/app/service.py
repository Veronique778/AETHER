"""Framework-independent request handlers.

Both ``app.main`` (FastAPI) and ``app.devserver`` (stdlib fallback) call these,
so the HTTP layer stays thin and the logic is testable without a web server.
"""
from . import db
import math
import time

from . import mission_engine
from .analytics import analyze, correlations, history_scores, spearman
from .schemas import Experiment, Measurement, PlanRequest, ProjectionRequest, RecoverySession, SimulationRequest
from .simulation import (CREW, SCENARIOS, TASKS, ZONE_IDS, calendar, environment, project,
                         run_scenario, schedules, ship_state, zone_history)

API_VERSION = '1.0.0'
# Version of the response contracts in docs/API_CONTRACTS.md (additive changes only since 0.9).
API_CONTRACT_VERSION = '1.0'


class NotFound(Exception):
    pass


class BadRequest(Exception):
    pass


class Unavailable(Exception):
    """Optional component (e.g. the Mission Systems engine without numpy/scipy) is not installed."""


def require_astronaut(astronaut_id: str):
    if astronaut_id not in {a['id'] for a in db.astronauts()}:
        raise NotFound('Unknown astronaut')


def _latest_rows(day: int) -> dict[str, dict]:
    out = {}
    for a in db.astronauts():
        rows = db.timeline(a['id'], day)
        if rows:
            out[a['id']] = rows[-1]
    return out


def health():
    return {'status': 'ok', 'project': 'AETHER', 'version': API_VERSION, 'data': 'synthetic mission data; optional local research and BLE recordings are stored separately', 'release_version': '1.5.0',
            'capabilities': ['ship', 'symbiosis-history', 'phantom-history', 'phantom-correlations',
                             'co-orbit-calendar', 'co-orbit-plan', 'mission-lab-project', 'recovery-details',
                             'symbiosis-crew-association', 'recovery-biofeedback', 'mission-lab-experiments',
                             'human-systems-quality', 'nasa-research', 'nasa-verified-public-csv', 'nasa-provenance-history']
            + (['mission-engine', 'phantom2', 'coorbit-phantom', 'coorbit-reject', 'environment-detector'] if mission_engine.ENGINE_ERROR is None else [])
            + ['science-core', 'biosignals-mmash', 'biosignals-ble', 'biosignals-partial-analysis',
               'nasa-classification', 'nasa-local-csv', 'nasa-reference-context', 'connectors', 'demo-recording', 'session-token'],
            'api_contract_version': API_CONTRACT_VERSION, 'personal_api_contract_version': '1.5',
            'mission_engine': mission_engine.status()}


def get_astronauts():
    return db.astronauts()


def get_timeline(astronaut_id: str, day: int):
    require_astronaut(astronaut_id)
    return db.timeline(astronaut_id, day)


def post_measurement(astronaut_id: str, m: Measurement):
    require_astronaut(astronaut_id)
    values = m.model_dump(exclude={'day'}, exclude_unset=True)
    if all(v is None for v in values.values()):
        raise BadRequest('At least one metric is required')
    db.add_measurement(astronaut_id, m.day, values, source='manual')
    return {'saved': True, 'astronaut_id': astronaut_id, 'day': m.day}


def phantom(astronaut_id: str, day: int):
    require_astronaut(astronaut_id)
    return analyze(db.timeline(astronaut_id, day), day)


def phantom_history(astronaut_id: str, day: int, start: int):
    require_astronaut(astronaut_id)
    return history_scores(db.timeline(astronaut_id, day), start, day)


def phantom_correlations(astronaut_id: str, day: int, window: int):
    require_astronaut(astronaut_id)
    return correlations(db.timeline(astronaut_id, day), day, window)


def symbiosis(day: int):
    return environment(day)


def symbiosis_history(zone: str, start: int, end: int):
    if zone not in ZONE_IDS:
        raise NotFound('Unknown compartment')
    if end < start:
        raise BadRequest('end must be >= start')
    return {'zone': zone, 'points': zone_history(start, end, zone), 'source': 'estimated'}


def ship(day: int, hour: float):
    latest = _latest_rows(day)
    status = {aid: analyze(db.timeline(aid, day), day)['status'] for aid in latest}
    return ship_state(day, hour, latest, status)


def co_orbit(reduce_a01: bool):
    return {'crew': CREW, 'schedule': schedules(reduce_a01, optimise=False)}


def co_orbit_calendar(day: int):
    return calendar(day, _latest_rows(day))


def co_orbit_plan(req: PlanRequest):
    tasks = [t.model_dump() for t in req.tasks] if req.tasks is not None else TASKS
    ids = [t['id'] for t in tasks]
    if len(ids) != len(set(ids)):
        raise BadRequest('Task ids must be unique')
    return schedules(tasks=tasks, capacity=req.capacity, unavailable=req.unavailable, optimise=req.optimise)


def scenarios():
    return SCENARIOS


def simulate(req: SimulationRequest):
    require_astronaut(req.astronaut_id)
    try:
        return run_scenario(db.timeline(req.astronaut_id, req.day), **req.model_dump(exclude={'astronaut_id'}))
    except ValueError as exc:
        raise NotFound(str(exc)) from exc


def projection(req: ProjectionRequest):
    require_astronaut(req.astronaut_id)
    try:
        return project(db.timeline(req.astronaut_id, req.start_day), **req.model_dump(exclude={'astronaut_id'}))
    except ValueError as exc:
        raise NotFound(str(exc)) from exc


def save_recovery(req: RecoverySession):
    require_astronaut(req.astronaut_id)
    return {'saved': True, 'id': db.add_recovery(req.model_dump())}


def get_recovery(astronaut_id: str):
    require_astronaut(astronaut_id)
    return db.recovery_history(astronaut_id)


# ---------------------------------------------------------------- v0.8 integration: former "pending backend" contracts
def crew_association(day: int, zone: str):
    """Spearman ρ between daily compartment CO₂ and each person's fatigue, days 41..day (same as the demo adapter)."""
    if zone not in ZONE_IDS:
        raise NotFound('Unknown compartment')
    co2 = {p['day']: p['co2_ppm'] for p in zone_history(41, day, zone)}
    rows = []
    for a in db.astronauts():
        pairs = [(co2[r['day']], float(r['fatigue_1_10'])) for r in db.timeline(a['id'], day)
                 if r['day'] >= 41 and r['day'] in co2 and r['fatigue_1_10'] is not None]
        rho = spearman([p[0] for p in pairs], [p[1] for p in pairs]) if len(pairs) >= 8 else None
        rows.append({'astronaut_id': a['id'], 'rho': None if rho is None else round(rho, 3), 'n': len(pairs)})
    return {'day': day, 'zone': zone, 'environment_metric': 'co2_ppm', 'outcome_metric': 'fatigue_1_10',
            'method': 'Spearman rank correlation, days 41+', 'rows': rows,
            'note': 'In the synthetic dataset both CO₂ and A01 strain rise after day 56 by construction; '
                    'a high ρ reflects the generator, not causation.', 'source': 'simulated'}


def biofeedback(astronaut_id: str):
    """Simulated biofeedback frame (no sensor is connected). Heart rate is centred on the person's latest
    stored resting value; breathing and coherence follow slow deterministic waves. Labelled 'simulated'."""
    require_astronaut(astronaut_id)
    rows = db.timeline(astronaut_id, 9999)
    hr0 = next((r['heart_rate_bpm'] for r in reversed(rows) if r['heart_rate_bpm'] is not None), 66.0)
    t = time.time()
    return {'astronaut_id': astronaut_id, 't': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t)),
            'breathing_rate_bpm': round(6 + math.sin(t / 20), 1), 'heart_rate_bpm': round(hr0 + 4 * math.sin(t / 5)),
            'coherence_0_1': round(0.55 + 0.25 * math.sin(t / 15), 2), 'quality': 'good', 'source': 'simulated'}


def list_experiments():
    return db.list_experiments()


def save_experiment(exp: Experiment):
    return {'saved': True, 'id': db.save_experiment(exp.model_dump())}


def delete_experiment(exp_id: str):
    if not db.delete_experiment(exp_id):
        raise NotFound('Unknown experiment')
    return {'deleted': True, 'id': exp_id}


# ---------------------------------------------------------------- Mission Systems engine (see app.mission_engine)
def _engine(fn, *args):
    try:
        return fn(*args)
    except mission_engine.EngineUnavailable as exc:
        raise Unavailable(str(exc)) from exc
    except KeyError as exc:
        raise NotFound(str(exc).strip("'")) from exc
    except ValueError as exc:
        raise BadRequest(str(exc)) from exc


def engine_status():
    return mission_engine.status()


def engine_templates():
    return _engine(mission_engine.templates)


def engine_runs():
    return _engine(mission_engine.list_runs)


def engine_run(req):
    return _engine(mission_engine.run, req)


def engine_get(run_id: str):
    return _engine(mission_engine.get_run, run_id)


def engine_control(run_id: str, body):
    return _engine(mission_engine.control, run_id, body)


def engine_evaluation(run_id: str):
    return _engine(mission_engine.evaluation, run_id)


def engine_compare(body):
    return _engine(mission_engine.compare, body)


# ---------------------------------------------------------------- 0.9: PHANTOM → CO-ORBIT (human-approved)
def engine_plan_profiles():
    return [{'id': k, 'detail': v} for k, v in mission_engine.PLAN_PROFILES.items()]


def engine_coorbit(run_id: str):
    return _engine(mission_engine.coorbit_recommendations, run_id)


def engine_coorbit_apply(run_id: str, body):
    return _engine(mission_engine.coorbit_apply, run_id, body)


def engine_coorbit_reject(run_id: str, body):
    return _engine(mission_engine.coorbit_reject, run_id, body)


def engine_environment(run_id: str, cabin_pressure_mmhg: float = 760.0):
    return _engine(mission_engine.environment_analysis, run_id, cabin_pressure_mmhg)


def phantom2_daily(astronaut_id: str, day: int):
    require_astronaut(astronaut_id)
    try:
        from . import phantom2_daily as pd
    except ImportError as exc:
        raise Unavailable(f'PHANTOM 2.0 needs numpy and scipy ({exc}).') from exc
    return pd.analyze(astronaut_id, day)


# ---------------------------------------------------------------- 0.9: scientific core
def science_evidence():
    from .science import evidence
    return {'verified_on': evidence.VERIFIED_ON, 'entries': [{**e, 'verified_on': evidence.VERIFIED_ON} for e in evidence.EVIDENCE],
            'unreachable': evidence.UNREACHABLE}


def science_hazards():
    from .science import hazards
    return {'hazards': hazards.HAZARDS, 'hrp_map': hazards.hrp_map(), 'destinations': {k: v['label'] for k, v in hazards.DESTINATIONS.items()}}


def science_graph(profile):
    from .science import hazards
    return hazards.graph(profile)


def science_radiation(body):
    from .science import radiation
    try:
        if body.preset:
            pr = radiation.PRESETS.get(body.preset)
            if pr is None:
                raise ValueError('Unknown preset')
            return {'title': pr['title'], **radiation.simulate(pr['segments'], pr['spe'], shielding_factor=body.shielding_factor,
                                                               prior_career_msv=body.prior_career_msv, runs=body.runs, seed=body.seed)}
        return {'title': body.title or 'Custom mission', **radiation.simulate([s.model_dump() for s in body.segments], [e.model_dump() for e in body.spe],
                                                                              shielding_factor=body.shielding_factor, prior_career_msv=body.prior_career_msv, runs=body.runs, seed=body.seed)}
    except ValueError as exc:
        raise BadRequest(str(exc)) from exc


def science_radiation_presets():
    from .science import radiation
    return {'presets': {k: v['title'] for k, v in radiation.PRESETS.items()},
            'environments': {k: {'label': v['label'], 'rate_msv_per_day': v['rate'], 'source': v['source'], 'uncertainty': v['spread']} for k, v in radiation.ENVIRONMENTS.items()},
            'limits': {'career_msv': radiation.CAREER_LIMIT_MSV, 'spe_msv': radiation.SPE_LIMIT_MSV}}



def engine_symbiosis(run_id: str, env_metric: str, metric: str, crew_id: int):
    return _engine(mission_engine.symbiosis_analytics, run_id, env_metric, metric, crew_id)


def symbiosis_compare_conditions(body):
    try:
        return mission_engine.compare_conditions(body)
    except ValueError as exc:
        raise BadRequest(str(exc)) from exc


def engine_replan(run_id: str, body):
    return _engine(mission_engine.replan_run, run_id, body)
