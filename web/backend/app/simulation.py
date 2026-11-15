"""Mission-systems mathematical prototypes with explicit assumptions.

Everything here is a transparent, deterministic *illustrative* model.
Coefficients are UI demonstration assumptions, not validated physiology.
The TypeScript demo adapter (web/frontend/src/api/demo) ports these functions
1:1; tests/test_parity.py checks the two implementations agree.
"""
import math
from typing import Any

from .analytics import BASELINE_END, analyze, compute_baselines, score_values
from .db import METRICS

SCENARIOS = [
    {'id': 'baseline', 'title': 'Nominal mission', 'detail': 'Steady routine and healthy baseline', 'sleep_delta': 0, 'workload': 50, 'co2_ppm': 850, 'temperature_c': 22, 'crew_available': 4},
    {'id': 'day67', 'title': 'Day 67 · accumulated strain', 'detail': 'Shorter sleep and heavier workload', 'sleep_delta': -1.8, 'workload': 85, 'co2_ppm': 1450, 'temperature_c': 25, 'crew_available': 4},
    {'id': 'recovery', 'title': 'Recovery intervention', 'detail': 'Additional rest and redistributed tasks', 'sleep_delta': 0.8, 'workload': 35, 'co2_ppm': 850, 'temperature_c': 21, 'crew_available': 4},
    {'id': 'crew3', 'title': 'One crew member unavailable', 'detail': 'Same task list shared by three people', 'sleep_delta': -0.5, 'workload': 60, 'co2_ppm': 1000, 'temperature_c': 23, 'crew_available': 3},
]
CREW = [
    {'id': 'A01', 'name': 'Alex Vega', 'skills': ['command', 'science'], 'capacity': 6, 'home_zone': 'command'},
    {'id': 'A02', 'name': 'Mira Chen', 'skills': ['engineering', 'science'], 'capacity': 7, 'home_zone': 'systems'},
    {'id': 'A03', 'name': 'Sam Okafor', 'skills': ['medical', 'science'], 'capacity': 6, 'home_zone': 'medical'},
    {'id': 'A04', 'name': 'Noor Patel', 'skills': ['engineering', 'command'], 'capacity': 7, 'home_zone': 'command'},
]
TASKS = [
    {'id': 'T1', 'title': 'Life-support check', 'skill': 'engineering', 'hours': 2, 'priority': 1, 'zone': 'systems'},
    {'id': 'T2', 'title': 'Health assessment', 'skill': 'medical', 'hours': 2, 'priority': 1, 'zone': 'medical'},
    {'id': 'T3', 'title': 'Navigation review', 'skill': 'command', 'hours': 2, 'priority': 2, 'zone': 'command'},
    {'id': 'T4', 'title': 'Science experiment', 'skill': 'science', 'hours': 3, 'priority': 2, 'zone': 'habitat'},
    {'id': 'T5', 'title': 'Equipment inspection', 'skill': 'engineering', 'hours': 2, 'priority': 3, 'zone': 'systems'},
]

# ---------------------------------------------------------------- spacecraft
ZONES = [
    {'id': 'command', 'name': 'Command deck', 'module': 'co-orbit', 'volume_m3': 38,
     'description': 'Flight control, navigation and communications.', 'offset': {'co2': -40, 'temp': -0.3, 'hum': -3}},
    {'id': 'habitat', 'name': 'Habitat ring', 'module': 'body', 'volume_m3': 96,
     'description': 'Crew quarters, galley and shared living space.', 'offset': {'co2': 60, 'temp': 0.4, 'hum': 4}},
    {'id': 'medical', 'name': 'Medical bay', 'module': 'phantom', 'volume_m3': 24,
     'description': 'Health checks, sensors and physiological measurements.', 'offset': {'co2': -20, 'temp': -0.2, 'hum': 0}},
    {'id': 'exercise', 'name': 'Exercise & recovery', 'module': 'recovery', 'volume_m3': 30,
     'description': 'Countermeasure exercise devices and recovery activities.', 'offset': {'co2': 90, 'temp': 0.8, 'hum': 6}},
    {'id': 'systems', 'name': 'Life support (ECLSS)', 'module': 'symbiosis', 'volume_m3': 42,
     'description': 'Air revitalisation, water recovery and thermal control.', 'offset': {'co2': 20, 'temp': 0.6, 'hum': -2}},
]
ZONE_IDS = [z['id'] for z in ZONES]
# Demo reference bands. Configurable research values – NOT flight rules or exposure limits.
REFERENCE = {
    'co2_ppm': {'attention': 1200, 'high': 2500, 'unit': 'ppm'},
    'temperature_c': {'low': 19, 'high': 26, 'unit': '°C'},
    'humidity_pct': {'low': 30, 'high': 65, 'unit': '%'},
    'light_lux': {'unit': 'lux'},
    'note': 'AETHER demo reference bands for visual grouping only; not spacecraft flight rules or exposure limits.',
}


