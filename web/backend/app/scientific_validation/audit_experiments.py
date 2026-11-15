"""AETHER 1.5 scientific audit — reproducible numerical experiments (Backend №3).

Run:  python -m app.scientific_validation.audit_experiments  [--quick]
Writes JSON to stdout. Every experiment is deterministic (fixed seeds). All data here are SYNTHETIC test
series built for checking the mathematics; none of the results says anything about real physiology.

E1  PHANTOM 2.0 Mahalanobis: in-control false-alarm rate of the χ²(0.995, k) threshold when the covariance is
    estimated from a short baseline (n = 40), for iid and for autocorrelated (AR(1), ρ = 0.9) baselines.
E2  PHANTOM 2.0 bootstrap: does iid resampling of an autocorrelated baseline reproduce the real sampling spread
    of d²?  Compared with a moving-block bootstrap.
E3  PHANTOM 2.0 prewhitening after a gap: the implementation uses the last value before the gap as if it were lag 1.
E4  PHANTOM 1.0 robust z: zero / near-zero MAD, with and without the scale floor.
E5  Biosignal HRV (rr_features): RMSSD / SDNN against hand-computable reference series and an independent numpy
    implementation.
"""
from __future__ import annotations

import json
import math
import sys

import numpy as np
from scipy.stats import chi2, f as fdist

from app import phantom2 as p2


def _ar1(rng, n, k, rho, corr=0.5):
    C = np.full((k, k), corr) + (1 - corr) * np.eye(k)
    L = np.linalg.cholesky(C)
    x = np.zeros((n, k))
    prev = L @ rng.standard_normal(k)
    for t in range(n):
        innov = L @ rng.standard_normal(k) * math.sqrt(1 - rho ** 2)
        prev = rho * prev + innov if t else prev
        x[t] = prev
    return x, C


def e1_mahalanobis_fpr(reps=200, tests=500, n=40, k=5, seed=11):
    rng = np.random.default_rng(seed)
    thr_chi2 = chi2.ppf(p2.CHI2_Q, k)
    # Prediction-region threshold for a new observation when mean and covariance are estimated (Hotelling)
    thr_hot = k * (n + 1) * (n - 1) / (n * (n - k)) * fdist.ppf(p2.CHI2_Q, k, n - k)
    out = {}
    for label, rho in (('iid_baseline', 0.0), ('ar1_rho_0.9_baseline', 0.9)):
        exceed_chi2 = exceed_hot = total = 0
        for _ in range(reps):
            Xb, C = _ar1(rng, n, k, rho)
            base = p2.fit_baseline(Xb, [f'm{j}' for j in range(k)], {})
            if base.cov is None:
                continue
            Lc = np.linalg.cholesky(C)
            Xt = (Lc @ rng.standard_normal((k, tests))).T      # new in-control points, same marginal distribution
            Z = (Xt - base.median) / base.scale
            for z in Z:
                d2, _, _ = p2._mahal(z, base.cov)
                exceed_chi2 += d2 > thr_chi2
                exceed_hot += d2 > thr_hot
                total += 1
        out[label] = {'nominal_rate': round(1 - p2.CHI2_Q, 4), 'observed_rate_chi2_threshold': round(exceed_chi2 / total, 4),
                      'observed_rate_hotelling_threshold': round(exceed_hot / total, 4), 'test_points': total}
    out['thresholds'] = {'chi2_0.995_k5': round(float(thr_chi2), 2), 'hotelling_prediction_n40_k5': round(float(thr_hot), 2)}
    out['setup'] = (f'{reps} baselines of n={n}, k={k}, equicorrelation 0.5, unit variance; robust covariance and '
                    'median/MAD standardisation exactly as app.phantom2.fit_baseline (floors disabled); '
                    f'{tests} new in-control points per baseline.')
    return out


def _block_indices(rng, n, block):
    idx = []
    while len(idx) < n:
        s = int(rng.integers(0, n - block + 1))
        idx.extend(range(s, s + block))
    return np.array(idx[:n])


def e2_bootstrap(reps=150, B=60, n=40, k=5, rho=0.9, block=8, seed=12):
    rng = np.random.default_rng(seed)
    z_test = np.full(k, 1.5)
    true_d2, iid_sd, blk_sd = [], [], []
    for _ in range(reps):
        Xb, _ = _ar1(rng, n, k, rho)
        base = p2.fit_baseline(Xb, [f'm{j}' for j in range(k)], {})
        if base.cov is None:
            continue
        true_d2.append(p2._mahal(z_test, base.cov)[0])
        for store, sampler in ((iid_sd, lambda: rng.integers(0, n, n)), (blk_sd, lambda: _block_indices(rng, n, block))):
            ds = []
            for _ in range(B):
                c = p2._robust_cov(base.Zb[sampler()])
                if c is not None:
                    ds.append(p2._mahal(z_test, c)[0])
            store.append(float(np.std(ds)) if len(ds) > 5 else np.nan)
    real = float(np.std(true_d2))
    return {'setup': f'AR(1) rho={rho}, n={n}, k={k}; fixed test vector z=1.5 on every metric; {reps} independent baselines; B={B}.',
            'real_sampling_sd_of_d2': round(real, 3),
            'mean_bootstrap_sd_iid': round(float(np.nanmean(iid_sd)), 3),
            'mean_bootstrap_sd_moving_block_8': round(float(np.nanmean(blk_sd)), 3),
            'ratio_iid_to_real': round(float(np.nanmean(iid_sd)) / real, 3),
            'ratio_block_to_real': round(float(np.nanmean(blk_sd)) / real, 3)}


