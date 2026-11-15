"""PHANTOM 2.0 – multivariate, adaptive and sequential deviation detectors (AETHER 0.9).

PHANTOM 1.0 (app.analytics: robust z-score against a fixed personal baseline, flag at z >= 2 in the
unfavourable direction) is kept unchanged as the reference. This module adds, on the SAME inputs:

  ewma         EWMA control chart on baseline-standardised values (Roberts 1959; Lucas & Saccucci 1990):
               E_t = λ z_t + (1-λ) E_{t-1}; alarm when the unfavourable E_t > L·σ_E, σ_E = sqrt(λ/(2-λ)).
  adaptive     robust z against an ADAPTIVE baseline: the location follows an EWMA of in-control values
               and is frozen while the sample is flagged (protects against learning the anomaly).
  cusum        one-sided tabular CUSUM per metric on standardised values (Page 1954): S_t = max(0, S_{t-1} + z_t - k),
               alarm when S_t > h. Detects persistent small shifts; reports the estimated change start.
  mahalanobis  multivariate distance with a robust covariance (MCD-style concentration steps, Rousseeuw &
               Van Driessen 1999) and shrinkage towards the identity (the baseline is short); missing metrics
               are dropped and the χ² threshold uses the number of observed metrics.
  phantom2     PHANTOM 2.0 decision. AETHER 1.0 (spec B2, validation/phantom_study.py): noise-adaptive –
               * clean regime (baseline noise index ν < NU_STAR): mahalanobis OR prewhitened-CUSUM (the 0.9 rule);
               * noisy regime (ν ≥ NU_STAR or ν unknown): EWMA chart with a calibrated limit EWMA_L_NOISY.
               ν = median over metrics of the robust SD of the baseline's prewhitened standardised residuals
               (≈ 0.1 when the scale floors dominate, → 1 when measurement noise dominates). Thresholds were fitted on
               nominal calibration runs (seeds 2001–2030), ν* on development seeds, the rule was selected on fresh
               validation seeds and then tested once on untouched seeds (VALIDATION_REPORT_1_0.md). The 0.9 rule is
               kept as `phantom2_v09`: under added noise its per-channel CUSUM raises false alarms (multiple comparisons).
               The calibration applies to Mission Systems engine data; the daily AETHER record keeps the 0.9 rule.

EWMA and CUSUM assume independent samples. Engine series are autocorrelated (AR noise, rolling daily indicators),
which produced 11–28 % false alarms on development seeds; both charts therefore run on AR(1)-prewhitened
residuals e_t = (z_t − ρ z_{t−1}) / sqrt(1 − ρ²), ρ estimated per metric from the baseline window
(residual control charts, Alwan & Roberts 1988).

Every multivariate result carries:
  * attribution – share of the distance contributed by each metric, c_i = z_i (Σ⁻¹ z)_i / d²;
  * uncertainty – bootstrap over the baseline window: flag probability and a 90 % interval of d²;
  * next-best measurement – for missing metrics, the probability that measuring it would change the decision
    (Gaussian conditioning on the observed metrics, Monte Carlo).

Missing data (1.0, spec B3): if too few complete baseline rows exist for the robust covariance, a pairwise robust
covariance (Gnanadesikan–Kettenring with MAD scales, projected to positive definite, same shrinkage) is used instead of
silently disabling the multivariate test; every sample gets a `state` – 'flag', 'no_flag' or 'insufficient_data'
(fewer than MIN_FEATURES observed metrics and no alarm): missing data is never reported as 'no anomaly'.

Limitations: thresholds are conventional (χ² 0.995, CUSUM k = 0.5, h = 5, EWMA λ = 0.2, L = 3) or calibrated on
synthetic engine data (EWMA_L_NOISY, NU_STAR), not fitted to astronaut data; a short baseline gives an imprecise
covariance; all evaluation in AETHER uses synthetic data.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.stats import chi2

CHI2_Q = 0.995
CUSUM_K, CUSUM_H = 0.5, 5.0
EWMA_LAMBDA, EWMA_L = 0.2, 3.0
ADAPT_LAMBDA = 0.05
SHRINK = 0.25
Z_FLAG = 2.0  # PHANTOM 1.0 threshold (app.analytics.FLAG_Z)
# 1.0 noise-adaptive decision (validation/results_1_0/b2_thresholds.json): EWMA limit calibrated to ≤ 2 % false samples
# on nominal calibration runs at noise 0 / 1 / 2 × floor; regime switch ν* chosen on development seeds.
EWMA_L_NOISY = 3.5597
NU_STAR = 0.6
MIN_FEATURES = 2
DETECTORS = ('zscore', 'ewma', 'adaptive', 'cusum', 'mahalanobis', 'phantom2', 'phantom2_v09')
DECISION_RULES = ('adaptive_1_0', 'v09')

REFERENCES = [
    'Page, E. S. (1954). Continuous inspection schemes. Biometrika 41(1/2), 100–115.',
    'Roberts, S. W. (1959). Control chart tests based on geometric moving averages. Technometrics 1(3), 239–250.',
    'Lucas, J. M. & Saccucci, M. S. (1990). Exponentially weighted moving average control schemes. Technometrics 32(1), 1–12.',
    'Rousseeuw, P. J. & Van Driessen, K. (1999). A fast algorithm for the minimum covariance determinant estimator. Technometrics 41(3), 212–223.',
    'Alwan, L. C. & Roberts, H. V. (1988). Time-series modeling for statistical process control. J. Bus. Econ. Stat. 6(1), 87–95.',
    'Leys, C. et al. (2013). Detecting outliers: do not use standard deviation around the mean, use absolute deviation around the median. J. Exp. Soc. Psychol. 49(4), 764–766.',
]


@dataclass
class Baseline:
    metrics: list[str]
    median: np.ndarray
    scale: np.ndarray
    cov: np.ndarray | None          # robust covariance of standardised baseline vectors (k×k)
    n: int
    rho: np.ndarray = field(repr=False, default=None)  # lag-1 autocorrelation per metric (baseline)
    Zb: np.ndarray = field(repr=False, default=None)  # standardised baseline rows (for bootstrap)
    nu: float = float('nan')        # 1.0 noise index of the baseline (see module docstring)
    cov_method: str = 'complete'    # 'complete' | 'pairwise' | 'none'


def _robust_loc_scale(col: np.ndarray, floor: float):
    v = col[~np.isnan(col)]
    if len(v) < 3:
        return np.nan, np.nan
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med)))
    return med, max(1.4826 * mad, floor)


def _robust_cov(Z: np.ndarray, iters: int = 10) -> np.ndarray | None:
    """Concentration-step robust covariance (pairwise-complete rows), shrunk towards the identity."""
    rows = Z[~np.isnan(Z).any(axis=1)]
    n, k = rows.shape if rows.ndim == 2 else (0, Z.shape[1])
    if n < max(6, k // 2 + 3):
        return None
    h = max(k + 1, int(math.ceil(0.75 * n)))
    subset = rows
    for _ in range(iters):
        mu = subset.mean(axis=0)
        S = np.cov(subset, rowvar=False) + 1e-6 * np.eye(k)
        S = (1 - SHRINK) * S + SHRINK * np.diag(np.diag(S)).mean() * np.eye(k)
        inv = np.linalg.pinv(S)
        d = np.einsum('ij,jk,ik->i', rows - mu, inv, rows - mu)
        new = rows[np.argsort(d)[:h]]
        if new.shape == subset.shape and np.allclose(new, subset):
            break
        subset = new
    S = np.cov(subset, rowvar=False)
    # consistency factor for the trimmed covariance (χ² quantile ratio), then shrinkage towards the identity
    c = (h / n) / chi2.cdf(chi2.ppf(h / n, k), k + 2) if h < n else 1.0
    S = c * S
    return (1 - SHRINK) * S + SHRINK * np.eye(k)


def pairwise_cov(Zb: np.ndarray) -> np.ndarray | None:
    """Robust covariance from pairwise-complete rows (Gnanadesikan & Kettenring 1972, MAD scales), projected to the
    nearest positive-definite matrix and shrunk towards the identity like _robust_cov. Used when too few complete rows."""
    k = Zb.shape[1]

    def mad(v):
        v = v[~np.isnan(v)]
        return 1.4826 * float(np.median(np.abs(v - np.median(v)))) if len(v) >= 6 else np.nan
    s = np.array([mad(Zb[:, j]) for j in range(k)])
    if np.isnan(s).sum() > k - 2:
        return None
    s = np.where(np.isnan(s) | (s <= 0), 1.0, s)
    R = np.eye(k)
    for i in range(k):
        for j in range(i + 1, k):
            ok = ~(np.isnan(Zb[:, i]) | np.isnan(Zb[:, j]))
            if ok.sum() < 6:
                continue
            u, v = Zb[ok, i] / s[i], Zb[ok, j] / s[j]
            a, b = mad(u + v) ** 2, mad(u - v) ** 2
            if np.isfinite(a) and np.isfinite(b) and a + b > 0:
                R[i, j] = R[j, i] = float(np.clip((a - b) / (a + b), -.95, .95))
    w, V = np.linalg.eigh(R)
    R = (V * np.clip(w, 1e-3, None)) @ V.T
    C = R * np.outer(s, s)
    return (1 - SHRINK) * C + SHRINK * np.eye(k)


def _prewhitened(A: np.ndarray, rho: np.ndarray) -> np.ndarray:
    """AR(1) residuals with exactly the recursion of run_detectors (first value / no history: the raw value)."""
    norm = np.sqrt(1 - rho ** 2)
    prev = np.full(A.shape[1], np.nan)
    out = np.full(A.shape, np.nan)
    for t, a in enumerate(A):
        valid = ~np.isnan(a)
        if not valid.any():
            continue
        e = np.where(np.isnan(prev), a, (a - rho * np.nan_to_num(prev)) / norm)
        out[t] = np.where(valid, e, np.nan)
        prev = np.where(valid, a, prev)
    return out


def noise_index(Zb: np.ndarray, rho: np.ndarray) -> float:
    sd = []
    for c in _prewhitened(Zb, rho).T:
        c = c[~np.isnan(c)]
        if len(c) >= 6:
            sd.append(1.4826 * float(np.median(np.abs(c - np.median(c)))))
    return float(np.median(sd)) if sd else float('nan')


def fit_baseline(Xb: np.ndarray, metrics: list[str], floors: dict[str, float]) -> Baseline:
    med = np.empty(len(metrics)); scale = np.empty(len(metrics))
    for j, m in enumerate(metrics):
        med[j], scale[j] = _robust_loc_scale(Xb[:, j], floors.get(m, 1e-6))
    Zb = (Xb - med) / scale
    rho = np.zeros(len(metrics))
    for j in range(len(metrics)):
        a, b = Zb[:-1, j], Zb[1:, j]
        ok = ~(np.isnan(a) | np.isnan(b))
        if ok.sum() >= 5 and np.std(a[ok]) > 0 and np.std(b[ok]) > 0:
            r = float(np.corrcoef(a[ok], b[ok])[0, 1])
            rho[j] = float(np.clip(r, 0, .95)) if np.isfinite(r) else 0.0
    cov, method = _robust_cov(Zb), 'complete'
    if cov is None:
        cov = pairwise_cov(Zb)
        method = 'pairwise' if cov is not None else 'none'
    return Baseline(metrics, med, scale, cov, len(Xb), Zb=Zb, rho=rho, nu=noise_index(Zb, rho), cov_method=method)


def _mahal(z: np.ndarray, cov: np.ndarray):
    """d², contributions and df for one standardised vector with NaNs (dropped)."""
    obs = ~np.isnan(z)
    k = int(obs.sum())
    if k < 2:
        return None, None, k
    zo = z[obs]; So = cov[np.ix_(obs, obs)]
    w = np.linalg.solve(So, zo)
    d2 = float(zo @ w)
    contrib = np.full(len(z), np.nan)
    contrib[obs] = zo * w / d2 if d2 > 1e-12 else 0
    return d2, contrib, k


def next_best_measurement(z: np.ndarray, cov: np.ndarray, metrics: list[str], rng: np.random.Generator, draws: int = 300):
    """For each missing metric: probability that measuring it flips the multivariate decision."""
    obs = ~np.isnan(z)
    if obs.sum() < 1 or obs.all():
        return []
    d2, _, k = _mahal(z, cov)
    current = None if d2 is None else d2 > chi2.ppf(CHI2_Q, k)
    out = []
    zo = z[obs]; Soo = cov[np.ix_(obs, obs)]; inv = np.linalg.pinv(Soo)
    for j in np.where(~obs)[0]:
        s_mo = cov[j, obs]
        mu = float(s_mo @ inv @ zo)
        var = max(1e-9, float(cov[j, j] - s_mo @ inv @ s_mo))
        samples = rng.normal(mu, math.sqrt(var), draws)
        flips = 0
        for s in samples:
            zz = z.copy(); zz[j] = s
            d, _, kk = _mahal(zz, cov)
            flag = d is not None and d > chi2.ppf(CHI2_Q, kk)
            flips += int(current is None or flag != current)
        out.append({'metric': metrics[j], 'p_decision_change': round(flips / draws, 3),
                    'expected_z': round(mu, 2), 'conditional_sd': round(math.sqrt(var), 2)})
    return sorted(out, key=lambda r: -r['p_decision_change'])


def regime(base: Baseline) -> str:
    return 'clean' if np.isfinite(base.nu) and base.nu < NU_STAR else 'noisy'


def run_detectors(X: np.ndarray, base: Baseline, direction: np.ndarray, *, bootstrap: int = 0,
                  rng: np.random.Generator | None = None, explain: bool = False, prewhiten: bool = True,
                  decision: str = 'adaptive_1_0') -> dict:
    """Apply all detectors to rows of X (n×k, NaN = missing). Returns per-detector flag arrays (None = abstain),
    per-sample `states` ('flag' | 'no_flag' | 'insufficient_data') of the PHANTOM 2.0 decision and the regime."""
    if decision not in DECISION_RULES:
        raise ValueError('Unknown PHANTOM 2.0 decision rule')
    rng = rng or np.random.default_rng(0)
    n, k = X.shape
    noisy = decision == 'adaptive_1_0' and regime(base) == 'noisy'
    states: list[str] = []
    Z = (X - base.median) / base.scale
    A = Z * direction                       # unfavourable-direction z (positive = worse)
    out: dict[str, list] = {d: [] for d in DETECTORS}
    details = []
    E = np.zeros(k); S = np.zeros(k); loc = base.median.copy()
    rho = base.rho if (base.rho is not None and prewhiten) else np.zeros(k)
    prev = np.full(k, np.nan)
    norm = np.sqrt(1 - rho ** 2)
    sig_e = math.sqrt(EWMA_LAMBDA / (2 - EWMA_LAMBDA))
    thr_cache: dict[int, float] = {}
    cusum_start = [None] * k
    for t in range(n):
        a, z = A[t], Z[t]
        valid = ~np.isnan(a)
        if not valid.any():
            for d in DETECTORS:
                out[d].append(None)
            details.append(None)
            states.append('insufficient_data')
            continue
        # PHANTOM 1.0 reference
        out['zscore'].append(bool(np.nanmax(a) >= Z_FLAG))
        # AR(1)-prewhitened residual (first sample / after a gap: the raw standardised value)
        e = np.where(np.isnan(prev), a, (a - rho * np.nan_to_num(prev)) / norm)
        prev = np.where(valid, a, prev)
        # EWMA control chart (missing metrics keep their previous statistic)
        E = np.where(valid, EWMA_LAMBDA * np.nan_to_num(e) + (1 - EWMA_LAMBDA) * E, E)
        out['ewma'].append(bool((E > EWMA_L * sig_e).any()))
        ewma_noisy = bool((E > EWMA_L_NOISY * sig_e).any())
        # adaptive baseline: location follows in-control values, frozen while flagged
        ra = direction * (X[t] - loc) / base.scale
        flag_a = bool(np.nanmax(np.where(valid, ra, -np.inf)) >= Z_FLAG)
        out['adaptive'].append(flag_a)
        if not flag_a:
            loc = np.where(valid, (1 - ADAPT_LAMBDA) * loc + ADAPT_LAMBDA * np.nan_to_num(X[t]), loc)
        # CUSUM
        S_new = np.where(valid, np.maximum(0, S + np.nan_to_num(e) - CUSUM_K), S)
        for j in range(k):
            if S[j] == 0 and S_new[j] > 0:
                cusum_start[j] = t
            if S_new[j] == 0:
                cusum_start[j] = None
        S = S_new
        alarm = S > CUSUM_H
        out['cusum'].append(bool(alarm.any()))
        # Mahalanobis
        flag_m = None; info = None
        if base.cov is not None:
            d2, contrib, kk = _mahal(z, base.cov)
            if d2 is not None:
                thr = thr_cache.setdefault(kk, float(chi2.ppf(CHI2_Q, kk)))
                flag_m = d2 > thr
                if explain or bootstrap:
                    info = {'d2': round(d2, 2), 'threshold': round(thr, 2), 'df': kk,
                            'attribution': {base.metrics[j]: round(float(contrib[j]), 3) for j in range(k) if not np.isnan(contrib[j])}}
        out['mahalanobis'].append(flag_m)
        v09 = bool(flag_m) or bool(alarm.any())
        out['phantom2_v09'].append(v09)
        final = ewma_noisy if noisy else v09
        out['phantom2'].append(final)
        states.append('flag' if final else ('insufficient_data' if int(valid.sum()) < MIN_FEATURES else 'no_flag'))
        if explain or bootstrap:
            info = info or {}
            info['regime'] = {'nu': None if not np.isfinite(base.nu) else round(base.nu, 3), 'regime': 'noisy' if noisy else 'clean',
                              'rule': 'EWMA (calibrated L)' if noisy else 'Mahalanobis OR CUSUM', 'observed_metrics': int(valid.sum())}
            info['cusum'] = {base.metrics[j]: {'S': round(float(S[j]), 2), 'alarm': bool(alarm[j]), 'start_index': cusum_start[j]} for j in range(k)}
            info['z'] = {base.metrics[j]: round(float(a[j]), 2) for j in range(k) if not np.isnan(a[j])}
        details.append(info)
    if bootstrap and base.cov is not None:
        _bootstrap(Z, base, details, out, bootstrap, rng)
    return {'flags': out, 'details': details, 'states': states,
            'regime': {'decision_rule': decision, 'nu': None if not np.isfinite(base.nu) else round(base.nu, 3),
                       'regime': 'noisy' if noisy else 'clean', 'nu_star': NU_STAR, 'ewma_l_noisy': EWMA_L_NOISY,
                       'covariance': base.cov_method}}


def _bootstrap(Z: np.ndarray, base: Baseline, details: list, out: dict, B: int, rng: np.random.Generator):
    """Resample the baseline window, refit the robust covariance, re-score every sample."""
    covs = []
    Zb = base.Zb
    for _ in range(B):
        idx = rng.integers(0, len(Zb), len(Zb))
        c = _robust_cov(Zb[idx])
        if c is not None:
            covs.append(c)
    if not covs:
        return
    for t, info in enumerate(details):
        if info is None or 'd2' not in info:
            continue
        ds, flags = [], 0
        for c in covs:
            d2, _, kk = _mahal(Z[t], c)
            ds.append(d2); flags += int(d2 > chi2.ppf(CHI2_Q, kk))
        info['uncertainty'] = {'flag_probability': round(flags / len(covs), 3),
                               'd2_interval_90': [round(float(np.percentile(ds, 5)), 2), round(float(np.percentile(ds, 95)), 2)],
                               'bootstrap_replicates': len(covs)}


def confusion(pred: list, truth: list[bool]) -> dict:
    tp = fp = tn = fn = ab = 0
    for p, y in zip(pred, truth):
        if p is None:
            ab += 1
        d = p is True
        tp += d and y; fp += d and not y; fn += (not d) and y; tn += (not d) and (not y)
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    # 1.5.1 (audit D5): abstentions are counted as negatives in tn/fn above (unchanged, for comparability with the 1.0
    # reports). The *_decided rates use only samples on which the detector actually decided.
    dec = [(p, y) for p, y in zip(pred, truth) if p is not None]
    d_tp = sum(p and y for p, y in dec); d_fp = sum(p and not y for p, y in dec)
    d_tn = sum((not p) and (not y) for p, y in dec); d_fn = sum((not p) and y for p, y in dec)
    return {'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn, 'precision': prec, 'recall': rec,
            'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
            'fpr': fp / (fp + tn) if fp + tn else None, 'abstained': ab,
            'decided': len(dec), 'abstention_rate': ab / len(pred) if pred else None,
            'fpr_decided': d_fp / (d_fp + d_tn) if d_fp + d_tn else None,
            'recall_decided': d_tp / (d_tp + d_fn) if d_tp + d_fn else None,
            'fnr_decided': d_fn / (d_tp + d_fn) if d_tp + d_fn else None,
            'abstention_policy': 'tn/fn/fpr/recall count abstentions as negatives; *_decided exclude them'}