def environment(day: int = 67) -> dict:
    strain = max(0, day - 56)
    return {
        'day': day, 'co2_ppm': round(850 + strain * 46),
        'temperature_c': round(22 + strain * .2, 1),
        'humidity_pct': 45, 'light_lux': 380 if day % 2 else 280,
        'source': 'simulated',
        'note': 'Illustrative simulation; not a life-support recommendation.'
    }


def _env_status(co2: float, temp: float, hum: float) -> str:
    if co2 >= REFERENCE['co2_ppm']['high']:
        return 'high'
    if (co2 >= REFERENCE['co2_ppm']['attention'] or not REFERENCE['temperature_c']['low'] <= temp <= REFERENCE['temperature_c']['high']
            or not REFERENCE['humidity_pct']['low'] <= hum <= REFERENCE['humidity_pct']['high']):
        return 'attention'
    return 'nominal'


def zone_environment(day: int, zone_id: str, hour: float, occupants: int) -> dict:
    """Per-compartment conditions derived from the cabin average plus occupancy and a daily cycle."""
    base = environment(day)
    z = next(x for x in ZONES if x['id'] == zone_id)
    cyc = math.sin((hour - 9) / 24 * 2 * math.pi)
    co2 = base['co2_ppm'] + z['offset']['co2'] + 55 * occupants + 25 * cyc
    temp = base['temperature_c'] + z['offset']['temp'] + 0.15 * occupants + 0.3 * cyc
    hum = base['humidity_pct'] + z['offset']['hum'] + 1.5 * occupants
    if zone_id == 'habitat':
        light = 20 if hour < 7 or hour >= 23 else (150 if hour >= 20 else 420)
    elif zone_id == 'exercise':
        light = 500 if 7 <= hour < 22 else 30
    else:
        light = base['light_lux'] if 7 <= hour < 22 else 60
    return {'zone': zone_id, 'day': day, 'hour': round(hour, 2), 'co2_ppm': round(co2),
            'temperature_c': round(temp, 1), 'humidity_pct': round(hum, 1), 'light_lux': light,
            'occupants': occupants, 'status': _env_status(co2, temp, hum), 'source': 'estimated'}


# ---------------------------------------------------------------- crew calendar
def _sleep_hours(history_by_person: dict[str, dict], person: str) -> float:
    row = history_by_person.get(person) or {}
    return float(row.get('sleep_hours') or 7.5)


def calendar(day: int, latest: dict[str, dict]) -> dict:
    """Synthetic 24 h plan per astronaut. Sleep length follows that day's sleep record."""
    shifts = {'A01': 0.0, 'A02': 1.0, 'A03': -0.5, 'A04': 0.5}
    out = {}
    for c in CREW:
        s = shifts[c['id']]
        wake = (23 + s + _sleep_hours(latest, c['id'])) % 24
        blocks = [
            {'start': 0.0, 'end': wake, 'kind': 'sleep', 'title': 'Sleep period', 'zone': 'habitat'},
            {'start': wake, 'end': wake + 1, 'kind': 'personal', 'title': 'Hygiene & breakfast', 'zone': 'habitat'},
            {'start': wake + 1, 'end': 12 + s, 'kind': 'work', 'title': 'Primary duties', 'zone': c['home_zone']},
            {'start': 12 + s, 'end': 13 + s, 'kind': 'meal', 'title': 'Crew meal', 'zone': 'habitat'},
            {'start': 13 + s, 'end': 14.5 + s, 'kind': 'exercise', 'title': 'Exercise countermeasures', 'zone': 'exercise'},
            {'start': 14.5 + s, 'end': 18.5 + s, 'kind': 'work', 'title': 'Assigned tasks', 'zone': c['home_zone']},
            {'start': 18.5 + s, 'end': 19.5 + s, 'kind': 'health', 'title': 'Daily check-in', 'zone': 'medical'},
            {'start': 19.5 + s, 'end': 23 + s, 'kind': 'personal', 'title': 'Personal & recovery time', 'zone': 'habitat'},
            {'start': 23 + s, 'end': 24.0, 'kind': 'sleep', 'title': 'Sleep period', 'zone': 'habitat'},
        ]
        out[c['id']] = [{**b, 'start': round(b['start'], 2), 'end': round(b['end'], 2)} for b in blocks if b['end'] - b['start'] > 0.01]
    return {'day': day, 'blocks': out, 'source': 'simulated'}


