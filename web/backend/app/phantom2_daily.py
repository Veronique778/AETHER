"""PHANTOM 2.0 on the daily AETHER record (same signals and baseline window as PHANTOM 1.0)."""
from __future__ import annotations

import numpy as np

from . import db, phantom2 as p2
from .analytics import BASELINE_END, LABELS, SCALE_FLOOR

METRICS = list(LABELS)
DIRECTION = np.array([LABELS[m][2] for m in METRICS], float)


MIN_OBSERVED_FOR_NO_FLAG = 3   # 1.5: same coverage rule as PHANTOM 1.0 (3 of 5) before "within baseline" is reported
THRESHOLD_NOTE = ('χ²(0.995, df) assumes a known covariance. With a 40-day baseline the in-control exceedance rate is '
                  'higher than 0.5 % (HEALTH_ALGORITHMS_AUDIT.md, experiment E1); treat the threshold as a review '
                  'trigger, not as a calibrated false-alarm rate.')
UNCERTAINTY_NOTE = ('flag_probability is the share of bootstrap re-fits of the baseline covariance that flag this day – '
                    'a stability measure of the statistic, not a probability of any health event.')


def _insufficient(astronaut_id, day, detail, reasons, last_day):
    return {'astronaut_id': astronaut_id, 'day': day, 'requested_day': day, 'analysed_day': None,
            'last_available_day': last_day, 'status': 'insufficient_data', 'today_state': 'insufficient_data',
            'score': None, 'diagnosis': None, 'detail': detail, 'insufficient_data': {'reasons': reasons},
            'origin': 'synthetic'}


def analyze(astronaut_id: str, day: int, *, bootstrap: int = 60) -> dict:
    rows = [r for r in db.timeline(astronaut_id, day)]
    rows.sort(key=lambda r: r['day'])
    last_day = rows[-1]['day'] if rows else None
    # 1.5: the requested day must exist. 1.4 silently analysed the last stored day (e.g. day 67 for a request of day 100).
    if not rows or rows[-1]['day'] != day:
        return _insufficient(astronaut_id, day, f'No record for day {day}; the last stored day is {last_day}. '
                             'Nothing was analysed and no other day was substituted.',
                             [{'code': 'no_measurements', 'signal': None, 'required': 1, 'available': 0,
                               'message': f'No daily record for day {day}.'}], last_day)
    days = [r['day'] for r in rows]
    X = np.array([[np.nan if r.get(m) is None else float(r[m]) for m in METRICS] for r in rows])
    # 1.5: baseline = days 1..BASELINE_END strictly before the analysed day (no self-inclusion for day <= 40)
    nb = sum(d <= min(BASELINE_END, day - 1) for d in days)
    if nb < 10:
        return {'astronaut_id': astronaut_id, 'day': day, 'requested_day': day, 'analysed_day': None,
                'last_available_day': last_day, 'status': 'insufficient_baseline', 'today_state': 'insufficient_data',
                'score': None, 'diagnosis': None,
                'detail': f'Need at least 10 baseline days before day {day} (within 1–{BASELINE_END}); have {nb}.',
                'insufficient_data': {'reasons': [{'code': 'too_few_baseline_windows', 'signal': None, 'required': 10,
                                                   'available': nb, 'message': 'Too few earlier baseline days.'}]}}
    base = p2.fit_baseline(X[:nb], METRICS, SCALE_FLOOR)
    # The 1.0 noise-adaptive decision was calibrated on Mission Systems engine data only → the daily record keeps the 0.9 rule.
    res = p2.run_detectors(X, base, DIRECTION, bootstrap=bootstrap, rng=np.random.default_rng(day), explain=True, decision='v09')
    i = len(rows) - 1
    observed = int((~np.isnan(X[i])).sum())
    if res['states'][i] == 'no_flag' and observed < MIN_OBSERVED_FOR_NO_FLAG:
        res['states'][i] = 'insufficient_data'
    det = res['details'][i] or {}
    series = []
    for k in range(nb, len(rows)):
        d = res['details'][k] or {}
        series.append({'day': days[k], 'd2': d.get('d2'), 'threshold': d.get('threshold'), 'state': res['states'][k],
                       **{name: res['flags'][name][k] for name in p2.DETECTORS}})
    z = (X[i] - base.median) / base.scale
    nbm = p2.next_best_measurement(z, base.cov, METRICS, np.random.default_rng(day)) if base.cov is not None else []
    first_cusum = {}
    for m, st in (det.get('cusum') or {}).items():
        if st['alarm'] and st['start_index'] is not None:
            first_cusum[m] = days[st['start_index']]
    return {
        'astronaut_id': astronaut_id, 'day': day, 'requested_day': day, 'analysed_day': days[i],
        'last_available_day': last_day, 'status': 'ok', 'origin': 'synthetic', 'diagnosis': None,
        'baseline_window': f'days 1–{days[nb - 1]} ({nb} days)',
        'observed_signals': observed, 'missing_signals': [m for m, v in zip(METRICS, X[i]) if np.isnan(v)],
        'assessment_scope': {'signals_assessed': [m for m, v in zip(METRICS, X[i]) if not np.isnan(v)],
                             'complete_assessment': observed == len(METRICS),
                             'statement': 'Statistical comparison of the observed signals with this person\'s baseline; '
                                          + ('all five daily signals were observed.' if observed == len(METRICS) else
                                             f'only {observed} of {len(METRICS)} signals were observed — not a complete assessment.')},
        'today': {name: res['flags'][name][i] for name in p2.DETECTORS},
        'today_state': res['states'][i],
        'decision_rule': {'rule': 'v09: Mahalanobis OR CUSUM', 'note': 'The AETHER 1.0 noise-adaptive rule is calibrated and '
                          'validated on Mission Systems engine data only; it is not applied to the daily record.',
                          'baseline_noise_index': res['regime']['nu'], 'covariance': res['regime']['covariance']},
        'multivariate': {**{k: det.get(k) for k in ('d2', 'threshold', 'df', 'attribution', 'uncertainty')},
                         'threshold_note': THRESHOLD_NOTE, 'uncertainty_note': UNCERTAINTY_NOTE},
        'cusum': det.get('cusum'), 'cusum_change_start_day': first_cusum,
        'z': det.get('z'), 'autocorrelation': {m: round(float(r), 2) for m, r in zip(METRICS, base.rho)},
        'next_best_measurement': nbm, 'series': series,
        'labels': {m: {'label': LABELS[m][0], 'unit': LABELS[m][1]} for m in METRICS},
        'method': p2.__doc__.strip().split('\n\n')[0] + ' See app/phantom2.py for all steps.',
        'parameters': {'chi2_quantile': p2.CHI2_Q, 'cusum_k': p2.CUSUM_K, 'cusum_h': p2.CUSUM_H,
                       'ewma_lambda': p2.EWMA_LAMBDA, 'ewma_L': p2.EWMA_L, 'shrinkage': p2.SHRINK, 'bootstrap': bootstrap},
        'references': p2.REFERENCES,
        'limitations': ['Thresholds are conventional, not fitted to astronaut data.',
                        'A 40-day baseline gives an imprecise 5×5 covariance; the bootstrap interval shows how much.',
                        'Synthetic dataset: detections reflect the generator, not real physiology.',
                        'A deviation is a prompt for review, never a diagnosis.'],
    }
