"""PHANTOM 2.0: each method must show a concrete, testable benefit over PHANTOM 1.0 (robust z)."""
import numpy as np
import pytest

from app import phantom2 as p2

FLOORS = {}


def _base(X, metrics):
    return p2.fit_baseline(X, metrics, FLOORS)


def test_mahalanobis_catches_broken_correlation_that_z_misses():
    rng = np.random.default_rng(1)
    n = 200
    a = rng.normal(0, 1, n)
    Xb = np.c_[a, a * 0.95 + rng.normal(0, .3, n)]       # strongly correlated pair
    base = _base(Xb, ['m1', 'm2'])
    # each value alone is within 1.6 robust SD, but the pair contradicts the learned correlation
    X = np.array([[1.6 * base.scale[0] + base.median[0], -1.6 * base.scale[1] + base.median[1]]])
    r = p2.run_detectors(X, base, np.array([1., 1.]), explain=True)
    assert r['flags']['zscore'][0] is False
    assert r['flags']['mahalanobis'][0] is True
    att = r['details'][0]['attribution']
    assert abs(sum(att.values()) - 1) < 1e-6


def test_cusum_detects_small_persistent_shift_and_its_start():
    rng = np.random.default_rng(2)
    Xb = rng.normal(0, 1, (100, 1))
    base = _base(Xb, ['m'])
    X = np.r_[rng.normal(0, 1, (30, 1)), rng.normal(0.9, 1, (60, 1))]   # +0.9 SD from index 30
    r = p2.run_detectors(X, base, np.array([1.]), explain=True)
    z_hits = sum(bool(f) for f in r['flags']['zscore'][30:])
    c = r['flags']['cusum']
    first = c.index(True)
    assert 30 <= first < 60, first
    assert sum(c[30:]) > 2 * z_hits                       # sequential evidence beats single-sample z
    assert sum(c[:30]) == 0
    assert r['details'][first + 5]['cusum']['m']['start_index'] >= 25


def test_prewhitening_controls_false_alarms_on_autocorrelated_noise():
    rng = np.random.default_rng(3)
    def ar1(n, rho=.85):
        x = np.zeros(n)
        for t in range(1, n):
            x[t] = rho * x[t - 1] + rng.normal(0, np.sqrt(1 - rho ** 2))
        return x
    Xb = ar1(300)[:, None]
    base = _base(Xb, ['m'])
    X = ar1(600)[:, None]
    raw = p2.run_detectors(X, base, np.array([1.]), prewhiten=False)['flags']['cusum']
    pw = p2.run_detectors(X, base, np.array([1.]), prewhiten=True)['flags']['cusum']
    assert base.rho[0] > .6
    assert sum(pw) < sum(raw) / 3


def test_adaptive_baseline_freezes_during_anomaly():
    Xb = np.random.default_rng(4).normal(0, 1, (50, 1))
    base = _base(Xb, ['m'])
    X = np.r_[np.zeros((10, 1)), np.full((20, 1), 6.0)]  # large step must stay flagged (not learned away)
    r = p2.run_detectors(X, base, np.array([1.]))
    assert all(r['flags']['adaptive'][10:])


def test_missing_data_abstains_and_adjusts_degrees_of_freedom():
    rng = np.random.default_rng(5)
    Xb = rng.normal(0, 1, (80, 3))
    base = _base(Xb, ['a', 'b', 'c'])
    X = np.array([[np.nan, np.nan, 0.1], [np.nan, 0.2, 0.1], [np.nan, np.nan, np.nan]])
    r = p2.run_detectors(X, base, np.ones(3), explain=True)
    assert r['flags']['mahalanobis'][0] is None           # < 2 observed metrics → abstain
    assert r['details'][1]['df'] == 2
    assert r['flags']['zscore'][2] is None


def test_bootstrap_uncertainty_is_quantitative():
    rng = np.random.default_rng(6)
    Xb = rng.normal(0, 1, (40, 2))
    base = _base(Xb, ['a', 'b'])
    X = np.array([[0.1, 0.0], [3.0, 3.2]])
    r = p2.run_detectors(X, base, np.ones(2), bootstrap=30, rng=rng)
    u0, u1 = r['details'][0]['uncertainty'], r['details'][1]['uncertainty']
    assert u0['flag_probability'] < .2 and u1['flag_probability'] > .8
    lo, hi = u1['d2_interval_90']
    assert lo <= r['details'][1]['d2'] <= hi or lo < hi


def test_next_best_measurement_ranks_by_information_not_by_correlation():
    """A metric that is almost predictable from what is already measured carries little new information:
    it is imputed (expected z follows the correlated metric) and ranked below an unpredictable one."""
    rng = np.random.default_rng(7)
    n = 400
    a = rng.normal(0, 1, n)
    Xb = np.c_[a, a * .95 + rng.normal(0, .3, n), rng.normal(0, 1, n), rng.normal(0, 1, n)]   # b tracks a; c, d independent
    base = _base(Xb, ['a', 'b', 'c', 'd'])
    z = np.array([3.2, np.nan, 0.0, np.nan])          # borderline: observed a (high) and c; b and d missing
    ranking = p2.next_best_measurement(z, base.cov, base.metrics, rng)
    by = {r['metric']: r for r in ranking}
    assert [r['p_decision_change'] for r in ranking] == sorted((r['p_decision_change'] for r in ranking), reverse=True)
    assert by['b']['expected_z'] > 2 and abs(by['d']['expected_z']) < .5          # imputation via correlation
    assert by['b']['conditional_sd'] < by['d']['conditional_sd']                  # redundancy recognised
    assert by['d']['p_decision_change'] >= by['b']['p_decision_change']


def test_next_best_measurement_clear_cases():
    rng = np.random.default_rng(8)
    Xb = rng.normal(0, 1, (300, 3))
    base = _base(Xb, ['a', 'b', 'c'])
    far = p2.next_best_measurement(np.array([9.0, 9.0, np.nan]), base.cov, base.metrics, rng)
    assert far[0]['p_decision_change'] < .05          # already clearly anomalous: one more value rarely changes it
    near = p2.next_best_measurement(np.array([2.3, 2.3, np.nan]), base.cov, base.metrics, rng)
    assert near[0]['p_decision_change'] > far[0]['p_decision_change']


def test_confusion_counts():
    c = p2.confusion([True, False, None, True], [True, True, False, False])
    assert (c['tp'], c['fn'], c['tn'], c['fp'], c['abstained']) == (1, 1, 1, 1, 1)
