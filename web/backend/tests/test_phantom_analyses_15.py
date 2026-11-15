"""AETHER 1.5 — personal PHANTOM pipeline (app/phantom_analyses.py) end to end on the storage fake.
All heart-rate series are SYNTHETIC test fixtures; tests check the pipeline, not physiology."""
import copy
import json
from datetime import timedelta

import pytest

from app import api15_science, phantom_analyses as pa
from app.science_errors import AnalysisError, Forbidden, InvalidInput, StorageUnavailable
from fakes.storage_fake import FakeContext, FakeStorage
from helpers_be3_signals_15 import T0, hr_series, span, store
from helpers_be3_signals_15 import P1, P2, P3, P4

CTX = FakeContext(user_id='a' * 32, astronaut_ids=frozenset({P1}))
OTHER = FakeContext(user_id='b' * 32, astronaut_ids=frozenset({P2}))
REQUIRED = {'analysis_id', 'astronaut_id', 'created_at', 'created_by', 'status', 'outcome', 'input', 'method',
            'processing_version', 'baseline', 'windows', 'flagged_signals', 'uncertainty', 'insufficient_data',
            'explanation', 'limitations', 'diagnosis'}


@pytest.fixture()
def st():
    return FakeStorage()


def run(st, ctx=CTX, **body):
    body.setdefault('astronaut_id', P1)
    if 'session_id' not in body and 'from' not in body:
        body['from'], body['to'] = span(90)
    code, res = pa.run(ctx, body, st)
    assert code == 201
    return res


def test_step_change_is_flagged_and_explained(st):
    store(st, CTX, hr_series())                       # 60 min ~62 bpm, then ~74 bpm
    r = run(st)
    assert REQUIRED <= set(r)
    assert r['outcome'] == 'flag' and r['flagged_signals'] == ['heart_rate'] and r['diagnosis'] is None
    assert r['insufficient_data'] is None
    assert 60 < r['baseline']['median_hr_bpm'] < 64 and r['baseline']['windows_used'] == 12
    tests = [w for w in r['windows'] if w['role'] == 'test']
    assert len(tests) == 6 and all(w['outcome'] == 'flag' for w in tests)
    assert r['input']['data_classes'] == ['real_wearable'] and r['input']['measurement_count'] == 5400
    assert r['flag_rate'] == 1.0 and 'not a medical finding' in r['explanation']


def test_stationary_series_is_no_flag(st):
    store(st, CTX, hr_series(step_at_min=None))
    r = run(st)
    assert r['outcome'] == 'no_flag' and r['flagged_signals'] == [] and r['flag_rate'] == 0.0


def test_analysis_is_persisted_and_readable_after_restart(tmp_path):
    p = tmp_path / 's.json'
    s1 = FakeStorage(p)
    store(s1, CTX, hr_series())
    r = run(s1)
    s2 = FakeStorage(p)
    again = pa.get_analysis(CTX, r['analysis_id'], s2)
    assert again == json.loads(json.dumps({k: v for k, v in r.items() if k not in ('idempotent_replay', 'idempotency_key')}))
    listed = pa.list_analyses(CTX, {'astronaut_id': [P1]}, s2)
    assert [a['analysis_id'] for a in listed['items']] == [r['analysis_id']] and 'windows' not in listed['items'][0]


def test_deterministic_rerun(st):
    # 02A: identical data on two independent stores → identical result (only created_at differs); the analysis_id is
    # deterministic, so a resend on the same store is an idempotent replay (see test_qa_fixes_02a.py)
    other = FakeStorage()
    store(st, CTX, hr_series()); store(other, CTX, hr_series())
    a, b = run(st), run(other)
    def strip(r):   # ids and digests differ by design: the two stores assigned different measurement_ids
        r = copy.deepcopy(r)
        for k in ('analysis_id', 'created_at', 'reproducibility', 'idempotency_key'):
            r.pop(k)
        r['input'].pop('measurement_digest')
        return r
    assert strip(a) == strip(b)
    assert a['input']['measurement_digest'] != b['input']['measurement_digest']


# ---------------------------------------------------------------- insufficient data, never "normal"
def test_empty_interval_is_insufficient(st):
    r = run(st)
    assert r['outcome'] == 'insufficient_data' and r['flag_rate'] is None
    codes = [x['code'] for x in r['insufficient_data']['reasons']]
    assert 'no_measurements' in codes and r['flagged_signals'] == []
    assert 'not a normal result' in r['explanation']


