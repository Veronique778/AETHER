"""AETHER 1.0 · B3 — missing-data robustness of PHANTOM 2.0 (synthetic data only).

    python validation/phantom_study.py missing --out validation/results_1_0

Matrix (B3.1): missing share 0, 10, 20, 30, 40, 50 % × mode
    random          each reading dropped independently
    dropout         one contiguous outage of all sensors covering the share of the run
    channel         round(share × 7) whole channels missing for the entire run
    during_anomaly  readings dropped only while the crew member has a labelled change
    baseline        readings dropped only inside the baseline window
at noise 0 (application default) and, for `random`, also at noise 1 × floor (exercises the noise-adaptive branch).
Seeds 5001–5012 (fresh; not used anywhere else). Templates: sleep_loss, pulse_shift, cognitive_decline, multifactor, normal.

Variants (B3.2):
    stats 'complete'   0.9 behaviour: robust covariance from complete baseline rows only (None → Mahalanobis abstains)
    stats 'hybrid'     complete-case covariance when available, otherwise pairwise robust (Gnanadesikan–Kettenring) with
                       PD projection + shrinkage (covariance regularisation); observed-subspace d² with df = observed count
    stats 'hybrid+gap' hybrid + gap-aware AR(1) prewhitening (ρ^(g+1) after g missing steps)
Conditional-mean imputation is NOT a separate variant: for a Gaussian model it gives exactly the observed-subspace d²
(tested in tests/test_phantom_missing.py), so it cannot change any Mahalanobis decision; imputed values would only add
fake evidence to per-channel CUSUM / EWMA.
`insufficient_data`: a sample with fewer than MIN_FEATURES observed channels and no alarm is reported as insufficient
instead of 'no anomaly' (its share is reported); an alarm on the observed channels is still reported.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

import phantom_study as ps

SEEDS = range(5001, 5013)
TEMPLATES = ['sleep_loss', 'pulse_shift', 'cognitive_decline', 'multifactor', 'normal']
LEVELS = (0.1, 0.2, 0.3, 0.4, 0.5)
MODES = ('random', 'dropout', 'channel', 'during_anomaly', 'baseline')
MIN_FEATURES = 2


def conditions():
    out = [{'label': 'none / 0.0 / noise 0', 'noise': 0.0, 'missing': 0.0, 'mode': 'random'}]
    out += [{'label': f'{m} / {lv} / noise 0', 'noise': 0.0, 'missing': lv, 'mode': m} for m in MODES for lv in LEVELS]
    out += [{'label': 'none / 0.0 / noise 1', 'noise': 1.0, 'missing': 0.0, 'mode': 'random'}]
    out += [{'label': f'random / {lv} / noise 1', 'noise': 1.0, 'missing': lv, 'mode': 'random'} for lv in LEVELS]
    return out


def score(run, truth, name, thresholds, min_features=MIN_FEATURES):
    sc = ps.score_run(run, truth, name, thresholds)
    ins = tot = 0
    for cid, r in run.items():
        f, _ = ps.flags_for(r['stats'], name, thresholds)
        for i, s in enumerate(r['samples']):
            if truth[s['sample_id']]['minute'] < ps.MONITOR_FROM:
                continue
            tot += 1
            ins += (r['stats']['n_observed'][i] < min_features) and not f[i]
    sc['insufficient_share'] = ins / tot if tot else None
    return sc


def missing_study(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    sel = json.loads((out / 'b2_selection.json').read_text())
    chosen = sel['chosen']
    th = {tuple(k.split('|', 1)): (-np.inf if v is None else v) for k, v in json.loads((out / 'b2_thresholds.json').read_text()).items()}
    for name in ps.ADAPTIVE:
        if ('nu*', name) in th:
            ps.NU_STAR[name] = th[('nu*', name)]
    ps.SPLITS['missing_eval'] = SEEDS
    conds = conditions()
    variants = {'complete': 'complete', 'hybrid': 'hybrid', 'hybrid+gap': ('hybrid', True)}
    names = {'mahalanobis (0.9)', 'cusum (0.9)', 'zscore (PHANTOM 1.0)', 'phantom2 0.9 = mahalanobis OR cusum', chosen}
    rows = []
    for vname, cov in variants.items():
        runs = ps.collect('missing_eval', conds, TEMPLATES, covariance=cov)
        for r in runs:
            for name in sorted(names):
                sc = score(r['run'], r['truth'], name, th)
                rows.append({'stats': vname, 'candidate': name, 'template': r['template'], 'seed': r['seed'],
                             'condition': r['condition'], 'mode': r.get('mode'), 'missing': r.get('missing'), 'noise': r.get('noise'), **sc})
        del runs
    ps.write_csv(out / 'b3_runs.csv', [{k: v for k, v in r.items() if k != 'delays_min'} for r in rows])
    summ = []
    for g in ps.aggregate(rows, ('stats', 'candidate', 'condition')):
        sub = [r for r in rows if r['stats'] == g['stats'] and r['candidate'] == g['candidate'] and r['condition'] == g['condition']]
        g['insufficient_share'] = round(float(np.mean([r['insufficient_share'] for r in sub])), 4)
        summ.append(g)
    ps.write_csv(out / 'b3_summary.csv', summ)
    res = {'protocol': {'seeds': f'{min(SEEDS)}-{max(SEEDS)}', 'templates': TEMPLATES, 'conditions': [c['label'] for c in conds],
                        'variants': {k: str(v) for k, v in variants.items()}, 'min_features': MIN_FEATURES, 'b2_chosen': chosen,
                        'doc': __doc__}, 'summary': summ, 'runtime_s': round(time.time() - t0, 1)}
    (out / 'b3_results.json').write_text(json.dumps(res, indent=1, default=str), encoding='utf-8')
    print('B3 done in', res['runtime_s'], 's')
    return res
