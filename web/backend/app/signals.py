"""AETHER 1.5 signal registry (Backend №3) — `GET /api/signals` and measurement validation.

Registry 1.5.1 (package 03A): canonical signal ids and units are the Backend №2 STORAGE names (app.schemas_15.SIGNALS),
so a stored row never needs renaming. Older Backend №3 names / units (sleep in hours, `fatigue`, `reaction_time`,
`activity_duration`, `breathing_rate`, `heart_rate_bpm`) are accepted only through the explicit conversions of
app.signal_compat.CONVERSIONS, which record source_signal / source_unit / source_value / conversion in provenance.
Any other unit is refused (no silent conversion; RR in seconds is never assumed to be milliseconds).

A signal is `operational` only when AETHER has a source that really produces it. SpO₂ and respiratory rate are stored
by Backend №2 but have no supported AETHER source; skin temperature is not mapped (Backend №2 `temperature` is cabin
air temperature — a different quantity).

Astronaut ids: app.identity (personal UUID from Backend №2, or legacy demo A01–A9999 for synthetic data only).
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from . import identity, signal_compat
from .science_errors import InvalidInput, InvalidUnits, TimestampWithoutOffset, UnsupportedSignal, ValueOutOfRange

REGISTRY_VERSION = '1.5.1'

QUALITY = ('good', 'screened', 'degraded', 'unverified', 'no_contact', 'corrupt', 'out_of_range', 'rejected', 'missing')
VALID_QUALITY = ('good', 'screened', 'degraded')          # 'unverified' is stored but never treated as checked data
DATA_CLASSES = ('synthetic', 'manual', 'real_wearable', 'terrestrial_research', 'nasa_public', 'derived')
HEX32 = re.compile(r'^[0-9a-f]{32}$')
ASTRONAUT_ID = identity.LEGACY_RE              # kept for backward compatibility of imports; use identity.* instead

_SIGNALS = [
    {'signal': 'heart_rate', 'unit': 'bpm', 'label': 'Heart rate', 'value_type': 'number', 'plausible_min': 20,
     'plausible_max': 240, 'legacy_key': 'heart_rate_bpm', 'aliases': ['heart_rate_bpm'], 'operational': True,
     'sources': ['ble_hrs', 'manual', 'research_import', 'synthetic'],
     'required_metadata': ['recorded_at', 'source', 'data_class'],
     'quality_rules': ['outside plausible range → out_of_range (devices/imports) or 422 (manual entry)',
                       'BLE contact bit false → no_contact; contact not reported by the device → screened (never good)'],
     'limitations': 'BLE HRS heart rate is device-computed; AETHER cannot verify its algorithm. Not breathing rate.'},
    {'signal': 'rr_interval', 'unit': 'ms', 'label': 'RR interval', 'value_type': 'number', 'plausible_min': 250,
     'plausible_max': 2500, 'legacy_key': None, 'aliases': [], 'operational': True,
     'sources': ['ble_hrs', 'research_import', 'synthetic'],
     'required_metadata': ['recorded_at', 'source', 'data_class', 'provenance.clock'],
     'quality_rules': ['HRS field unit is 1/1024 s; the BLE adapter converts (×1000/1024) and records rr_raw_1024',
                       'beat times are reconstructed from host receipt time (see provenance.clock)',
                       'screened RR are NOT validated NN intervals'],
     'limitations': 'Several RR values may arrive in one notification; their individual times are estimates.'},
    {'signal': 'sleep_duration', 'unit': 's', 'label': 'Sleep duration', 'value_type': 'number', 'plausible_min': 0,
     'plausible_max': 86400, 'legacy_key': 'sleep_hours', 'aliases': ['sleep_hours (h → s ×3600)', 'sleep_duration in h (×3600)'],
     'operational': True, 'sources': ['manual', 'research_import', 'synthetic'],
     'required_metadata': ['recorded_at', 'source', 'data_class'],
     'quality_rules': ['self-reported unless a device source is named', 'hours are converted ×3600, original kept in provenance'],
     'limitations': 'No supported wearable source for sleep in 1.5; manual entry only.'},
    {'signal': 'fatigue_1_10', 'unit': 'score', 'label': 'Self-reported fatigue (1–10)', 'value_type': 'number',
     'plausible_min': 1, 'plausible_max': 10, 'legacy_key': 'fatigue_1_10', 'aliases': ['fatigue'], 'operational': True,
     'sources': ['manual', 'synthetic'], 'required_metadata': ['recorded_at', 'source', 'data_class'],
     'quality_rules': ['subjective ordinal scale 1–10; the same scale under every alias'],
     'limitations': 'Ordinal self-report; differences are not physical units.'},
    {'signal': 'reaction_ms', 'unit': 'ms', 'label': 'Reaction time', 'value_type': 'number', 'plausible_min': 50,
     'plausible_max': 2000, 'legacy_key': 'reaction_ms', 'aliases': ['reaction_time'], 'operational': True,
     'sources': ['manual', 'synthetic'], 'required_metadata': ['recorded_at', 'source', 'data_class'],
     'quality_rules': ['test protocol must be stated in source'],
     'limitations': 'Depends on test, device latency and time of day.'},
    {'signal': 'activity_minutes', 'unit': 'min', 'label': 'Physical activity', 'value_type': 'number',
     'plausible_min': 0, 'plausible_max': 1440, 'legacy_key': 'activity_minutes', 'aliases': ['activity_duration'],
     'operational': True, 'sources': ['manual', 'synthetic'], 'required_metadata': ['recorded_at', 'source', 'data_class'],
     'quality_rules': ['self-reported'], 'limitations': 'No intensity information.'},
    {'signal': 'respiratory_rate', 'unit': 'breaths/min', 'label': 'Respiratory rate', 'value_type': 'number',
     'plausible_min': 2, 'plausible_max': 60, 'legacy_key': 'breathing_rate_bpm', 'aliases': ['breathing_rate'],
     'operational': False, 'sources': [], 'required_metadata': [], 'quality_rules': [],
     'limitations': 'Not operational: the only 1.4 value (RECOVERY biofeedback) is a simulated wave, not a measurement.'},
    {'signal': 'spo2', 'unit': '%', 'label': 'SpO₂', 'value_type': 'number', 'plausible_min': 50, 'plausible_max': 100,
     'legacy_key': None, 'aliases': ['spo2 in percent'], 'operational': False, 'sources': [], 'required_metadata': [],
     'quality_rules': [], 'limitations': 'Not operational: no supported AETHER source provides SpO₂ (not part of BLE HRS).'},
    {'signal': 'skin_temperature', 'unit': 'degC', 'label': 'Skin temperature', 'value_type': 'number',
     'plausible_min': 20, 'plausible_max': 45, 'legacy_key': None, 'aliases': [], 'operational': False, 'sources': [],
     'required_metadata': [], 'quality_rules': [],
     'limitations': 'Not operational and not mapped: Backend №2 `temperature` is cabin air temperature, a different quantity.'},
]
BY_ID = {s['signal']: s for s in _SIGNALS}
OPERATIONAL = {s['signal']: s for s in _SIGNALS if s['operational']}


def registry() -> dict:
    """Body of GET /api/signals. `signals` lists operational signals (contract shape); `not_operational` the rest."""
    return {'registry_version': REGISTRY_VERSION,
            'signals': [dict(s) for s in _SIGNALS if s['operational']],
            'not_operational': [{'signal': s['signal'], 'unit': s['unit'], 'reason': s['limitations']}
                                for s in _SIGNALS if not s['operational']],
            'conversions': [{'from_signal': a, 'from_unit': u, 'to_signal': t, 'to_unit': tu, 'factor': f, 'rule': d}
                            for (a, u), (t, tu, f, d) in signal_compat.CONVERSIONS.items()],
            'quality_states': list(QUALITY), 'valid_quality_states': list(VALID_QUALITY), 'data_classes': list(DATA_CLASSES)}


def parse_utc(value, field: str = 'recorded_at') -> datetime | None:
    """ISO 8601 with an explicit offset → aware UTC datetime. None stays None. No offset → 422."""
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise InvalidInput(f'{field} must be an ISO 8601 string', field=field)
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise InvalidInput(f'{field} is not a valid ISO 8601 timestamp', field=field) from exc
    if dt.tzinfo is None:
        raise TimestampWithoutOffset(f'{field} has no UTC offset; AETHER does not guess time zones', field=field)
    return dt.astimezone(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


def signal_info(signal: str) -> dict:
    s = BY_ID.get(signal)
    if s is None or not s['operational']:
        raise UnsupportedSignal(f'Signal {signal!r} is not supported' + ('' if s is None else f': {s["limitations"]}'),
                                field='signal')
    return s


def check_quality(value, quality: str, info: dict, manual: bool) -> tuple[str, bool, bool]:
    """Returns (quality, valid, missing) following contract §1.8. Raises for manual out-of-range values."""
    if quality not in QUALITY:
        raise InvalidInput(f'quality must be one of {", ".join(QUALITY)}', field='quality')
    if value is None:
        return 'missing', False, True
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise InvalidInput('value must be a finite number or null (NaN/Infinity are not stored)', field='value')
    if quality == 'missing':
        raise InvalidInput("quality 'missing' requires value null", field='quality')
    v = float(value)
    if not info['plausible_min'] <= v <= info['plausible_max']:
        if manual:
            raise ValueOutOfRange(f'{info["signal"]} {v:g} {info["unit"]} is outside {info["plausible_min"]}–'
                                  f'{info["plausible_max"]}', field='value')
        quality = 'out_of_range'
    return quality, quality in VALID_QUALITY, False


def contact_quality(signal: str, data_class: str, quality: str, valid: bool, provenance: dict | None,
                    pre: str = '') -> tuple[str, bool]:
    """Sensor-contact consistency at storage time (QA fix 02A-2; same rule as phantom_analyses.contact_rule).
    HR / RR from any non-manual source: contact False → 'no_contact' (invalid); contact True with quality 'no_contact'
    → stays invalid; contact not reported (None / missing) → at most 'screened'; non-boolean contact → 422."""
    if signal not in ('heart_rate', 'rr_interval') or data_class == 'manual' or quality == 'missing':
        return quality, valid
    contact = (provenance or {}).get('contact')
    if contact is not None and not isinstance(contact, bool):
        raise InvalidInput('provenance.contact must be true, false or null', field=pre + 'provenance.contact')
    if contact is False:
        return 'no_contact', False
    if contact is None and quality == 'good':
        return 'screened', valid
    return quality, valid


def validate_item(item: dict, index: int = 0) -> dict:
    """Validate one measurement against the registry (used by storage adapters and Backend №2).
    Returns a normalised copy in canonical signal/unit. Documented conversions are applied explicitly and recorded
    in provenance; nothing is fabricated, clipped or silently converted."""
    pre = f'items[{index}].'
    if not isinstance(item, dict):
        raise InvalidInput('measurement must be an object', field=f'items[{index}]')
    aid, kind = identity.validate_astronaut_id(item.get('astronaut_id'), pre + 'astronaut_id')
    dc = item.get('data_class')
    if dc not in DATA_CLASSES:
        raise InvalidInput(f'data_class must be one of {", ".join(DATA_CLASSES)}', field=pre + 'data_class')
    identity.check_data_classes(kind, [dc], pre + 'data_class')
    prov = item.get('provenance')
    if prov is not None and not isinstance(prov, dict):
        raise InvalidInput('provenance must be an object', field=pre + 'provenance')
    sig, unit, value, prov = signal_compat.normalise_signal(item.get('signal'), item.get('unit'), item.get('value'),
                                                            prov, OPERATIONAL, pre)
    info = signal_info(sig)
    rec = parse_utc(item.get('recorded_at'), pre + 'recorded_at')
    if rec is None and not item.get('original_timestamp'):
        raise InvalidInput('recorded_at may be null only together with original_timestamp', field=pre + 'recorded_at')
    src = item.get('source')
    if not isinstance(src, str) or not 1 <= len(src) <= 120:
        raise InvalidInput('source must be 1–120 characters', field=pre + 'source')
    q, valid, missing = check_quality(value, item.get('quality', 'unverified' if dc == 'manual' else None) or '',
                                      info, manual=(dc == 'manual'))
    q, valid = contact_quality(sig, dc, q, valid, prov, pre)
    out = dict(item)
    out.update(signal=sig, unit=unit, provenance=prov, recorded_at=iso_utc(rec) if rec else None, quality=q, valid=valid,
               missing=missing, value=None if value is None else float(value), astronaut_kind=kind)
    return out
