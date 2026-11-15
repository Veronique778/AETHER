"""AETHER 1.0 · B2/B3 — PHANTOM 2.0 noise and missing-data study (synthetic data only).

    python validation/phantom_study.py noise   --out validation/results_1_0      # B2
    python validation/phantom_study.py missing --out validation/results_1_0      # B3

Protocol (fixed before any validation or test result was looked at; written to protocol.json on every run)
---------------------------------------------------------------------------------------------------------
* Data: Mission Systems generator (educational-1.0), 3 crew, sample every 30 min, 2 days (2880 min), injected event
  at minute 1800 (ramp 360 min), personal baseline = first 1440 min of the same run (no events), monitoring window =
  minute ≥ 1440 (49 samples × 3 crew per run).
* Seed splits – none of them overlaps the seeds used in AETHER 0.9 (1–10 development, 101–130 held-out, 101–110 engine):
    development 1001–1010   exploration / root-cause analysis only (B2.2)
    calibration 2001–2030   nominal runs ('normal' template), thresholds fitted here (labels not needed)
    validation  3001–3020   model selection between candidates
    final_test  4001–4030   untouched; evaluated once, after the choice was frozen
* Labels (B4 audit, generator field `physiological_change`): positive = injected crew-level physiological change
  (strength ≥ 0.25). Clean negative = no injected change AND no shared-cabin exposure. Samples of crew members who are
  only exposed to a cabin change (environment / multifactor templates) are neither: they are scored separately
  (`exposed_flag_rate`) because the generator does change their physiology a little. The 0.9 label (`anomaly`) is
  also reported (`fpr_v09_labels`) so numbers stay comparable with VALIDATION_REPORT 0.9.
* Noise (B2): i.i.d. Gaussian added to every physiological reading of the whole run (baseline included),
  σ = level × metric floor, levels 0, 0.5, 1, 2, 3 (calibration uses 0, 1, 2 only → 0.5 and 3 test inter/extrapolation).
  This is on top of the engine's own AR(1) measurement noise (σ 0.2, φ 0.7).
* Metrics: precision, recall, F1, FPR per sample; false alerts per hour (alert episodes = maximal runs of flagged
  samples whose first sample is a clean negative, per clean-negative monitoring hour); detection delay = minutes from
  the first positive label to the first alert (per crew member with an event; missed events reported separately).
  Mean over seeds with a 95 % percentile bootstrap CI over seeds (seeds are independent replicates).
* Calibration target: per-sample FPR ≤ 2 % on nominal calibration runs at EVERY calibration noise level (minimax).
  OR-rules split the budget 1 % + 1 % (union bound).
* Selection rule (validation split): candidates whose worst-case FPR over noise levels ≤ 3 % are eligible; pick the
  highest mean F1 over (detection templates × noise levels); within 0.01 F1 prefer the lower median delay, then the
  simpler rule. If no eligible candidate beats Mahalanobis-only, Mahalanobis-only is chosen (spec B2.6).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from scipy.stats import chi2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'validation'))

import run_validation as rv  # noqa: E402
from app import phantom2 as p2, phantom2_engine as pe  # noqa: E402
from mission_systems.mission_lab.experiments import phantom_input  # noqa: E402

SPLITS = {'development': range(1001, 1011), 'calibration': range(2001, 2031),
          'validation': range(3001, 3021), 'validation_2': range(3101, 3121), 'final_test': range(4001, 4031)}
DETECTION = ['sleep_loss', 'fatigue_rise', 'pulse_shift', 'cognitive_decline', 'workload_rise', 'multifactor']
EVAL_TEMPLATES = DETECTION + ['environment', 'normal', 'noise']
NOISE_CAL = (0.0, 1.0, 2.0)
NOISE_EVAL = (0.0, 0.5, 1.0, 2.0, 3.0)
NOISE_STAGE2 = (0.0, 0.25, 0.5, 0.75, 1.0, 2.0, 3.0)   # stage 2 probes the regime boundary as well
NU_GRID = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
TARGET_FPR = 0.02
ELIGIBLE_FPR = 0.03
SAMPLE_MIN = 30
MONITOR_FROM = 1440
CUSUM_K = p2.CUSUM_K


# ---------------------------------------------------------------- data
def degrade(noise: float = 0.0, missing: float = 0.0, mode: str = 'random', seed: int = 0):
    """Payload transform. mode: random | dropout | channel | during_anomaly | baseline (B3.1)."""
    rng = np.random.default_rng(seed)

    def f(payload, truth=None):
        samples = payload['samples']
        by_crew: dict[int, list] = {}
        for s in samples:
            by_crew.setdefault(s['crew_id'], []).append(s)
        drop: set[tuple[str, str]] = set()
        if missing:
            for cid, rows in by_crew.items():
                rows.sort(key=lambda s: s['timestamp'])
                n = len(rows)
                if mode == 'random':
                    for s in rows:
                        drop |= {(s['sample_id'], r['metric']) for r in s['measurements'] if rng.random() < missing}
                elif mode == 'dropout':     # one contiguous outage of all sensors covering `missing` of the run
                    length = int(round(missing * n)); start = int(rng.integers(0, max(1, n - length + 1)))
                    drop |= {(s['sample_id'], r['metric']) for s in rows[start:start + length] for r in s['measurements']}
                elif mode == 'channel':     # whole channels missing for the entire run: round(missing × 7) channels
                    lost = set(rng.choice(pe.PHYS, size=int(round(missing * len(pe.PHYS))), replace=False))
                    drop |= {(s['sample_id'], r['metric']) for s in rows for r in s['measurements'] if r['metric'] in lost}
                elif mode == 'during_anomaly':   # readings missing only while the crew member has a labelled change
                    pos = {t['sample_id'] for t in truth if t.get('physiological_change')}
                    for s in rows:
                        if s['sample_id'] in pos:
                            drop |= {(s['sample_id'], r['metric']) for r in s['measurements'] if rng.random() < missing}
                elif mode == 'baseline':    # readings missing only in the baseline window
                    t0 = rows[0]['timestamp']
                    from datetime import datetime
                    for s in rows:
                        if (datetime.fromisoformat(s['timestamp']) - datetime.fromisoformat(t0)).total_seconds() / 60 < MONITOR_FROM:
                            drop |= {(s['sample_id'], r['metric']) for r in s['measurements'] if rng.random() < missing}
                else:
                    raise ValueError(mode)
        for s in samples:
            keep = []
            for r in s['measurements']:
                if (s['sample_id'], r['metric']) in drop:
                    continue
                if noise and r['metric'] in pe.FLOORS and r.get('value') is not None:
                    r = {**r, 'value': r['value'] + float(rng.normal(0, noise * pe.FLOORS[r['metric']]))}
                keep.append(r)
            s['measurements'] = keep
        return payload
    return f


def run_data(template: str, seed: int, transform=None):
    ds = rv.dataset(template, seed)
    payload = phantom_input(ds)
    if transform is not None:
        payload = transform(payload, ds['ground_truth'])
    keep = ('minute', 'anomaly', 'physiological_change', 'environment_exposure', 'crew_id')
    truth = {t['sample_id']: {k: t.get(k) for k in keep} for t in ds['ground_truth']}
    return payload, truth


# ---------------------------------------------------------------- statistics (thresholds applied afterwards)
def crew_stats(X: np.ndarray, base: p2.Baseline, direction: np.ndarray, covariance: str = 'complete', gap_aware: bool = False) -> dict:
    n, k = X.shape
    Z = (X - base.median) / base.scale
    A = Z * direction
    rho = base.rho if base.rho is not None else np.zeros(k)
    norm = np.sqrt(1 - rho ** 2)
    sig_e = math.sqrt(p2.EWMA_LAMBDA / (2 - p2.EWMA_LAMBDA))
    zmax = np.full(n, np.nan); cus = np.zeros((n, k)); ewm = np.full(n, np.nan); mlogp = np.full(n, np.nan)
    resid = np.full((n, k), np.nan); nobs = np.zeros(n, int)
    S = np.zeros(k); E = np.zeros(k); prev = np.full(k, np.nan)
    complete = p2._robust_cov(base.Zb)          # 0.9 behaviour (production fit_baseline now falls back to pairwise)
    cov = {'complete': complete, 'pairwise': pairwise_cov(base.Zb),
           'hybrid': complete if complete is not None else pairwise_cov(base.Zb)}[covariance]
    gap = np.zeros(k)
    for t in range(n):
        a = A[t]; valid = ~np.isnan(a); nobs[t] = int(valid.sum())
        if not valid.any():
            cus[t] = S; gap += 1; continue
        zmax[t] = np.nanmax(a)
        if gap_aware:   # AR(1) prediction after g missing steps: ρ^(g+1)·prev, innovation variance 1 − ρ^(2(g+1))
            r_g = rho ** (gap + 1)
            e = np.where(np.isnan(prev), a, (a - r_g * np.nan_to_num(prev)) / np.sqrt(np.maximum(1e-9, 1 - r_g ** 2)))
        else:
            e = np.where(np.isnan(prev), a, (a - rho * np.nan_to_num(prev)) / norm)
        gap = np.where(valid, 0, gap + 1)
        prev = np.where(valid, a, prev)
        resid[t] = np.where(valid, e, np.nan)
        E = np.where(valid, p2.EWMA_LAMBDA * np.nan_to_num(e) + (1 - p2.EWMA_LAMBDA) * E, E)
        ewm[t] = float(np.max(E) / sig_e)
        S = np.where(valid, np.maximum(0, S + np.nan_to_num(e) - CUSUM_K), S)
        cus[t] = S
        if cov is not None:
            d2, _, kk = p2._mahal(Z[t], cov)
            if d2 is not None:
                mlogp[t] = -math.log10(max(chi2.sf(d2, kk), 1e-300))
    # residual-vector statistics: CUSUM on standardised d² of prewhitened residuals, and Crosier's MCUSUM
    nb = len(base.Zb)
    Rb = resid[:nb] if nb <= n else None
    rcov = None
    if Rb is not None:
        rc = p2._robust_cov(Rb)
        rcov = {'complete': rc, 'pairwise': pairwise_cov(Rb), 'hybrid': rc if rc is not None else pairwise_cov(Rb)}[covariance]
    cd2 = np.full(n, np.nan); mcu = np.full(n, np.nan)
    if rcov is not None:
        Sm = 0.0; Sv = np.zeros(k); inv = np.linalg.pinv(rcov)
        for t in range(n):
            r = resid[t]
            if np.isnan(r).all():
                cd2[t] = Sm; mcu[t] = float(np.sqrt(max(0.0, Sv @ inv @ Sv))); continue
            d2, _, kk = p2._mahal(r, rcov)
            if d2 is not None:
                Sm = max(0.0, Sm + (d2 - kk) / math.sqrt(2 * kk) - CUSUM_K)
            cd2[t] = Sm
            x = Sv + np.nan_to_num(r)
            C = float(np.sqrt(max(0.0, x @ inv @ x)))
            Sv = np.zeros(k) if C <= CUSUM_K else x * (1 - CUSUM_K / C)
            mcu[t] = float(np.sqrt(max(0.0, Sv @ inv @ Sv)))
    srt = np.sort(cus, axis=1)
    return {'zscore': zmax, 'cusum': srt[:, -1], 'cusum_2ch': srt[:, -2], 'ewma': ewm, 'mahalanobis': mlogp,
            'cusum_d2': cd2, 'mcusum': mcu, 'n_observed': nobs, 'nu': noise_index(resid[:nb])}


def noise_index(Rb: np.ndarray) -> float:
    """Stage 2: data-quality index ν = median over channels of the robust SD of the baseline's prewhitened,
    standardised residuals. ≈0.1 when the floors dominate (clean engine data), →1 when measurement noise dominates."""
    sd = []
    for c in Rb.T:
        c = c[~np.isnan(c)]
        if len(c) >= 6:
            sd.append(1.4826 * float(np.median(np.abs(c - np.median(c)))))
    return float(np.median(sd)) if sd else float('nan')


def pairwise_cov(Zb: np.ndarray | None) -> np.ndarray | None:
    """B3: robust covariance from pairwise-complete baseline rows (Gnanadesikan–Kettenring with MAD scales),
    projected to the nearest positive-definite matrix and shrunk towards the identity like p2._robust_cov."""
    if Zb is None:
        return None
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
    return (1 - p2.SHRINK) * C + p2.SHRINK * np.eye(k)


def run_stats(payload: dict, covariance: str = 'complete', gap_aware: bool = False) -> dict:
    metrics, crews = pe._rows(payload, False)
    direction = np.array([pe.DIRECTION[m] for m in metrics], float)
    out = {}
    for cid, (samples, X) in crews.items():
        nb = sum(1 for s in samples if _minute(s, samples[0]) < MONITOR_FROM)
        base = p2.fit_baseline(X[:nb], metrics, pe.FLOORS)
        st = crew_stats(X, base, direction, covariance, gap_aware)
        out[cid] = {'samples': [{'sample_id': x['sample_id']} for x in samples], 'stats': st}   # ids only (memory)
    return out


def _minute(s, s0):
    from datetime import datetime
    return (datetime.fromisoformat(s['timestamp']) - datetime.fromisoformat(s0['timestamp'])).total_seconds() / 60


# ---------------------------------------------------------------- candidates (pre-registered)
def bonferroni_h(k_channels: int = 7, k: float = CUSUM_K, h0: float = p2.CUSUM_H) -> float:
    """h with k_channels × the in-control ARL of (k, h0), Siegmund's approximation ARL ≈ (e^{2kb}−2kb−1)/(2k²), b = h+1.166."""
    arl = lambda h: (math.exp(2 * k * (h + 1.166)) - 2 * k * (h + 1.166) - 1) / (2 * k * k)
    target = k_channels * arl(h0)
    lo, hi = h0, h0 + 20
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if arl(mid) < target else (lo, mid)
    return round((lo + hi) / 2, 3)