def test_recording_shorter_than_baseline_is_insufficient(st):
    store(st, CTX, hr_series(minutes=40))
    r = run(st)
    assert r['outcome'] == 'insufficient_data'
    reason = next(x for x in r['insufficient_data']['reasons'] if x['code'] == 'too_few_baseline_windows')
    assert reason['required'] == 10 and reason['available'] == 8


def test_baseline_only_no_test_window_is_insufficient(st):
    store(st, CTX, hr_series(minutes=60))
    r = run(st)
    assert r['outcome'] == 'insufficient_data'
    assert 'too_few_samples' in [x['code'] for x in r['insufficient_data']['reasons']]


def test_gaps_are_reported_not_filled(st):
    store(st, CTX, hr_series(gaps=[(70, 80)]))
    r = run(st)
    gap_windows = [w for w in r['windows'] if w['samples'] == 0]
    assert len(gap_windows) == 2 and all(w['mean_hr_bpm'] is None and w['outcome'] == 'insufficient_data' for w in gap_windows)
    assert all(w['unusable_reason'] == 'no_measurements' for w in gap_windows)
    assert r['signal_quality']['heart_rate']['longest_gap_s'] >= 600
    assert r['input']['measurement_count'] == 5400 - 600     # nothing invented: exactly the stored rows


def test_low_valid_fraction_windows_unusable(st):
    rows = hr_series()
    for i, r in enumerate(rows):
        if r['signal'] == 'heart_rate' and 3000 <= int(r['client_measurement_id'].rsplit('-', 2)[1]) < 3300 and i % 4:
            r['quality'] = 'no_contact'
    store(st, CTX, rows)
    r = run(st)
    w = next(w for w in r['windows'] if w['start'].endswith('08:50:00.000Z'))
    assert w['mean_hr_bpm'] is None and w['unusable_reason'] in ('low_valid_fraction', 'too_few_samples')


def test_constant_heart_rate_uses_scale_floor_no_explosion(st):
    store(st, CTX, hr_series(constant=True, step_to=63.0))
    r = run(st)
    assert r['baseline']['mad_bpm'] == 0 and r['baseline']['scale_floor_applied'] and r['baseline']['scale_bpm'] == 3.0
    tests = [w for w in r['windows'] if w['role'] == 'test']
    assert all(abs(w['score'] - 1 / 3) < 1e-3 for w in tests) and r['outcome'] == 'no_flag'


def test_short_outlier_burst_does_not_move_the_baseline(st):
    rows = hr_series()
    for r_ in rows:
        sec = int(r_['client_measurement_id'].rsplit('-', 2)[1])
        if r_['signal'] == 'heart_rate' and 1200 <= sec < 1230:
            r_['value'] = 180.0
    store(st, CTX, rows)
    r = run(st)
    clean = FakeStorage(); store(clean, CTX, hr_series())
    assert abs(r['baseline']['median_hr_bpm'] - run(clean)['baseline']['median_hr_bpm']) < 0.6


# ---------------------------------------------------------------- data rules: no hidden substitution / mixing
def test_synthetic_data_never_used_for_real_wearable_request(st):
    store(st, CTX, hr_series(data_class='synthetic'))
    r = run(st)
    assert r['outcome'] == 'insufficient_data' and r['input']['measurement_count'] == 0
    assert r['input']['excluded'] == {'excluded_data_class:synthetic': 5400}


def test_synthetic_and_real_cannot_be_mixed(st):
    with pytest.raises(InvalidInput):
        run(st, data_classes=['synthetic', 'real_wearable'])
    with pytest.raises(InvalidInput):
        run(st, data_classes=['nasa_public'])


def test_explicit_synthetic_request_is_labelled(st):
    store(st, CTX, hr_series(data_class='synthetic'))
    r = run(st, data_classes=['synthetic'])
    assert r['outcome'] == 'flag' and r['source_data_classes'] == ['synthetic'] and r['data_class'] == 'derived'


def test_other_astronaut_never_in_baseline(st):
    store(st, CTX, hr_series(minutes=40))
    admin = FakeContext(role='admin')
    store(st, admin, hr_series(astronaut=P2, step_at_min=None))
    r = run(st)
    assert r['outcome'] == 'insufficient_data' and r['input']['measurement_count'] == 2400


