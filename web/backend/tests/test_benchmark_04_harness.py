"""BE3_04 — the Level B benchmark exercises the PRODUCT path, not a re-implementation.

For dev-split recordings, the benchmark's direct path (validate_item → _screen → compute) must give exactly the same
outcome and window scores as the full product service phantom_analyses.run() over storage. SYNTHETIC data."""
import sys
from pathlib import Path

import pytest

from app import phantom_analyses as pa
from fakes.storage_fake import FakeContext, FakeStorage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'validation'))
import phantom_benchmark_04 as bench  # noqa: E402

CTX = FakeContext(user_id='b' * 32, astronaut_ids=frozenset({bench.AID}))


def test_detector_fingerprint_matches_the_preregistered_protocol():
    assert bench.detector_fingerprint() == bench.CONFIG['detector']['fingerprint_sha256']


def test_generator_is_deterministic():
    a, b = bench.generate(1003, 'ST15'), bench.generate(1003, 'ST15')
    assert a['samples'] == b['samples'] and a['onset_s'] == b['onset_s']
    assert bench.generate(1003, 'N0')['samples'] != a['samples']


@pytest.mark.parametrize('seed,scenario', [(1000, 'ST15'), (1001, 'N0'), (1002, 'BM'), (1004, 'CL'), (1005, 'SPC')])
def test_benchmark_path_equals_product_service(seed, scenario):
    direct = bench.analyse(seed, scenario)
    gen = bench.generate(seed, scenario)
    st = FakeStorage()
    rows = [{k: v for k, v in r.items() if k not in ('measurement_id', 'status', 'mission_id', 'session_id',
                                                     'supersedes_id', 'valid', 'missing', 'astronaut_kind')}
            for r in bench.rows_for(seed, scenario, gen['samples'])]
    for i in range(0, len(rows), 500):
        st.save_measurements(CTX, rows[i:i + 500])
    body = {'astronaut_id': bench.AID, 'from': bench.reg.iso_utc(bench.T0),
            'to': bench.reg.iso_utc(bench.T0 + bench.timedelta(seconds=bench.DUR_S)), 'data_classes': ['synthetic']}
    code, r = pa.run(CTX, body, st)
    assert code == 201 and r['outcome'] == direct['outcome']
    tests = [w for w in r['windows'] if w['role'] == 'test']
    assert [w['score'] is not None for w in tests] == [w['scored'] for w in direct['windows']]
    assert [(w['outcome'] == 'flag') if w['score'] is not None else None for w in tests] == \
        [w['phantom'] for w in direct['windows']]
    assert r['input']['data_classes'] == ['synthetic'] and r['diagnosis'] is None


def test_labels_follow_the_preregistered_rule():
    gen = bench.generate(1000, 'ST15')
    on = gen['onset_s']
    assert bench.label(gen, on, on + 300) == 'pos' and bench.label(gen, on - 300, on) == 'neg'
    assert bench.label(gen, on - 10, on + 290) is None
    assert bench.label(bench.generate(1000, 'BO'), 4000, 4300) == 'neg'          # short bouts are NOT sustained


def test_wilson_interval_reference_values():
    # hand-checked: k=59, n=60 → [0.9114, 0.9971]; k=0, n=60 → [0, 0.0602]
    assert bench.wilson(59, 60) == [0.9114, 0.9971]
    assert bench.wilson(0, 60) == [0.0, 0.0602]
