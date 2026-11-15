"""Bridge between the AETHER API (app.service) and the Mission Systems engine (web/backend/mission_systems).

Mission Systems (SYMBIOSIS / CO-ORBIT / MISSION LAB research engine, delivered as AETHER_Mission_Systems_2)
provides: 11 deterministic scenario templates, minute-resolution synthetic time series for a 3-person crew,
a MILP crew scheduler (scipy HiGHS) with an independent validator, time controls (start / pause / seek / tick)
and a research evaluation contract (PHANTOM input without labels → predictions → TP/FP/TN/FN against
hidden injected labels).

This module:
  * exposes the engine through framework-independent functions (FastAPI and the stdlib server both call them);
  * connects the AETHER PHANTOM method (robust personal baseline, median / MAD, app.analytics) to the engine's
    PhantomAdapter contract, so PHANTOM is evaluated on labelled synthetic events it never sees;
  * maps an engine run onto the AETHER cross-module scenario parameters (sleep / workload / CO2 / temperature /
    crew), so MISSION LAB → BODY → PHANTOM → SYMBIOSIS → CO-ORBIT → RECOVERY stay one data flow.

All data are synthetic ("origin": "synthetic"). Nothing here is a clinical or operational result.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from statistics import median
from threading import RLock
from typing import Any, Literal

from pydantic import BaseModel, Field

from . import db
from . import coorbit_phantom, phantom2_engine as pe
from .analytics import FLAG_Z

import importlib.util

# The engine needs numpy + scipy (MILP). They are imported lazily on first use so the backend (and the desktop
# sidecar) starts fast; availability is detected without importing them.
_engine = None
ENGINE_ERROR: str | None = None if all(importlib.util.find_spec(m) for m in ('numpy', 'scipy', 'mission_systems')) \
    else 'numpy, scipy or the mission_systems package is not installed'
SCENARIOS = ['normal', 'sleep_loss', 'fatigue_rise', 'pulse_shift', 'cognitive_decline',
             'workload_rise', 'environment', 'multifactor', 'missing', 'corrupt', 'noise']
ENGINE_API_VERSION, MODEL_VERSION = '1.0', 'educational-1.0'


def _load():
    """Import the engine once; returns a namespace with the engine symbols."""
    global _engine, ENGINE_ERROR
    if _engine is None:
        try:
            from types import SimpleNamespace
            from mission_systems import contracts as c
            from mission_systems.mission_lab import experiments as x, scenarios as sc, simulator as si
            from mission_systems.storage import Store
            _engine = SimpleNamespace(PhantomResult=c.PhantomResult, Scenario=c.Scenario, compare_runs=x.compare_runs,
                                      experiment_report=x.experiment_report, phantom_input=x.phantom_input,
                                      SCENARIOS=sc.SCENARIOS, demo=sc.demo, Simulator=si.Simulator, Store=Store)
        except Exception as exc:  # pragma: no cover - depends on the installed environment
            ENGINE_ERROR = f'{type(exc).__name__}: {exc}'
            raise EngineUnavailable(f'Mission Systems engine unavailable ({ENGINE_ERROR}).') from exc
    return _engine


class EngineUnavailable(Exception):
    pass


TEMPLATE_INFO: dict[str, tuple[str, str]] = {
    'normal': ('Nominal day', 'No injected event; reference run for comparisons.'),
    'sleep_loss': ('Sleep loss', 'Commander loses sleep from minute 360 (ramped).'),
    'fatigue_rise': ('Fatigue rise', 'Gradual fatigue increase for the commander.'),
    'pulse_shift': ('Heart-rate shift', 'Resting heart rate drifts upwards for the commander.'),
    'cognitive_decline': ('Cognitive decline', 'Cognitive test score decreases for the commander.'),
    'workload_rise': ('Workload rise', 'Extra workload accumulates for the commander.'),
    'environment': ('Cabin environment', 'CO₂ / temperature deviation in the habitat for the whole crew.'),
    'multifactor': ('Multifactor (day 67)', 'Combined sleep, fatigue, heart-rate and workload changes.'),
    'missing': ('Missing data', 'Sensor dropouts – tests abstention and coverage.'),
    'corrupt': ('Corrupt data', 'Invalid readings – tests quality handling.'),
    'noise': ('High noise', 'Noisy measurements – tests false alarms.'),
}

PHYS = ('heart_rate', 'sleep_hours', 'sleep_quality', 'activity', 'fatigue', 'cognition', 'workload')
ENV = ('temperature', 'humidity', 'co2', 'light')
# +1: higher is less favourable, -1: lower is less favourable (same convention as app.analytics.LABELS)
DIRECTION = {'heart_rate': 1, 'fatigue': 1, 'workload': 1, 'cognition': -1, 'sleep_hours': -1, 'sleep_quality': -1, 'activity': -1}
SCALE_FLOOR = {'heart_rate': 2.8, 'fatigue': .55, 'workload': .6, 'cognition': 2.5, 'sleep_hours': .35, 'sleep_quality': 3.0, 'activity': 6.0}
MIN_BASELINE = 6


class EngineRunRequest(BaseModel):
    template: str = 'multifactor'
    seed: int = Field(default=67, ge=0, le=2**31 - 1)
    duration_minutes: int = Field(default=1440, ge=120, le=4320)
    sample_minutes: int = Field(default=30, ge=5, le=240)
    sleep_hours: float = Field(default=8, ge=0, le=12)
    extra_rest_hours: float = Field(default=0, ge=0, le=8)
    workload_hours: float = Field(default=0, ge=0, le=12)
    intensity: float = Field(default=1, ge=0, le=3)
    noise: float = Field(default=.2, ge=0, le=3)
    co2_ppm: float = Field(default=800, ge=250, le=10000)
    temperature_c: float = Field(default=22, ge=10, le=35)
    humidity_pct: float = Field(default=45, ge=5, le=95)
    light_lux: float = Field(default=500, ge=0, le=10000)
    phantom: bool = True
    plan_profile: Literal['standard', 'high_workload', 'reduced_availability', 'extended_rest'] = 'standard'


class ConditionCompare(BaseModel):
    a: dict = Field(default_factory=dict)
    b: dict = Field(default_factory=lambda: {'co2': 4000, 'temperature': 26, 'night_light': 50})
    sleep_a: float = Field(default=8, ge=0, le=24)
    sleep_b: float = Field(default=8, ge=0, le=24)
    rest_a: float = Field(default=0, ge=0, le=24)
    rest_b: float = Field(default=0, ge=0, le=24)
    workload: float = Field(default=6, ge=0, le=24)


class ReplanRequest(BaseModel):
    crew_updates: list[dict] = Field(default_factory=list, max_length=12)
    task_updates: list[dict] = Field(default_factory=list, max_length=20)


class CoorbitApply(BaseModel):
    approved_ids: list[str] = Field(default_factory=list, max_length=30)
    approved_by: str = Field(default='', max_length=80)
    note: str = Field(default='', max_length=400)


class CoorbitReject(BaseModel):
    rejected_ids: list[str] = Field(default_factory=list, max_length=30)
    reviewed_by: str = Field(default='', max_length=80)
    note: str = Field(default='', max_length=400)


# Planning profiles (AETHER 0.9): the team's 6-task day is loose enough that every scenario produced the same
# optimal schedule. These profiles change workload, availability or rest so constraints actually bind.
PLAN_PROFILES = {
    'standard': 'Team plan: 6 tasks, all crew 08:00–20:00.',
    'high_workload': 'Standard plan + EVA preparation, medical check, communications, stowage and cleanup (11 tasks).',
    'reduced_availability': 'Standard plan; the Commander is available only 08:00–12:00 and the Researcher from 10:00.',
    'extended_rest': 'Standard plan + mandatory rest 10:00–11:00 for everyone and a 5-hour daily work cap.',
}


def apply_plan_profile(planning: dict, profile: str) -> dict:
    p = json.loads(json.dumps(planning))
    if profile == 'high_workload':
        p['tasks'] += [
            {'id': 'eva_prep', 'title': 'EVA preparation', 'duration_minutes': 120, 'priority': 5, 'people': 2,
             'required_skills': ['maintenance'], 'physical_load': .9, 'cognitive_load': .6},
            {'id': 'medical', 'title': 'Medical check', 'duration_minutes': 45, 'priority': 4, 'required_skills': ['science']},
            {'id': 'comms', 'title': 'Ground communications', 'duration_minutes': 60, 'priority': 3, 'cognitive_load': .7},
            {'id': 'stowage', 'title': 'Cargo stowage', 'duration_minutes': 90, 'priority': 2, 'physical_load': .7},
            {'id': 'cleanup', 'title': 'Habitat cleanup', 'duration_minutes': 60, 'priority': 2, 'physical_load': .6},
        ]
    elif profile == 'reduced_availability':
        for c in p['crew']:
            if c['id'] == 1:
                c['available'] = [{'start': 480, 'end': 720}]
            if c['id'] == 3:
                c['available'] = [{'start': 600, 'end': 1200}]
    elif profile == 'extended_rest':
        for c in p['crew']:
            c['rest'] = c.get('rest', []) + [{'start': 600, 'end': 660}]
            c['max_work_minutes_per_day'] = 300
    return p


class EngineControl(BaseModel):
    action: Literal['start', 'pause', 'resume', 'reset', 'seek', 'speed', 'tick']
    value: float = 0


class EngineCompare(BaseModel):
    a: str = Field(min_length=1)
    b: str = Field(min_length=1)


_lock = RLock()
_sims: dict[str, Any] = {}
_store_obj = None


def _require():
    if ENGINE_ERROR:
        raise EngineUnavailable(f'Mission Systems engine unavailable ({ENGINE_ERROR}). Install numpy and scipy.')
    return _load()


def _store():
    global _store_obj
    E = _require()
    path = Path(db.DB_PATH)
    if _store_obj is None or Path(_store_obj.path) != path:
        _store_obj = E.Store(path)
    return _store_obj


def _sim(run_id: str):
    with _lock:
        if run_id not in _sims:
            try:
                _sims[run_id] = _load().Simulator.restore(_store(), run_id)
            except KeyError as exc:
                raise KeyError(f'Unknown engine run {run_id}') from exc
        return _sims[run_id]


# ------------------------------------------------------------------ public API
def status() -> dict:
    return {'available': ENGINE_ERROR is None, 'error': ENGINE_ERROR, 'engine_api_version': ENGINE_API_VERSION,
            'model_version': MODEL_VERSION, 'origin': 'synthetic',
            'provides': ['11 scenario templates', 'MILP crew scheduler (HiGHS) + validator', 'time controls',
                         'PHANTOM research evaluation (TP/FP/TN/FN against hidden labels)']}


def templates() -> list[dict]:
    _require()
    return [{'id': t, 'title': TEMPLATE_INFO.get(t, (t, ''))[0], 'detail': TEMPLATE_INFO.get(t, ('', ''))[1]} for t in SCENARIOS]


def run(req: EngineRunRequest) -> dict:
    E = _require()
    if req.template not in SCENARIOS:
        raise ValueError(f'Unknown template {req.template}')
    base = E.demo(req.template, seed=req.seed).model_dump(mode='json')
    for e in base['events']:  # keep template events inside the requested horizon
        e['minute'] = min(e['minute'], max(0, req.duration_minutes // 4))
    params = req.model_dump()
    key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:10]
    base.update({
        'id': f'aether-{req.template}-{key}', 'title': f'{TEMPLATE_INFO.get(req.template, (req.template,))[0]} · AETHER run',
        'seed': req.seed, 'duration_minutes': req.duration_minutes, 'sample_minutes': req.sample_minutes,
        'sleep_hours': req.sleep_hours, 'extra_rest_hours': req.extra_rest_hours, 'workload_hours': req.workload_hours,
        'intensity': req.intensity, 'noise': req.noise,
    })
    base['environment'].update({'co2': req.co2_ppm, 'temperature': req.temperature_c, 'humidity': req.humidity_pct, 'light': req.light_lux})
    base['planning'] = apply_plan_profile(base['planning'], req.plan_profile)
    scenario = E.Scenario.model_validate(base)
    with _lock:
        sim = E.Simulator(scenario, _store())
        report = None
        if req.phantom:
            report = sim.submit_phantom(aether_phantom(E.phantom_input(sim.dataset), E.phantom_input(baseline_day(sim))))
        sim.save()
        _sims[scenario.id] = sim
    return summarize(sim, params, report)


def get_run(run_id: str) -> dict:
    sim = _sim(run_id)
    return summarize(sim, None, None)


def list_runs() -> list[dict]:
    store = _store()
    out = []
    for item in store.list('scenario'):
        sid = item.get('id') if isinstance(item, dict) else None
        if sid and str(sid).startswith('aether-'):
            out.append({'id': sid, 'title': item.get('title'), 'seed': item.get('seed'), 'duration_minutes': item.get('duration_minutes')})
    return out


def control(run_id: str, body: EngineControl) -> dict:
    sim = _sim(run_id)
    methods = {'start': sim.start, 'pause': sim.pause, 'resume': sim.resume, 'reset': sim.reset,
               'seek': sim.seek, 'speed': sim.set_speed, 'tick': sim.tick}
    with sim.lock:
        st = methods[body.action](body.value) if body.action in ('seek', 'speed', 'tick') else methods[body.action]()
        sim.save()
    return _state(st)


def evaluation(run_id: str) -> dict:
    sim = _sim(run_id)
    return _load().experiment_report(sim.dataset, sim.phantom_results)


def compare(body: EngineCompare) -> dict:
    a, b = _sim(body.a), _sim(body.b)
    return _load().compare_runs(a, b)


# ------------------------------------------------------------------ AETHER PHANTOM as an engine PhantomAdapter
def aether_phantom(payload: dict, baseline_payload: dict | None = None) -> list:
    """Apply the AETHER PHANTOM method (robust personal-baseline deviation) to engine samples.

    Uses ONLY the label-free PHANTOM input. Baseline per crew member and metric = median of the first
    quarter of that person's valid samples (≥ MIN_BASELINE points); spread = max(1.4826·MAD, floor).
    A sample is flagged when any metric deviates ≥ FLAG_Z in its unfavourable direction; it abstains
    (anomaly = None) when no metric could be scored.
    """
    PhantomResult = _load().PhantomResult
    by_crew: dict[int, list[dict]] = {}
    for s in payload['samples']:
        by_crew.setdefault(s['crew_id'], []).append(s)
    prior: dict[int, list[dict]] = {}
    for s in (baseline_payload or {}).get('samples', []):
        prior.setdefault(s['crew_id'], []).append(s)
    results = []
    for cid, samples in by_crew.items():
        samples.sort(key=lambda s: s['timestamp'])
        # 0.9: personal baseline = the preceding nominal day when given; otherwise the first quarter of the run
        base_samples = prior.get(cid) or samples[:max(MIN_BASELINE, len(samples) // 4)]
        base: dict[str, tuple[float, float]] = {}
        for m in DIRECTION:
            vals = [r['value'] for s in base_samples for r in s['measurements'] if r['metric'] == m and r['quality'] == 'valid' and r['value'] is not None]
            if len(vals) >= MIN_BASELINE:
                med = median(vals)
                mad = median([abs(v - med) for v in vals])
                base[m] = (med, max(1.4826 * mad, SCALE_FLOOR[m]))
        for s in samples:
            zs = []
            for r in s['measurements']:
                b = base.get(r['metric'])
                if b is None or r['quality'] != 'valid' or r['value'] is None:
                    continue
                zs.append((r['metric'], DIRECTION[r['metric']] * (r['value'] - b[0]) / b[1]))
            if not zs:
                results.append(PhantomResult(sample_id=s['sample_id'], anomaly=None, summary='Abstained: no valid scored signal'))
                continue
            flagged = [(m, z) for m, z in zs if z >= FLAG_Z]
            worst = max(z for _, z in zs)
            results.append(PhantomResult(
                sample_id=s['sample_id'], anomaly=bool(flagged), confidence=round(min(1.0, max(0.0, worst / (2 * FLAG_Z))), 3),
                summary=('Flagged: ' + ', '.join(f'{m} z={z:.1f}' for m, z in flagged)) if flagged else 'Within personal baseline'))
    return results


# ------------------------------------------------------------------ response shaping
def _state(st: dict) -> dict:
    return {k: st[k] for k in ('scenario_id', 'status', 'minute', 'duration_minutes', 'speed', 'phantom_status', 'sample_policy')} | {
        'frame_minute': st['frame']['minute']}


def _mean(values: list) -> float | None:
    v = [x for x in values if x is not None]
    return sum(v) / len(v) if v else None


def summarize(sim, params: dict | None, report: dict | None) -> dict:
    ds, sc = sim.dataset, sim.scenario
    crew = sc.planning.crew
    times = [f['minute'] for f in ds['frames']]
    series = {c.id: {m: [] for m in PHYS} for c in crew}
    quality = {c.id: [] for c in crew}
    env = {m: [] for m in ENV}
    for f in ds['frames']:
        seen = {(r['crew_id'], r['metric']): r for r in f['measurements']}
        for c in crew:
            bad = 0
            for m in PHYS:
                r = seen.get((c.id, m))
                ok = r is not None and r['quality'] == 'valid'
                series[c.id][m].append(round(r['value'], 3) if ok and r['value'] is not None else None)
                bad += 0 if ok else 1
            quality[c.id].append(bad)
        es = {r['metric']: r for r in f['environment']}
        for m in ENV:
            r = es.get(m)
            env[m].append(round(r['value'], 2) if r is not None and r['quality'] == 'valid' and r['value'] is not None else None)
    flags: dict[int, list[int]] = {c.id: [] for c in crew}
    if sim.phantom_results:
        sid_to = {t['sample_id']: (t['crew_id'], t['minute']) for t in ds['ground_truth']}
        for r in sim.phantom_results:
            if r.get('anomaly'):
                cid, minute = sid_to[r['sample_id']]
                flags[cid].append(minute)
    sched = sim.schedules['alternatives'][1]
    work = sched['metrics'].get('work_minutes', {})
    mean_work_h = (sum(work.values()) / max(1, len(work))) / 60 if work else 0
    workload_index = round(min(100, max(0, (mean_work_h + sc.workload_hours) / 10 * 100)))
    bridge = {
        'sleep_delta': round(max(-5, min(5, sc.sleep_hours - 8 - (2 if sc.events and sc.events[0].kind in ('sleep_loss', 'multifactor') else 0) * sc.intensity * .5)), 1),
        'workload': int(max(0, min(100, workload_index + (25 if sc.events and sc.events[0].kind in ('workload_rise', 'multifactor') else 0)))),
        'co2_ppm': int(max(350, min(5000, round(_mean(env['co2']) or sc.environment.co2)))),
        'temperature_c': round(max(10, min(35, _mean(env['temperature']) or sc.environment.temperature)), 1),
        'crew_available': 4,
        'note': 'Derived from the engine run: planned sleep (minus injected sleep-loss), scheduled work + extra workload, '
                'mean modelled cabin CO₂ and temperature. The 3-person engine crew maps onto the 4-person AETHER crew.',
    }
    evaluation = report['evaluation'] if report else _load().experiment_report(ds, sim.phantom_results)
    E = _load()
    payload = E.phantom_input(ds)
    prior = baseline_day(sim)
    p2res = pe.detect(payload, baseline_payload=E.phantom_input(prior))
    p2flags = {str(c.id): [] for c in crew}
    sid_to = {t['sample_id']: (t['crew_id'], t['minute']) for t in ds['ground_truth']}
    for sid, f in p2res['flags']['phantom2'].items():
        if f:
            cid, minute = sid_to[sid]
            p2flags[str(cid)].append(minute)
    phantom2 = {
        'physiology': pe.compare(ds, E.phantom_input, baseline_dataset=prior),
        'exposure_aware': pe.compare(ds, E.phantom_input, with_env=True, baseline_dataset=prior),
        'flags': {k: sorted(v) for k, v in p2flags.items()},
        'method': 'PHANTOM 2.0 (AETHER 1.0, noise-adaptive): clean baseline (noise index ν < 0.6) → robust Mahalanobis OR '
                  'AR(1)-prewhitened CUSUM; noisy baseline → EWMA with a calibrated limit. `phantom2_v09` keeps the 0.9 rule. '
                  'Exposure-aware variant adds cabin CO₂ / temperature / humidity channels.',
        'regimes': {str(k): v for k, v in p2res['regimes'].items()},
        'states': {k: sum(1 for x in p2res['states'].values() if x == k) for k in ('flag', 'no_flag', 'insufficient_data')},
        'note': 'Detector comparison on this run uses its hidden synthetic labels. Personal baseline = a preceding nominal '
                'day simulated for the same crew (default sleep, workload and cabin set-points, no injected events).',
    }
    return {
        'id': sc.id, 'title': sc.title, 'template': next((e.kind for e in sc.events), 'normal'), 'seed': sc.seed,
        'mission_day': sc.mission_day, 'duration_minutes': sc.duration_minutes, 'sample_minutes': sc.sample_minutes,
        'params': params, 'origin': 'synthetic', 'model_version': ds['model_version'],
        'events': [e.model_dump(mode='json') for e in sc.events],
        'crew': [{'id': c.id, 'name': c.name, 'role': c.role, 'skills': sorted(c.skills)} for c in crew],
        'times': times, 'series': {str(k): v for k, v in series.items()}, 'quality_gaps': {str(k): v for k, v in quality.items()},
        'environment': env, 'phantom_flags': {str(k): v for k, v in flags.items()},
        'schedules': {'strategies': [coorbit_phantom.strategy_view(a) | {'criteria': a.get('criteria')}
                                     for a in sim.schedules['alternatives']],
                      'has_feasible_solution': sim.schedules.get('has_feasible_solution'),
                      'explanation': sim.schedules.get('explanation'), 'identical': sim.schedules.get('identical'),
                      'tasks': [{'id': t.id, 'title': t.title, 'priority': t.priority, 'duration_minutes': t.duration_minutes,
                                 'people': t.people, 'skills': sorted(t.required_skills), 'dependencies': t.dependencies,
                                 'equipment': t.equipment} for t in sc.planning.tasks]},
        'evaluation': evaluation, 'proposed_schedules': (report or {}).get('proposed_schedules'),
        'state': _state(sim.state()), 'bridge': bridge, 'limitations': ds['limitations'],
        'phantom2': phantom2, 'plan_profile': (params or {}).get('plan_profile') or _profile_of(sc),
        'plan_profile_detail': PLAN_PROFILES.get((params or {}).get('plan_profile') or _profile_of(sc), ''),
    }


def _profile_of(sc) -> str:
    ids = {t.id for t in sc.planning.tasks}
    if 'eva_prep' in ids:
        return 'high_workload'
    if any(any(w.start == 600 and w.end == 660 for w in c.rest) for c in sc.planning.crew):
        return 'extended_rest'
    if any(c.id == 1 and c.available and c.available[-1].end == 720 for c in sc.planning.crew):
        return 'reduced_availability'
    return 'standard'


# ------------------------------------------------------------------ PHANTOM → CO-ORBIT (human-approved constraints)
def coorbit_recommendations(run_id: str) -> dict:
    sim = _sim(run_id)
    recs = coorbit_phantom.recommendations(sim, _load().phantom_input, baseline_day(sim))
    # 1.0 (B4.3): SYMBIOSIS tells PHANTOM / CO-ORBIT about the cabin context; the statement is attached, never a diagnosis
    try:
        ctx = {c['crew_id']: c for c in environment_analysis(run_id)['crew_context']}
    except Exception:  # pragma: no cover - context is advisory; recommendations must not fail because of it
        ctx = {}
    for r in recs:
        c = ctx.get(r['crew_id'])
        r['environment_context'] = None if c is None else {k: c[k] for k in ('environment_stressor', 'stressor_kinds', 'statement', 'evidence')}
    return {'run_id': run_id, 'recommendations': recs, 'rules': coorbit_phantom.RULES and {k: v['summary'] for k, v in coorbit_phantom.RULES.items()},
            'environment_context': list(ctx.values()),
            'policy': 'Recommendations are proposals. They change the plan only after a named person approves them; '
                      'no rule removes a crew member from the schedule.'}


def coorbit_apply(run_id: str, body: CoorbitApply) -> dict:
    sim = _sim(run_id)
    from mission_systems.co_orbit.optimization import replan
    recs = coorbit_phantom.recommendations(sim, _load().phantom_input, baseline_day(sim))
    with sim.lock:
        return coorbit_phantom.apply(sim, body.approved_ids, body.approved_by, recs, replan, store=_store(), note=body.note)


def coorbit_reject(run_id: str, body: CoorbitReject) -> dict:
    sim = _sim(run_id)
    recs = coorbit_phantom.recommendations(sim, _load().phantom_input, baseline_day(sim))
    return coorbit_phantom.reject(sim, body.rejected_ids, body.reviewed_by, recs, store=_store(), note=body.note)


def environment_analysis(run_id: str, cabin_pressure_mmhg: float = 760.0) -> dict:
    """1.0 (B4): cabin-event detection (SYMBIOSIS) + per-crew environmental context for PHANTOM.

    Baseline = the preceding nominal day (as for PHANTOM 2.0). The cabin detector reads cabin channels only; PHANTOM
    reads physiology only; their co-occurrence is reported as a hypothesis, never as a cause or a diagnosis."""
    from . import environment_detector as ed
    sim = _sim(run_id)
    E = _load()
    prior = baseline_day(sim)
    bm, bs = ed.series_from_frames([f for f in prior['frames'] if f['minute'] < 1440])
    rm, rs = ed.series_from_frames(sim.dataset['frames'])
    minutes = [m - 1440 for m in bm] + rm
    series = {ch: bs[ch] + rs[ch] for ch in ed.CHANNELS}
    res = ed.detect(minutes, series, baseline_minutes=1440, cabin_pressure_mmhg=cabin_pressure_mmhg)
    frames = [f for f in res['frames'] if f['minute'] >= 0]
    events = [e for e in res['events'] if e['end_minute'] > 0]
    # PHANTOM 2.0 on physiology only, same baseline as the run summary
    p2res = pe.detect(E.phantom_input(sim.dataset), baseline_payload=E.phantom_input(prior))
    sid_to = {t['sample_id']: (t['crew_id'], t['minute']) for t in sim.dataset['ground_truth']}
    flags: dict[int, list[int]] = {c.id: [] for c in sim.plan.crew}
    states: dict[int, dict] = {c.id: {'scored': 0, 'insufficient': 0} for c in sim.plan.crew}
    for sid, f in p2res['flags']['phantom2'].items():
        cid, minute = sid_to[sid]
        states[cid]['scored' if f is not None else 'insufficient'] += 1
        if f:
            flags[cid].append(minute)
    context = ed.crew_context({'frames': frames}, flags, states)
    names = {c.id: c.name for c in sim.plan.crew}
    for c in context:
        c['crew_name'] = names.get(c['crew_id'], str(c['crew_id']))
    return {'run_id': run_id, 'zone_id': sim.scenario.environment.zone_id, 'origin': 'synthetic',
            'frames': [{k: f[k] for k in ('minute', 'state', 'environment_event', 'sensor_fault', 'alarms', 'faults')} |
                       {'ppco2_1h_mmhg': f['statistics'].get('ppco2_1h_mmhg')} for f in frames],
            'events': events, 'crew_context': context, 'co2_limit': res['co2_limit'], 'applicability': res['applicability'],
            'baseline': res['baseline'], 'parameters': res['parameters'], 'scope': res['scope'],
            'evaluation_against_hidden_labels': ed.evaluate(frames, sim.dataset['frames']),
            'note': 'Synthetic run. Cabin events come from cabin channels only; physiological statements come from PHANTOM 2.0; '
                    'their co-occurrence is a hypothesis. No diagnosis is produced.'}


_baselines: dict[str, dict] = {}


def baseline_day(sim) -> dict:
    """Preceding nominal day for the same crew: default sleep / workload / cabin set-points, no injected events,
    a different noise realisation. Deterministic, so it is regenerated instead of stored."""
    key = sim.scenario.id
    if key not in _baselines:
        E = _load()
        from mission_systems.mission_lab.generator import generate
        d = sim.scenario.model_dump(mode='json')
        d.update({'id': key + ':baseline', 'events': [], 'duration_minutes': 1440, 'sleep_hours': 8, 'extra_rest_hours': 0,
                  'workload_hours': 0, 'intensity': 1, 'seed': (sim.scenario.seed + 1_000_003) % (2 ** 31)})
        d['environment'] = {**d['environment'], 'co2': 800, 'temperature': 22, 'humidity': 45, 'light': 500}
        nominal = E.Scenario.model_validate(d)
        _baselines[key] = generate(nominal, sim.schedules['alternatives'][1])
    return _baselines[key]


# ------------------------------------------------------------------ Mission Systems analytics (SYMBIOSIS / CO-ORBIT)
LAGS = [0, 30, 60, 120, 240]


def symbiosis_analytics(run_id: str, env_metric: str = 'co2', metric: str = 'fatigue', crew_id: int = 1) -> dict:
    """relationship() at several lags + compare_periods() before/after the first event (or halves) for one run."""
    from mission_systems.symbiosis.analysis import compare_periods, relationship
    from datetime import datetime, timedelta
    sim = _sim(run_id)
    ds = sim.dataset
    env = [r for f in ds['frames'] for r in f['environment']]
    phys = [r for f in ds['frames'] for r in f['measurements']]
    if env_metric not in ENV or metric not in PHYS:
        raise ValueError('Unknown metric')
    rel = [{**relationship(env, phys, env_metric=env_metric, metric=metric, crew_id=crew_id, zone_id=sim.scenario.environment.zone_id, lag_minutes=l)}
           for l in LAGS]
    start = datetime.fromisoformat(ds['frames'][0]['timestamp'])
    split = sim.scenario.events[0].minute if sim.scenario.events else sim.scenario.duration_minutes // 2
    split = max(sim.scenario.sample_minutes, min(split, sim.scenario.duration_minutes - sim.scenario.sample_minutes))
    end = start + timedelta(minutes=sim.scenario.duration_minutes + 1)
    mid = start + timedelta(minutes=split)
    readings = [r for r in env + phys if (r['metric'] == env_metric) or (r['metric'] == metric and r.get('crew_id') == crew_id)]
    per = compare_periods(readings, start, mid, mid, end)
    pick = lambda rows, m: next((x for x in rows if x['metric'] == m), None)
    periods = {m: {'a': pick(per['a'], m), 'b': pick(per['b'], m)} for m in (env_metric, metric)}
    return {'run_id': run_id, 'env_metric': env_metric, 'metric': metric, 'crew_id': crew_id, 'relationship': rel,
            'periods': periods, 'split_minute': split,
            'split_basis': 'first injected event' if sim.scenario.events else 'half of the run',
            'causal': False,
            'note': 'Pearson correlation of synthetic series at fixed lags. Autocorrelation and confounding are not controlled – '
                    'this is not evidence of causation. In the engine the coupling exists by construction (illustrative coefficients).'}


def compare_conditions(body: ConditionCompare) -> dict:
    from mission_systems.contracts import Environment
    from mission_systems.symbiosis.scenarios import compare_conditions as cc
    a = Environment.model_validate({**body.a})
    b = Environment.model_validate({**body.b})
    return cc(a, b, sleep_a=body.sleep_a, sleep_b=body.sleep_b, rest_a=body.rest_a, rest_b=body.rest_b, workload=body.workload) | {
        'a_input': a.model_dump(), 'b_input': b.model_dump()}


def replan_run(run_id: str, body: ReplanRequest) -> dict:
    """CO-ORBIT replan(): availability / rest / urgent-task changes → re-optimised, validated schedule."""
    from mission_systems.co_orbit.optimization import compare as cmp, replan
    sim = _sim(run_id)
    for u in body.crew_updates:
        if 'id' not in u:
            raise ValueError('crew update needs id')
        if 'available' in u and not u['available']:
            raise ValueError('Removing all availability is not allowed here – use rest windows or work caps.')
    updates = []
    for u in body.crew_updates:
        u = dict(u)
        if 'add_rest' in u:   # convenience: append rest windows instead of replacing the existing ones
            cur = next((c for c in sim.plan.crew if c.id == u['id']), None)
            if cur is None:
                raise ValueError('Unknown crew member')
            u['rest'] = [w.model_dump() for w in cur.rest] + list(u.pop('add_rest'))
        updates.append(u)
    from mission_systems.co_orbit.optimization import dropped_tasks, preferred
    from mission_systems.co_orbit.scheduler import is_valid
    new_plan, alts = replan(sim.plan, crew_updates=updates, task_updates=body.task_updates)
    before, after = sim.schedules['alternatives'][1], preferred(alts)
    valid = is_valid(after)
    dropped = dropped_tasks(before, after, sim.plan) if valid else []
    reason = after.get('reason', '') if valid else 'No feasible schedule after the change: ' + (after.get('reason') or after.get('status', '')).removeprefix('No feasible schedule: ')
    if dropped:
        reason += f" {len(dropped)} task(s) scheduled today would no longer fit: " + ', '.join(d['title'] for d in dropped) + '.'
    # The run's own plan and schedule are never modified by replan(): the result is a proposal.
    return {'run_id': run_id, 'before': before,
            'after': coorbit_phantom.strategy_view(after if valid else before), 'proposal': coorbit_phantom.strategy_view(after),
            'comparison': cmp(new_plan, before['assignments'], after['assignments'] if valid else before['assignments']),
            'valid': valid, 'decision_status': 'proposal_ready' if valid else 'rejected_no_feasible_schedule',
            'reason': reason.strip(), 'applied': False, 'previous_schedule_preserved': True,
            'dropped_tasks': dropped, 'requires_review': (not valid) or bool(dropped),
            'next_actions': [] if valid else coorbit_phantom.NEXT_ACTIONS_FAILED[1:],
            'tasks': [{'id': t.id, 'title': t.title, 'priority': t.priority, 'required': t.required} for t in new_plan.tasks]}
