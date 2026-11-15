"""Scientifically bounded radiation-exposure simulator (AETHER 0.9).

What it does: accumulates DOSE EQUIVALENT (mSv) over mission segments using instrument-measured environment rates,
adds user-specified solar particle event (SPE) doses, propagates rate uncertainty by Monte Carlo and compares the
result with NASA permissible-exposure limits (career 600 mSv; 250 mSv per SPE).

What it does NOT do: it does not estimate cancer risk, organ doses, acute effects or any clinical consequence.
Comparison with a limit is a standards comparison only. Dose quantity (1.0 review, B8.3): the rates are
detector dose equivalents, while the NASA limits are defined in NASA effective dose (tissue-weighted, model-based,
NASA-STD-3001 Vol 1 Rev C [V1 4030] career < 600 mSv; [V1 4031] design-reference SPE < 250 mSv). Using a measured dose
equivalent as a stand-in for effective dose is an approximation; the response says so in `dose_quantity`. Dose rates depend on solar cycle and shielding; the
uncertainty used here is the reported measurement spread where available, otherwise a stated model assumption.
"""
from __future__ import annotations

import numpy as np

CAREER_LIMIT_MSV = 600.0   # NASA-STD-3001 Vol 1 Rev C [V1 4030] (OCHMO-TB-020)
SPE_LIMIT_MSV = 250.0      # short-term SPE limit quoted in OCHMO standards overview / TB-020

# dose-equivalent rate (mSv/day), relative 1-σ uncertainty, source id, whether the spread is measured
ENVIRONMENTS = {
    'earth': {'rate': 0.0, 'rel_sd': 0.0, 'source': None, 'label': 'Earth (background ignored)', 'spread': 'n/a'},
    'iss': {'rate': 0.731, 'rel_sd': 0.20, 'source': 'ZHANG-2020', 'label': 'ISS (LEO)',
            'spread': 'model assumption ±20 % (solar cycle, orbit); rate measured during solar minimum 2019'},
    'deep_space': {'rate': 1.84, 'rel_sd': 0.18, 'source': 'ZEITLIN-2013', 'label': 'Deep-space transit (MSL-like shielding)',
                   'spread': '±18 % from the reported 0.66 ± 0.12 Sv round-trip estimate'},
    'lunar_surface': {'rate': 1.369, 'rel_sd': 0.15, 'source': 'ZHANG-2020', 'label': 'Lunar surface',
                      'spread': 'model assumption ±15 % (single solar-minimum measurement; measurement error not used here)'},
    'mars_surface': {'rate': 0.64, 'rel_sd': 0.19, 'source': 'HASSLER-2014', 'label': 'Mars surface (Gale crater)',
                     'spread': '±19 % from the reported 0.21 ± 0.04 mGy/day GCR absorbed dose'},
}

PRESETS = {
    'iss_6_months': {'title': 'ISS – 6 months', 'segments': [{'environment': 'iss', 'days': 182}], 'spe': []},
    'lunar_30_days': {'title': 'Lunar surface stay – 30 days + transit',
                      'segments': [{'environment': 'deep_space', 'days': 5}, {'environment': 'lunar_surface', 'days': 30}, {'environment': 'deep_space', 'days': 5}], 'spe': []},
    'mars_conjunction': {'title': 'Mars conjunction-class (180 d transit + 500 d surface + 180 d return)',
                         'segments': [{'environment': 'deep_space', 'days': 180}, {'environment': 'mars_surface', 'days': 500}, {'environment': 'deep_space', 'days': 180}], 'spe': []},
    'mars_with_spe': {'title': 'Mars conjunction-class + one user-defined SPE (50 mSv, day 90)',
                      'segments': [{'environment': 'deep_space', 'days': 180}, {'environment': 'mars_surface', 'days': 500}, {'environment': 'deep_space', 'days': 180}],
                      'spe': [{'day': 90, 'dose_msv': 50.0}]},
}


