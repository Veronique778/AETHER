"""AETHER 1.5 — regression tests for the confirmed PHANTOM 1.0 / 2.0 defects (HEALTH_ALGORITHMS_AUDIT.md D1–D3)."""
import pytest

from app import analytics, db
from app.analytics import analyze, compute_baselines, history_scores
from app.db import SEED_SHIFTS, seed_row

COLS = ('astronaut_id', 'day', 'heart_rate_bpm', 'sleep_hours', 'fatigue_1_10', 'reaction_ms', 'activity_minutes', 'source')


def history(p='A01', days=67):
    return [dict(zip(COLS, seed_row(p, dict(SEED_SHIFTS)[p], d))) for d in range(1, days + 1)]


# ---------------------------------------------------------------- D2: "normal" with almost no data
def test_one_of_five_signals_is_insufficient_not_normal():
    h = history()
    h[-1] = {**h[-1], 'heart_rate_bpm': 66.0, 'sleep_hours': None, 'fatigue_1_10': None, 'reaction_ms': None, 'activity_minutes': None}
    r = analyze(h, 67)
    assert r['status'] == 'insufficient' and r['score'] is None
    assert 'not a normal result' in r['explanation']


def test_two_of_five_unflagged_is_insufficient():
    h = history('A02')
    h[-1] = {**h[-1], 'reaction_ms': None, 'activity_minutes': None, 'fatigue_1_10': None}
    assert analyze(h, 67)['status'] == 'insufficient'


def test_three_of_five_unflagged_may_be_normal():
    h = history('A02')
    h[-1] = {**h[-1], 'reaction_ms': None, 'activity_minutes': None}
    r = analyze(h, 67)
    assert r['status'] == 'normal' and r['score'] == 0


def test_flag_with_low_coverage_stays_attention_not_normal():
    h = history()
    h[-1] = {**h[-1], 'sleep_hours': None, 'fatigue_1_10': None, 'reaction_ms': None, 'activity_minutes': None, 'heart_rate_bpm': 95.0}
    r = analyze(h, 67)
    assert r['status'] == 'attention' and r['data_quality'] == 'insufficient' and r['uncertainty'] == 'high'


def test_history_points_never_normal_with_one_signal():
    h = history()
    h[50] = {**h[50], 'sleep_hours': None, 'fatigue_1_10': None, 'reaction_ms': None, 'activity_minutes': None}
    p = next(x for x in history_scores(h, 41, 67)['points'] if x['day'] == 51)
    assert p['status'] == 'insufficient' and p['score'] is None


# ---------------------------------------------------------------- D3: no self-inclusion / no future data in the baseline
def test_current_anomalous_value_is_not_in_its_own_baseline():
    h = history(days=20)
    normal_baseline = compute_baselines(h, 20)['heart_rate_bpm']['median']
    h[-1] = {**h[-1], 'heart_rate_bpm': 200.0}
    assert compute_baselines(h, 20)['heart_rate_bpm']['median'] == normal_baseline
    assert compute_baselines(h, 20)['heart_rate_bpm']['n'] == 19          # days 1..19 only
    r = analyze(h, 20)
    hr = next(s for s in r['signals'] if s['key'] == 'heart_rate_bpm')
    assert hr['baseline'] == round(normal_baseline, 2) and hr['flagged']


def test_baseline_day_is_not_scored_with_future_days():
    h = history()
    h[29] = {**h[29], 'heart_rate_bpm': 150.0}     # anomaly on day 30
    h[34] = {**h[34], 'heart_rate_bpm': 150.0}     # and on day 35 (future relative to day 30)
    pts = {p['day']: p for p in history_scores(h, 20, 67)['points']}
    # day 30 must be judged against days 1..29 only: the day-35 value must not influence it
    h2 = [dict(r) for r in h]
    h2[34] = {**h2[34], 'heart_rate_bpm': 60.0}
    pts2 = {p['day']: p for p in history_scores(h2, 20, 67)['points']}
    assert pts[30] == pts2[30]


def test_days_after_baseline_unchanged_by_the_fix():
    # 1.4 values for day 67 (captured from the 1.4 server before the change)
    r = analyze(history(), 67)
    assert (r['status'], r['score'], r['flagged_count']) == ('attention', 79, 4)
    assert r['baseline_days'] == 40


def test_too_early_day_is_insufficient():
    r = analyze(history(days=5), 5)
    assert r['status'] == 'insufficient' and r['score'] is None


def test_analyze_keys_unchanged_for_parity_with_typescript_port():
    keys = {'day', 'status', 'score', 'data_quality', 'uncertainty', 'signals', 'flagged_count', 'multi_signal_pattern',
            'explanation', 'next_measurements', 'source', 'current_source', 'baseline_days', 'method', 'disclaimer'}
    assert set(analyze(history(), 67)) == keys


# ---------------------------------------------------------------- D1: PHANTOM 2.0 daily date substitution
@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'p2.sqlite3')
    db.init_db()
    from app import phantom2_daily
    return phantom2_daily


@pytest.mark.parametrize('day', [68, 100, 9999])
def test_phantom2_day_outside_data_is_insufficient_not_substituted(seeded, day):
    r = seeded.analyze('A01', day, bootstrap=5)
    assert r['status'] == 'insufficient_data' and r['today_state'] == 'insufficient_data'
    assert r['analysed_day'] is None and r['requested_day'] == day and r['last_available_day'] == 67
    assert r['score'] is None and r['diagnosis'] is None
    assert r['insufficient_data']['reasons'][0]['code'] == 'no_measurements'
    assert 'series' not in r


def test_phantom2_empty_history_is_insufficient(seeded):
    r = seeded.analyze('ZZZ', 67, bootstrap=5)          # unknown id → no rows at all (service rejects it earlier)
    assert r['status'] == 'insufficient_data' and r['last_available_day'] is None


def test_phantom2_reports_the_day_it_analysed(seeded):
    r = seeded.analyze('A01', 67, bootstrap=5)
    assert r['status'] == 'ok' and r['analysed_day'] == 67 == r['day'] and r['series'][-1]['day'] == 67


def test_phantom2_baseline_excludes_analysed_day(seeded):
    r = seeded.analyze('A01', 30, bootstrap=5)
    assert r['baseline_window'] == 'days 1–29 (29 days)'


def test_phantom2_too_few_signals_is_not_within_baseline(seeded):
    with db.connect() as c:
        c.execute('UPDATE measurements SET sleep_hours=NULL, fatigue_1_10=NULL, reaction_ms=NULL, activity_minutes=NULL '
                  "WHERE astronaut_id='A02' AND day=67")
    r = seeded.analyze('A02', 67, bootstrap=5)
    assert r['observed_signals'] == 1 and r['today_state'] != 'no_flag'


def test_phantom2_notes_explain_threshold_and_bootstrap(seeded):
    r = seeded.analyze('A01', 67, bootstrap=5)
    assert 'not as a calibrated false-alarm rate' in r['multivariate']['threshold_note']
    assert 'not a probability' in r['multivariate']['uncertainty_note']
