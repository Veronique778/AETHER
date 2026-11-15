"""03A — every combination of quality × contact × data class × signal, through storage validation, the Backend №2
quality mapping (both ways) and the PHANTOM contact rule. Invariants (docs/SIGNAL_COMPATIBILITY_MATRIX.md §5):

  I1  contact = false (HR/RR, non-manual)       → never valid, never analysed
  I2  contact unknown (null / key missing)      → never 'good'
  I3  'unverified' (and every non-VALID quality) → never valid
  I4  BE3 → Backend №2 → BE3 never raises confidence; 'good' survives only with contact = true
  I5  an unknown Backend №2 quality             → 'rejected' (fail closed)
  I6  contact of a non-boolean type             → 422 at storage time, 'rejected' at analysis time
"""
import itertools

import pytest

from app import phantom_analyses as pa
from app import signal_compat as sc
from app import signals
from app.science_errors import InvalidInput
from helpers_be3_signals_15 import P1

RANK = {'good': 3, 'screened': 2, 'degraded': 1, 'unverified': 1}           # everything else: 0
MISSING = object()
CONTACTS = [True, False, None, MISSING]
QUALITIES = list(signals.QUALITY)
CLASSES = ['real_wearable', 'manual', 'synthetic']
SIGNALS = [('heart_rate', 'bpm', 62.0), ('rr_interval', 'ms', 950.0), ('reaction_ms', 'ms', 300.0)]


def _item(sig, unit, val, q, dc, contact):
    prov = {} if contact is MISSING else {'contact': contact}
    v = None if q == 'missing' else val
    return {'astronaut_id': P1, 'signal': sig, 'unit': unit, 'value': v, 'recorded_at': '2026-11-10T06:30:00Z',
            'data_class': dc, 'source': 'matrix', 'quality': q, 'provenance': prov, 'client_measurement_id': 'k'}


CASES = list(itertools.product(SIGNALS, QUALITIES, CLASSES, CONTACTS))


@pytest.mark.parametrize('sigdef,q,dc,contact', CASES,
                         ids=[f'{s[0]}-{q}-{dc}-{"missing" if c is MISSING else c}' for s, q, dc, c in CASES])
def test_matrix(sigdef, q, dc, contact):
    sig, unit, val = sigdef
    out = signals.validate_item(_item(sig, unit, val, q, dc, contact))
    contact_signal = sig in pa.CONTACT_SIGNALS and dc != 'manual'
    eq, ev = out['quality'], out['valid']
    # storage-time invariants
    if contact_signal and contact is False:
        assert not ev and eq in ('no_contact', 'missing')                                 # I1
    if contact_signal and contact in (None, MISSING):
        assert eq != 'good'                                                               # I2
    if q not in signals.VALID_QUALITY:
        assert not ev                                                                     # I3
    assert RANK.get(eq, 0) <= RANK.get(q, 0)                                              # never upgraded
    # analysis-time rule (same rule again, on what storage returns)
    aq, av, _ = pa.contact_rule(sig, dc, eq, ev, out['provenance'])
    if contact_signal and contact is False:
        assert not av
    if contact_signal and contact in (None, MISSING):
        assert aq != 'good'
    assert RANK.get(aq, 0) <= RANK.get(eq, 0) and (av <= ev)
    # Backend №2 round trip
    if dc in sc.TO_BE2_ORIGIN:
        from app.science_storage_be2 import from_be2_row, to_be2_item
        be2 = to_be2_item(out)
        assert be2['quality'] in sc.BE2_QUALITIES
        back = from_be2_row({**be2, 'id': 'm', 'received_at': '2026-11-10T06:31:00Z'})
        assert RANK.get(back['quality'], 0) <= RANK.get(eq, 0)                            # I4
        if back['quality'] == 'good':
            assert out['provenance'].get('contact') is True
        if contact_signal and contact is False:
            assert not back['valid']
        if q not in signals.VALID_QUALITY:
            assert not back['valid']


@pytest.mark.parametrize('bad', ['yes', 1, 0, 'true', [True], {'v': True}])
def test_non_boolean_contact(bad):
    with pytest.raises(InvalidInput):                                                     # I6 storage
        signals.validate_item(_item('heart_rate', 'bpm', 62.0, 'good', 'real_wearable', bad))
    q, v, key = pa.contact_rule('heart_rate', 'real_wearable', 'good', True, {'contact': bad})
    assert (q, v, key) == ('rejected', False, 'invalid_contact_metadata')                 # I6 analysis


@pytest.mark.parametrize('be2q', ['validated', 'legacy_unverified', 'nonsense', '', None, 'GOOD', 'good'])
def test_be2_quality_from_outside_is_never_good(be2q):
    q = sc.from_be2_quality(be2q, 62.0, {})
    assert q != 'good'
    if be2q not in sc.BE2_QUALITIES and be2q != 'legacy_unverified':
        assert q == 'rejected'                                                            # I5
    if be2q == 'validated':
        assert q == 'screened'                                    # 'validated' is not clinical validation


@pytest.mark.parametrize('claimed,stored,contact,expected', [
    ('good', 'screened', True, 'good'), ('good', 'screened', None, 'screened'), ('good', 'screened', False, 'screened'),
    ('good', 'unverified', True, 'unverified'),                  # inconsistent claim → Backend №2 value wins
    ('good', 'rejected', True, 'rejected'), ('degraded', 'unverified', True, 'degraded'),
    ('screened', 'screened', None, 'screened'), (None, 'screened', True, 'screened'),
])
def test_be3_quality_claim_honoured_only_if_consistent(claimed, stored, contact, expected):
    md = {'contact': contact} if contact is not None else {}
    if claimed:
        md['be3_quality'] = claimed
    assert sc.from_be2_quality(stored, 62.0, md) == expected


def test_connection_lost_without_value_is_missing():
    assert sc.from_be2_quality('connection_lost', None, {}) == 'missing'
    assert sc.from_be2_quality('connection_lost', 62.0, {}) == 'rejected'
