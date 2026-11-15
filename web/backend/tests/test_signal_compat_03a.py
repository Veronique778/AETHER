"""03A — signal names, units, conversions and provenance between Backend №2 storage and Backend №3 science.
Reference: docs/SIGNAL_COMPATIBILITY_MATRIX.md."""
import math

import pytest

from app import signal_compat as sc
from app import signals
from app.science_errors import InvalidInput, InvalidUnits, UnsupportedSignal
from helpers_be3_signals_15 import P1

T = '2026-11-10T06:30:00Z'


def item(**kw):
    base = {'astronaut_id': P1, 'signal': 'heart_rate', 'value': 61.0, 'unit': 'bpm', 'recorded_at': T,
            'data_class': 'manual', 'source': 'manual form', 'quality': 'screened'}
    base.update(kw)
    return base


def test_be2_signal_table_is_mirrored_exactly():
    pytest.importorskip('pydantic')
    from app import schemas_15
    be2 = schemas_15.SIGNALS
    for sig, (unit, lo, hi) in sc.BE2_STORAGE.items():
        assert sig in be2, sig
        got = be2[sig]
        u, glo, ghi = (got if isinstance(got, tuple) else (got['unit'], got['min'], got['max']))[:3]
        assert (u, glo, ghi) == (unit, lo, hi), sig
    for sig in signals.OPERATIONAL:
        assert sig in sc.BE2_STORAGE and signals.OPERATIONAL[sig]['unit'] == sc.BE2_STORAGE[sig][0]


@pytest.mark.parametrize('h,s', [(0, 0), (7.5, 27000), (8, 28800), (0.25, 900), (24, 86400)])
def test_hours_seconds_both_ways(h, s):
    assert sc.hours_to_seconds(h) == s and sc.seconds_to_hours(s) == h


@pytest.mark.parametrize('raw,ms', [(1024, 1000.0), (512, 500.0), (0, 0.0), (1, 1000 / 1024), (0xFFFF, 0xFFFF * 1000 / 1024)])
def test_rr_raw_1_1024_s(raw, ms):
    assert math.isclose(sc.rr_raw_to_ms(raw), ms)


@pytest.mark.parametrize('raw', [-1, 0x10000, 1.5, True, None, '1024'])
def test_rr_raw_invalid(raw):
    with pytest.raises(InvalidInput):
        sc.rr_raw_to_ms(raw)


@pytest.mark.parametrize('sig,unit,val,to_sig,to_unit,to_val', [
    ('sleep_hours', 'h', 7.5, 'sleep_duration', 's', 27000.0),
    ('sleep_duration', 'h', 6.0, 'sleep_duration', 's', 21600.0),
    ('sleep_duration', 's', 21600.0, 'sleep_duration', 's', 21600.0),
    ('fatigue', 'score_1_10', 4, 'fatigue_1_10', 'score', 4.0),
    ('fatigue_1_10', 'score_1_10', 4, 'fatigue_1_10', 'score', 4.0),
    ('fatigue_1_10', 'score', 4.0, 'fatigue_1_10', 'score', 4.0),
    ('reaction_time', 'ms', 310, 'reaction_ms', 'ms', 310.0),
    ('activity_duration', 'min', 45, 'activity_minutes', 'min', 45.0),
    ('heart_rate_bpm', 'bpm', 62, 'heart_rate', 'bpm', 62.0),
])
def test_conversions_keep_the_original(sig, unit, val, to_sig, to_unit, to_val):
    out = signals.validate_item(item(signal=sig, unit=unit, value=val))
    assert (out['signal'], out['unit'], out['value']) == (to_sig, to_unit, to_val)
    prov = out['provenance']
    if (sig, unit) != (to_sig, to_unit):
        assert prov['source_signal'] == sig and prov['source_unit'] == unit and prov['source_value'] == val
        assert prov['conversion']
    else:
        assert 'conversion' not in prov


def test_no_double_conversion():
    out = signals.validate_item(item(signal='sleep_hours', unit='h', value=7.0))
    assert out['value'] == 25200.0
    # re-submitting the already converted row with the OLD unit label must not multiply by 3600 again
    with pytest.raises(InvalidInput) as e:
        signals.validate_item(item(signal='sleep_duration', unit='h', value=25200.0, provenance=out['provenance']))
    assert e.value.code == 'double_conversion'
    # the converted row itself (canonical unit) passes unchanged
    again = signals.validate_item(item(signal='sleep_duration', unit='s', value=25200.0, provenance=out['provenance']))
    assert again['value'] == 25200.0