DEFAULTS = {'zscore': p2.Z_FLAG, 'cusum': p2.CUSUM_H, 'ewma': p2.EWMA_L,
            'mahalanobis': -math.log10(1 - p2.CHI2_Q), 'cusum_bonf': bonferroni_h()}
CANDIDATES = {
    # name: (components [(statistic, threshold source)], combination, persistence)
    'zscore (PHANTOM 1.0)': ([('zscore', 'default')], 'any', None),
    'mahalanobis (0.9)': ([('mahalanobis', 'default')], 'any', None),
    'cusum (0.9)': ([('cusum', 'default')], 'any', None),
    'ewma (0.9)': ([('ewma', 'default')], 'any', None),
    'phantom2 0.9 = mahalanobis OR cusum': ([('mahalanobis', 'default'), ('cusum', 'default')], 'any', None),
    'mahalanobis OR cusum, Bonferroni/Holm h': ([('mahalanobis', 'default'), ('cusum', 'cusum_bonf')], 'any', None),
    'phantom2 0.9 + persistence 2-of-3': ([('mahalanobis', 'default'), ('cusum', 'default')], 'any', (2, 3)),
    'zscore calibrated': ([('zscore', 'cal')], 'any', None),
    'mahalanobis calibrated': ([('mahalanobis', 'cal')], 'any', None),
    'cusum calibrated (max over channels)': ([('cusum', 'cal')], 'any', None),
    'cusum ≥2 channels calibrated': ([('cusum_2ch', 'cal')], 'any', None),
    'ewma calibrated': ([('ewma', 'cal')], 'any', None),
    'cusum on Mahalanobis d² calibrated': ([('cusum_d2', 'cal')], 'any', None),
    'MCUSUM (Crosier) calibrated': ([('mcusum', 'cal')], 'any', None),
    'mahalanobis OR cusum, calibrated': ([('mahalanobis', 'cal/2'), ('cusum', 'cal/2')], 'any', None),
}
SIMPLICITY = {name: len(comp) + (1 if pers else 0) + (0 if all(src == 'default' for _, src in comp) else .5)
              for name, (comp, _, pers) in CANDIDATES.items()}


