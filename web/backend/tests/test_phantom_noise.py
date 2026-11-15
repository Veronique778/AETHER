"""AETHER 1.0 · B2/B3: production PHANTOM 2.0 == the rule selected by validation/phantom_study.py."""
import copy
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from app import phantom2 as p2, phantom2_engine as pe

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'validation' / 'results_1_0'
sys.path.insert(0, str(ROOT / 'validation'))


def thresholds():
    return {tuple(k.split('|', 1)): (-np.inf if v is None else v) for k, v in json.loads((RESULTS / 'b2_thresholds.json').read_text()).items()}


def test_production_constants_match_the_study():
    th = thresholds()
    sel = json.loads((RESULTS / 'b2_selection.json').read_text())
    assert sel['chosen'] == 'adaptive: phantom2 0.9 | ewma calibrated'
    assert p2.EWMA_L_NOISY == pytest.approx(round(th[('ewma', 'cal')], 4))
    assert p2.NU_STAR == th[('nu*', sel['chosen'])]


@pytest.mark.parametrize('noise', [0.0, 0.75, 2.0])
def test_production_flags_equal_study_flags(noise):
    import phantom_study as ps
    th = thresholds()
    name = 'adaptive: phantom2 0.9 | ewma calibrated'
    for template in ('multifactor', 'pulse_shift', 'normal'):
        payload, _ = ps.run_data(template, 1001, ps.degrade(noise=noise, seed=7))
        ref = pe.detect(copy.deepcopy(payload), baseline_minutes=1440)
        for cid, x in ps.run_stats(payload).items():
            f, _ = ps.flags_for(x['stats'], name, th)
            assert list(f) == [bool(ref['flags']['phantom2'][s['sample_id']]) for s in x['samples']]
            assert ref['regimes'][cid]['regime'] == ('noisy' if x['stats']['nu'] >= p2.NU_STAR else 'clean')


def test_noise_index_tracks_measurement_noise():
    rng = np.random.default_rng(0)
    smooth = np.cumsum(rng.normal(0, .05, (60, 3)), axis=0)          # floor-dominated, highly autocorrelated
    base_clean = p2.fit_baseline(smooth, ['a', 'b', 'c'], {'a': 1, 'b': 1, 'c': 1})
    base_noisy = p2.fit_baseline(smooth + rng.normal(0, 1, (60, 3)), ['a', 'b', 'c'], {'a': .1, 'b': .1, 'c': .1})
    assert base_clean.nu < p2.NU_STAR <= base_noisy.nu
    assert p2.regime(base_clean) == 'clean' and p2.regime(base_noisy) == 'noisy'


def test_v09_rule_still_available_and_daily_record_keeps_it():
    rng = np.random.default_rng(1)
    base = p2.fit_baseline(rng.normal(0, 1, (60, 3)), ['a', 'b', 'c'], {})
    X = rng.normal(0, 1, (40, 3))
    a = p2.run_detectors(X, base, np.ones(3))
    b = p2.run_detectors(X, base, np.ones(3), decision='v09')
    assert b['flags']['phantom2'] == b['flags']['phantom2_v09'] == a['flags']['phantom2_v09']
    with pytest.raises(ValueError):
        p2.run_detectors(X, base, np.ones(3), decision='magic')


# ------------------------------------------------------------------ B3: missing data
def test_pairwise_covariance_replaces_silent_abstention():
    rng = np.random.default_rng(2)
    Xb = rng.multivariate_normal(np.zeros(7), np.eye(7) + .5, 49)
    Xb[rng.random(Xb.shape) < .35] = np.nan                          # ≈5 % complete rows → complete-case fails
    assert p2._robust_cov((Xb - np.nanmedian(Xb, 0))) is None
    base = p2.fit_baseline(Xb, list('abcdefg'), {})
    assert base.cov is not None and base.cov_method == 'pairwise'
    assert np.all(np.linalg.eigvalsh(base.cov) > 0)
    X = np.full((2, 7), np.nan); X[0, :3] = 6.0; X[1, :3] = 0.0
    r = p2.run_detectors(X, base, np.ones(7))
    assert r['flags']['mahalanobis'] == [True, False]                  # the multivariate test works again


def test_insufficient_data_is_not_reported_as_normal():
    rng = np.random.default_rng(3)
    base = p2.fit_baseline(rng.normal(0, 1, (60, 3)), ['a', 'b', 'c'], {})
    X = np.array([[0.1, np.nan, np.nan], [np.nan, np.nan, np.nan], [0.1, 0.2, 0.0], [9.0, np.nan, np.nan]])
    r = p2.run_detectors(X, base, np.ones(3))
    assert r['states'] == ['insufficient_data', 'insufficient_data', 'no_flag', 'flag']   # an alarm is never hidden


def test_conditional_mean_imputation_equals_observed_subspace_distance():
    """Why imputation is not a separate B3 variant: for a Gaussian model it cannot change the Mahalanobis decision."""
    rng = np.random.default_rng(4)
    A = rng.normal(size=(5, 5)); S = A @ A.T + 5 * np.eye(5)
    z = rng.normal(size=5); obs = np.array([1, 1, 0, 1, 0], bool)
    zo, Soo = z[obs], S[np.ix_(obs, obs)]
    d_obs = zo @ np.linalg.solve(Soo, zo)
    zi = z.copy(); zi[~obs] = S[np.ix_(~obs, obs)] @ np.linalg.solve(Soo, zo)
    assert zi @ np.linalg.solve(S, zi) == pytest.approx(d_obs)


@pytest.mark.parametrize('mode', ['random', 'channel', 'baseline'])
def test_production_equals_study_hybrid_with_missing_data(mode):
    import phantom_study as ps
    th = thresholds()
    name = 'adaptive: phantom2 0.9 | ewma calibrated'
    payload, _ = ps.run_data('multifactor', 1002, ps.degrade(missing=.4, mode=mode, seed=3))
    ref = pe.detect(copy.deepcopy(payload), baseline_minutes=1440)
    for cid, x in ps.run_stats(payload, 'hybrid').items():
        f, _ = ps.flags_for(x['stats'], name, th)
        assert list(f) == [bool(ref['flags']['phantom2'][s['sample_id']]) for s in x['samples']]
        m, _ = ps.flags_for(x['stats'], 'mahalanobis (0.9)', th)
        assert list(m) == [bool(ref['flags']['mahalanobis'][s['sample_id']]) for s in x['samples']]