def block_at(blocks: list[dict], hour: float) -> dict:
    for b in blocks:
        if b['start'] <= hour < b['end']:
            return b
    return blocks[-1]


AVAILABILITY = {'sleep': 'resting', 'work': 'on task', 'exercise': 'exercise', 'meal': 'available',
                'personal': 'available', 'health': 'check-in'}


def ship_state(day: int, hour: float, latest: dict[str, dict], phantom_status: dict[str, str]) -> dict:
    cal = calendar(day, latest)
    crew = []
    for c in CREW:
        b = block_at(cal['blocks'][c['id']], hour)
        crew.append({'id': c['id'], 'name': c['name'], 'zone': b['zone'], 'activity': b['title'],
                     'availability': AVAILABILITY[b['kind']],
                     # Permission-safe derived flag only – no raw physiology.
                     'reduced_load_suggested': phantom_status.get(c['id']) == 'attention',
                     'location_source': 'schedule'})
    zones = []
    for z in ZONES:
        occ = sum(1 for p in crew if p['zone'] == z['id'])
        zones.append({**{k: v for k, v in z.items() if k != 'offset'},
                      'environment': zone_environment(day, z['id'], hour, occ)})
    return {'day': day, 'hour': hour, 'zones': zones, 'crew': crew, 'reference': REFERENCE,
            'source': 'simulated',
            'note': 'Crew positions are inferred from the synthetic schedule, not tracked.'}


def zone_history(start: int, end: int, zone_id: str) -> list[dict]:
    """Daily mean conditions for one compartment (occupancy averaged over a typical day)."""
    occ = {'command': 1.4, 'habitat': 1.6, 'medical': 0.3, 'exercise': 0.4, 'systems': 0.6}[zone_id]
    out = []
    for d in range(max(1, start), end + 1):
        e = zone_environment(d, zone_id, 9.0, 0)
        e['co2_ppm'] = round(e['co2_ppm'] + 55 * occ)
        e['occupants'] = occ
        e['status'] = _env_status(e['co2_ppm'], e['temperature_c'], e['humidity_pct'])
        out.append(e)
    return out


# ---------------------------------------------------------------- scheduling
def _utilisation(loads: dict, limits: dict) -> float:
    return max(loads[k] / limits[k] if limits[k] else (1e9 if loads[k] else 0) for k in loads)


def schedules(reduce_a01: bool = False, tasks: list[dict] | None = None,
              capacity: dict[str, float] | None = None, unavailable: list[str] | None = None,
              optimise: bool = True) -> dict:
    """Greedy assignment (priority first) followed by a deterministic local-search
    that moves single tasks when it lowers the peak utilisation. Not globally optimal."""
    tasks = TASKS if tasks is None else tasks
    limits = {c['id']: float(c['capacity']) for c in CREW}
    if reduce_a01:
        limits['A01'] = 2
    for k, v in (capacity or {}).items():
        if k in limits:
            limits[k] = float(v)
    for k in unavailable or []:
        if k in limits:
            limits[k] = 0
    skills = {c['id']: c['skills'] for c in CREW}
    loads = {key: 0.0 for key in limits}
    who: dict[str, str | None] = {}
    for task in sorted(tasks, key=lambda x: (x['priority'], -x['hours'], x['id'])):
        q = [c for c in limits if task['skill'] in skills[c] and loads[c] + task['hours'] <= limits[c]]
        if q:
            best = sorted(q, key=lambda c: (loads[c] / max(1, limits[c]), c))[0]
            loads[best] += task['hours']
            who[task['id']] = best
        else:
            who[task['id']] = None
    greedy_peak = _utilisation(loads, limits)
    moves = 0
    if optimise:
        improved = True
        while improved and moves < 50:
            improved = False
            for task in sorted(tasks, key=lambda x: x['id']):
                cur = who[task['id']]
                if cur is None:
                    continue
                for c in sorted(limits):
                    if c == cur or task['skill'] not in skills[c] or loads[c] + task['hours'] > limits[c]:
                        continue
                    trial = dict(loads)
                    trial[cur] -= task['hours']
                    trial[c] += task['hours']
                    if _utilisation(trial, limits) < _utilisation(loads, limits) - 1e-9:
                        loads, who[task['id']] = trial, c
                        moves += 1
                        improved = True
                        break
    assignments = [{**t, 'astronaut_id': who[t['id']]} for t in sorted(tasks, key=lambda x: (x['priority'], -x['hours'], x['id']))]
    return {'assignments': assignments, 'loads': {k: round(v, 2) for k, v in loads.items()},
            'capacity': limits, 'unassigned': sum(x['astronaut_id'] is None for x in assignments),
            'peak_utilisation': round(_utilisation(loads, limits), 3),
            'greedy_peak_utilisation': round(greedy_peak, 3), 'local_search_moves': moves,
            'method': 'greedy_heuristic+local_search' if optimise else 'greedy_heuristic', 'source': 'simulated'}


