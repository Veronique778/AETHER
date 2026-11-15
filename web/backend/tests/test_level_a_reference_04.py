"""BE3_04 — Level A: numeric correctness against HAND-DERIVED, versioned expectations
(tests/fixtures/level_a_expected_v1.json). The code under test is never used to produce the expected values."""
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import phantom_analyses as pa
from app import signals as reg
from app.devices import hrs
from app.science_errors import CorruptedData, TimestampWithoutOffset
from fakes.storage_fake import FakeContext, FakeStorage
from helpers_be3_signals_15 import P1

EXP = json.loads((Path(__file__).parent / 'fixtures/level_a_expected_v1.json').read_text(encoding='utf-8'))
T0 = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)


def test_expectations_are_for_this_detector_version():
    assert EXP['detector_processing_version'] == pa.PROCESSING_VERSION


def _row(t_s, v, contact=True, quality='good', cid=None):
    item = reg.validate_item({'astronaut_id': P1, 'signal': 'heart_rate', 'value': v, 'unit': 'bpm',
                              'recorded_at': reg.iso_utc(T0 + timedelta(seconds=t_s)), 'data_class': 'synthetic',
                              'source': 'level A', 'quality': quality, 'provenance': {'contact': contact},
                              'client_measurement_id': cid or f'a-{t_s}'})
    item.update(measurement_id=cid or f'a-{t_s}', status='active', mission_id=None, session_id=None)
    return item


def _const_windows(means, extra=()):
    """One constant-valued window per mean (30 samples every 10 s) → the window mean is exactly that value."""
    rows = []
    for k, m in enumerate(list(means) + list(extra)):
        rows += [_row(k * 300 + 10 * i, float(m)) for i in range(30)]
    return rows


def _compute(rows, n_windows):
    req = pa.parse_request({'astronaut_id': P1, 'from': reg.iso_utc(T0),
                            'to': reg.iso_utc(T0 + timedelta(seconds=300 * n_windows)), 'data_classes': ['synthetic']})
    c = Counter()
    return pa.compute(req, pa._screen(rows, P1, ['synthetic'], c), None, c)


@pytest.mark.parametrize('case', ['baseline_median_mad', 'scale_floor'])
def test_median_mad_scale_and_robust_z(case):
    e = EXP[case]
    tests = [w['mean'] for w in e['test_windows']]
    res = _compute(_const_windows(e['window_means'], tests), 12 + len(tests))
    b = res['baseline']
    assert b['median_hr_bpm'] == e['median'] and b['mad_bpm'] == e['mad'] and b['scale_bpm'] == e['scale']
    assert round(max(3.0, 1.4826 * e['mad']), 4) == e['scale_unrounded']        # the formula, independently
    assert b['scale_floor_applied'] is e['floor_applied'] and b['windows_used'] == 12
    scored = [w for w in res['windows'] if w['role'] == 'test']
    for w, exp in zip(scored, e['test_windows']):
        assert w['mean_hr_bpm'] == round(exp['mean'], 3)      # reported AND scored at 0.001 bpm (F-7)
        assert w['score'] == exp['z'], exp['derivation']
        assert w['outcome'] == exp['outcome'], exp['derivation']


def test_baseline_is_frozen_first_hour_never_includes_test_windows():
    e = EXP['baseline_median_mad']
    res_a = _compute(_const_windows(e['window_means'], [65.5] * 6), 18)
    res_b = _compute(_const_windows(e['window_means'], [120.0] * 6), 18)        # very different test data
    assert res_a['baseline'] == res_b['baseline']                                    # baseline unchanged
    assert res_b['baseline']['from'] == reg.iso_utc(T0) and res_b['baseline']['to'] == reg.iso_utc(T0 + timedelta(hours=1))


def _usable(times, valid=None):
    samples = [(t, 60.0, True if valid is None else valid[i]) for i, t in enumerate(times)]
    return pa.window_usable(pa.window_coverage(samples, 0.0, 300.0))


def test_coverage_rules_at_their_boundaries():
    exp = {c['case']: (c['usable'], c['reason']) for c in EXP['coverage_rules']}
    assert _usable([15 * i for i in range(20)]) == exp['20 valid, span 285 s, gaps 15 s']
    assert _usable([15 * i for i in range(19)]) == exp['19 valid']
    assert _usable([i * 239 / 19 for i in range(20)]) == exp['20 valid, span 239 s']
    assert _usable([10 * i for i in range(13)] + [180.5 + 10 * i for i in range(12)]) == exp['gap 60.5 s']
    assert _usable([10 * i for i in range(13)] + [180 + 10 * i for i in range(12)]) == exp['gap exactly 60 s']
    assert _usable([10 * i for i in range(30)], [i % 5 != 0 for i in range(30)]) == \
        exp['valid fraction 0.8 exactly (24 valid of 30)']
    v = [i % 5 != 0 for i in range(30)]
    v[1] = False
    assert _usable([10 * i for i in range(30)], v) == exp['valid fraction 23/30 = 0.7667']