ADAPTIVE = {   # stage 2 (designed on development seeds after stage-1 validation; ν* fitted on development)
    'adaptive: phantom2 0.9 | ewma calibrated': ('phantom2 0.9 = mahalanobis OR cusum', 'ewma calibrated'),
    'adaptive: phantom2 0.9 | mahalanobis OR cusum calibrated': ('phantom2 0.9 = mahalanobis OR cusum', 'mahalanobis OR cusum, calibrated'),
}
NU_STAR: dict[str, float] = {}


def flags_for(stats: dict, name: str, thresholds: dict) -> np.ndarray:
    if name in ADAPTIVE:
        low, high = ADAPTIVE[name]
        nu = stats['nu']
        use_high = not np.isfinite(nu) or nu >= thresholds.get(('nu*', name), NU_STAR.get(name, 0.5))
        return flags_for(stats, high if use_high else low, thresholds)
    comp, _, pers = CANDIDATES[name]
    any_valid = stats['n_observed'] > 0
    f = np.zeros(len(any_valid), bool)
    for stat, src in comp:
        thr = thresholds[(stat, src)]
        v = stats[stat]
        f |= np.where(np.isnan(v), False, v > thr if stat != 'zscore' else v >= thr)
    if pers:
        m, w = pers
        c = np.convolve(f.astype(int), np.ones(w, int))[:len(f)]
        f = c >= m
    return np.where(any_valid, f, False), any_valid


