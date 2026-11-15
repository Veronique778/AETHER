"""PHANTOM – explainable research score, NOT a clinical risk probability or diagnosis.

Method (kept deliberately simple and inspectable):
  baseline   = median of the astronaut's own days 1..BASELINE_END
  scale      = max(1.4826 * MAD, floor)     (robust standard-deviation estimate)
  deviation  = (value - baseline) / scale   (robust z-score)
  flagged    = deviation in the "worse" direction >= FLAG_Z
  index      = sum(min(15, 3*|z|)) over flagged signals (+20 if >=2 flagged), capped at 100

1.5 (Backend №3, HEALTH_ALGORITHMS_AUDIT.md A1):
  * no self-inclusion / no future data: the baseline for day d uses only days < d inside 1..BASELINE_END
    (for d > BASELINE_END this is exactly the 1.4 baseline, so results for days 41+ are unchanged);
  * fewer than MIN_COVERAGE of the signals observed and nothing flagged -> status 'insufficient', score None
    (1.4 reported 'normal' with index 0 when 1 of 5 signals was present);
  * the index is an UNCALIBRATED ANOMALY INDEX: not a health percentage, not a probability, not a diagnosis.
"""
from statistics import median
from typing import Any

from .db import METRICS

BASELINE_END = 40
MIN_BASELINE_POINTS = 10
MIN_COVERAGE = 0.6   # share of METRICS that must be observed before 'normal' may be reported (1.5)
FLAG_Z = 2.0
LABELS = {
    'heart_rate_bpm': ('Resting heart rate', 'bpm', 1),
    'sleep_hours': ('Sleep duration', 'h', -1),
    'fatigue_1_10': ('Self-reported fatigue', '/10', 1),
    'reaction_ms': ('Reaction time', 'ms', 1),
    'activity_minutes': ('Physical activity', 'min', -1),
}
# Minimum variability guards against unrealistically small MAD in simulated data.
SCALE_FLOOR = {'heart_rate_bpm': 2.8, 'sleep_hours': .35, 'fatigue_1_10': .55,
               'reaction_ms': 13, 'activity_minutes': 11}
METHOD = {
    'name': 'Robust personal-baseline deviation (median / MAD)',
    'baseline_window': f'mission days 1–{BASELINE_END}',
    'flag_threshold_z': FLAG_Z,
    'steps': [
        f'Personal baseline = median of days 1–{BASELINE_END} for each signal.',
        'Spread = 1.4826 × median absolute deviation, with a per-signal minimum.',
        'Deviation = (today − baseline) / spread, signed so that positive means “less favourable”.',
        f'A signal is flagged when its deviation is ≥ {FLAG_Z:g}.',
        'Index = Σ min(15, 3·|z|) over flagged signals, +20 if two or more change together, capped at 100.',
    ],
    'limitations': [
        'Uncalibrated anomaly index (0–100): not a health percentage, not a probability and not a diagnosis.',
        'Fewer than three of five signals and no flag → insufficient data, never “normal”.',
        'Assumes the baseline window was representative of the person.',
        'Co-occurring deviations do not establish a cause.',
    ],
}


def baseline_rows(history: list[dict[str, Any]], before_day: int | None = None) -> list[dict[str, Any]]:
    """Rows allowed in the baseline: days 1..BASELINE_END and, when before_day is given, strictly earlier days."""
    return [r for r in history if r.get('day', 0) <= BASELINE_END and (before_day is None or r.get('day', 0) < before_day)]


def compute_baselines(history: list[dict[str, Any]], before_day: int | None = None) -> dict[str, dict[str, float] | None]:
    earlier = baseline_rows(history, before_day)
    out: dict[str, dict[str, float] | None] = {}
    for key in METRICS:
        valid = [float(x[key]) for x in earlier if x.get(key) is not None]
        if len(valid) < MIN_BASELINE_POINTS:
            out[key] = None
            continue
        base = median(valid)
        mad = median([abs(v - base) for v in valid])
        out[key] = {'median': base, 'scale': max(1.4826 * mad, SCALE_FLOOR[key]), 'n': len(valid)}
    return out


def score_values(current: dict[str, Any], baselines: dict, n_baseline_days: int) -> dict[str, Any]:
    signals, missing = [], []
    for key in METRICS:
        b = baselines.get(key)
        now = current.get(key)
        if now is None or b is None:
            missing.append(key)
            continue
        z = (float(now) - b['median']) / b['scale']
        direction = LABELS[key][2]
        severity = max(0., direction * z)
        signals.append({
            'key': key, 'label': LABELS[key][0], 'unit': LABELS[key][1],
            'value': round(float(now), 2), 'baseline': round(b['median'], 2),
            'scale': round(b['scale'], 3), 'deviation': round(z, 2),
            'adverse_deviation': round(severity, 2), 'flagged': severity >= FLAG_Z,
        })
    flagged = [x for x in signals if x['flagged']]
    coverage = len(signals) / len(METRICS)
    multi = len(flagged) >= 2
    score = min(100, round(sum(min(15, abs(x['deviation']) * 3) for x in flagged) + (20 if multi else 0)))
    quality = 'complete' if coverage == 1 else ('partial' if coverage >= .6 else 'insufficient')
    uncertain = 'high' if n_baseline_days < 15 or coverage < .6 else ('medium' if coverage < 1 else 'low')
    status = 'insufficient' if not signals else ('attention' if flagged else ('normal' if coverage >= MIN_COVERAGE else 'insufficient'))
    if status == 'insufficient':
        score = None
    return {'signals': signals, 'missing': missing, 'flagged': flagged, 'multi': multi, 'score': score,
            'quality': quality, 'uncertainty': uncertain, 'status': status}


