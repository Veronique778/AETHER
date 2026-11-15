"""AETHER 1.5 — the numerical claims of docs/HEALTH_ALGORITHMS_AUDIT.md are reproducible (reduced sizes, fixed seeds)."""
import math

from app.phantom2 import confusion
from app.scientific_validation import audit_experiments as ax


def test_e1_chi2_threshold_exceeds_nominal_rate_with_estimated_covariance():
    r = ax.e1_mahalanobis_fpr(reps=40, tests=250)
    iid = r['iid_baseline']
    assert iid['observed_rate_chi2_threshold'] > 2 * iid['nominal_rate']          # ≈ 4× in the full run
    assert 0.001 <= iid['observed_rate_hotelling_threshold'] <= 0.012              # ≈ nominal 0.5 %
    assert r['ar1_rho_0.9_baseline']['observed_rate_chi2_threshold'] > 0.1          # autocorrelated baseline: far worse


def test_e3_prewhitening_after_gap_differs_from_documented_behaviour():
    r = ax.e3_gap_prewhitening()
    assert abs(r['residual_implementation'] - 0.32) < 0.01
    assert r['residual_implementation'] != r['residual_if_raw_value_after_gap']


def test_e4_zero_mad_is_bounded_by_floor():
    r = ax.e4_zero_mad()
    assert r['constant_baseline_mad'] == 0 and math.isinf(r['z_for_+1_bpm_without_floor'])
    assert abs(r['z_for_+1_bpm_with_floor'] - 1 / 2.8) < 1e-3


def test_e5_hrv_matches_reference_and_numpy():
    r = ax.e5_hrv_reference()
    a = r['alternating_800_820']
    assert a['rmssd_impl'] == 20.0 and abs(a['sdnn_impl'] - a['sdnn_expected']) < 1e-6
    b = r['random_walk_series']
    assert abs(b['rmssd_impl'] - b['rmssd_numpy']) < 1e-9 and abs(b['sdnn_impl'] - b['sdnn_numpy']) < 1e-9
    assert r['single_artefact']['rmssd_impl'] == 20.0 and r['single_artefact']['rejected'] == 2
    assert r['too_short_50_beats']['quality'] == 'insufficient_data'


def test_confusion_counts_abstentions_as_negatives_documented_defect():
    # 2 abstentions + 1 false alarm + 1 true negative among 4 non-events
    c = confusion([None, None, True, False], [False] * 4)
    assert c['fpr'] == 0.25 and c['abstained'] == 2           # FPR among decided samples would be 0.5 (audit D5)
