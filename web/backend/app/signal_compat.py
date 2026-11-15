"""AETHER 1.5 — the ONE signal / unit / provenance / quality mapping between Backend №2 storage and Backend №3 science.

Backend №2 (app.schemas_15.SIGNALS, raw_measurements) owns the stored representation. Backend №3 code uses the canonical
names below, which ARE the Backend №2 storage names, so stored data never needs renaming. Older Backend №3 names and
units are accepted only through explicit, recorded conversions (CONVERSIONS); everything else is refused (422).

Principles (tested in tests/test_signal_compat_03a.py and tests/test_quality_contact_matrix_03a.py)
* No silent conversion: every conversion writes provenance.source_signal / source_unit / source_value / conversion.
* No double conversion: a value whose provenance already records a conversion is never converted again.
* No silent clipping: a device value outside Backend №2's storage range is stored as value null, quality 'rejected',
  provenance.original_value = the received value (explicit, reversible) — never clamped.
* No upgrade of trust: data class and quality mappings only keep or LOWER confidence; ambiguous inputs are refused
  or classified as '*_unclassified' (excluded from analyses) instead of being guessed.
"""
from __future__ import annotations

import math

from .science_errors import InvalidInput, InvalidUnits, UnsupportedSignal

# canonical signal → (unit, Backend №2 storage range lo, hi). Mirrors app.schemas_15.SIGNALS (checked by a test).
BE2_STORAGE = {
    'heart_rate': ('bpm', 0, 300), 'rr_interval': ('ms', 100, 5000), 'sleep_duration': ('s', 0, 86400),
    'fatigue_1_10': ('score', 1, 10), 'reaction_ms': ('ms', 0, 10000), 'activity_minutes': ('min', 0, 1440),
    'respiratory_rate': ('breaths/min', 0, 120), 'spo2': ('%', 0, 100),
}
# (incoming signal, incoming unit) → (canonical signal, canonical unit, factor, description)
CONVERSIONS = {
    ('heart_rate_bpm', 'bpm'): ('heart_rate', 'bpm', 1.0, 'rename heart_rate_bpm → heart_rate (no numeric change)'),
    ('sleep_hours', 'h'): ('sleep_duration', 's', 3600.0, 'hours × 3600 = seconds'),
    ('sleep_duration', 'h'): ('sleep_duration', 's', 3600.0, 'hours × 3600 = seconds'),
    ('fatigue', 'score_1_10'): ('fatigue_1_10', 'score', 1.0, 'rename fatigue → fatigue_1_10; same 1–10 scale'),
    ('fatigue', 'score'): ('fatigue_1_10', 'score', 1.0, 'rename fatigue → fatigue_1_10; same 1–10 scale'),
    ('fatigue_1_10', 'score_1_10'): ('fatigue_1_10', 'score', 1.0, 'unit label score_1_10 → score; same 1–10 scale'),
    ('reaction_time', 'ms'): ('reaction_ms', 'ms', 1.0, 'rename reaction_time → reaction_ms'),
    ('activity_duration', 'min'): ('activity_minutes', 'min', 1.0, 'rename activity_duration → activity_minutes'),
    ('breathing_rate', 'breaths_per_min'): ('respiratory_rate', 'breaths/min', 1.0, 'rename breathing_rate → respiratory_rate'),
    ('spo2', 'percent'): ('spo2', '%', 1.0, 'unit label percent → %'),
}
SECONDS_PER_HOUR = 3600.0
RR_RAW_TO_MS = 1000.0 / 1024.0   # BLE HRS RR field resolution 1/1024 s


def hours_to_seconds(h: float) -> float:
    return float(h) * SECONDS_PER_HOUR


def seconds_to_hours(s: float) -> float:
    return float(s) / SECONDS_PER_HOUR


def rr_raw_to_ms(raw: int) -> float:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0 or raw > 0xFFFF:
        raise InvalidInput('RR raw value must be an unsigned 16-bit integer (1/1024 s)')
    return raw * RR_RAW_TO_MS


def _finite(v) -> bool:
    return v is not None and not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(float(v))


