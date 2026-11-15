"""BE3_04 release gate — the PHANTOM DTO (with the F5 `explain` block) against Backend №2's published OpenAPI
(docs/1.5/openapi-be2-06.json), over the real BE2 HTTP server + SQLite. SYNTHETIC data. No second API."""
import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from be3_real_backend import Account, real_db, stdlib_server  # noqa: F401

jsonschema = pytest.importorskip('jsonschema')
ROOT = Path(__file__).resolve().parents[3]
OPENAPI = json.loads((ROOT / 'docs/1.5/openapi-be2-06.json').read_text(encoding='utf-8'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'validation'))
import demo_30s_04 as demo  # noqa: E402

EXPLAIN_REQUIRED = {'explain_version', 'available', 'outcome', 'data_label', 'signal_quality', 'time_bounds', 'baseline',
                    'deviation', 'method', 'why', 'next_measurement', 'not_medical_advice', 'diagnosis', 'limitations',
                    'research_context', 'validation_status'}


def _schema(path, method, status):
    return OPENAPI['paths'][path][method]['responses'][str(status)]['content']['application/json']['schema']


def test_phantom_dto_matches_openapi_and_carries_the_explanation(real_db):
    alice = Account('alice')
    t0, rows = demo.synthetic_series(seed=7)
    with stdlib_server() as call:
        for i in range(0, len(rows), 500):
            code, body = call('POST', '/api/measurements/batch', {'measurements': rows[i:i + 500]}, alice.token)
            assert code in (200, 201), body
        body = {'astronaut_id': alice.astronaut_id, 'from': t0.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'to': (t0 + timedelta(minutes=180)).strftime('%Y-%m-%dT%H:%M:%SZ'), 'data_classes': ['synthetic']}
        code, r = call('POST', '/api/phantom-analyses', body, alice.token)
        assert code == 201
        jsonschema.validate(r, _schema('/api/phantom-analyses', 'post', 201))
        code, again = call('POST', '/api/phantom-analyses', body, alice.token)
        assert code == 200 and again['analysis_id'] == r['analysis_id']
        jsonschema.validate(again, _schema('/api/phantom-analyses', 'post', 200))
        code, got = call('GET', f'/api/phantom-analyses/{r["analysis_id"]}', token=alice.token)
        assert code == 200
        jsonschema.validate(got, _schema('/api/phantom-analyses/{analysis_id}', 'get', 200))
        for dto in (r, again, got):
            e = dto['explain']
            assert EXPLAIN_REQUIRED <= set(e) and e['diagnosis'] is None and e['data_label'] == 'SYNTHETIC'
            assert e['validation_status']['hardware_verified'] is False
        assert got['explain'] == r['explain']                  # deterministic, read-time
        # the explanation is part of the SAME DTO — there is no separate explanation route
        assert call('GET', f'/api/phantom-analyses/{r["analysis_id"]}/explain', token=alice.token)[0] in (404, 410)
        # Backend №2's own history keeps the stored result WITHOUT the read-time block
        from app import db
        with db.connect() as c:
            stored = c.execute('SELECT result FROM analysis_runs WHERE model=?', ('phantom_hr_univariate_1_4',)).fetchone()[0]
        assert '"explain"' not in stored