# ---------------------------------------------------------------- calibration
def calibrate(cal_runs: list[dict]) -> dict:
    """Minimax-FPR thresholds on nominal calibration runs; returns {(stat, src): threshold}."""
    th = {}
    for stat, v in DEFAULTS.items():
        th[(stat if stat != 'cusum_bonf' else 'cusum', 'default' if stat != 'cusum_bonf' else 'cusum_bonf')] = v
    stats_needed = {s for comp, _, _ in CANDIDATES.values() for s, src in comp if src.startswith('cal')}
    for stat in stats_needed:
        for src, target in (('cal', TARGET_FPR), ('cal/2', TARGET_FPR / 2)):
            per_noise = []
            for noise in NOISE_CAL:
                vals = np.concatenate([r['stats'][stat][r['monitor']] for r in cal_runs if r['noise'] == noise])
                N = len(vals); allowed = int(math.floor(target * N))
                v = np.sort(vals[~np.isnan(vals)])[::-1]
                per_noise.append(-np.inf if allowed >= len(v) else float(v[allowed]))
            th[(stat, src)] = max(per_noise)
    return th


# ---------------------------------------------------------------- scoring
def score_run(run: dict, truth: dict, name: str, thresholds: dict) -> dict:
    tp = fp = tn = fn = 0; fp09 = tn09 = 0; exp_f = exp_n = 0; episodes = 0; neg_hours = 0.0
    delays, missed = [], 0
    for cid, r in run.items():
        f, valid = flags_for(r['stats'], name, thresholds)
        rows = [(i, s, truth[s['sample_id']]) for i, s in enumerate(r['samples'])]
        rows = [(i, s, g) for i, s, g in rows if g['minute'] >= MONITOR_FROM]
        prev = False; onset = None; first = None
        for i, s, g in rows:
            pos = g['physiological_change']; clean = not pos and not g['environment_exposure']
            if g['anomaly'] is False:
                fp09 += bool(f[i]); tn09 += not f[i]
            if pos:
                tp += bool(f[i]); fn += not f[i]
                onset = g['minute'] if onset is None else onset
                if first is None and f[i]:
                    first = g['minute']
            elif clean:
                fp += bool(f[i]); tn += not f[i]; neg_hours += SAMPLE_MIN / 60
                if f[i] and not prev:
                    episodes += 1
            else:
                exp_f += bool(f[i]); exp_n += 1
            prev = bool(f[i])
        if onset is not None:
            if first is None:
                missed += 1
            else:
                delays.append(first - onset)
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    return {'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn, 'precision': prec, 'recall': rec,
            'f1': 2 * tp / (2 * tp + fp + fn) if (tp + fn) else None,
            'fpr': fp / (fp + tn) if fp + tn else None, 'fpr_v09_labels': fp09 / (fp09 + tn09) if fp09 + tn09 else None,
            'false_alerts_per_hour': episodes / neg_hours if neg_hours else None,
            'exposed_flag_rate': exp_f / exp_n if exp_n else None,
            'delays_min': delays, 'missed_events': missed}