def run_scenario(history: list[dict[str, Any]], *, sleep_delta: float, workload: int,
                 co2_ppm: int, temperature_c: float, day: int = 67, crew_available: int = 4) -> dict:
    """Counterfactual single-day simulation, intentionally illustrative and non-causal."""
    original = next((x for x in history if x['day'] == day), None)
    if original is None:
        raise ValueError('No measurement for this mission day')
    adjusted = dict(original)
    eff = effective_workload(workload, crew_available)
    adjusted['sleep_hours'] = round(max(2, min(12, original['sleep_hours'] + sleep_delta)), 2)
    load_delta = (eff - 50) / 35
    adjusted['heart_rate_bpm'] = round(original['heart_rate_bpm'] + load_delta * 3 + (co2_ppm - 850) / 600 * 1.8, 1)
    adjusted['fatigue_1_10'] = round(max(1, min(10, original['fatigue_1_10'] + load_delta * .6 - sleep_delta * .3)), 1)
    adjusted['reaction_ms'] = round(original['reaction_ms'] + load_delta * 12 - sleep_delta * 5, 1)
    adjusted['activity_minutes'] = round(max(0, original['activity_minutes'] + load_delta * 15), 1)
    adjusted['source'] = 'simulated'
    copied = [dict(row) for row in history if row['day'] != day] + [adjusted]
    result = analyze(copied, day)
    unavailable = [c['id'] for c in CREW[crew_available:]] if crew_available < 4 else []
    return {
        'day': day, 'input': {'sleep_delta': sleep_delta, 'workload': workload, 'co2_ppm': co2_ppm,
                              'temperature_c': temperature_c, 'crew_available': crew_available},
        'metrics': {k: adjusted[k] for k in METRICS},
        'phantom': result, 'environment': {'co2_ppm': co2_ppm, 'temperature_c': temperature_c},
        'crew': schedules(reduce_a01=(eff > 70), unavailable=unavailable),
        'source': 'simulated',
        'assumptions': 'Illustrative coefficients, not validated biological effects or causation.'
    }


def effective_workload(workload: float, crew_available: int) -> float:
    return min(100.0, workload * 4 / max(1, crew_available))


# ---------------------------------------------------------------- projection
MASK = 0xFFFFFFFF


class Mulberry32:
    """Tiny deterministic PRNG, identical to the TypeScript implementation."""

    def __init__(self, seed: int):
        self.a = seed & MASK

    @staticmethod
    def _imul(a: int, b: int) -> int:
        return (a * b) & MASK

    def next(self) -> float:
        self.a = (self.a + 0x6D2B79F5) & MASK
        t = self.a
        t = self._imul(t ^ (t >> 15), t | 1)
        t ^= (t + self._imul(t ^ (t >> 7), t | 61)) & MASK
        t &= MASK
        return ((t ^ (t >> 14)) & MASK) / 4294967296

    def normal(self) -> float:
        u = max(self.next(), 1e-12)
        v = self.next()
        return math.sqrt(-2 * math.log(u)) * math.cos(2 * math.pi * v)


# Effect coefficients per unit of: sleep debt (h), workload index, environment index.
COEF = {
    'heart_rate_bpm': (1.2, 3.0, 1.8),
    'fatigue_1_10': (0.45, 0.6, 0.3),
    'reaction_ms': (9.0, 12.0, 6.0),
    'activity_minutes': (0.0, -15.0, 0.0),
}
NOISE = {'heart_rate_bpm': 1.5, 'fatigue_1_10': 0.4, 'reaction_ms': 8.0, 'activity_minutes': 6.0, 'sleep_hours': 0.25}
CLAMP = {'heart_rate_bpm': (30, 200), 'fatigue_1_10': (1, 10), 'reaction_ms': (120, 1500),
         'activity_minutes': (0, 240), 'sleep_hours': (2, 12)}