def normalise_signal(signal: str, unit: str, value, provenance: dict | None, canonical: dict, field: str = '') -> tuple[str, str, float | None, dict]:
    """→ (canonical_signal, canonical_unit, value, provenance). `canonical` maps signal → registry entry with 'unit'.
    Raises UnsupportedSignal / InvalidUnits / InvalidInput; never guesses."""
    prov = dict(provenance or {})
    if signal in canonical:
        cu = canonical[signal]['unit']
        if unit == cu:
            return signal, unit, value, prov
        conv = CONVERSIONS.get((signal, unit))
        if conv is None:
            raise InvalidUnits(f"Signal {signal} must use unit '{cu}', got {unit!r} (no documented conversion)", field=field + 'unit')
    else:
        conv = CONVERSIONS.get((signal, unit))
        if conv is None:
            known_units = sorted(u for (s, u) in CONVERSIONS if s == signal)
            if known_units:
                raise InvalidUnits(f'Signal {signal!r} is accepted only with unit(s) {known_units}', field=field + 'unit')
            raise UnsupportedSignal(f'Signal {signal!r} is not supported', field=field + 'signal')
    if 'source_unit' in prov or 'conversion' in prov:
        raise InvalidInput('Value is already converted (provenance.conversion present); refusing a second conversion',
                           field=field + 'unit', code='double_conversion')
    target, tunit, factor, desc = conv
    if value is not None:
        if not _finite(value):
            raise InvalidInput('value must be a finite number or null', field=field + 'value')
        new = float(value) * factor
    else:
        new = None
    prov.update(source_signal=signal, source_unit=unit, source_value=value, conversion=desc)
    return target, tunit, new, prov


# ------------------------------------------------------------------ provenance / data class
TO_BE2_ORIGIN = {'real_wearable': 'real', 'manual': 'manual', 'synthetic': 'simulated'}
REFUSED_FOR_PERSONAL_STORE = {'terrestrial_research': 'research_separate', 'nasa_public': 'research_separate',
                              'derived': 'derived_not_raw'}


def to_be2_origin(data_class: str) -> str:
    if data_class in TO_BE2_ORIGIN:
        return TO_BE2_ORIGIN[data_class]
    if data_class in REFUSED_FOR_PERSONAL_STORE:
        raise InvalidInput(f'data_class {data_class!r} does not belong in the personal measurement store '
                           f'({REFUSED_FOR_PERSONAL_STORE[data_class]})', field='data_class',
                           code=REFUSED_FOR_PERSONAL_STORE[data_class])
    raise InvalidInput(f'Unknown data_class {data_class!r}', field='data_class')


def from_be2_data_class(origin: str, metadata: dict | None) -> str:
    """Never upgrades: 'real' becomes 'real_wearable' only when the row was written as such (metadata.data_class);
    other 'real' rows stay 'real_unclassified'; research never becomes nasa_public/terrestrial_research automatically."""
    md = metadata or {}
    if origin == 'manual':
        return 'manual'
    if origin == 'simulated':
        return 'synthetic'
    if origin == 'real':
        return 'real_wearable' if md.get('data_class') == 'real_wearable' else 'real_unclassified'
    if origin == 'research':
        return 'research_unclassified'
    return 'unknown'


# ------------------------------------------------------------------ quality
TO_BE2_QUALITY = {'good': 'screened', 'screened': 'screened', 'degraded': 'unverified', 'unverified': 'unverified',
                  'no_contact': 'no_contact', 'corrupt': 'corrupt', 'rejected': 'rejected', 'out_of_range': 'rejected',
                  'missing': 'connection_lost'}
BE2_QUALITIES = ('unverified', 'screened', 'validated', 'rejected', 'corrupt', 'no_contact', 'connection_lost')


def to_be2_quality(q: str) -> str:
    if q not in TO_BE2_QUALITY:
        raise InvalidInput(f'Unknown quality {q!r}', field='quality')
    return TO_BE2_QUALITY[q]


def from_be2_quality(q: str, value, metadata: dict | None) -> str:
    """Backend №2 quality (+ the BE3 original kept in metadata) → BE3 quality. Never upgrades:
    * be3_quality is honoured only if mapping it forward gives exactly the stored Backend №2 quality, and 'good' only
      when metadata.contact is True (a stored claim of contact);
    * 'validated' is not trusted as clinical validation → 'screened'; 'unverified' stays 'unverified';
    * connection_lost → 'missing' (value null) / 'rejected'; anything unknown → 'rejected' (fail closed)."""
    md = metadata or {}
    b3 = md.get('be3_quality')
    if b3 in TO_BE2_QUALITY and TO_BE2_QUALITY[b3] == q:
        if b3 == 'good' and md.get('contact') is not True:
            return 'screened'
        return b3
    return {'unverified': 'unverified', 'legacy_unverified': 'unverified',   # Backend №2 seeded demo rows
            'screened': 'screened', 'validated': 'screened', 'rejected': 'rejected',
            'corrupt': 'corrupt', 'no_contact': 'no_contact'}.get(q, 'missing' if q == 'connection_lost' and value is None else 'rejected')
