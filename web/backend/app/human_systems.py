"""Human-systems extension for the AETHER v0.6 desktop Python backend.

The primary BODY/PHANTOM/SYMBIOSIS data pipeline remains unchanged. This
extension reports provenance-aware data quality and actionable missing readings.
No synthetic values are silently imputed. Not a diagnostic instrument.
"""
from __future__ import annotations
import math
import statistics
from . import db

REQUIRED = ('heart_rate_bpm', 'sleep_hours', 'fatigue_1_10', 'reaction_ms', 'activity_minutes')
UNITS = {'heart_rate_bpm': 'bpm', 'sleep_hours': 'h', 'fatigue_1_10': 'score 1–10',
         'reaction_ms': 'ms', 'activity_minutes': 'min'}

def summary(astronaut_id: str, day: int = 67, window: int = 14) -> dict:
    if astronaut_id not in {a['id'] for a in db.astronauts()}:
        raise ValueError('Unknown astronaut')
    if not (1 <= day <= 100000 and 3 <= window <= 365):
        raise ValueError('Invalid analysis period')
    rows = [r for r in db.timeline(astronaut_id, day) if r['day'] > day-window]
    observed = sum(r.get(k) is not None and isinstance(r.get(k), (float,int))
                   and math.isfinite(r[k]) for r in rows for k in REQUIRED)
    expected = window*len(REQUIRED)
    missing = [k for k in REQUIRED if not rows or rows[-1].get(k) is None]
    baselines = {}
    for k in REQUIRED:
        values = [float(r[k]) for r in rows if r.get(k) is not None and math.isfinite(r[k])]
        baselines[k] = {'median': round(statistics.median(values), 3) if len(values)>=3 else None,
                        'samples': len(values), 'unit': UNITS[k],
                        'status': 'available' if len(values)>=3 else 'insufficient_history'}
    sources = sorted({r.get('source', 'unknown') for r in rows})
    recommendations = [{'metric': k, 'reason': 'No recent measurement available; verify the sensor or enter a measured value.'}
                       for k in missing]
    if len(rows)<7:
        recommendations.append({'metric': 'history', 'reason': 'At least seven observation days are recommended for a more informative trend comparison.'})
    return {'astronaut_id': astronaut_id, 'day': day, 'window_days': window,
            'record_count': len(rows), 'observed_values': observed, 'expected_values': expected,
            'completeness': round(observed/expected, 3), 'sources': sources,
            'baselines': baselines, 'missing_latest': missing,
            'suggested_measurements': recommendations,
            'uncertainty': {'data': 'high' if observed/expected<0.7 else 'moderate' if observed/expected<0.95 else 'lower',
                            'model': 'not quantified; no calibrated probability is provided'},
            'research_only': True, 'note': 'Historical demo data are synthetic; no clinical conclusions.'}