def test_foreign_rows_from_broken_storage_abort(st):
    store(st, CTX, hr_series())

    class Leaky(FakeStorage):
        def query_measurements(self, ctx, astronaut_id, **kw):
            page = super().query_measurements(ctx, astronaut_id, **kw)
            if page['items']:
                page['items'][0] = {**page['items'][0], 'astronaut_id': P2}
            return page
    leaky = Leaky(); leaky.db = st.db
    with pytest.raises(AnalysisError):
        run(leaky)


def test_rows_with_wrong_unit_from_storage_are_excluded(st):
    store(st, CTX, hr_series())

    class Bad(FakeStorage):
        def query_measurements(self, ctx, astronaut_id, **kw):
            page = super().query_measurements(ctx, astronaut_id, **kw)
            page['items'] = [{**x, 'unit': 'Hz'} if x['signal'] == 'heart_rate' else x for x in page['items']]
            return page
    bad = Bad(); bad.db = st.db
    r = run(bad)
    assert r['input']['excluded']['unit_mismatch'] == 2700 and r['outcome'] == 'insufficient_data'


def test_invalidated_rows_are_not_used(st):
    out = st.save_measurements(CTX, hr_series(minutes=1, rr=False))
    for it in out['items']:
        st.invalidate(CTX, it['measurement_id'], 'test')
    r = run(st)
    assert r['input']['measurement_count'] == 0


def test_unvalidated_rr_only_exploratory(st):
    store(st, CTX, hr_series())
    r = run(st)
    hrv = next(w['hrv'] for w in r['windows'] if w['hrv'])
    assert hrv['quality'] in ('exploratory', 'insufficient_data') and 'not validated NN' in hrv['limitation']
    assert 'NOT verified NN' in r['signal_quality']['validated_interval_summary']['note']


def test_missing_contact_flag_is_reported(st):
    store(st, CTX, hr_series(contact=None))
    r = run(st)
    assert r['signal_quality']['heart_rate']['contact'] == {'not_reported': 2700}
    assert 'does not prove skin contact' in r['signal_quality']['heart_rate']['contact_note']


# ---------------------------------------------------------------- baselines without leakage
def test_explicit_baseline_must_be_earlier(st):
    f, t = span(90)
    with pytest.raises(InvalidInput) as e:
        run(st, **{'from': f, 'to': t, 'baseline_from': f, 'baseline_to': t})
    assert 'earlier data' in e.value.message


def test_explicit_earlier_baseline_used(st):
    day1 = hr_series(minutes=60, step_at_min=None)
    day2 = hr_series(minutes=30, base=75.0, step_at_min=None, start=T0 + timedelta(days=1), seed=3)
    store(st, CTX, day1 + day2)
    bf, bt = span(60)
    f, t = span(30, T0 + timedelta(days=1))
    r = run(st, **{'from': f, 'to': t, 'baseline_from': bf, 'baseline_to': bt})
    assert r['method']['baseline_mode'] == 'explicit' and r['baseline']['to'] == bt
    assert r['outcome'] == 'flag' and len([w for w in r['windows'] if w['role'] == 'test']) == 6


def test_session_mode_reports_actual_interval(st):
    sid = st.create_session(CTX, P1, 'live_sensor', 'test')
    store(st, CTX, hr_series(session_id=sid))
    r = run(st, session_id=sid)
    assert r['input']['from'] == '2026-11-20T08:00:00.000Z' and r['input']['session_ids'] == [sid]
    assert r['input']['requested_from'] is None


# ---------------------------------------------------------------- input validation, access, storage failures
@pytest.mark.parametrize('patch', [
    {'astronaut_id': 'X1'}, {'method': 'magic'}, {'signals': ['spo2']}, {'signals': ['rr_interval']},
    {'from': '2026-11-20T08:00:00', 'to': '2026-11-20T09:00:00'},
    {'from': '2026-11-20T09:00:00Z', 'to': '2026-11-20T08:00:00Z'},
    {'from': '2026-10-01T00:00:00Z', 'to': '2026-11-20T00:00:00Z'},
    {'session_id': 'not a valid id!'}, {'astronaut_id': 'A01'},   # demo id with real data class (03A)
])
def test_invalid_requests_rejected(st, patch):
    body = {'astronaut_id': P1, 'from': span(90)[0], 'to': span(90)[1], **patch}
    with pytest.raises(InvalidInput):
        pa.run(CTX, body, st)