def e3_gap_prewhitening(rho=0.95):
    # one metric, baseline-standardised values; 10 missing samples, then the signal is back at the same level
    a = np.array([[2.0]] * 5 + [[np.nan]] * 10 + [[2.0]])
    impl = p2._prewhitened(a, np.array([rho]))[-1, 0]
    raw_after_gap = 2.0      # what the docstring says is used "after a gap"
    lag_eff = 11
    proper = (2.0 - rho ** lag_eff * 2.0) / math.sqrt(1 - rho ** (2 * lag_eff))   # AR(1) with the correct lag
    return {'rho': rho, 'residual_implementation': round(float(impl), 3), 'residual_if_raw_value_after_gap': raw_after_gap,
            'residual_with_correct_lag_11': round(proper, 3),
            'note': 'The implementation treats the last value before the gap as lag 1. For a constant level the error is '
                    'small here, but for a level that moved during the gap the residual is inflated by 1/sqrt(1-rho^2).'}


def e4_zero_mad():
    from app.analytics import SCALE_FLOOR
    base = [60.0] * 20
    med = float(np.median(base)); mad = float(np.median(np.abs(np.array(base) - med)))
    z_floor = (61.0 - med) / max(1.4826 * mad, SCALE_FLOOR['heart_rate_bpm'])
    z_nofloor = (61.0 - med) / (1.4826 * mad) if mad else math.inf
    near = [60.0] * 19 + [60.1]
    mad2 = float(np.median(np.abs(np.array(near) - np.median(near))))
    return {'constant_baseline_mad': mad, 'z_for_+1_bpm_with_floor': round(z_floor, 3),
            'z_for_+1_bpm_without_floor': z_nofloor, 'near_constant_mad': mad2,
            'conclusion': 'The per-signal floor (2.8 bpm for HR) prevents unbounded z; the floor value is heuristic.'}


def e5_hrv_reference():
    from app.biosignals import rr_features
    out = {}
    # (a) alternating 800/820 ms, 400 beats → successive differences ±20 → RMSSD = 20 exactly
    rr = [800.0 if i % 2 == 0 else 820.0 for i in range(400)]
    rows, t = [], 0.0
    for v in rr:
        t += v / 1000; rows.append((t, v, True))
    r = rr_features(rows)
    out['alternating_800_820'] = {'rmssd_impl': r['rmssd_ms'], 'rmssd_expected': 20.0,
                                  'sdnn_impl': r['sdnn_ms'], 'sdnn_expected': round(float(np.std(rr, ddof=1)), 6)}
    # (b) random series, independent numpy formula
    rng = np.random.default_rng(5)
    rr = list(850 + np.cumsum(rng.normal(0, 4, 400)).clip(-150, 150))
    rows, t = [], 0.0
    for v in rr:
        t += v / 1000; rows.append((t, float(v), True))
    r = rr_features(rows)
    d = np.diff(rr)
    out['random_walk_series'] = {'rmssd_impl': r['rmssd_ms'], 'rmssd_numpy': float(np.sqrt(np.mean(d ** 2))),
                                 'sdnn_impl': r['sdnn_ms'], 'sdnn_numpy': float(np.std(rr, ddof=1))}
    # (c) one ectopic-like artefact (+40 %) must be rejected and its two differences must not enter RMSSD
    rr_art = [800.0 if i % 2 == 0 else 820.0 for i in range(400)]
    rr_art[201] = 1150.0
    rows, t = [], 0.0
    for v in rr_art:
        t += v / 1000; rows.append((t, v, True))
    r = rr_features(rows)
    out['single_artefact'] = {'rejected': r['rejected_intervals'], 'rmssd_impl': r['rmssd_ms'], 'rmssd_expected_without_artefact': 20.0}
    # (d) too short
    r = rr_features([(i * 0.8, 800.0, True) for i in range(50)])
    out['too_short_50_beats'] = {'sdnn': r['sdnn_ms'], 'rmssd': r['rmssd_ms'], 'quality': r['quality']}
    return out


def main(quick=False):
    res = {'E1': e1_mahalanobis_fpr(reps=40 if quick else 200, tests=200 if quick else 500),
           'E2': e2_bootstrap(reps=40 if quick else 150, B=30 if quick else 60),
           'E3': e3_gap_prewhitening(), 'E4': e4_zero_mad(), 'E5': e5_hrv_reference(),
           'data_class': 'SYNTHETIC test series (mathematical verification only)'}
    return res


if __name__ == '__main__':
    print(json.dumps(main('--quick' in sys.argv), indent=2, default=float))