PROJECTION_ASSUMPTIONS = [
    'Sleep debt accumulates from the gap between planned sleep and personal baseline, recovering 40 % per day.',
    'Workload is divided among available crew; one index unit = 35 points above a workload of 50.',
    'Environment index = (CO₂ − 850 ppm)/600 + max(0, temperature − 24 °C)/3.',
    'The starting day’s deviation from baseline fades with a time constant of 4–10 days.',
    'Each run samples effect sizes (log-normal, σ = 0.3) and daily noise; bands show the 10th–90th percentile of runs.',
    'All coefficients are illustrative assumptions, not validated physiology.',
]


def _pct(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return float('nan')
    pos = (len(sorted_vals) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def project(history: list[dict[str, Any]], *, start_day: int, horizon_days: int, sleep_delta: float,
            workload: float, co2_ppm: float, temperature_c: float, crew_available: int = 4,
            runs: int = 200, seed: int = 67) -> dict:
    start = next((x for x in history if x['day'] == start_day), None)
    if start is None:
        raise ValueError('No measurement for this mission day')
    baselines = compute_baselines(history)
    if any(baselines[k] is None for k in METRICS):
        raise ValueError('Insufficient baseline history for projection')
    n_base = len([r for r in history if r.get('day', 0) <= BASELINE_END])
    base = {k: baselines[k]['median'] for k in METRICS}
    planned_sleep = max(2.0, min(12.0, base['sleep_hours'] + sleep_delta))
    deficit = max(0.0, base['sleep_hours'] - planned_sleep)
    load = (effective_workload(workload, crew_available) - 50) / 35
    env = (co2_ppm - 850) / 600 + max(0.0, temperature_c - 24) / 3
    rng = Mulberry32(seed)
    keys = list(METRICS) + ['score']
    samples = {k: [[] for _ in range(horizon_days + 1)] for k in keys}
    attention = [0] * (horizon_days + 1)
    for _ in range(runs):
        mult = [math.exp(0.3 * rng.normal()) for _ in range(3)]
        tau = 4 + 6 * rng.next()
        debt = 0.0
        for t in range(horizon_days + 1):
            if t > 0:
                debt = debt * 0.6 + deficit
            fade = math.exp(-t / tau)
            vals = {}
            for k in METRICS:
                start_offset = float(start[k]) - base[k]
                if k == 'sleep_hours':
                    v = start[k] if t == 0 else planned_sleep + NOISE[k] * rng.normal()
                else:
                    a, b, c = COEF[k]
                    effect = mult[0] * a * debt + mult[1] * b * load + mult[2] * c * env
                    v = base[k] + start_offset * fade + (effect if t > 0 else 0)
                    if t > 0:
                        v += NOISE[k] * rng.normal()
                lo, hi = CLAMP[k]
                vals[k] = min(hi, max(lo, float(v)))
                samples[k][t].append(vals[k])
            s = score_values(vals, baselines, n_base)
            samples['score'][t].append(float(s['score']))
            if s['status'] == 'attention':
                attention[t] += 1
    days = []
    for t in range(horizon_days + 1):
        row = {'day': start_day + t, 'attention_share': round(attention[t] / runs, 3)}
        for k in keys:
            vs = sorted(samples[k][t])
            row[k] = {'p10': round(_pct(vs, .1), 2), 'p50': round(_pct(vs, .5), 2), 'p90': round(_pct(vs, .9), 2)}
        days.append(row)
    return {
        'start_day': start_day, 'horizon_days': horizon_days, 'runs': runs, 'seed': seed,
        'input': {'sleep_delta': sleep_delta, 'workload': workload, 'co2_ppm': co2_ppm,
                  'temperature_c': temperature_c, 'crew_available': crew_available},
        'derived': {'planned_sleep_h': round(planned_sleep, 2), 'sleep_deficit_h': round(deficit, 2),
                    'workload_index': round(load, 3), 'environment_index': round(env, 3),
                    'baseline': {k: round(v, 2) for k, v in base.items()}},
        'days': days, 'assumptions': PROJECTION_ASSUMPTIONS, 'source': 'simulated',
        'note': '“attention_share” is the fraction of simulated runs that crossed the PHANTOM flag threshold – '
                'a property of this model, not a probability of a real health event.',
    }

