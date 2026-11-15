"""NASA Five Hazards model, HRP risk mapping and hazard-interaction graph (AETHER 0.9).

Exposure indices are transparent normalisations of a mission profile, each against a stated reference
(a NASA standard where one exists, otherwise a documented model assumption). They are not risk probabilities.
Graph edges are typed: 'evidence' (a library source supports the link), 'assumption' (a modelling choice made
by AETHER) or 'hypothesis' (plausible, not supported by the library). Edge strength never claims an effect size.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from . import radiation

DESTINATIONS = {
    'iss': {'label': 'ISS (low Earth orbit)', 'gravity_g': 0.0, 'delay_min': 0.0, 'segments': lambda d: [{'environment': 'iss', 'days': d}]},
    'moon': {'label': 'Lunar surface mission', 'gravity_g': 0.166, 'delay_min': 1.3 / 60,
             'segments': lambda d: [{'environment': 'deep_space', 'days': min(5, d)}] + ([{'environment': 'lunar_surface', 'days': d - 5}] if d > 5 else [])},
    'mars': {'label': 'Mars mission', 'gravity_g': 0.38, 'delay_min': 12.5,
             'segments': lambda d: [{'environment': 'deep_space', 'days': min(180, d)}] + ([{'environment': 'mars_surface', 'days': d - 180}] if d > 180 else [])},
}


class MissionProfile(BaseModel):
    destination: str = Field(default='mars', pattern='^(iss|moon|mars)$')
    mission_days: int = Field(default=180, ge=1, le=1200)
    crew_size: int = Field(default=4, ge=1, le=12)
    co2_ppm: float = Field(default=2500, ge=300, le=20000)
    cabin_pressure_mmhg: float = Field(default=760, ge=200, le=800)
    temperature_c: float = Field(default=22, ge=10, le=35)
    sleep_hours: float = Field(default=6.5, ge=0, le=12)
    spe_dose_msv: float = Field(default=0, ge=0, le=1000)


HAZARDS = [
    {'id': 'radiation', 'name': 'Space Radiation',
     'inputs': ['mission segments (environment, days)', 'shielding factor', 'solar particle events'],
     'body_indicators': ['cumulative effective dose (dosimetry) – AETHER has no biological radiation marker'],
     'consequences': ['Risk of Radiation-Induced Cancers (HRP)'],
     'sources': ['NASA-HAZARDS', 'OCHMO-TB-020', 'ZEITLIN-2013', 'HASSLER-2014', 'ZHANG-2020'],
     'limitations': ['Exposure index = median dose / 600 mSv career limit; it is not a cancer-risk estimate.'],
     'modules': ['MISSION LAB (radiation simulator)', 'PHANTOM (exposure context events)'],
     'reference': '600 mSv career limit (NASA-STD-3001)'},
    {'id': 'isolation', 'name': 'Isolation and Confinement',
     'inputs': ['mission duration', 'crew size'],
     'body_indicators': ['sleep duration and timing', 'activity (hypokinesis)', 'reaction time', 'self-reported fatigue'],
     'consequences': ['Risk of Behavioral Changes and Psychiatric Disorders', 'Risk of Inadequate Teamwork', 'Risk of Inadequate Sleep and Irregular Schedules'],
     'sources': ['NASA-HAZARDS', 'BASNER-2013'],
     'limitations': ['Exposure index = duration / 520 days (length of the Mars-520 analogue) – a model assumption, not a dose–response.'],
     'modules': ['BODY', 'PHANTOM', 'CO-ORBIT', 'RECOVERY'], 'reference': 'Mars-520 analogue duration (model assumption)'},
    {'id': 'distance', 'name': 'Distance from Earth',
     'inputs': ['destination', 'one-way communication delay'],
     'body_indicators': ['none directly – affects operations, autonomy and access to medical care'],
     'consequences': ['Risk of Inadequate Systems Operations Support'],
     'sources': ['NASA-HAZARDS', 'ESA-OWLT'],
     'limitations': ['Exposure index = one-way delay / 24 min (approximate maximum Earth–Mars light time).'],
     'modules': ['CO-ORBIT (autonomous planning)', 'MISSION LAB'], 'reference': '≈24 min maximum Earth–Mars one-way delay'},
    {'id': 'gravity', 'name': 'Altered Gravity Fields',
     'inputs': ['gravity level of each phase', 'duration'],
     'body_indicators': ['activity / exercise', 'heart rate (cardiovascular adaptation proxy)', 'bone and muscle – not measured by AETHER'],
     'consequences': ['Risk of Spaceflight-Induced Bone Changes', 'Risk of Reduced Cardiorespiratory and Musculoskeletal Fitness',
                      'Risk of Cardiovascular Adaptations', 'Risk of Altered Sensorimotor and Vestibular Function',
                      'Risk of Spaceflight Associated Neuro-ocular Syndrome (SANS)'],
     'sources': ['NASA-HAZARDS', 'OCHMO-TB-030', 'GARRETT-BAKELMAN-2019', 'NASA-HRP-RESEARCH'],
     'limitations': ['Exposure index = (1 − g) × min(1, days / 180); the 180-day scale is a model assumption.'],
     'modules': ['BODY (musculoskeletal layer, heart rate)', 'CO-ORBIT (exercise blocks)'], 'reference': 'unloading × duration (model assumption)'},
    {'id': 'environment', 'name': 'Hostile / Closed Environment',
     'inputs': ['cabin CO₂ partial pressure', 'temperature', 'lighting / noise (not modelled)'],
     'body_indicators': ['headache / performance (not measured)', 'sleep', 'fatigue'],
     'consequences': ['Risk of Host-Microorganism Interactions', 'Risk of Altered Immune System Responses', 'Risk of Hypoxia'],
     'sources': ['NASA-HAZARDS', 'OCHMO-TB-004', 'NASA-STD-3001'],
     'limitations': ['Exposure index = ppCO₂ / 3 mmHg (NASA-STD-3001 V2 6004 one-hour limit); temperature, noise and microbes are not in the index.'],
     'modules': ['SYMBIOSIS', 'PHANTOM (exposure-aware variant)'], 'reference': '3 mmHg ppCO₂ one-hour limit (NASA-STD-3001)'},
]

HRP_RISKS = [
    # (risk name as listed by NASA, group, AETHER modules/metrics, status, relation type, sources)
    ('Risk of Altered Immune System Responses', 'physiology', [], 'not measured', 'hypothesis', ['NASA-RISKS', 'NASA-HAZARDS']),
    ('Risk of Altered Sensorimotor and Vestibular Function', 'physiology', [], 'not measured', 'evidence', ['NASA-HAZARDS']),
    ('Risk of Cardiovascular Adaptations', 'physiology', ['BODY: resting heart rate', 'PHANTOM: heart-rate signal'], 'partial (heart rate only)', 'evidence', ['GARRETT-BAKELMAN-2019', 'CSA-ISS-SCIENCE']),
    ('Risk of Decompression Sickness', 'physiology', [], 'not measured', 'hypothesis', ['NASA-RISKS']),
    ('Risk of Host-Microorganism Interactions', 'physiology', [], 'not measured', 'evidence', ['NASA-HAZARDS']),
    ('Risk of Hypoxia', 'physiology', ['SYMBIOSIS: cabin atmosphere (CO₂ only)'], 'partial (no O₂ model)', 'assumption', ['NASA-STD-3001']),
    ('Risk of Inadequate Food and Nutrition', 'physiology', [], 'not measured', 'hypothesis', ['NASA-RISKS']),
    ('Risk of Injury and Compromised Performance from Spacewalks', 'physiology', ['CO-ORBIT: EVA preparation task (high-workload plan)'], 'planning only', 'assumption', ['NASA-RISKS']),
    ('Risk of Reduced Cardiorespiratory and Musculoskeletal Fitness', 'physiology', ['BODY: activity minutes', 'PHANTOM: activity signal'], 'partial', 'evidence', ['BASNER-2013', 'NASA-HAZARDS']),
    ('Risk of Spaceflight Associated Neuro-ocular Syndrome (SANS)', 'physiology', [], 'not measured', 'evidence', ['NASA-HRP-RESEARCH']),
    ('Risk of Spaceflight-Induced Bone Changes', 'physiology', ['BODY: skeleton / musculoskeletal layer (visual only)'], 'not measured', 'evidence', ['OCHMO-TB-030']),
    ('Risk of Behavioral Changes and Psychiatric Disorders', 'behavioral', ['PHANTOM: fatigue, reaction time', 'RECOVERY: mood before/after'], 'partial (self-report)', 'evidence', ['BASNER-2013', 'NASA-HAZARDS']),
    ('Risk of Inadequate Teamwork', 'behavioral', ['CO-ORBIT: load balance across crew'], 'proxy (workload only)', 'hypothesis', ['NASA-HAZARDS']),
    ('Risk of Inadequate Sleep and Irregular Schedules', 'behavioral', ['BODY/PHANTOM: sleep hours', 'CO-ORBIT: rest windows', 'RECOVERY: Zero-G Garden'], 'measured (synthetic)', 'evidence', ['BARGER-2014', 'BASNER-2013']),
    ('Risk of Inadequate Systems Operations Support', 'behavioral', ['CO-ORBIT: autonomous re-planning', 'MISSION LAB: communication delay'], 'planning only', 'evidence', ['NASA-HAZARDS', 'ESA-OWLT']),
    ('Risk of Injury from Dynamic Loads', 'behavioral', [], 'not measured', 'hypothesis', ['NASA-RISKS']),
    ('Risk of Radiation-Induced Cancers', 'radiation', ['MISSION LAB: cumulative dose vs 600 mSv'], 'dose only – no cancer-risk estimate', 'evidence', ['OCHMO-TB-020', 'ZEITLIN-2013']),
]

# (from, to, type, sources, note)
EDGES = [
    ('radiation', 'Risk of Radiation-Induced Cancers', 'evidence', ['OCHMO-TB-020'], 'The 600 mSv limit is set around a 3 % cancer-mortality risk.'),
    ('radiation', 'Risk of Cardiovascular Adaptations', 'hypothesis', [], 'Not supported by the AETHER library.'),
    ('radiation', 'Risk of Behavioral Changes and Psychiatric Disorders', 'hypothesis', [], 'CNS effects of GCR are not in the library.'),
    ('isolation', 'Risk of Behavioral Changes and Psychiatric Disorders', 'evidence', ['NASA-HAZARDS', 'BASNER-2013'], ''),
    ('isolation', 'Risk of Inadequate Sleep and Irregular Schedules', 'evidence', ['BASNER-2013'], ''),
    ('isolation', 'Risk of Inadequate Teamwork', 'evidence', ['NASA-HAZARDS'], 'NASA: crews must be chosen, trained and supported to work as a team.'),
    ('distance', 'Risk of Inadequate Systems Operations Support', 'evidence', ['NASA-HAZARDS', 'ESA-OWLT'], ''),
    ('distance', 'Risk of Behavioral Changes and Psychiatric Disorders', 'hypothesis', [], 'Delayed contact with family / ground.'),
    ('gravity', 'Risk of Spaceflight-Induced Bone Changes', 'evidence', ['OCHMO-TB-030'], '≈1–1.5 % BMD loss per month in microgravity.'),
    ('gravity', 'Risk of Reduced Cardiorespiratory and Musculoskeletal Fitness', 'evidence', ['NASA-HAZARDS'], ''),
    ('gravity', 'Risk of Altered Sensorimotor and Vestibular Function', 'evidence', ['NASA-HAZARDS'], 'Inner ear adapts to each gravity level.'),
    ('gravity', 'Risk of Cardiovascular Adaptations', 'evidence', ['GARRETT-BAKELMAN-2019'], 'Carotid changes after a 340-day mission.'),
    ('gravity', 'Risk of Spaceflight Associated Neuro-ocular Syndrome (SANS)', 'evidence', ['NASA-HRP-RESEARCH'], 'Fluid-shift research on eye/brain changes.'),
    ('environment', 'Risk of Host-Microorganism Interactions', 'evidence', ['NASA-HAZARDS'], ''),
    ('environment', 'Risk of Altered Immune System Responses', 'evidence', ['NASA-HAZARDS'], ''),
    ('environment', 'Risk of Hypoxia', 'assumption', ['NASA-STD-3001'], 'Cabin atmosphere control; AETHER models CO₂ only.'),
    ('environment', 'Risk of Inadequate Sleep and Irregular Schedules', 'hypothesis', [], 'CO₂ / temperature effects on sleep are modelled in SYMBIOSIS with illustrative coefficients.'),
    ('Risk of Inadequate Sleep and Irregular Schedules', 'Risk of Behavioral Changes and Psychiatric Disorders', 'assumption', [], 'AETHER propagates sleep debt to fatigue / cognition.'),
    ('Risk of Inadequate Sleep and Irregular Schedules', 'Risk of Inadequate Teamwork', 'hypothesis', [], ''),
    ('isolation', 'distance', 'hypothesis', [], 'Combined isolation and delayed contact may compound behavioural load.'),
    ('radiation', 'gravity', 'hypothesis', [], 'Combined-exposure effects are not quantified in the library.'),
]
TYPE_WEIGHT = {'evidence': 1.0, 'assumption': .6, 'hypothesis': .3}


def exposure(p: MissionProfile) -> dict:
    dest = DESTINATIONS[p.destination]
    rad = radiation.simulate(dest['segments'](p.mission_days), [{'day': min(90, p.mission_days - 1), 'dose_msv': p.spe_dose_msv}] if p.spe_dose_msv else [], runs=300)
    pp_co2 = p.co2_ppm * 1e-6 * p.cabin_pressure_mmhg
    raw = {
        'radiation': rad['final']['p50'] / radiation.CAREER_LIMIT_MSV,
        'isolation': p.mission_days / 520,
        'distance': dest['delay_min'] / 24,
        'gravity': (1 - dest['gravity_g']) * min(1.0, p.mission_days / 180),
        'environment': pp_co2 / 3.0,
    }
    return {'index': {k: round(min(1.5, v), 3) for k, v in raw.items()},
            'detail': {'radiation_median_msv': rad['final']['p50'], 'radiation_p95_msv': rad['final']['p95'],
                       'pp_co2_mmhg': round(pp_co2, 2), 'one_way_delay_min': dest['delay_min'], 'gravity_g': dest['gravity_g']},
            'radiation': rad}


def graph(p: MissionProfile) -> dict:
    exp = exposure(p)
    level: dict[str, float] = {h['id']: min(1.0, exp['index'][h['id']]) for h in HAZARDS}
    risk_names = [r[0] for r in HRP_RISKS]
    for r in risk_names:
        level.setdefault(r, 0.0)
    edges = []
    # two passes so risk→risk edges see hazard-driven levels
    for _ in range(2):
        for a, b, kind, src, note in EDGES:
            w = TYPE_WEIGHT[kind] * level.get(a, 0.0)
            level[b] = max(level.get(b, 0.0), round(w, 3)) if b in risk_names else level.get(b, 0.0)
    for a, b, kind, src, note in EDGES:
        edges.append({'from': a, 'to': b, 'type': kind, 'sources': src, 'note': note, 'strength': round(TYPE_WEIGHT[kind] * level.get(a, 0.0), 3)})
    nodes = [{'id': h['id'], 'label': h['name'], 'kind': 'hazard', 'level': round(level[h['id']], 3)} for h in HAZARDS]
    nodes += [{'id': r[0], 'label': r[0].replace('Risk of ', ''), 'kind': 'risk', 'group': r[1], 'level': round(level[r[0]], 3),
               'aether_status': r[3]} for r in HRP_RISKS if any(e['to'] == r[0] or e['from'] == r[0] for e in edges)]
    top = sorted((n for n in nodes), key=lambda n: -n['level'])[:3]
    return {'profile': p.model_dump(), 'exposure': exp['index'], 'exposure_detail': exp['detail'], 'nodes': nodes, 'edges': edges,
            'summary': ', '.join(f"{n['label']} {n['level']:.2f}" for n in top),
            'legend': {'evidence': 'supported by a library source', 'assumption': 'AETHER modelling choice', 'hypothesis': 'plausible, not supported by the library'},
            'note': 'Levels are normalised exposures propagated along typed edges (evidence 1.0, assumption 0.6, hypothesis 0.3). '
                    'They rank attention, not probability or severity.'}


def hrp_map() -> list[dict]:
    return [{'risk': r[0], 'group': r[1], 'aether': r[2], 'status': r[3], 'relation': r[4], 'sources': r[5]} for r in HRP_RISKS]