def boot_ci(v: list[float], B: int = 2000, seed: int = 0):
    v = np.array([x for x in v if x is not None], float)
    if len(v) == 0:
        return None, None, None
    rng = np.random.default_rng(seed)
    means = v[rng.integers(0, len(v), (B, len(v)))].mean(1)
    return float(v.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def aggregate(rows: list[dict], keys: tuple) -> list[dict]:
    out = []
    groups = sorted({tuple(r[k] for k in keys) for r in rows}, key=str)
    for g in groups:
        sel = [r for r in rows if tuple(r[k] for k in keys) == g]
        rec = dict(zip(keys, g)); rec['n_runs'] = len(sel)
        for m in ('precision', 'recall', 'f1', 'fpr', 'fpr_v09_labels', 'false_alerts_per_hour', 'exposed_flag_rate'):
            mean, lo, hi = boot_ci([r[m] for r in sel])
            rec[m] = None if mean is None else round(mean, 4)
            rec[m + '_ci95'] = None if mean is None else [round(lo, 4), round(hi, 4)]
        d = [x for r in sel for x in r['delays_min']]
        ev = len(d) + sum(r['missed_events'] for r in sel)
        rec['median_delay_min'] = float(np.median(d)) if d else None
        rec['events_detected'] = f'{len(d)}/{ev}' if ev else None
        out.append(rec)
    return out


# ---------------------------------------------------------------- experiment drivers
def _one(job):
    t, s, c, covariance = job
    cov, gap = (covariance, False) if not isinstance(covariance, tuple) else covariance
    tr = degrade(seed=s * 1009 + hash_c(c), **{k: v for k, v in c.items() if k != 'label'})
    payload, truth = run_data(t, s, tr)
    st = run_stats(payload, cov, gap)
    return {'template': t, 'seed': s, 'condition': c['label'], **{k: v for k, v in c.items() if k != 'label'},
            'run': st, 'truth': truth}


def collect(split: str, conditions: list[dict], templates: list[str], covariance: str = 'complete', workers: int | None = None) -> list[dict]:
    """Deterministic: every job has its own seed, results come back in job order."""
    import os
    from concurrent.futures import ProcessPoolExecutor
    jobs = [(t, s, c, covariance) for t in templates for s in SPLITS[split] for c in conditions]
    workers = workers or min(8, os.cpu_count() or 1)
    if workers <= 1:
        return [_one(j) for j in jobs]
    with ProcessPoolExecutor(workers) as ex:
        return list(ex.map(_one, jobs, chunksize=4))


def hash_c(c: dict) -> int:
    return int(round(c.get('noise', 0) * 100)) * 7 + int(round(c.get('missing', 0) * 100)) * 13 + \
        ['random', 'dropout', 'channel', 'during_anomaly', 'baseline'].index(c.get('mode', 'random')) * 101


def cal_runs_from(runs: list[dict]) -> list[dict]:
    out = []
    for r in runs:
        for cid, x in r['run'].items():
            mon = np.array([r['truth'][s['sample_id']]['minute'] >= MONITOR_FROM for s in x['samples']])
            out.append({'noise': r['noise'], 'stats': x['stats'], 'monitor': mon})
    return out


def evaluate(runs: list[dict], thresholds: dict, names=None) -> list[dict]:
    rows = []
    for r in runs:
        for name in names or CANDIDATES:
            sc = score_run(r['run'], r['truth'], name, thresholds)
            rows.append({'candidate': name, 'template': r['template'], 'seed': r['seed'], 'condition': r['condition'], **sc})
    return rows


def select(val_rows: list[dict], names=None) -> dict:
    table = []
    for name in names or CANDIDATES:
        sel = [r for r in val_rows if r['candidate'] == name]
        fpr_by_cond = {}
        for c in sorted({r['condition'] for r in sel}):
            v = [r['fpr'] for r in sel if r['condition'] == c and r['fpr'] is not None]
            fpr_by_cond[c] = float(np.mean(v)) if v else None
        f1 = [r['f1'] for r in sel if r['template'] in DETECTION and r['f1'] is not None]
        d = [x for r in sel if r['template'] in DETECTION for x in r['delays_min']]
        table.append({'candidate': name, 'worst_fpr': max(v for v in fpr_by_cond.values() if v is not None),
                      'fpr_by_condition': fpr_by_cond, 'mean_f1_detection': float(np.mean(f1)) if f1 else 0.0,
                      'median_delay_min': float(np.median(d)) if d else None, 'simplicity': SIMPLICITY.get(name, 3.5)})
    eligible = [t for t in table if t['worst_fpr'] <= ELIGIBLE_FPR]
    ref = next(t for t in table if t['candidate'] == 'mahalanobis (0.9)')
    choice, rule = None, ''
    if eligible:
        best = max(t['mean_f1_detection'] for t in eligible)
        near = [t for t in eligible if t['mean_f1_detection'] >= best - 0.01]
        near.sort(key=lambda t: (t['median_delay_min'] if t['median_delay_min'] is not None else 1e9, t['simplicity']))
        choice = near[0]
        rule = 'highest mean F1 among eligible (worst-case FPR ≤ 3 %), ties within 0.01 → lower median delay → simpler'
    if choice is None or choice['mean_f1_detection'] <= ref['mean_f1_detection']:
        choice, rule = ref, 'no eligible candidate beats Mahalanobis-only → Mahalanobis-only (spec B2.6)'
    return {'table': sorted(table, key=lambda t: -t['mean_f1_detection']), 'chosen': choice['candidate'], 'rule': rule,
            'reference': ref['candidate']}


def write_csv(path: Path, rows: list[dict]):
    rows = [{k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in r.items()} for r in rows]
    with open(path, 'w', newline='', encoding='utf-8') as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in rows for k in r)), restval='')
            w.writeheader(); w.writerows(rows)