def simulate(segments: list[dict], spe: list[dict] | None = None, *, shielding_factor: float = 1.0, prior_career_msv: float = 0.0,
             runs: int = 500, seed: int = 67) -> dict:
    if not segments:
        raise ValueError('At least one mission segment is required')
    if not 0.3 <= shielding_factor <= 1.5:
        raise ValueError('shielding_factor must be within 0.3..1.5 (model assumption multiplier)')
    days = []
    for seg in segments:
        env = ENVIRONMENTS.get(seg['environment'])
        if env is None:
            raise ValueError(f"Unknown environment {seg['environment']}")
        if not 0 < int(seg['days']) <= 3000:
            raise ValueError('Segment length must be 1..3000 days')
        days += [seg['environment']] * int(seg['days'])
    total = len(days)
    spe = sorted(spe or [], key=lambda e: e['day'])
    for e in spe:
        if not 0 <= e['day'] < total:
            raise ValueError('SPE day outside the mission')
        if not 0 <= e['dose_msv'] <= 2000:
            raise ValueError('SPE dose must be 0..2000 mSv')
    rng = np.random.default_rng(seed)
    # one lognormal factor per environment per run (rate uncertainty is systematic, not day-to-day noise)
    envs = sorted({d for d in days})
    factors = {e: np.exp(rng.normal(0, ENVIRONMENTS[e]['rel_sd'], runs) - ENVIRONMENTS[e]['rel_sd'] ** 2 / 2) for e in envs}
    daily = np.zeros((runs, total))
    for t, e in enumerate(days):
        daily[:, t] = ENVIRONMENTS[e]['rate'] * shielding_factor * factors[e]
    for e in spe:
        daily[:, e['day']] += e['dose_msv']
    cum = prior_career_msv + np.cumsum(daily, axis=1)
    p5, p50, p95 = (np.percentile(cum, q, axis=0) for q in (5, 50, 95))
    step = max(1, total // 200)
    idx = list(range(0, total, step)) + ([total - 1] if (total - 1) % step else [])
    final = cum[:, -1]

    def first_day(level):
        hit = np.where(p50 >= level)[0]
        return int(hit[0]) if len(hit) else None

    events = [{'day': e['day'], 'kind': 'solar_particle_event', 'dose_msv': e['dose_msv'],
               'exceeds_spe_limit': e['dose_msv'] >= SPE_LIMIT_MSV} for e in spe]
    for frac in (.5, 1.0):
        d = first_day(CAREER_LIMIT_MSV * frac)
        if d is not None:
            events.append({'day': d, 'kind': f'median_reaches_{int(frac * 100)}pct_career_limit', 'dose_msv': round(float(p50[d]), 1)})
    events.sort(key=lambda e: e['day'])
    return {
        'days': total, 'series': [{'day': i + 1, 'p5': round(float(p5[i]), 1), 'p50': round(float(p50[i]), 1), 'p95': round(float(p95[i]), 1),
                                   'environment': days[i]} for i in idx],
        'final': {'p5': round(float(np.percentile(final, 5)), 1), 'p50': round(float(np.median(final)), 1), 'p95': round(float(np.percentile(final, 95)), 1)},
        'fraction_of_career_limit': {k: round(v / CAREER_LIMIT_MSV, 3) for k, v in
                                     {'p5': float(np.percentile(final, 5)), 'p50': float(np.median(final)), 'p95': float(np.percentile(final, 95))}.items()},
        'probability_exceeds_career_limit': round(float((final >= CAREER_LIMIT_MSV).mean()), 3),
        'events': events,
        'by_environment': {e: {'days': days.count(e), 'rate_msv_per_day': ENVIRONMENTS[e]['rate'], 'source': ENVIRONMENTS[e]['source'],
                               'uncertainty': ENVIRONMENTS[e]['spread']} for e in envs},
        'limits': {'career_msv': CAREER_LIMIT_MSV, 'spe_msv': SPE_LIMIT_MSV, 'source': 'OCHMO-TB-020 / NASA-STD-3001 Vol 1 Rev C [V1 4030]'},
        'inputs': {'segments': segments, 'spe': spe, 'shielding_factor': shielding_factor, 'prior_career_msv': prior_career_msv, 'runs': runs, 'seed': seed},
        'not_modelled': ['cancer or other health risk', 'organ doses', 'acute radiation effects', 'SPE probability (events are user-specified)',
                         'solar-cycle modulation beyond the stated spread', 'detailed shielding transport'],
        'dose_quantity': {'accumulated': 'dose equivalent from instrument measurements (mSv)',
                          'limits': 'NASA effective dose (mSv) – NASA-STD-3001 Vol 1 Rev C [V1 4030], [V1 4031]',
                          'note': 'Measured dose equivalent is used as a proxy for effective dose; the limit comparison is approximate.'},
        'origin': 'estimated',
    }
