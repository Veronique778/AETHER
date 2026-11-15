"""AETHER 1.5 — regression tests for the independent QA review of BE3_02 (package 02A).
Each section reproduces one reported defect first, then checks the fix. All series are SYNTHETIC test fixtures."""
import copy
import json
import random
from collections import Counter

import pytest

from app import biosignals, db, phantom_analyses as pa, signals
from app.analytics import analyze
from app.db import SEED_SHIFTS, seed_row
from app.phantom2 import confusion
from app.science_errors import Forbidden, InvalidInput, StorageUnavailable
from fakes.storage_fake import FakeContext, FakeStorage
from datetime import timedelta

from helpers_be3_signals_15 import T0 as HT0, hr_series, span, store
from helpers_be3_signals_15 import P1, P2, P3, P4

CTX = FakeContext(user_id='a' * 32, astronaut_ids=frozenset({P1}))
T0 = 1_800_000_000.0


def _item(t, v=62.0, ok=True, q='screened', contact=True, mid='m'):
    return (t, 'heart_rate', v, ok, q, contact, mid, 'real_wearable', None, None)


def _window(items):
    return pa._windows(items, T0, T0 + 300)[0]


# ============================================================ 02A-1  coverage of VALID samples
def test_reviewer_case_burst_plus_invalid_tail_is_not_usable():
    items = [_item(T0 + i * 2, mid=f'v{i}') for i in range(20)]                      # 20 valid within 38 s
    items += [_item(T0 + 250 + i * 10, ok=False, q='no_contact', contact=False, mid=f'x{i}') for i in range(5)]
    w = _window(items)
    assert w['valid'] == 20 and w['samples'] == 25 and w['valid_fraction'] == 0.8
    assert w['valid_span_s'] == 38 and w['mean_hr_bpm'] is None and w['unusable_reason'] == 'coverage_too_short'


def test_invalid_rows_never_extend_coverage():
    valid = [_item(T0 + i * 2, mid=f'v{i}') for i in range(100)]
    tail = [_item(T0 + 280, ok=False, q='corrupt', mid='bad')]
    assert _window(valid)['valid_span_s'] == _window(valid + tail)['valid_span_s'] == 198


def test_internal_gap_longer_than_60s_rejects_window():
    items = [_item(T0 + i * 2, mid=f'a{i}') for i in range(60)]                      # 0..118 s
    items += [_item(T0 + 200 + i * 2, mid=f'b{i}') for i in range(50)]               # 200..298 s → gap 82 s
    w = _window(items)
    assert w['valid_span_s'] >= 240 and w['max_valid_gap_s'] == 82 and w['unusable_reason'] == 'gap_too_long'