def protocol() -> dict:
    return {'splits': {k: f'{min(v)}-{max(v)}' for k, v in SPLITS.items()}, 'eval_templates': EVAL_TEMPLATES,
            'detection_templates': DETECTION, 'noise_calibration': NOISE_CAL, 'noise_eval': NOISE_EVAL,
            'target_fpr': TARGET_FPR, 'eligible_fpr': ELIGIBLE_FPR, 'sampling_minutes': SAMPLE_MIN,
            'signal_dimensions': pe.PHYS, 'run_minutes': rv.PROTOCOL['duration_minutes'], 'event_minute': rv.PROTOCOL['event_minute'],
            'event_ramp_minutes': 360, 'event_duration_minutes': rv.PROTOCOL['duration_minutes'] - rv.PROTOCOL['event_minute'],
            'baseline_minutes': MONITOR_FROM, 'noise_distribution': 'i.i.d. Gaussian, sigma = level x metric floor, added to every reading incl. baseline; '
            'engine AR(1) noise sigma 0.2, phi 0.7 underneath', 'floors': {m: pe.FLOORS[m] for m in pe.PHYS},
            'labels': 'positive = generator physiological_change; clean negative = no change and no cabin exposure',
            'candidates': {k: {'components': v[0], 'combination': v[1], 'persistence': v[2]} for k, v in CANDIDATES.items()},
            'defaults': DEFAULTS, 'selection_rule': select.__doc__ or 'see module docstring'}


