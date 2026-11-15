"""AETHER 1.5 — explainable view of one personal PHANTOM result (Backend №3, BE3_04 / F5).

`explain(result)` is a PURE function of a stored PHANTOM result: it is computed when the result is returned
(POST / GET / list of /api/phantom-analyses) and is never written to storage, so an existing analysis keeps its stored
content, idempotency and digest. It adds no new data and makes no medical statement; it re-states what the stored
result already contains in one fixed, documented shape (`explain_version`).

Same DTO, same routes — no second API.
"""
from __future__ import annotations

EXPLAIN_VERSION = 'aether-phantom-explain-v1'

NASA_CONTEXT = {
    'title': 'Risk of Performance Decrements and Adverse Health Outcomes Resulting from Sleep Loss, Circadian '
             'Desynchronization, and Work Overload (NASA Human Research Program)',
    'url': 'https://humanresearchroadmap.nasa.gov/risks/risk.aspx?i=100',
    'relevance': 'Problem context only: NASA documents why crew fatigue and workload matter. It does not validate this '
                 'method, its thresholds or its use for astronauts.',
}

DATA_LABELS = {'real_wearable': 'REAL SENSOR', 'manual': 'MANUAL ENTRY', 'synthetic': 'SYNTHETIC',
               'terrestrial_research': 'TERRESTRIAL HUMAN RESEARCH DATA'}

VALIDATION_STATUS = {
    'level_a_numeric_reference': 'passed (tests/test_level_a_reference_04.py)',
    'level_b_synthetic_benchmark': 'protocol AETHER-BE3-04-PHANTOM-HR-SYNTH-v1: pre-registered criteria met on SYNTHETIC '
                                   'data only (docs/validation/RESULTS_BE3_04.md); short 5–8 min HR bouts are flagged',
    'level_c_external_human_data': 'not performed',
    'clinical_validation': 'not performed',
    'hardware_verified': False,
}


def _label(classes: list[str]) -> str:
    labels = sorted({DATA_LABELS.get(c, c.upper()) for c in classes or []})
    return ' + '.join(labels) if labels else 'NO DATA'


def _explain(result: dict) -> dict:
    method = result.get('method') or {}
    params = method.get('parameters') or {}
    threshold = params.get('threshold_robust_z')
    inp = result.get('input') or {}
    windows = [w for w in (result.get('windows') or []) if isinstance(w, dict)] if isinstance(result.get('windows'), list) else []
    tests = [w for w in windows if w.get('role') == 'test']
    scored = [w for w in tests if w.get('score') is not None]
    flagged = [w for w in scored if w.get('outcome') == 'flag']
    base = result.get('baseline')
    quality = (result.get('signal_quality') or {}).get('heart_rate') or {}
    outcome = result.get('outcome')
    classes = result.get('source_data_classes') or inp.get('data_classes') or []

    dev = None
    if base and scored:
        top = max(scored, key=lambda w: w['score'])
        dev = {'max_robust_z': top['score'], 'window_start': top.get('start'), 'window_end': top.get('end'),
               'window_mean_hr_bpm': top.get('mean_hr_bpm'),
               'difference_from_baseline_bpm': round(top['mean_hr_bpm'] - base['median_hr_bpm'], 3)
               if top.get('mean_hr_bpm') is not None else None,
               'threshold_robust_z': threshold, 'flagged_windows': len(flagged), 'scored_windows': len(scored)}

    if outcome == 'flag':
        why = [f'{len(flagged)} of {len(scored)} usable 5-minute windows have mean HR at least {threshold} robust SD '
               f'from this person\'s frozen baseline.']
        nxt = ('Optional, not medical advice: repeat a recording at rest under comparable conditions (time of day, posture, '
               'recent activity, caffeine) to see whether the change persists. Short activity bouts of 5 minutes or more '
               'are also flagged by this method.')
    elif outcome == 'no_flag':
        why = [f'None of {len(scored)} usable 5-minute windows reached {threshold} robust SD from the frozen baseline.']
        nxt = ('Optional, not medical advice: no_flag means only that no large heart-rate change relative to the own '
               'baseline was found; changes smaller than about 10 bpm are usually not detected and other signals were not '
               'assessed. It does not mean healthy.')
    else:
        reasons = ((result.get('insufficient_data') or {}).get('reasons') if isinstance(result.get('insufficient_data'), dict)
                   else None) or []
        why = [r.get('message') or r.get('code') for r in reasons if isinstance(r, dict)]
        if not why:
            why = ['Not enough valid heart-rate data for a personal-baseline comparison.']
        nxt = ('Optional, not medical advice: record at least 60 minutes of baseline with sensor contact reported '
               '(at least 10 usable 5-minute windows), then continue recording; insufficient_data is not a normal result.')

    return {
        'explain_version': EXPLAIN_VERSION,
        'available': True,
        'outcome': outcome,
        'what_was_measured': {'signal': 'heart_rate', 'unit': 'bpm',
                              'statistic': 'mean of valid samples per 5-minute window, compared with the own frozen baseline',
                              'signals_not_assessed': (result.get('assessment_scope') or {}).get('signals_not_assessed', [])},
        'data_class': classes,
        'data_label': _label(classes),
        'signal_quality': {'measurements': inp.get('measurement_count'), 'valid': inp.get('valid_count'),
                           'excluded': inp.get('excluded') or {}, 'contact': quality.get('contact'),
                           'longest_gap_s': quality.get('longest_gap_s'),
                           'test_windows': len(tests), 'usable_test_windows': len(scored),
                           'coverage': round(len(scored) / len(tests), 4) if tests else None},
        'time_bounds': {'requested_from': inp.get('requested_from'), 'requested_to': inp.get('requested_to'),
                        'analysed_from': inp.get('from'), 'analysed_to': inp.get('to'),
                        'baseline_from': (base or {}).get('from'), 'baseline_to': (base or {}).get('to')},
        'baseline': None if not base else {'median_hr_bpm': base.get('median_hr_bpm'), 'robust_scale_bpm': base.get('scale_bpm'),
                                           'windows_used': base.get('windows_used'),
                                           'scale_floor_applied': base.get('scale_floor_applied'),
                                           'policy': base.get('policy')},
        'deviation': dev,
        'method': {'id': method.get('id'), 'processing_version': result.get('processing_version'),
                   'classification': method.get('classification'), 'threshold_robust_z': threshold},
        'why': why,
        'next_measurement': nxt,
        'not_medical_advice': True,
        'diagnosis': None,
        'limitations': list(result.get('limitations') or []),
        'research_context': NASA_CONTEXT,
        'validation_status': dict(VALIDATION_STATUS),
    }


def explain(result: dict) -> dict:
    """Never fails a read: a stored result of an unexpected (older / foreign) shape gets an explicit 'not available'."""
    try:
        return _explain(result if isinstance(result, dict) else {})
    except (AttributeError, TypeError, KeyError, ValueError):
        return {'explain_version': EXPLAIN_VERSION, 'available': False, 'outcome': (result or {}).get('outcome')
                if isinstance(result, dict) else None,
                'reason': 'The stored result does not have the shape this explanation version understands.',
                'not_medical_advice': True, 'diagnosis': None}


def with_explain(result: dict) -> dict:
    return {**result, 'explain': explain(result)}
