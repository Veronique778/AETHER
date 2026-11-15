"""AETHER 1.5 — signal registry and measurement validation (app/signals.py)."""
import math

import pytest

from app import signals
from app.science_errors import InvalidInput, InvalidUnits, TimestampWithoutOffset, UnsupportedSignal, ValueOutOfRange
from helpers_be3_signals_15 import P1, P2, P3, P4

BASE = {'astronaut_id': P1, 'signal': 'heart_rate', 'value': 64, 'unit': 'bpm', 'recorded_at': '2026-11-20T06:30:00Z',
        'data_class': 'manual', 'source': 'manual form'}


def item(**kw):
    return {**BASE, **kw}


def test_registry_lists_only_operational_signals():
    r = signals.registry()
    ids = [s['signal'] for s in r['signals']]
    # 03A: canonical ids = Backend №2 storage names (docs/SIGNAL_COMPATIBILITY_MATRIX.md)
    assert ids == ['heart_rate', 'rr_interval', 'sleep_duration', 'fatigue_1_10', 'reaction_ms', 'activity_minutes']
    assert {'spo2', 'skin_temperature', 'respiratory_rate'} == {s['signal'] for s in r['not_operational']}
    for s in r['signals']:
        assert {'signal', 'unit', 'label', 'plausible_min', 'plausible_max', 'legacy_key', 'sources', 'value_type',
                'required_metadata', 'quality_rules', 'limitations'} <= set(s)
    assert r['registry_version'] == '1.5.1' and r['conversions']


def test_valid_manual_item_is_normalised_to_utc():
    out = signals.validate_item(item(recorded_at='2026-11-20T08:30:00+02:00'))
    # 03A: manual entries default to 'unverified' (never an implicit 'good'); explicit quality is kept
    assert out['recorded_at'] == '2026-11-20T06:30:00.000Z' and not out['missing'] and out['quality'] == 'unverified' and not out['valid']
    assert signals.validate_item(item(quality='good'))['valid']


@pytest.mark.parametrize('sig,unit', [('spo2', 'percent'), ('skin_temperature', 'degC'), ('breathing_rate', 'breaths_per_min'),
                                      ('respiratory_rate', 'breaths/min'), ('glucose', 'mmol/L')])
def test_unsupported_signals_rejected(sig, unit):
    with pytest.raises(UnsupportedSignal):          # not operational (no AETHER source) or unknown
        signals.validate_item(item(signal=sig, unit=unit))


@pytest.mark.parametrize('sig,unit', [('heart_rate', 'Hz'), ('rr_interval', 's'), ('sleep_duration', 'min'), ('heart_rate', None)])
def test_wrong_units_rejected_never_converted(sig, unit):
    with pytest.raises(InvalidUnits) as e:
        signals.validate_item(item(signal=sig, unit=unit, value=1))
    assert e.value.code == 'unit_mismatch' and e.value.field == 'items[0].unit'


def test_missing_value_is_stored_as_missing():
    out = signals.validate_item(item(value=None))
    assert out['quality'] == 'missing' and out['missing'] and not out['valid'] and out['value'] is None


@pytest.mark.parametrize('v', [math.nan, math.inf, -math.inf, '64', True])
def test_nan_inf_and_non_numbers_rejected(v):
    with pytest.raises(InvalidInput):
        signals.validate_item(item(value=v))


def test_manual_out_of_range_rejected_but_device_out_of_range_kept():
    with pytest.raises(ValueOutOfRange):
        signals.validate_item(item(value=400))
    out = signals.validate_item(item(value=400, data_class='real_wearable', quality='screened'))
    assert out['quality'] == 'out_of_range' and not out['valid'] and out['value'] == 400


def test_timestamp_without_offset_rejected():
    with pytest.raises(TimestampWithoutOffset):
        signals.validate_item(item(recorded_at='2026-11-20T06:30:00'))


def test_null_time_only_with_original_timestamp():
    with pytest.raises(InvalidInput):
        signals.validate_item(item(recorded_at=None))
    out = signals.validate_item(item(recorded_at=None, original_timestamp='day 2 12:00', data_class='terrestrial_research', quality='screened'))
    assert out['recorded_at'] is None


def test_non_manual_requires_explicit_quality():
    with pytest.raises(InvalidInput):
        signals.validate_item(item(data_class='real_wearable'))


def test_unknown_data_class_and_bad_astronaut():
    with pytest.raises(InvalidInput):
        signals.validate_item(item(data_class='nasa'))
    with pytest.raises(InvalidInput):
        signals.validate_item(item(astronaut_id='a01'))


def test_quality_missing_with_value_is_inconsistent():
    with pytest.raises(InvalidInput):
        signals.validate_item(item(quality='missing'))