def snr_table(runs: list[dict]) -> dict:
    """Empirical SNR per detection template: mean unfavourable z of positives minus clean negatives, over the SD of the
    clean-negative z (pooled over channels' max) – a descriptive number for B2.1, not used by any detector."""
    out = {}
    for t in DETECTION:
        for c in sorted({r['condition'] for r in runs}):
            pos, neg = [], []
            for r in runs:
                if r['template'] != t or r['condition'] != c:
                    continue
                for cid, x in r['run'].items():
                    for i, s in enumerate(x['samples']):
                        g = r['truth'][s['sample_id']]; z = x['stats']['zscore'][i]
                        if g['minute'] < MONITOR_FROM or np.isnan(z):
                            continue
                        if g['physiological_change']:
                            pos.append(z)
                        elif not g['environment_exposure']:
                            neg.append(z)
            if pos and neg and np.std(neg) > 0:
                out[f'{t} / {c}'] = round(float((np.mean(pos) - np.mean(neg)) / np.std(neg)), 2)
    return out


def design_nu(dev_rows: list[dict], name: str) -> dict:
    """Stage 2 design on development seeds: ν* maximising mean F1 subject to worst-case FPR ≤ TARGET_FPR."""
    grid = []
    for nu in NU_GRID:
        rows = [r for r in dev_rows if r['candidate'] == f'{name}@{nu}']
        fpr = {}
        for c in sorted({r['condition'] for r in rows}):
            v = [r['fpr'] for r in rows if r['condition'] == c and r['fpr'] is not None]
            fpr[c] = float(np.mean(v)) if v else 0.0
        f1 = [r['f1'] for r in rows if r['template'] in DETECTION and r['f1'] is not None]
        grid.append({'nu_star': nu, 'worst_fpr': max(fpr.values()), 'mean_f1': float(np.mean(f1))})
    ok = [g for g in grid if g['worst_fpr'] <= TARGET_FPR]
    # fallback: lowest worst-case FPR (to 0.1 pp), ties → highest mean F1  (a first version broke ties by grid order;
    # fixed before the final test was looked at – see b2_protocol.json disclosure)
    best = max(ok, key=lambda g: g['mean_f1']) if ok else min(grid, key=lambda g: (round(g['worst_fpr'], 3), -g['mean_f1']))
    return {'grid': grid, 'nu_star': best['nu_star'],
            'rule': 'max mean F1 s.t. worst FPR ≤ 2 %' if ok else 'no ν* meets 2 % → lowest worst FPR, ties → highest F1'}


def evaluate_adaptive_grid(runs, thresholds, name):
    rows = []
    for nu in NU_GRID:
        th = {**thresholds, ('nu*', name): nu}
        for r in runs:
            sc = score_run(r['run'], r['truth'], name, th)
            rows.append({'candidate': f'{name}@{nu}', 'template': r['template'], 'seed': r['seed'], 'condition': r['condition'], **sc})
    return rows