def analyze(history: list[dict[str, Any]], day: int = 67) -> dict[str, Any]:
    """Compare a day against days 1..40, avoiding contamination by later drift."""
    current = next((r for r in history if r.get('day') == day), None)
    if current is None:
        return {'status': 'insufficient', 'score': None, 'data_quality': 'no current reading',
                'uncertainty': 'high', 'signals': [], 'flagged_count': 0, 'multi_signal_pattern': False,
                'explanation': 'No reading for selected day.', 'day': day,
                'next_measurements': ['Record current measurements'], 'source': 'research_prototype',
                'current_source': None, 'method': METHOD,
                'disclaimer': 'Research-only heuristic on synthetic data; not a diagnosis or probability.'}
    n_base = len(baseline_rows(history, day))
    s = score_values(current, compute_baselines(history, day), n_base)
    flagged = s['flagged']
    if flagged:
        summary = ', '.join(x['label'].lower() for x in flagged)
        explanation = f'Changes relative to this astronaut\'s historical baseline: {summary}.'
        if s['multi']:
            explanation += ' Multiple metrics changed together; this does not establish a cause.'
        if s['missing']:   # 1.5.1 (QA 02A §6): a flag on partial data must not read as a complete assessment
            explanation += (f' Only {len(s["signals"])} of {len(METRICS)} signals were measured; '
                            'this is not a complete assessment.')
    elif s['status'] == 'insufficient':
        explanation = ('Too few signals or too little earlier history for a personal-baseline comparison; '
                       'this is not a normal result.')
    else:
        explanation = 'No large deviations from the available personal baseline were found.'
    next_m = [LABELS[key][0] for key in s['missing']]
    if not next_m and flagged:
        next_m = ['Repeat resting heart-rate measurement', 'Confirm sleep and workload log']
        if any(x['key'] == 'reaction_ms' for x in flagged):
            next_m.append('Repeat a Mind Pulse reaction test at a consistent time of day')
    return {
        'day': day, 'status': s['status'], 'score': s['score'],
        'data_quality': s['quality'], 'uncertainty': s['uncertainty'], 'signals': s['signals'],
        'flagged_count': len(flagged), 'multi_signal_pattern': s['multi'],
        'explanation': explanation, 'next_measurements': next_m[:3],
        'source': 'research_prototype', 'current_source': current.get('source'),
        'baseline_days': n_base, 'method': METHOD,
        'disclaimer': 'Research-only heuristic on synthetic data; not a diagnosis or probability.'
    }


def history_scores(history: list[dict[str, Any]], start: int, end: int) -> dict[str, Any]:
    """Day-by-day PHANTOM index and the alert episodes derived from it."""
    baselines = compute_baselines(history)
    n_base = len(baseline_rows(history))
    by_day = {r['day']: r for r in history}
    points, episodes, open_ep = [], [], None
    for day in range(max(1, start), end + 1):
        row = by_day.get(day)
        if row is None:
            points.append({'day': day, 'status': 'insufficient', 'score': None, 'flagged': []})
            continue
        if day <= BASELINE_END:   # 1.5: never score a baseline day against itself or later days
            s = score_values(row, compute_baselines(history, day), len(baseline_rows(history, day)))
        else:
            s = score_values(row, baselines, n_base)
        keys = [x['key'] for x in s['flagged']]
        points.append({'day': day, 'status': s['status'], 'score': s['score'], 'flagged': keys,
                       'source': row.get('source')})
        if s['status'] == 'attention':
            if open_ep is None:
                open_ep = {'start_day': day, 'end_day': day, 'peak_score': s['score'], 'signals': set(keys)}
            else:
                open_ep['end_day'] = day
                open_ep['peak_score'] = max(open_ep['peak_score'], s['score'])
                open_ep['signals'].update(keys)
        elif open_ep is not None:
            episodes.append(open_ep)
            open_ep = None
    if open_ep is not None:
        open_ep['ongoing'] = True
        episodes.append(open_ep)
    alerts = [{**e, 'signals': sorted(e['signals']), 'ongoing': e.get('ongoing', False),
               'label': 'Review suggested' if e['peak_score'] < 50 else 'Priority review suggested'}
              for e in episodes]
    return {'points': points, 'alerts': list(reversed(alerts)), 'source': 'research_prototype'}


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    sa = sum((x - ma) ** 2 for x in a) ** .5
    sb = sum((y - mb) ** 2 for y in b) ** .5
    if sa == 0 or sb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb)


def spearman(a: list[float], b: list[float]) -> float | None:
    return _pearson(_ranks(a), _ranks(b))


def correlations(history: list[dict[str, Any]], day: int, window: int = 30) -> dict[str, Any]:
    rows = [r for r in history if day - window < r['day'] <= day]
    matrix = []
    for a in METRICS:
        for b in METRICS:
            pairs = [(float(r[a]), float(r[b])) for r in rows if r.get(a) is not None and r.get(b) is not None]
            rho = spearman([p[0] for p in pairs], [p[1] for p in pairs]) if len(pairs) >= 8 else None
            matrix.append({'a': a, 'b': b, 'rho': None if rho is None else round(rho, 3), 'n': len(pairs)})
    return {'day': day, 'window_days': window, 'method': 'Spearman rank correlation',
            'metrics': list(METRICS), 'matrix': matrix,
            'note': 'Association within one person’s recent history; not evidence of causation. '
                    'Pairs with fewer than 8 days are not computed.',
            'source': 'research_prototype'}