def test_access_denied_for_other_astronaut(st):
    with pytest.raises(Forbidden):
        run(st, ctx=OTHER)
    with pytest.raises(Forbidden):
        pa.list_analyses(OTHER, {'astronaut_id': P1}, st)


def test_reading_someone_elses_analysis_forbidden(st):
    store(st, CTX, hr_series())
    r = run(st)
    with pytest.raises(Forbidden):
        pa.get_analysis(OTHER, r['analysis_id'], st)


def test_storage_failure_is_honest(st):
    st.fail_next = 'query_measurements'
    with pytest.raises(StorageUnavailable):
        run(st)
    store(st, CTX, hr_series())
    st.fail_next = 'save_analysis_bundle'
    with pytest.raises(StorageUnavailable):
        run(st)
    assert st.db['analyses'] == {}


def test_record_log_and_audit_written(st):
    store(st, CTX, hr_series())
    r = run(st)
    assert st.db['records'][-1]['kind'] == 'phantom_analysis' and st.db['records'][-1]['ref_ids'] == [r['analysis_id']]
    assert st.db['audit'][-1]['action'] == 'phantom_analysis.create'


# ---------------------------------------------------------------- route table / dispatch (independent of Backend №2)
def test_dispatch_routes_and_errors(st):
    api15_science.set_storage(st)
    try:
        store(st, CTX, hr_series())
        f, t = span(90)
        code, body = api15_science.dispatch(CTX, 'POST', '/api/phantom-analyses', {}, {'astronaut_id': P1, 'from': f, 'to': t})
        assert code == 201 and body['outcome'] == 'flag'
        code, got = api15_science.dispatch(CTX, 'GET', f'/api/phantom-analyses/{body["analysis_id"]}')
        assert code == 200 and got['analysis_id'] == body['analysis_id']
        code, lst = api15_science.dispatch(CTX, 'GET', '/api/phantom-analyses', {'astronaut_id': [P1], 'outcome': ['flag']})
        assert code == 200 and len(lst['items']) == 1
        code, err = api15_science.dispatch(OTHER, 'POST', '/api/phantom-analyses', {}, {'astronaut_id': P1, 'from': f, 'to': t})
        # 03A: foreign astronaut → 404 not_found (Backend №2 semantics, no existence leak); Backend №2 error envelope
        assert code == 404 and err['error']['code'] == 'not_found' and P1 not in err['error']['detail']
        code, err = api15_science.dispatch(CTX, 'POST', '/api/phantom-analyses', {}, {'astronaut_id': P1})
        assert code == 422 and err['error']['code'] == 'validation_error' and err['error']['field'] == 'from'
        assert api15_science.dispatch(CTX, 'GET', '/api/phantom-analyses/123')[0] == 404
        code, sig = api15_science.dispatch(None, 'GET', '/api/signals')
        assert code == 200 and sig['registry_version'] == '1.5.1'
    finally:
        api15_science.set_storage(None)


def test_without_storage_module_answers_503_not_fake(monkeypatch):
    import sys
    api15_science.set_storage(None)
    for mod in ('app.storage.api', 'app.persistence', 'app.persistence.repository'):
        monkeypatch.setitem(sys.modules, mod, None)              # no Backend №2 storage at all
    code, err = api15_science.dispatch(CTX, 'POST', '/api/phantom-analyses', {}, {'astronaut_id': P1, 'from': span(90)[0], 'to': span(90)[1]})
    assert code == 503 and err['error']['code'] == 'storage_unavailable'


def test_with_backend2_present_a_non_backend2_context_is_refused():
    pytest.importorskip('argon2')                                 # Backend №2 auth must import (see be3_argon2_env)
    api15_science.set_storage(None)
    code, err = api15_science.dispatch(CTX, 'POST', '/api/phantom-analyses', {}, {'astronaut_id': P1, 'from': span(90)[0], 'to': span(90)[1]})
    assert code == 401 and err['error']['code'] == 'unauthenticated'    # FakeStorage is never picked up automatically


def test_contract_example_keys_are_produced(st):
    from pathlib import Path
    ex = Path(__file__).resolve().parents[3] / 'docs/api_1_5/examples/phantom_analysis_201_insufficient.json'
    if not ex.exists():
        pytest.skip('contract examples not merged into this tree')
    expected = set(json.loads(ex.read_text(encoding='utf-8')))
    r = run(st)
    assert expected - set(r) == set(), expected - set(r)