def noise_study(out: Path):
    """Two-stage protocol (see module docstring + DISCLOSURE below). Writes b2_* files."""
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    (out / 'b2_protocol.json').write_text(json.dumps({**protocol(), 'stage2': {
        'adaptive_candidates': ADAPTIVE, 'nu_grid': NU_GRID, 'noise_stage2': NOISE_STAGE2,
        'disclosure': 'Stage 2 was added after the stage-1 validation showed that minimax-calibrated thresholds lose recall '
                      'at noise 0 (the application default). ν* is fitted on development seeds 1001-1010 only; stage-2 '
                      'selection uses fresh seeds 3101-3120; the final test (4001-4030) was not examined before both '
                      'stages were frozen. The ν* fallback tie-break (grid order → highest F1) was corrected once, '
                      'before the final test was examined; the earlier partial run was discarded unread.'}}, indent=1, default=str), encoding='utf-8')
    # ---- calibration (nominal runs only)
    cal = collect('calibration', [{'label': f'noise {n}', 'noise': n} for n in NOISE_CAL], ['normal'])
    thresholds = calibrate(cal_runs_from(cal))
    th_out = {f'{k[0]}|{k[1]}': (None if v == -np.inf else round(v, 4)) for k, v in thresholds.items()}
    # ---- stage 1: pre-registered candidates, validation seeds 3001-3020
    val = collect('validation', [{'label': f'noise {n}', 'noise': n} for n in NOISE_EVAL], EVAL_TEMPLATES)
    vrows = evaluate(val, thresholds)
    stage1 = select(vrows)
    write_csv(out / 'b2_validation_runs.csv', [{k: v for k, v in r.items() if k != 'delays_min'} for r in vrows])
    write_csv(out / 'b2_validation_summary.csv', aggregate(vrows, ('candidate', 'condition')))
    del val
    # ---- stage 2 design: ν* on development seeds
    conds2 = [{'label': f'noise {n}', 'noise': n} for n in NOISE_STAGE2]
    dev = collect('development', conds2, EVAL_TEMPLATES)
    design = {}
    for name in ADAPTIVE:
        design[name] = design_nu(evaluate_adaptive_grid(dev, thresholds, name), name)
        thresholds[('nu*', name)] = design[name]['nu_star']; NU_STAR[name] = design[name]['nu_star']
        th_out[f'nu*|{name}'] = design[name]['nu_star']
    del dev
    (out / 'b2_thresholds.json').write_text(json.dumps(th_out, indent=1), encoding='utf-8')
    # ---- stage 2 selection on fresh validation seeds 3101-3120
    names2 = [stage1['chosen'], 'mahalanobis (0.9)', 'phantom2 0.9 = mahalanobis OR cusum', *ADAPTIVE]
    names2 = list(dict.fromkeys(names2))
    val2 = collect('validation_2', conds2, EVAL_TEMPLATES)
    v2rows = evaluate(val2, thresholds, names2)
    stage2 = select(v2rows, names2)
    write_csv(out / 'b2_validation2_summary.csv', aggregate(v2rows, ('candidate', 'condition')))
    del val2
    choice = {'stage1': stage1, 'stage2_design': design, 'stage2': stage2, 'chosen': stage2['chosen']}
    (out / 'b2_selection.json').write_text(json.dumps(choice, indent=1), encoding='utf-8')
    # ---- frozen: final test (untouched seeds), every candidate reported
    test = collect('final_test', conds2, EVAL_TEMPLATES)
    all_names = list(CANDIDATES) + list(ADAPTIVE)
    trows = evaluate(test, thresholds, all_names)
    write_csv(out / 'b2_test_runs.csv', [{k: v for k, v in r.items() if k != 'delays_min'} for r in trows])
    summ = aggregate(trows, ('candidate', 'condition'))
    write_csv(out / 'b2_test_summary.csv', summ)
    focus = (choice['chosen'], 'mahalanobis (0.9)', 'phantom2 0.9 = mahalanobis OR cusum', stage1['chosen'])
    write_csv(out / 'b2_test_by_template.csv', aggregate([r for r in trows if r['candidate'] in focus], ('candidate', 'template', 'condition')))
    overall = aggregate([{**r, 'all': 'all conditions'} for r in trows if r['template'] in DETECTION or r['template'] == 'normal'], ('candidate', 'all'))
    result = {'protocol': protocol(), 'thresholds': th_out, 'selection': choice, 'final_test_summary': summ,
              'final_test_overall': overall, 'snr_final_test': snr_table(test), 'runtime_s': round(time.time() - t0, 1)}
    (out / 'b2_results.json').write_text(json.dumps(result, indent=1, default=str), encoding='utf-8')
    print('B2 done in', result['runtime_s'], 's; stage 1:', stage1['chosen'], '| stage 2 (final):', choice['chosen'])
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('study', choices=['noise', 'missing'])
    ap.add_argument('--out', default=str(ROOT / 'validation' / 'results_1_0'))
    a = ap.parse_args()
    if a.study == 'noise':
        noise_study(Path(a.out))
    else:
        from missing_study import missing_study   # noqa: E402  (B3, separate module)
        missing_study(Path(a.out))