@pytest.mark.parametrize('sig,unit', [('heart_rate', 'percent'), ('heart_rate', 'bps'), ('rr_interval', 's'),
                                      ('sleep_duration', 'min'), ('fatigue_1_10', '%'), ('heart_rate_bpm', 'percent')])
def test_unknown_units_are_refused(sig, unit):
    with pytest.raises(InvalidUnits):
        signals.validate_item(item(signal=sig, unit=unit))


@pytest.mark.parametrize('sig', ['glucose', 'HEART_RATE', 'heart-rate', '', 'blood_pressure'])
def test_unknown_signals_refused(sig):
    with pytest.raises((UnsupportedSignal, InvalidInput)):
        signals.validate_item(item(signal=sig, unit='bpm'))


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), '61', True, [61]])
def test_bad_numbers_refused(value):
    with pytest.raises(InvalidInput):
        signals.validate_item(item(value=value))


def test_null_value_is_missing_not_zero():
    out = signals.validate_item(item(value=None, quality='missing'))
    assert out['value'] is None and out['missing'] and not out['valid']


def test_out_of_range_is_refused_or_kept_never_clipped():
    from app.science_errors import ValueOutOfRange
    with pytest.raises(ValueOutOfRange):                          # implausible input: 422, nothing stored
        signals.validate_item(item(value=400.0))
    # a value accepted by the BE3 registry but outside Backend №2's storage range is stored as null + original_value
    from app.science_storage_be2 import to_be2_item
    out = signals.validate_item(item(value=61.0))
    be2 = to_be2_item({**out, 'value': 400.0, 'client_measurement_id': 'k1'})
    assert be2['value'] is None and be2['quality'] == 'rejected' and be2['metadata']['original_value'] == 400.0


@pytest.mark.parametrize('dc,origin', [('real_wearable', 'real'), ('manual', 'manual'), ('synthetic', 'simulated')])
def test_origin_mapping(dc, origin):
    assert sc.to_be2_origin(dc) == origin


@pytest.mark.parametrize('dc,code', [('nasa_public', 'research_separate'), ('terrestrial_research', 'research_separate'),
                                     ('derived', 'derived_not_raw'), ('bogus', None)])
def test_research_and_derived_never_enter_the_personal_store(dc, code):
    with pytest.raises(InvalidInput) as e:
        sc.to_be2_origin(dc)
    if code:
        assert e.value.code == code


@pytest.mark.parametrize('origin,md,expected', [
    ('real', {'data_class': 'real_wearable'}, 'real_wearable'),
    ('real', {}, 'real_unclassified'), ('real', {'data_class': 'nasa_public'}, 'real_unclassified'),
    ('manual', {'data_class': 'real_wearable'}, 'manual'),        # metadata cannot upgrade a manual row
    ('simulated', {'data_class': 'real_wearable'}, 'synthetic'),  # … nor a simulated one
    ('research', {}, 'research_unclassified'), ('weird', {}, 'unknown')])
def test_data_class_from_be2_never_upgrades(origin, md, expected):
    assert sc.from_be2_data_class(origin, md) == expected


def test_manual_default_is_unverified_not_good():
    out = signals.validate_item({k: v for k, v in item().items() if k != 'quality'})
    assert out['quality'] == 'unverified' and not out['valid']


def test_measured_at_and_recorded_at_and_keys_round_trip():
    from app.science_storage_be2 import from_be2_row, to_be2_item
    out = signals.validate_item(item(data_class='real_wearable', quality='good', provenance={'contact': True},
                                     session_id='s-1', device_id='d-1', client_measurement_id='cm-1'))
    be2 = to_be2_item(out)
    assert be2['measured_at'] == out['recorded_at'] and be2['idempotency_key'] == 'cm-1' and be2['origin'] == 'real'
    back = from_be2_row({**be2, 'id': 'm-1', 'quality': be2['quality'], 'received_at': T})
    assert back['recorded_at'] == out['recorded_at'] and back['client_measurement_id'] == 'cm-1'
    assert back['data_class'] == 'real_wearable' and back['quality'] == 'good' and back['value'] == 61.0
    with pytest.raises(InvalidInput):
        to_be2_item({**out, 'client_measurement_id': None})       # Backend №2 needs an idempotency key
