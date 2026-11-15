"""BE3_04 / F5 — one explainable DTO for a PHANTOM result (read-time, never stored). SYNTHETIC fixtures."""
import pytest

from app import phantom_analyses as pa
from app.phantom_explain import EXPLAIN_VERSION, explain
from fakes.storage_fake import FakeContext, FakeStorage
from helpers_be3_signals_15 import P1, P2, hr_series, span, store

CTX = FakeContext(user_id='a' * 32, astronaut_ids=frozenset({P1}))
OTHER = FakeContext(user_id='b' * 32, astronaut_ids=frozenset({P2}))
KEYS = {'explain_version', 'available', 'outcome', 'what_was_measured', 'data_class', 'data_label', 'signal_quality',
        'time_bounds', 'baseline', 'deviation', 'method', 'why', 'next_measurement', 'not_medical_advice', 'diagnosis',
        'limitations', 'research_context', 'validation_status'}


def _run(st, minutes=90, **kw):
    f, t = span(minutes)
    code, r = pa.run(CTX, {'astronaut_id': P1, 'from': f, 'to': t, **kw}, st)
    assert code in (200, 201)
    return r


@pytest.fixture()
def st():
    return FakeStorage()


def test_flag_explanation(st):
    store(st, CTX, hr_series())
    e = _run(st)['explain']
    assert KEYS <= set(e) and e['explain_version'] == EXPLAIN_VERSION and e['available']
    assert e['outcome'] == 'flag' and e['diagnosis'] is None and e['not_medical_advice'] is True
    assert e['data_label'] == 'REAL SENSOR' and e['data_class'] == ['real_wearable']
    assert e['deviation']['flagged_windows'] >= 1 and e['deviation']['max_robust_z'] >= 3.5
    assert e['deviation']['difference_from_baseline_bpm'] > 0
    assert e['baseline']['windows_used'] == 12 and e['time_bounds']['baseline_from'] and e['method']['processing_version']
    assert 'not medical advice' in e['next_measurement'].lower()
    assert e['validation_status']['hardware_verified'] is False
    assert e['validation_status']['clinical_validation'] == 'not performed'
    assert 'does not validate' in e['research_context']['relevance']


def test_no_flag_is_not_healthy(st):
    store(st, CTX, hr_series(step_at_min=None))
    e = _run(st)['explain']
    assert e['outcome'] == 'no_flag' and 'does not mean healthy' in e['next_measurement']


def test_insufficient_data_explains_why_and_is_not_normal(st):
    store(st, CTX, hr_series(minutes=40))                   # < 60 min baseline
    r = _run(st, minutes=40)
    e = r['explain']
    assert e['outcome'] == 'insufficient_data' and e['deviation'] is None and e['baseline'] is None
    assert e['why'] and any('baseline' in w for w in e['why'])
    assert 'not a normal result' in e['next_measurement']
    assert all(w['score'] is None for w in r['windows'])


def test_synthetic_is_labelled(st):
    store(st, CTX, hr_series(data_class='synthetic'))
    e = _run(st, data_classes=['synthetic'])['explain']
    assert e['data_label'] == 'SYNTHETIC'


def test_explain_is_never_stored_and_is_deterministic_after_restart(tmp_path):
    p = tmp_path / 's.json'
    s1 = FakeStorage(p)
    store(s1, CTX, hr_series())
    r = _run(s1)
    assert all('explain' not in a for a in s1.db['analyses'].values())
    s2 = FakeStorage(p)
    got = pa.get_analysis(CTX, r['analysis_id'], s2)
    assert got['explain'] == r['explain']
    lst = pa.list_analyses(CTX, {'astronaut_id': P1}, s2)
    assert lst['items'][0]['explain'] == r['explain']


def test_other_user_gets_no_explanation(st):
    store(st, CTX, hr_series())
    r = _run(st)
    from app.science_errors import ScienceError
    with pytest.raises(ScienceError) as e:
        pa.get_analysis(OTHER, r['analysis_id'], st)
    assert e.value.status == 404


@pytest.mark.parametrize('bad', [{}, {'windows': 3}, {'windows': [1, 2]}, {'baseline': 'x', 'windows': []}, None])
def test_unexpected_stored_shapes_never_break_a_read(bad):
    e = explain(bad)
    assert e['explain_version'] == EXPLAIN_VERSION and e['diagnosis'] is None and e['not_medical_advice'] is True
