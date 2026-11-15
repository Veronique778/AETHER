"""Unit tests for the pure analytic / simulation functions."""
import math

from app.analytics import analyze, correlations, spearman
from app.db import SEED_SHIFTS, seed_row
from app.simulation import Mulberry32, project, schedules, TASKS


def history(person='A01', days=67):
    shift = dict(SEED_SHIFTS)[person]
    cols = ('astronaut_id', 'day', 'heart_rate_bpm', 'sleep_hours', 'fatigue_1_10', 'reaction_ms',
            'activity_minutes', 'source')
    return [dict(zip(cols, seed_row(person, shift, d))) for d in range(1, days + 1)]


def test_baseline_period_is_normal():
    assert analyze(history(), 30)['status'] == 'normal'


def test_strained_day_flags_multiple_signals():
    r = analyze(history(), 67)
    assert r['status'] == 'attention' and r['flagged_count'] >= 2
    assert 0 <= r['score'] <= 100


def test_unstrained_crew_member_stays_normal():
    assert analyze(history('A02'), 67)['status'] == 'normal'


def test_missing_metric_raises_uncertainty():
    h = history()
    h[-1] = {**h[-1], 'heart_rate_bpm': None, 'reaction_ms': None}
    r = analyze(h, 67)
    assert r['data_quality'] == 'partial' and r['uncertainty'] == 'medium'


def test_spearman_known_values():
    assert abs(spearman([1, 2, 3, 4], [10, 20, 30, 40]) - 1) < 1e-12
    assert abs(spearman([1, 2, 3, 4], [4, 3, 2, 1]) + 1) < 1e-12
    assert spearman([1, 1, 1], [1, 2, 3]) is None


def test_correlation_matrix_symmetric():
    m = {(c['a'], c['b']): c['rho'] for c in correlations(history(), 67)['matrix']}
    assert m[('sleep_hours', 'fatigue_1_10')] == m[('fatigue_1_10', 'sleep_hours')]


def test_mulberry32_reference_sequence():
    # Reference values produced by the canonical JS implementation (seed 1).
    r = Mulberry32(1)
    vals = [r.next() for _ in range(3)]
    assert [round(v, 10) for v in vals] == [0.6270739406, 0.0027357212, 0.52744704]


def test_projection_deterministic_and_ordered():
    kw = dict(start_day=67, horizon_days=14, sleep_delta=-1.8, workload=85, co2_ppm=1450,
              temperature_c=25, runs=60, seed=3)
    a, b = project(history(), **kw), project(history(), **kw)
    assert a == b
    for d in a['days']:
        for k in ('heart_rate_bpm', 'fatigue_1_10', 'reaction_ms', 'score'):
            assert d[k]['p10'] <= d[k]['p50'] <= d[k]['p90']
        assert 0 <= d['attention_share'] <= 1


def test_recovery_scenario_lowers_projected_strain():
    strain = project(history(), start_day=67, horizon_days=14, sleep_delta=-1.8, workload=85,
                     co2_ppm=1450, temperature_c=25, runs=80)
    rest = project(history(), start_day=67, horizon_days=14, sleep_delta=0.8, workload=35,
                   co2_ppm=850, temperature_c=21, runs=80)
    assert rest['days'][-1]['score']['p50'] < strain['days'][-1]['score']['p50']


def test_schedule_respects_capacity_and_skills():
    s = schedules(capacity={'A01': 2}, unavailable=['A03'])
    assert s['loads']['A01'] <= 2 and s['loads']['A03'] == 0
    med = next(t for t in s['assignments'] if t['skill'] == 'medical')
    assert med['astronaut_id'] is None  # only A03 has medical skill
    assert s['unassigned'] >= 1


def test_local_search_never_worse_than_greedy():
    s = schedules(tasks=TASKS + [{'id': 'T6', 'title': 'x', 'skill': 'science', 'hours': 3, 'priority': 1}])
    assert s['peak_utilisation'] <= s['greedy_peak_utilisation'] + 1e-9
    assert not math.isnan(s['peak_utilisation'])