@pytest.mark.parametrize('gap,usable', [(60.0, True), (60.5, False)])
def test_gap_boundary(gap, usable):
    items = [_item(T0 + i * 2, mid=f'a{i}') for i in range(60)]
    last = T0 + 118
    items += [_item(last + gap + i * 2, mid=f'b{i}') for i in range(int((300 - 118 - gap) // 2))]
    assert (_window(items)['mean_hr_bpm'] is not None) is usable


def test_regular_2s_stream_still_usable_and_uniformity_reported():
    w = _window([_item(T0 + i * 2, mid=f'v{i}') for i in range(150)])
    assert w['mean_hr_bpm'] == 62.0 and w['median_interval_s'] == 2 and w['max_valid_gap_s'] == 2


def test_irregular_stream_with_bounded_gaps_is_usable():
    rng = random.Random(4); t = T0; items = []
    while t < T0 + 299:
        items.append(_item(t, mid=str(t))); t += rng.uniform(1, 14)
    w = _window(items)
    assert w['mean_hr_bpm'] is not None and w['max_valid_gap_s'] <= 14


def test_low_frequency_device_gives_insufficient_data():
    st = FakeStorage()
    rows = [r for r in hr_series(every_s=60, rr=False)]                                 # 1 sample per minute
    store(st, CTX, rows)
    code, r = pa.run(CTX, {'astronaut_id': P1, 'from': span(90)[0], 'to': span(90)[1]}, st)
    assert r['outcome'] == 'insufficient_data'
    assert {w['unusable_reason'] for w in r['windows']} == {'too_few_samples'}


def test_legacy_biosignal_adapter_has_the_same_fix(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'bio.sqlite3')
    db.init_db(); biosignals.init()
    sid = biosignals.create('test', 'live_sensor', 'test fixture')
    rows = [biosignals.measurement(T0 + i * 2, 'heart_rate', 62.0, 'bpm', quality='screened') for i in range(20)]
    rows += [biosignals.measurement(T0 + 250 + i * 10, 'heart_rate', 62.0, 'bpm', quality='no_contact') for i in range(5)]
    biosignals.append(sid, rows); biosignals.finish(sid, 'ready')
    w = biosignals.analyze(sid)['windows'][0]
    assert w['valid'] == 20 and w['valid_span_s'] == 38 and w['mean_hr_bpm'] is None


# ============================================================ 02A-2  sensor contact consistency
@pytest.mark.parametrize('contact,quality,valid,expect', [
    (True, 'good', True, ('good', True, None)),
    (False, 'good', True, ('no_contact', False, 'no_contact_reported')),
    (False, 'screened', True, ('no_contact', False, 'no_contact_reported')),
    (None, 'good', True, ('screened', True, 'quality_capped_contact_not_reported')),
    ('missing', 'good', True, ('screened', True, 'quality_capped_contact_not_reported')),
    (None, 'screened', True, ('screened', True, None)),
    ('yes', 'good', True, ('rejected', False, 'invalid_contact_metadata')),
    (1, 'good', True, ('rejected', False, 'invalid_contact_metadata')),
    (True, 'no_contact', False, ('no_contact', False, 'contradictory_contact_quality')),
])
@pytest.mark.parametrize('signal', ['heart_rate', 'rr_interval'])
def test_contact_rule_matrix(signal, contact, quality, valid, expect):
    prov = {} if contact == 'missing' else {'contact': contact}
    assert pa.contact_rule(signal, 'real_wearable', quality, valid, prov) == expect


def test_contact_rule_not_applied_to_manual_entries():
    assert pa.contact_rule('heart_rate', 'manual', 'good', True, {}) == ('good', True, None)


def _raw(v=62.0, **kw):
    base = {'astronaut_id': P1, 'status': 'active', 'data_class': 'real_wearable', 'signal': 'heart_rate', 'unit': 'bpm',
            'recorded_at': '2026-11-20T08:00:00Z', 'value': v, 'valid': True, 'quality': 'good',
            'provenance': {'contact': True}, 'measurement_id': 'm'}
    return {**base, **kw}


def test_reviewer_case_contact_false_quality_good_is_rejected():
    c = Counter()
    out = pa._screen([_raw(provenance={'contact': False})], P1, ['real_wearable'], c)
    assert out[0][3] is False and out[0][4] == 'no_contact' and c['no_contact_reported'] == 1


def test_contradictory_valid_flags_never_make_a_sample_valid():
    c = Counter()
    out = pa._screen([_raw(quality='rejected'), _raw(valid=False), _raw(value=float('nan'))], P1, ['real_wearable'], c)
    assert [x[3] for x in out] == [False, False, False] and c['valid_flag_inconsistent'] == 2


def test_contact_false_stream_end_to_end_is_insufficient():
    class RawStore(FakeStorage):          # returns rows exactly as an inconsistent writer stored them
        def query_measurements(self, ctx, astronaut_id, **kw):
            page = super().query_measurements(ctx, astronaut_id, **kw)
            page['items'] = [{**x, 'quality': 'good', 'valid': True, 'provenance': {'contact': False}} for x in page['items']]
            return page
    st = RawStore(); store(st, CTX, hr_series())
    code, r = pa.run(CTX, {'astronaut_id': P1, 'from': span(90)[0], 'to': span(90)[1]}, st)
    assert r['outcome'] == 'insufficient_data' and r['input']['valid_count'] == 0
    assert r['input']['excluded']['no_contact_reported'] == 5400


def test_contact_not_reported_is_never_good_in_analysis():
    class RawStore(FakeStorage):
        def query_measurements(self, ctx, astronaut_id, **kw):
            page = super().query_measurements(ctx, astronaut_id, **kw)
            page['items'] = [{**x, 'quality': 'good', 'provenance': {}} for x in page['items']]
            return page
    st = RawStore(); store(st, CTX, hr_series())
    code, r = pa.run(CTX, {'astronaut_id': P1, 'from': span(90)[0], 'to': span(90)[1]}, st)
    assert 'good' not in r['signal_quality']['quality_counts'] and r['outcome'] == 'flag'
    assert r['input']['excluded']['quality_capped_contact_not_reported'] == 5400


@pytest.mark.parametrize('contact,quality,expect', [(False, 'good', ('no_contact', False)), (None, 'good', ('screened', True)),
                                                    (True, 'good', ('good', True))])
def test_storage_validation_applies_the_same_rule(contact, quality, expect):
    out = signals.validate_item({'astronaut_id': P1, 'signal': 'rr_interval', 'value': 800, 'unit': 'ms',
                                 'recorded_at': '2026-11-20T08:00:00Z', 'data_class': 'real_wearable', 'source': 'test',
                                 'quality': quality, 'provenance': {'contact': contact}})
    assert (out['quality'], out['valid']) == expect


def test_storage_validation_rejects_non_boolean_contact():
    with pytest.raises(InvalidInput):
        signals.validate_item({'astronaut_id': P1, 'signal': 'heart_rate', 'value': 60, 'unit': 'bpm',
                               'recorded_at': '2026-11-20T08:00:00Z', 'data_class': 'real_wearable', 'source': 't',
                               'quality': 'good', 'provenance': {'contact': 'yes'}})


# ============================================================ 02A-3  measurement digest
@pytest.mark.parametrize('field,value', [
    ('data_class', 'synthetic'), ('unit', 'Hz'), ('quality', 'screened'), ('recorded_at', '2026-11-20T08:00:01Z'),
    ('value', 62.5), ('valid', False), ('source', 'other device'), ('provenance', {'contact': None}),
    ('signal', 'rr_interval'), ('session_id', 'f' * 32), ('device_id', 'd' * 32), ('status', 'invalidated'),
])
def test_digest_changes_with_every_relevant_field(field, value):
    assert pa.measurement_digest([_raw()]) != pa.measurement_digest([_raw(**{field: value})])


def test_reviewer_case_data_class_change_changes_digest_and_result_hash():
    a, b = _raw(), _raw(data_class='synthetic')
    assert pa.measurement_digest([a]) != pa.measurement_digest([b])


def test_digest_is_independent_of_key_order_row_order_and_time_notation():
    r1, r2 = _raw(measurement_id='m1'), _raw(measurement_id='m2', value=70.0)
    reordered = dict(reversed(list(r1.items())))
    assert pa.measurement_digest([r1, r2]) == pa.measurement_digest([r2, reordered])
    assert pa.measurement_digest([r1]) == pa.measurement_digest([_raw(measurement_id='m1', recorded_at='2026-11-20T10:00:00+02:00')])


def test_digest_excludes_secrets_and_server_metadata():
    extra = _raw(created_by='u' * 32, received_at='2030-01-01T00:00:00Z',
                 provenance={'contact': True, 'token': 'secret', 'password': 'x'})
    assert pa.measurement_digest([_raw()]) == pa.measurement_digest([extra])
    canon = json.dumps(pa.canonical_row(extra, 'analysis'))
    assert 'secret' not in canon and 'created_by' not in canon and 'received_at' not in canon


def test_digest_handles_nan_and_non_numeric_without_crashing():
    d1 = pa.measurement_digest([_raw(value=float('nan'))])
    d2 = pa.measurement_digest([_raw(value='62')])
    assert len(d1) == len(d2) == 64 and d1 != d2


def test_result_carries_schema_versions_and_analysis_digest():
    st = FakeStorage(); store(st, CTX, hr_series())
    code, r = pa.run(CTX, {'astronaut_id': P1, 'from': span(90)[0], 'to': span(90)[1]}, st)
    assert r['input']['digest_schema'] == 'aether-measurement-digest-v1'
    assert r['reproducibility']['digest_schema'] == 'aether-analysis-digest-v1' and len(r['reproducibility']['analysis_digest']) == 64
    assert r['input']['fetched_count'] == 5400


def test_excluded_rows_still_change_the_digest():
    st = FakeStorage(); store(st, CTX, hr_series(minutes=40)); store(st, CTX, hr_series(minutes=40, data_class='synthetic'))
    st2 = FakeStorage(); st2.db = copy.deepcopy(st.db)
    for m in st2.db['measurements'].values():
        if m['data_class'] == 'synthetic':
            m['value'] += 1
    body = {'astronaut_id': P1, 'from': span(90)[0], 'to': span(90)[1]}
    a, b = pa.run(CTX, body, st)[1], pa.run(CTX, body, st2)[1]
    assert a['outcome'] == b['outcome'] and a['input']['measurement_digest'] != b['input']['measurement_digest']


# ============================================================ 02A-4  pagination with filters
def _seed_analyses(st, n=23):
    admin = FakeContext(role='admin', user_id='z' * 32)
    expected = []
    outs = ['flag', 'no_flag', 'insufficient_data']
    for i in range(n):
        aid = P1 if i % 3 else P2
        a_id = f'{i:032x}'
        payload = {'outcome': outs[(i * 7) % 3], 'astronaut_id': aid, 'created_at': f'2026-11-20T08:{i // 2:02d}:00.000Z',
                   'windows': [1, 2]}
        st.save_analysis_bundle(admin, 'phantom_personal', aid, payload, idempotency_key=a_id,
                                record={'kind': 'phantom_analysis', 'ref_ids': [a_id], 'astronaut_id': aid, 'data_class': 'derived', 'summary': ''},
                                audit={'action': 'x', 'target_kind': 'phantom_analysis', 'target_id': a_id, 'outcome': 'success'})
        expected.append((payload['created_at'], a_id, aid, payload['outcome']))
    expected.sort(reverse=True)
    return expected


def _walk(ctx, st, **q):
    got, cursor, pages = [], None, 0
    while True:
        query = {**{k: v for k, v in q.items() if v is not None}, **({'cursor': cursor} if cursor else {})}
        page = pa.list_analyses(ctx, query, st)
        got += [a['analysis_id'] for a in page['items']]
        assert all('windows' not in a for a in page['items'])
        pages += 1
        cursor = page['next_cursor']
        if not cursor:
            return got, pages
        assert pages < 100


def test_reviewer_case_filter_before_pagination():
    st = FakeStorage()
    for i, (out, t) in enumerate((('flag', '08:00'), ('no_flag', '09:00'))):
        st.save_analysis_bundle(CTX, 'phantom_personal', P1, {'outcome': out, 'astronaut_id': P1, 'created_at': f'2026-11-20T{t}:00.000Z'},
                                idempotency_key=f'{i:032x}', record={'kind': 'k', 'ref_ids': [], 'astronaut_id': P1, 'data_class': 'derived', 'summary': ''},
                                audit={'action': 'x', 'target_kind': 'x', 'target_id': None, 'outcome': 'success'})
    page = pa.list_analyses(CTX, {'outcome': 'flag', 'limit': '1'}, st)
    assert [a['outcome'] for a in page['items']] == ['flag'] and page['next_cursor'] is None


@pytest.mark.parametrize('limit', [1, 2, 3, 7, 500])
@pytest.mark.parametrize('outcome', [None, 'flag', 'no_flag', 'insufficient_data'])
def test_pages_have_no_duplicates_or_gaps(limit, outcome, monkeypatch):
    monkeypatch.setattr(pa, 'SCAN_PAGE', 4)                    # force many storage pages
    st = FakeStorage(); exp = _seed_analyses(st)
    admin = FakeContext(role='admin', user_id='z' * 32)
    got, _ = _walk(admin, st, outcome=outcome, limit=str(limit))
    want = [e[1] for e in exp if outcome is None or e[3] == outcome]
    assert got == want and len(set(got)) == len(got)


def test_role_and_astronaut_isolation_in_lists(monkeypatch):
    monkeypatch.setattr(pa, 'SCAN_PAGE', 5)
    st = FakeStorage(); exp = _seed_analyses(st)
    got, _ = _walk(CTX, st, limit='2')                            # crew A01, no astronaut filter
    assert got == [e[1] for e in exp if e[2] == P1]
    got, _ = _walk(CTX, st, astronaut_id=P1, outcome='flag', limit='1')
    assert got == [e[1] for e in exp if e[2] == P1 and e[3] == 'flag']
    with pytest.raises(Forbidden):
        pa.list_analyses(CTX, {'astronaut_id': P2}, st)


def test_cursor_cannot_be_tampered_or_reused_with_other_filters():
    st = FakeStorage(); _seed_analyses(st)
    admin = FakeContext(role='admin', user_id='z' * 32)
    cur = pa.list_analyses(admin, {'outcome': 'flag', 'limit': '1'}, st)['next_cursor']
    with pytest.raises(InvalidInput):
        pa.list_analyses(admin, {'outcome': 'no_flag', 'cursor': cur}, st)
    with pytest.raises(InvalidInput):
        pa.list_analyses(admin, {'cursor': 'not-a-cursor'}, st)


def test_scan_limit_returns_partial_page_with_cursor_and_completes(monkeypatch):
    monkeypatch.setattr(pa, 'SCAN_PAGE', 3); monkeypatch.setattr(pa, 'MAX_SCAN', 4)
    st = FakeStorage(); exp = _seed_analyses(st)
    admin = FakeContext(role='admin', user_id='z' * 32)
    first = pa.list_analyses(admin, {'outcome': 'flag', 'limit': '50'}, st)
    assert first['scan_truncated'] and first['next_cursor']
    got, _ = _walk(admin, st, outcome='flag', limit='50')
    assert got == [e[1] for e in exp if e[3] == 'flag']


# ============================================================ 02A-5  atomic, idempotent persistence
def _body():
    f, t = span(90)
    return {'astronaut_id': P1, 'from': f, 'to': t}


def _counts(st):
    return (len(st.db['analyses']), sum(r['kind'] == 'phantom_analysis' for r in st.db['records']),
            sum(a['action'] == 'phantom_analysis.create' for a in st.db['audit']))


@pytest.mark.parametrize('stage', ['save_analysis_bundle', 'bundle:after_analysis', 'bundle:after_record'])
def test_failure_at_each_stage_leaves_nothing_and_retry_succeeds(stage, tmp_path):
    p = tmp_path / 's.json'
    st = FakeStorage(p); store(st, CTX, hr_series())
    before = _counts(st)
    st.fail_next = stage
    with pytest.raises(StorageUnavailable) as e:
        pa.run(CTX, _body(), st)
    assert 'safe to resend' in e.value.message
    assert _counts(st) == before == _counts(FakeStorage(p)) == (0, 0, 0)          # also after a restart
    code, r = pa.run(CTX, _body(), st)
    assert code == 201 and _counts(st) == (1, 1, 1) and _counts(FakeStorage(p)) == (1, 1, 1)


def test_lost_acknowledgement_then_retry_is_an_idempotent_replay(tmp_path):
    p = tmp_path / 's.json'
    st = FakeStorage(p); store(st, CTX, hr_series())
    st.fail_next = 'bundle:after_commit'
    with pytest.raises(StorageUnavailable):
        pa.run(CTX, _body(), st)
    assert _counts(st) == (1, 1, 1)
    restarted = FakeStorage(p)
    code, r = pa.run(CTX, _body(), restarted)                            # retry after a restart
    assert code == 200 and r['idempotent_replay'] is True and len(r['analysis_id']) == 32
    assert _counts(FakeStorage(p)) == (1, 1, 1)


def test_resend_after_success_creates_no_duplicate():
    st = FakeStorage(); store(st, CTX, hr_series())
    c1, a = pa.run(CTX, _body(), st)
    c2, b = pa.run(CTX, _body(), st)
    assert (c1, c2) == (201, 200) and a['analysis_id'] == b['analysis_id'] and b['idempotent_replay']
    assert {k: v for k, v in a.items() if k != 'idempotent_replay'} == {k: v for k, v in b.items() if k != 'idempotent_replay'}
    assert _counts(st) == (1, 1, 1)


def test_new_data_or_other_user_gives_a_new_analysis():
    st = FakeStorage(); store(st, CTX, hr_series())
    a = pa.run(CTX, _body(), st)[1]
    surgeon = FakeContext(user_id='s' * 32, role='flight_surgeon', astronaut_ids=frozenset({P1}))
    b = pa.run(surgeon, _body(), st)[1]
    store(st, CTX, hr_series(minutes=1, seed=99, start=HT0 + timedelta(minutes=30)))     # one more minute of data
    c = pa.run(CTX, _body(), st)[1]
    assert len({a['analysis_id'], b['analysis_id'], c['analysis_id']}) == 3 and _counts(st) == (3, 3, 3)


def test_storage_without_atomic_bundle_fails_closed():
    class LegacyStorage(FakeStorage):
        save_analysis_bundle = None
    st = LegacyStorage(); store(st, CTX, hr_series()); st.calls.clear()
    with pytest.raises(StorageUnavailable) as e:
        pa.run(CTX, _body(), st)
    assert 'A-11' in e.value.message and _counts(st) == (0, 0, 0) and 'query_measurements' not in st.calls


# ============================================================ §6 consistency of states on incomplete data
def test_personal_flag_states_its_limited_scope():
    st = FakeStorage(); store(st, CTX, hr_series())
    r = pa.run(CTX, _body(), st)[1]
    assert r['outcome'] == 'flag' and r['assessment_scope']['complete_assessment'] is False
    assert 'not an overall health assessment' in r['assessment_scope']['statement'] and 'Only heart rate' in r['explanation']


def test_phantom1_flag_on_partial_data_says_incomplete():
    cols = ('astronaut_id', 'day', 'heart_rate_bpm', 'sleep_hours', 'fatigue_1_10', 'reaction_ms', 'activity_minutes', 'source')
    h = [dict(zip(cols, seed_row('A01', dict(SEED_SHIFTS)['A01'], d))) for d in range(1, 68)]
    h[-1] = {**h[-1], 'sleep_hours': None, 'fatigue_1_10': None}
    r = analyze(h, 67)
    assert r['status'] == 'attention' and 'not a complete assessment' in r['explanation']
    full = analyze([dict(zip(cols, seed_row('A01', dict(SEED_SHIFTS)['A01'], d))) for d in range(1, 68)], 67)
    assert 'not a complete assessment' not in full['explanation']      # full-data text unchanged (TS parity)


def test_phantom2_daily_reports_assessment_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'p.sqlite3'); db.init_db()
    from app import phantom2_daily
    with db.connect() as c:
        c.execute("UPDATE measurements SET sleep_hours=NULL WHERE astronaut_id='A01' AND day=67")
    r = phantom2_daily.analyze('A01', 67, bootstrap=5)
    assert r['assessment_scope']['complete_assessment'] is False and 'sleep_hours' not in r['assessment_scope']['signals_assessed']


# ============================================================ D5 (audit) additive decided-only rates
def test_confusion_decided_rates():
    c = confusion([None, None, True, False], [False] * 4)
    assert c['fpr'] == 0.25 and c['fpr_decided'] == 0.5 and c['decided'] == 2 and c['abstention_rate'] == 0.5
    c = confusion([True, False, None, True], [True, True, False, False])
    assert (c['tp'], c['fn'], c['tn'], c['fp'], c['abstained']) == (1, 1, 1, 1, 1)       # 1.4 counts unchanged
    assert c['recall_decided'] == 0.5 and c['fnr_decided'] == 0.5