def test_windows_are_half_open_and_out_of_interval_rows_are_not_clamped():
    e = EXP['windows_half_open']
    items = [(T0.timestamp() + o, 'heart_rate', 60.0 + i, True) for i, o in enumerate(e['sample_offsets_s'])]
    wins = pa._windows(items, T0.timestamp(), T0.timestamp() + e['interval_s'])
    assert len(wins) == 2
    got = {0: wins[0]['samples'], 1: wins[1]['samples']}
    want = Counter(k for k in e['expected_window_of_each'] if k is not None)
    assert got == dict(want)


@pytest.mark.parametrize('case', EXP['rr_1_1024'])
def test_rr_resolution(case):
    from app import signal_compat
    assert signal_compat.rr_raw_to_ms(case['raw']) == case['ms']
    assert hrs.decode(hrs.encode(60, [case['raw']])).rr_ms == [case['ms']]


@pytest.mark.parametrize('case', EXP['hrs_packets'], ids=[c['hex'] for c in EXP['hrs_packets']])
def test_hrs_packets(case):
    pkt = bytes.fromhex(case['hex'])
    if 'error' in case:
        with pytest.raises(CorruptedData):
            hrs.decode(pkt)
        return
    m = hrs.decode(pkt)
    assert (m.heart_rate_bpm, m.contact, m.rr_ms) == (case['hr'], case['contact'], case['rr_ms']), case['derivation']


@pytest.mark.parametrize('case', EXP['time'])
def test_time_normalisation(case):
    if 'error' in case:
        with pytest.raises(TimestampWithoutOffset):
            reg.parse_utc(case['in'], 'recorded_at')
        return
    assert reg.iso_utc(reg.parse_utc(case['in'], 'recorded_at')) == case['out']


@pytest.mark.parametrize('n_missing,key', [(5, 'five_missing'), (10, 'ten_missing')])
def test_missing_values_are_missing_not_zero_and_not_counted(n_missing, key):
    e = EXP['missing_values'][key]
    rows = _const_windows([60] * 12, [60])
    rows += [_row(12 * 300 + 5 + 10 * i, None, quality='missing') for i in range(n_missing)]
    w = _compute(rows, 13)['windows'][-1]
    assert w['samples'] == 30 + n_missing and w['valid'] == 30
    assert (w['mean_hr_bpm'] is not None) is e['usable'], EXP['missing_values']['derivation']
    if e['usable']:
        assert w['mean_hr_bpm'] == e['mean']
    else:
        assert w['unusable_reason'] == e['reason'] and w['score'] is None


def test_duplicate_keys_are_stored_once():
    st = FakeStorage()
    ctx = FakeContext(user_id='a' * 32, astronaut_ids=frozenset({P1}))
    did = st.upsert_device(ctx, {'hardware_address': 'C4:7A:1C:00:12:9F', 'name': 's', 'astronaut_id': P1, 'kind': 'ble_hrs'})['device_id']
    sid = st.create_session(ctx, P1, 'live_sensor', 's', device_id=did)
    item = {'astronaut_id': P1, 'signal': 'heart_rate', 'value': 61.0, 'unit': 'bpm', 'recorded_at': reg.iso_utc(T0),
            'data_class': 'real_wearable', 'source': 's', 'quality': 'good', 'provenance': {'contact': True},
            'client_measurement_id': 'dup-1', 'session_id': sid, 'device_id': did}
    assert st.save_measurements(ctx, [item])['saved'] == 1
    again = st.save_measurements(ctx, [dict(item)])
    assert again['saved'] == 0 and again['duplicates'] == 1


@pytest.mark.parametrize('contact,expect_valid,expect_quality', [(True, True, 'good'), (False, False, 'no_contact'),
                                                                 (None, True, 'screened')])
def test_contact_and_quality_logic(contact, expect_valid, expect_quality):
    c = Counter()
    row = _row(0, 61.0, contact=contact)
    if contact is None:
        row['provenance'] = {}
    (item,) = pa._screen([row], P1, ['synthetic'], c)
    assert item[3] is expect_valid and item[4] == expect_quality


def test_insufficient_data_is_never_no_flag_and_has_null_scores():
    rows = _const_windows([60] * 9, [90] * 3)               # only 9 baseline windows (< 10)
    res = _compute(rows, 12)
    assert res['outcome'] == 'insufficient_data'
    assert all(w['score'] is None for w in res['windows'])
