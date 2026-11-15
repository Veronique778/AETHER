"""AETHER 1.5 — Personal PHANTOM pipeline on stored personal measurements (Backend №3).

    Wearable / manual measurement → storage (Backend №2, app/storage) → this module:
    access check → fetch → time / unit / provenance / astronaut checks → validity filter → window statistics →
    personal baseline sufficiency → change detection → explainable result → save_analysis → analysis_id.

Method `phantom_hr_univariate_1_4` (same mathematics as the 1.4 biosignal adapter, app/biosignals.analyze, now on the
canonical measurement store and with explicit baselines):

  windows      5-minute windows on a fixed grid from the interval start. 1.5.1 (QA fix 02A-1): ALL coverage criteria are
               computed on VALID samples only — invalid rows never extend the covered time. A window is usable when
                 (a) ≥ 20 valid HR samples,
                 (b) the valid samples span ≥ 240 s (first → last valid sample),
                 (c) no gap between consecutive valid samples is longer than 60 s,
                 (d) ≥ 80 % of the received samples in the window are valid.
               Purpose: the window mean must describe the whole window, not a burst. (a), (b), (d) are the 1.4 values;
               (c) is derived from them: (b) already tolerates 60 s (20 % of the window) without valid data at the edges,
               (c) applies the same 20 % tolerance inside the window. HEURISTIC — not tuned on data.
               Consequence: sources sampling less often than ~1/15 s on average or with gaps > 60 s (low-frequency or
               intermittent devices, manual entries) never give usable windows → 'insufficient_data'. Such sources need a
               different method; none is offered in 1.5. Empty windows are reported, never filled.
  baseline     'first_hour' (default): usable windows in [from, from + 60 min) — frozen, never adapted;
               'explicit': usable windows in [baseline_from, baseline_to) with baseline_to ≤ from, i.e. strictly
               EARLIER data (no future data, no self-inclusion). ≥ 10 usable windows are required.
  scale        s = max(3 bpm, 1.4826 · MAD of baseline window means)      (robust SD; floor prevents s → 0)
  score        |mean_HR(window) − median_baseline| / s                    (two-sided robust z, per test window)
  decision     window flagged when score ≥ 3.5; outcome 'flag' if any test window is flagged, 'no_flag' if none,
               'insufficient_data' when the baseline or the analysed interval do not meet the criteria.
  HRV          per window from rr_interval rows with app.biosignals.rr_features (screened RR, exploratory only).

The threshold 3.5 and the 3-bpm floor are HEURISTIC / UNCALIBRATED (no labelled real events exist). The result is a
statistical prompt for review: `diagnosis` is always null and no probability is reported.

Data rules: only the requested astronaut's rows (any foreign row aborts the analysis), only the requested data classes
(default real_wearable; synthetic data are never mixed with real data; nasa_public never enters a personal baseline),
invalid / invalidated / missing rows are excluded and counted, nothing is interpolated or carried forward.
Deterministic: identical rows and parameters give an identical result (no random procedures are used).
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import statistics as st
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from . import identity, signals as reg
from .phantom_explain import explain, with_explain
from .biosignals import rr_features
from .science_errors import AnalysisError, Forbidden, InvalidInput, ScienceError, StorageUnavailable

METHOD_ID = 'phantom_hr_univariate_1_4'
METHODS = (METHOD_ID,)
PROCESSING_VERSION = 'aether-phantom-personal-1.5.1'
DIGEST_SCHEMA = 'aether-measurement-digest-v1'
ANALYSIS_DIGEST_SCHEMA = 'aether-analysis-digest-v1'
KIND = 'phantom_personal'
WINDOW_S = 300
BASELINE_S = 3600
MIN_BASELINE_WINDOWS = 10
MIN_WINDOW_VALID = 20          # (a) valid samples per window — 1.4 value
MIN_VALID_SPAN_S = 240         # (b) time between first and last VALID sample — 1.4 value, now on valid samples only
MAX_VALID_GAP_S = 60.0         # (c) longest gap between consecutive valid samples = the 20 % tolerance of (b)
MIN_VALID_FRACTION = 0.8       # (d) valid / received samples — 1.4 value
MIN_WINDOW_SPAN_S = MIN_VALID_SPAN_S   # backward-compatible name
SCALE_FLOOR_BPM = 3.0
THRESHOLD = 3.5
MAX_INTERVAL = timedelta(days=31)
MAX_ROWS = 400_000
PAGE = 5000
GAP_S = 10.0
METHOD_SIGNALS = ('heart_rate', 'rr_interval')
ALLOWED_CLASSES = ('real_wearable', 'manual', 'terrestrial_research', 'synthetic')
DEFAULT_CLASSES = ('real_wearable',)
NOT_MAPPED = ('sleep_duration', 'fatigue', 'reaction_time', 'activity_duration')
PARAMETERS = {'window_s': WINDOW_S, 'baseline_s': BASELINE_S, 'min_baseline_windows': MIN_BASELINE_WINDOWS,
              'min_window_valid': MIN_WINDOW_VALID, 'min_valid_span_s': MIN_VALID_SPAN_S, 'max_valid_gap_s': MAX_VALID_GAP_S,
              'min_valid_fraction': MIN_VALID_FRACTION, 'scale_floor_bpm': SCALE_FLOOR_BPM, 'threshold_robust_z': THRESHOLD,
              'contact_rule': 'contact False → rejected; contact not reported → at most screened'}

LIMITATIONS = [
    'Uncalibrated exploratory threshold (3.5 robust z) and scale floor (3 bpm); no labelled real events exist, so no '
    'false-positive or detection rate can be stated.',
    'Activity, posture, caffeine, stress, artefacts and circadian rhythm change heart rate; a flag is not a health finding.',
    'Screened RR intervals are not validated NN intervals; HRV values are exploratory.',
    'Beat times of RR values are reconstructed from host receipt time.',
    'NASA research data are not used in this analysis and never set personal baselines or thresholds.',
]


# --------------------------------------------------------------------------------------------- request
def parse_request(body: dict) -> dict:
    if not isinstance(body, dict):
        raise InvalidInput('Request body must be a JSON object')
    aid, kind = identity.validate_astronaut_id(body.get('astronaut_id'))
    mission = body.get('mission_id')
    if mission is not None:
        identity.validate_object_id(mission, 'mission_id')
    method = body.get('method') or METHOD_ID
    if method not in METHODS:
        raise InvalidInput(f'Unknown method {method!r}; supported: {", ".join(METHODS)}', field='method')
    sigs = body.get('signals') or list(METHOD_SIGNALS)
    if not isinstance(sigs, list) or not sigs or any(s not in METHOD_SIGNALS for s in sigs) or 'heart_rate' not in sigs:
        raise InvalidInput(f'signals must include heart_rate and be a subset of {list(METHOD_SIGNALS)} for {method}',
                           field='signals')
    sid = body.get('session_id')
    if sid is not None:
        identity.validate_object_id(sid, 'session_id')
    t0 = reg.parse_utc(body.get('from'), 'from')
    t1 = reg.parse_utc(body.get('to'), 'to')
    if sid is None and (t0 is None or t1 is None):
        raise InvalidInput('Give from and to (UTC), or a session_id', field='from')
    if (t0 is None) != (t1 is None):
        raise InvalidInput('from and to must be given together', field='to')
    if t0 is not None:
        if t0 >= t1:
            raise InvalidInput('from must be earlier than to', field='from')
        if t1 - t0 > MAX_INTERVAL:
            raise InvalidInput('The analysed interval may not exceed 31 days', field='to')
    classes = body.get('data_classes') or list(DEFAULT_CLASSES)
    if not isinstance(classes, list) or any(c not in ALLOWED_CLASSES for c in classes):
        raise InvalidInput(f'data_classes must be a subset of {list(ALLOWED_CLASSES)} (nasa_public never enters a '
                           'personal baseline)', field='data_classes')
    if 'synthetic' in classes and len(set(classes)) > 1:
        raise InvalidInput('Synthetic data cannot be mixed with real data in one analysis', field='data_classes')
    identity.check_data_classes(kind, classes)
    b0 = reg.parse_utc(body.get('baseline_from'), 'baseline_from')
    b1 = reg.parse_utc(body.get('baseline_to'), 'baseline_to')
    if (b0 is None) != (b1 is None):
        raise InvalidInput('baseline_from and baseline_to must be given together', field='baseline_to')
    if b0 is not None:
        if b0 >= b1:
            raise InvalidInput('baseline_from must be earlier than baseline_to', field='baseline_from')
        if b1 - b0 > MAX_INTERVAL:
            raise InvalidInput('The baseline interval may not exceed 31 days', field='baseline_to')
        if t0 is not None and b1 > t0:
            raise InvalidInput('baseline_to must not be later than from: the baseline may only use earlier data '
                               '(no future data, no self-inclusion)', field='baseline_to')
    return {'astronaut_id': aid, 'astronaut_kind': kind, 'mission_id': mission, 'method': method, 'signals': sorted(set(sigs)), 'session_id': sid, 'from': t0, 'to': t1,
            'data_classes': sorted(set(classes)), 'baseline_from': b0, 'baseline_to': b1,
            'baseline_mode': 'explicit' if b0 is not None else 'first_hour'}


# --------------------------------------------------------------------------------------------- fetch
def _fetch(ctx, storage, astronaut_id, signals_, start, end, session_id, mission_id=None) -> list[dict]:
    rows, cursor = [], None
    while True:
        try:
            kw = {'mission_id': mission_id} if mission_id else {}
            page = storage.query_measurements(ctx, astronaut_id, signals=signals_, start=start, end=end,
                                              session_id=session_id, include_invalid=False, limit=PAGE, cursor=cursor, **kw)
        except ScienceError:
            raise
        except Exception as exc:          # storage layer failure: never answer with a partial or invented result
            raise StorageUnavailable(f'Measurement storage failed: {type(exc).__name__}') from exc
        rows.extend(page.get('items') or [])
        if len(rows) > MAX_ROWS:
            raise InvalidInput(f'The interval contains more than {MAX_ROWS} measurements; analyse a shorter interval',
                               field='to')
        cursor = page.get('next_cursor')
        if not cursor:
            return rows


CONTACT_SIGNALS = ('heart_rate', 'rr_interval')
_MISSING = object()


def contact_rule(signal: str, data_class: str, quality: str, valid: bool, provenance: dict | None) -> tuple[str, bool, str | None]:
    """Sensor-contact consistency (QA fix 02A-2). Returns (effective_quality, effective_valid, counter_key | None).

    Applies to HR and RR from devices / imports (every data class except `manual`, where contact does not exist).
      contact False                      → rejected for analysis (quality 'no_contact'), whatever quality/valid claim
      quality 'no_contact', contact True → contradictory → rejected (the conservative reading wins)
      contact True                       → unchanged
      contact None / key missing         → not reported: never better than 'screened' (a plausible value is not
                                           proof of skin contact)
      contact of any other type          → invalid metadata → rejected
    The same rule is applied when measurements are stored (app.signals.validate_item) and must be applied by the
    Bluetooth Device Manager (package 03), which writes `provenance.contact` on BOTH the HR row and the RR rows of a
    notification.
    """
    if signal not in CONTACT_SIGNALS or data_class == 'manual':
        return quality, valid, None
    contact = (provenance or {}).get('contact', _MISSING)
    if contact is False:
        return 'no_contact', False, 'no_contact_reported'
    if contact is True:
        if quality == 'no_contact':
            return 'no_contact', False, 'contradictory_contact_quality'
        return quality, valid, None
    if contact is None or contact is _MISSING:
        if quality == 'good':
            return 'screened', valid, 'quality_capped_contact_not_reported'
        return quality, valid, None
    return 'rejected', False, 'invalid_contact_metadata'


def _screen(rows: list[dict], astronaut_id: str, classes: list[str], counts: Counter) -> list[tuple]:
    """→ [(t_unix, signal, value, valid, quality, contact, measurement_id, data_class, mission_id, session_id)]."""
    out = []
    # 03A: Backend №2 corrections are append-only (supersedes_id); a replaced revision is never analysed.
    replaced = {r.get('supersedes_id') for r in rows if r.get('supersedes_id')}
    for r in rows:
        if r.get('measurement_id') in replaced:
            counts['superseded'] += 1; continue
        if r.get('astronaut_id') != astronaut_id:
            # isolation guarantee: a foreign row means the storage contract is broken → refuse to analyse
            raise AnalysisError('Storage returned measurements of another astronaut; analysis aborted', code='analysis_error')
        if r.get('status', 'active') != 'active':
            counts['invalidated'] += 1; continue
        if r.get('data_class') not in classes:
            counts[f"excluded_data_class:{r.get('data_class')}"] += 1; continue
        info = reg.BY_ID.get(r.get('signal'))
        if info is None or r.get('unit') != info['unit']:
            counts['unit_mismatch'] += 1; continue
        if r.get('recorded_at') is None:
            counts['no_utc_timestamp'] += 1; continue
        t = reg.parse_utc(r['recorded_at']).timestamp()
        v = r.get('value')
        finite = v is not None and not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(float(v))
        quality = r.get('quality')
        valid = r.get('valid') is True and finite and quality in reg.VALID_QUALITY
        if r.get('valid') is True and not valid:
            counts['valid_flag_inconsistent'] += 1
        prov = r.get('provenance') or {}
        quality, valid, key = contact_rule(r['signal'], r.get('data_class'), quality, valid, prov)
        if key:
            counts[key] += 1
        contact = prov.get('contact', 'not_reported') if r.get('data_class') != 'manual' else 'not_applicable'
        out.append((t, r['signal'], float(v) if finite else None, bool(valid), quality, contact, r.get('measurement_id'),
                    r.get('data_class'), r.get('mission_id'), r.get('session_id')))
    out.sort(key=lambda x: (x[0], x[1], x[6] or ''))
    return out


# --------------------------------------------------------------------------------------------- statistics
def window_coverage(samples: list[tuple], w_start: float, w_end: float) -> dict:
    """Coverage of one window from (t, value, valid) samples. Only VALID samples count as covered time (02A-1)."""
    vt = sorted(t for t, _, ok in samples if ok)
    gaps = [b - a for a, b in zip(vt, vt[1:])]
    n = len(samples)
    return {'samples': n, 'valid': len(vt), 'valid_fraction': round(len(vt) / n, 4) if n else 0.0,
            'valid_span_s': round(vt[-1] - vt[0], 3) if vt else 0.0,
            'max_valid_gap_s': round(max(gaps), 3) if gaps else None,
            'edge_gap_start_s': round(vt[0] - w_start, 3) if vt else None,
            'edge_gap_end_s': round(w_end - vt[-1], 3) if vt else None,
            'median_interval_s': round(st.median(gaps), 3) if gaps else None}


def window_usable(cov: dict) -> tuple[bool, str | None]:
    if cov['samples'] == 0:
        return False, 'no_measurements'
    if cov['valid'] < MIN_WINDOW_VALID:
        return False, 'too_few_samples'
    if cov['valid_span_s'] < MIN_VALID_SPAN_S:
        return False, 'coverage_too_short'
    if cov['max_valid_gap_s'] is not None and cov['max_valid_gap_s'] > MAX_VALID_GAP_S:
        return False, 'gap_too_long'
    if cov['valid_fraction'] < MIN_VALID_FRACTION:
        return False, 'low_valid_fraction'
    return True, None


def _windows(items: list[tuple], start: float, end: float) -> list[dict]:
    n = max(1, int(math.ceil((end - start) / WINDOW_S)))
    hr, rr = defaultdict(list), defaultdict(list)
    for t, sig, v, ok, *_ in items:
        b = int((t - start) // WINDOW_S)
        if 0 <= b < n:
            (hr if sig == 'heart_rate' else rr)[b].append((t, v, ok))
    out = []
    for b in range(n):
        w0, w1 = start + b * WINDOW_S, min(end, start + (b + 1) * WINDOW_S)
        h = hr.get(b, [])
        cov = window_coverage(h, w0, w1)
        usable, reason = window_usable(cov)
        valid = [v for _, v, ok in h if ok]
        out.append({'start_unix': w0, 'start': reg.iso_utc(datetime.fromtimestamp(w0, timezone.utc)),
                    'end': reg.iso_utc(datetime.fromtimestamp(w1, timezone.utc)),
                    **cov, 'mean_hr_bpm': round(st.mean(valid), 3) if usable else None,
                    'quality': 'screened' if usable else 'insufficient_data', 'unusable_reason': reason,
                    'hrv': rr_features(rr[b]) if rr.get(b) else None, 'score': None, 'outcome': 'insufficient_data',
                    'role': None})
    return out


def _baseline(windows: list[dict]) -> dict | None:
    means = [w['mean_hr_bpm'] for w in windows if w['mean_hr_bpm'] is not None]
    if len(means) < MIN_BASELINE_WINDOWS:
        return None
    med = st.median(means)
    mad = st.median(abs(m - med) for m in means)
    return {'median_hr_bpm': round(med, 3), 'mad_bpm': round(mad, 3), 'scale_bpm': round(max(SCALE_FLOOR_BPM, 1.4826 * mad), 3),
            'scale_floor_applied': 1.4826 * mad < SCALE_FLOOR_BPM, 'windows_used': len(means), '_median': med,
            '_scale': max(SCALE_FLOOR_BPM, 1.4826 * mad)}


def _quality_report(items: list[tuple]) -> dict:
    hr = [x for x in items if x[1] == 'heart_rate']
    rr = [x for x in items if x[1] == 'rr_interval']
    gaps = [b[0] - a[0] for a, b in zip(hr, hr[1:]) if b[0] - a[0] > GAP_S]
    contact = Counter('reported_true' if x[5] is True else 'reported_false' if x[5] is False else 'not_reported' for x in hr)
    rr_vals = [x[2] for x in rr if x[2] is not None]
    rr_ok = [x[2] for x in rr if x[3]]
    return {
        'quality_counts': dict(Counter(x[4] for x in items)),
        'heart_rate': {'rows': len(hr), 'valid': sum(x[3] for x in hr), 'gaps_over_10s': len(gaps),
                       'longest_gap_s': round(max(gaps), 1) if gaps else 0.0, 'contact': dict(contact),
                       'contact_note': None if not contact.get('not_reported') else
                       'Some samples come from a device that does not report sensor contact; a plausible value does '
                       'not prove skin contact (quality at most "screened").'},
        'raw_rr_summary': {'rows': len(rr), 'with_value': len(rr_vals),
                           'min_ms': round(min(rr_vals), 1) if rr_vals else None, 'max_ms': round(max(rr_vals), 1) if rr_vals else None,
                           'mean_ms': round(st.mean(rr_vals), 1) if rr_vals else None},
        'validated_interval_summary': {'screened_valid': len(rr_ok), 'rejected_or_missing': len(rr) - len(rr_ok),
                                       'mean_ms': round(st.mean(rr_ok), 1) if rr_ok else None,
                                       'note': 'Screened by plausibility and device quality only; NOT verified NN intervals.'},
    }


DIGEST_PROVENANCE_KEYS = ('profile', 'contact', 'clock', 'conversion', 'time_uncertainty_s', 'event', 'entered_via')


def canonical_row(r: dict, role: str) -> dict:
    """Canonical, secret-free representation of one fetched measurement for hashing (02A-3).
    No user ids, tokens, free-text notes or server receipt times; timestamps normalised to UTC."""
    rec = r.get('recorded_at')
    try:
        rec = reg.iso_utc(reg.parse_utc(rec)) if rec else None
    except ScienceError:
        rec = f'unparseable:{rec}'
    v = r.get('value')
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        v = None if v is None else f'non-numeric:{v!r}'
    elif not math.isfinite(float(v)):
        v = f'non-finite:{v}'
    else:
        v = float(v)
    prov = r.get('provenance') or {}
    return {'role': role, 'measurement_id': r.get('measurement_id'), 'astronaut_id': r.get('astronaut_id'),
            'signal': r.get('signal'), 'value': v, 'unit': r.get('unit'), 'recorded_at': rec,
            'original_timestamp': r.get('original_timestamp'), 'quality': r.get('quality'), 'valid': r.get('valid'),
            'status': r.get('status', 'active'), 'data_class': r.get('data_class'), 'source': r.get('source'),
            'session_id': r.get('session_id'), 'device_id': r.get('device_id'), 'mission_id': r.get('mission_id'),
            'provenance': {k: prov[k] for k in DIGEST_PROVENANCE_KEYS if k in prov}}


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                                     allow_nan=False).encode('ascii')).hexdigest()


def measurement_digest(rows: list[dict], baseline_rows: list[dict] | None = None) -> str:
    """SHA-256 over ALL fetched rows (used and excluded), canonical and order-independent (02A-3)."""
    canon = [canonical_row(r, 'analysis') for r in rows] + [canonical_row(r, 'baseline') for r in (baseline_rows or [])]
    canon.sort(key=lambda c: (c['role'], str(c['recorded_at']), str(c['signal']), str(c['measurement_id'])))
    return _sha({'schema': DIGEST_SCHEMA, 'rows': canon})


def analysis_digest(req: dict, m_digest: str) -> str:
    """Hash of everything that determines the result: inputs + method + parameters (reproducibility check)."""
    iso = lambda d: reg.iso_utc(d) if d else None
    return _sha({'schema': ANALYSIS_DIGEST_SCHEMA, 'measurement_digest': m_digest, 'method': req['method'],
                 'processing_version': PROCESSING_VERSION, 'parameters': PARAMETERS, 'astronaut_id': req['astronaut_id'],
                 'from': iso(req['from']), 'to': iso(req['to']), 'session_id': req['session_id'], 'signals': req['signals'],
                 'data_classes': req['data_classes'], 'baseline_mode': req['baseline_mode'], 'mission_id': req.get('mission_id'),
                 'baseline_from': iso(req['baseline_from']), 'baseline_to': iso(req['baseline_to'])})


def compute(req: dict, items: list[tuple], baseline_items: list[tuple] | None, counts: Counter) -> dict:
    """Pure, deterministic analysis of already screened rows. No I/O, no randomness."""
    if req['from'] is not None:
        start, end = req['from'].timestamp(), req['to'].timestamp()
    elif items:
        start, end = items[0][0], items[-1][0] + 1
    else:
        start = end = None
    reasons, windows, base = [], [], None
    if start is None:
        reasons.append({'code': 'no_measurements', 'signal': 'heart_rate', 'required': None, 'available': 0,
                        'message': 'The session contains no usable measurements of the requested data classes.'})
    else:
        windows = _windows(items, start, end)
        if req['baseline_mode'] == 'explicit':
            bwin = _windows(baseline_items or [], req['baseline_from'].timestamp(), req['baseline_to'].timestamp())
            for w in bwin:
                w['role'] = 'baseline'
            tests = windows
            base_windows = bwin
        else:
            base_windows = [w for w in windows if w['start_unix'] < start + BASELINE_S]
            tests = [w for w in windows if w['start_unix'] >= start + BASELINE_S]
            for w in base_windows:
                w['role'] = 'baseline'
        for w in tests:
            w['role'] = 'test'
        base = _baseline(base_windows)
        n_hr = sum(1 for x in items if x[1] == 'heart_rate')
        if n_hr == 0:
            reasons.append({'code': 'no_measurements', 'signal': 'heart_rate', 'required': None, 'available': 0,
                            'message': 'No heart-rate measurements of the requested data classes in the interval.'})
        if base is None:
            usable = sum(w['mean_hr_bpm'] is not None for w in base_windows)
            reasons.append({'code': 'too_few_baseline_windows', 'signal': 'heart_rate', 'required': MIN_BASELINE_WINDOWS,
                            'available': usable, 'message': f'Need at least {MIN_BASELINE_WINDOWS} usable 5-minute baseline '
                            f'windows ({"first hour" if req["baseline_mode"] == "first_hour" else "explicit baseline interval"}); '
                            f'{usable} were usable.'})
        else:
            for w in tests:
                if w['mean_hr_bpm'] is not None:
                    w['score'] = round(abs(w['mean_hr_bpm'] - base['_median']) / base['_scale'], 3)
                    w['outcome'] = 'flag' if w['score'] >= THRESHOLD else 'no_flag'
            if not any(w['score'] is not None for w in tests):
                reasons.append({'code': 'too_few_samples', 'signal': 'heart_rate', 'required': 1,
                                'available': 0, 'message': 'No usable 5-minute window after the baseline period.'})
        if counts.get('no_utc_timestamp'):
            reasons.append({'code': 'no_utc_timestamps', 'signal': None, 'required': None, 'available': counts['no_utc_timestamp'],
                            'message': 'Some measurements have no UTC time and were not used.'})
        if req['baseline_mode'] == 'explicit':
            windows = bwin + windows
    scored = [w for w in windows if w['role'] == 'test' and w['score'] is not None]
    hard = [r for r in reasons if r['code'] != 'no_utc_timestamps']
    outcome = 'insufficient_data' if hard or not scored else ('flag' if any(w['outcome'] == 'flag' for w in scored) else 'no_flag')
    for w in windows:
        w.pop('start_unix', None)
    baseline = None
    if base is not None:
        baseline = {k: v for k, v in base.items() if not k.startswith('_')}
        baseline.update(mode=req['baseline_mode'],
                        **({'from': reg.iso_utc(req['baseline_from']), 'to': reg.iso_utc(req['baseline_to'])}
                           if req['baseline_mode'] == 'explicit' else
                           {'from': reg.iso_utc(datetime.fromtimestamp(start, timezone.utc)),
                            'to': reg.iso_utc(datetime.fromtimestamp(min(end, start + BASELINE_S), timezone.utc))}),
                        policy='Frozen; never adapted to the analysed data.')
    return {'outcome': outcome, 'reasons': reasons, 'windows': windows, 'baseline': baseline, 'scored': scored,
            'interval': None if start is None else (start, end)}


# --------------------------------------------------------------------------------------------- service
def analysis_id_for(astronaut_id: str, user_id: str | None, a_digest: str) -> str:
    """Deterministic id (02A-5): the same user re-sending the same request over the same data gets the same analysis,
    so a retry after a lost response can never create a duplicate."""
    return hashlib.sha256(f'{KIND}|{astronaut_id}|{user_id or "-"}|{a_digest}'.encode()).hexdigest()[:32]


def _assessment_scope(outcome: str) -> dict:
    return {'signals_assessed': ['heart_rate'], 'signals_not_assessed': list(NOT_MAPPED), 'complete_assessment': False,
            'statement': ('Only heart rate was compared with this person\'s own baseline. ' +
                          ('A flag means one signal changed statistically; it is not an overall health assessment.'
                           if outcome == 'flag' else 'The other signals were not assessed.'))}


def run(ctx, body: dict, storage) -> tuple[int, dict]:
    req = parse_request(body)
    aid = req['astronaut_id']
    if not _can(ctx, 'phantom:run', aid, req['mission_id']):     # checked BEFORE any personal data is read
        raise Forbidden()
    bundle = getattr(storage, 'save_analysis_bundle', None)
    if bundle is None:
        # 02A-5: without one atomic write the analysis, history record and audit event can diverge. Fail closed.
        raise StorageUnavailable('The storage API has no atomic save_analysis_bundle (amendment A-11); '
                                 'the analysis was not run and nothing was stored', code='storage_unavailable')
    counts: Counter = Counter()
    iso = lambda d: reg.iso_utc(d) if d else None
    rows = _fetch(ctx, storage, aid, req['signals'], iso(req['from']), iso(req['to']), req['session_id'], req['mission_id'])
    items = _screen(rows, aid, req['data_classes'], counts)
    b_rows = b_items = None
    if req['baseline_mode'] == 'explicit':
        b_rows = _fetch(ctx, storage, aid, req['signals'], iso(req['baseline_from']), iso(req['baseline_to']), None, req['mission_id'])
        b_items = _screen(b_rows, aid, req['data_classes'], counts)
    m_digest = measurement_digest(rows, b_rows)
    a_digest = analysis_digest(req, m_digest)
    res = compute(req, items, b_items, counts)
    used = items + (b_items or [])
    classes = sorted({x[7] for x in used})
    missions = sorted({x[8] for x in used if x[8]})
    flagged = ['heart_rate'] if res['outcome'] == 'flag' else []
    insufficient = None
    if res['outcome'] == 'insufficient_data':
        reasons = res['reasons'] or [{'code': 'too_few_samples', 'signal': 'heart_rate', 'required': None, 'available': 0,
                                      'message': 'No usable analysis window.'}]
        insufficient = {'reasons': reasons, 'missing_signals': list(NOT_MAPPED),
                        'suggested_next_measurement': 'Record at least 60 minutes of resting heart rate with verified '
                                                      'strap contact, then the period of interest.'}
    if res['outcome'] == 'flag':
        n = sum(w['outcome'] == 'flag' for w in res['scored'])
        explanation = (f'{n} of {len(res["scored"])} analysed 5-minute windows differ from this person\'s baseline heart rate '
                       f'by at least {THRESHOLD} robust SD. Only heart rate was assessed. This is a statistical change in '
                       f'one signal, not a medical finding and not an overall health assessment.')
    elif res['outcome'] == 'no_flag':
        explanation = (f'None of {len(res["scored"])} analysed 5-minute windows differs from the personal baseline heart rate by '
                       f'{THRESHOLD} robust SD or more. Only heart rate was assessed.')
    else:
        explanation = 'Not enough valid data for a personal-baseline comparison. This is not a normal result.'
    analysis_id = analysis_id_for(aid, getattr(ctx, 'user_id', None), a_digest)
    result = {
        'analysis_id': analysis_id, 'astronaut_id': aid,
        'mission_id': req['mission_id'] or (missions[0] if len(missions) == 1 else None),
        'created_at': reg.iso_utc(datetime.now(timezone.utc)), 'created_by': getattr(ctx, 'user_id', None), 'status': 'completed',
        'input': {'requested_from': iso(req['from']), 'requested_to': iso(req['to']),
                  'from': None if res['interval'] is None else reg.iso_utc(datetime.fromtimestamp(res['interval'][0], timezone.utc)),
                  'to': None if res['interval'] is None else reg.iso_utc(datetime.fromtimestamp(res['interval'][1], timezone.utc)),
                  'signals': req['signals'], 'session_id': req['session_id'], 'requested_data_classes': req['data_classes'],
                  'astronaut_kind': req['astronaut_kind'],
                  'data_classes': classes, 'fetched_count': len(rows) + len(b_rows or []), 'measurement_count': len(used),
                  'valid_count': sum(x[3] for x in used), 'excluded': dict(counts),
                  'session_ids': sorted({x[9] for x in used if x[9]}),
                  'measurement_digest': m_digest, 'digest_schema': DIGEST_SCHEMA},
        'reproducibility': {'analysis_digest': a_digest, 'digest_schema': ANALYSIS_DIGEST_SCHEMA, 'deterministic': True,
                            'random_seed': None, 'note': 'Same analysis_digest ⇒ same result (except analysis_id/created_*).'},
        'method': {'id': req['method'], 'name': 'PHANTOM personal: univariate HR robust baseline (5-min windows)',
                   'processing_version': PROCESSING_VERSION, 'baseline_mode': req['baseline_mode'],
                   'parameters': dict(PARAMETERS),
                   'classification': 'HEURISTIC / UNCALIBRATED (HEALTH_ALGORITHMS_AUDIT.md A6)'},
        'processing_version': PROCESSING_VERSION,
        'outcome': res['outcome'], 'assessment_scope': _assessment_scope(res['outcome']),
        'baseline': res['baseline'], 'windows': res['windows'], 'flagged_signals': flagged,
        'flag_rate': (round(sum(w['outcome'] == 'flag' for w in res['scored']) / len(res['scored']), 4) if res['scored'] else None),
        'signal_quality': _quality_report(used),
        'uncertainty': {'kind': 'not_quantified', 'statement': 'No calibrated uncertainty or probability exists for this '
                        'method; the robust scale and the number of baseline windows are reported instead.',
                        'baseline_windows': None if res['baseline'] is None else res['baseline']['windows_used'],
                        'scale_floor_applied': None if res['baseline'] is None else res['baseline']['scale_floor_applied']},
        'insufficient_data': insufficient, 'explanation': explanation, 'diagnosis': None, 'limitations': list(LIMITATIONS),
        'nasa_reference_context': {'used': False, 'policy': 'NASA data are context only; never used as a personal baseline.'},
        'data_class': 'derived', 'source_data_classes': classes,
    }
    record = {'kind': 'phantom_analysis', 'ref_ids': [analysis_id], 'astronaut_id': aid, 'data_class': 'derived',
              'summary': f'PHANTOM personal: {res["outcome"]}'}
    audit = {'action': 'phantom_analysis.create', 'target_kind': 'phantom_analysis', 'target_id': analysis_id,
             'outcome': 'success', 'details': {'outcome': res['outcome'], 'analysis_digest': a_digest}}
    try:
        input_ids = sorted({r['measurement_id'] for r in rows + (b_rows or []) if r.get('measurement_id')})
        saved = bundle(ctx, KIND, aid, result, record=record, audit=audit, idempotency_key=analysis_id, input_ids=input_ids)
    except StorageUnavailable as exc:
        raise StorageUnavailable(f'{exc.message}. The analysis write is atomic and idempotent: '
                                 'it is safe to resend the same request') from exc
    except ScienceError:
        raise
    except Exception as exc:
        raise StorageUnavailable(f'Atomic analysis write failed ({type(exc).__name__}). The write is atomic and '
                                 'idempotent: it is safe to resend the same request') from exc
    # The storage assigns the public analysis id (Backend №2: a UUID); `analysis_id` above is the idempotency key.
    public_id = saved.get('analysis_id')
    if not public_id:
        raise AnalysisError('Storage did not return an analysis id', code='analysis_error')
    stored = saved.get('payload') or get_analysis(ctx, public_id, storage)
    stored = {**stored, 'analysis_id': public_id, 'idempotency_key': analysis_id}
    if stored.get('astronaut_id') != aid:
        raise AnalysisError('Storage returned an analysis of another astronaut', code='analysis_error')
    # F5 (BE3_04): read-time explanation, a pure function of the stored result — never stored itself
    return (201 if saved.get('created') else 200), with_explain({**stored, 'idempotent_replay': not saved.get('created')})


def _can(ctx, permission: str, astronaut_id: str, mission_id: str | None = None) -> bool:
    """Server-side permission check via the RequestContext. mission_id is passed when known: Backend №2 grants medical
    officers access per mission (access_control.profile)."""
    if ctx is None:
        return False
    return bool(ctx.can(permission, astronaut_id, mission_id=mission_id)) if mission_id else bool(ctx.can(permission, astronaut_id))


def _first(query: dict, key: str):
    v = (query or {}).get(key)
    return v[0] if isinstance(v, list) else v


SCAN_PAGE = 100
MAX_SCAN = 2000
OUTCOMES = ('flag', 'no_flag', 'insufficient_data')


def _encode_cursor(storage_cursor, offset: int, fingerprint: str) -> str:
    raw = json.dumps({'v': 1, 's': storage_cursor, 'o': offset, 'f': fingerprint}, separators=(',', ':'))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip('=')


def _decode_cursor(cursor: str | None, fingerprint: str):
    if not cursor:
        return None, 0
    try:
        d = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)).decode())
        if d.get('v') != 1 or not isinstance(d.get('o'), int) or d['o'] < 0:
            raise ValueError
    except Exception:
        raise InvalidInput('cursor is not valid; start again without a cursor', field='cursor')
    if d.get('f') != fingerprint:
        raise InvalidInput('cursor belongs to a request with other filters', field='cursor')
    return d.get('s'), d['o']


def list_analyses(ctx, query: dict, storage) -> dict:
    """Filters are applied BEFORE pagination (02A-4).

    The storage API (contract §2.3) pages by (astronaut, kind) only. Until it supports an `outcome` filter (IR-12), this
    function scans storage pages in their stable order (created_at desc, analysis_id desc) and returns exactly `limit`
    matching items; the opaque cursor = (storage cursor, offset inside that storage page, filter fingerprint), so no item
    is skipped or repeated as long as the storage cursor itself is stable. At most MAX_SCAN rows are scanned per call;
    then `scan_truncated: true` and a cursor are returned (fewer items, never wrong items)."""
    aid = _first(query, 'astronaut_id')
    mission = _first(query, 'mission_id')
    if aid is not None:
        identity.validate_astronaut_id(aid)
    if mission is not None:
        identity.validate_object_id(mission, 'mission_id')
    if aid is not None and not _can(ctx, 'measurement:read', aid, mission):
        raise Forbidden()
    outcome = _first(query, 'outcome')
    if outcome is not None and outcome not in OUTCOMES:
        raise InvalidInput('outcome must be flag, no_flag or insufficient_data', field='outcome')
    raw = _first(query, 'limit') or '100'
    if not str(raw).isdigit() or not 1 <= int(raw) <= 500:
        raise InvalidInput('limit must be 1–500', field='limit')
    limit = int(raw)
    fp = hashlib.sha256(f'{aid}|{mission}|{outcome}|{getattr(ctx, "user_id", None)}'.encode()).hexdigest()[:16]
    s_cursor, offset = _decode_cursor(_first(query, 'cursor'), fp)
    items, scanned = [], 0
    while True:
        try:
            page = storage.list_analyses(ctx, aid, KIND, SCAN_PAGE, s_cursor, **({'mission_id': mission} if mission else {}))
        except ScienceError:
            raise
        except Exception as exc:
            raise StorageUnavailable(f'Analysis storage failed: {type(exc).__name__}') from exc
        rows, nxt = page.get('items') or [], page.get('next_cursor')
        if offset > len(rows):
            raise InvalidInput('cursor is out of range; start again without a cursor', field='cursor')
        i = offset
        while i < len(rows):
            a = rows[i]; i += 1; scanned += 1
            if aid is not None and a.get('astronaut_id') != aid:
                raise AnalysisError('Storage returned an analysis of another astronaut', code='analysis_error')
            if outcome is None or a.get('outcome') == outcome:
                items.append({**{k: v for k, v in a.items() if k != 'windows'}, 'explain': explain(a)})
            if len(items) == limit or scanned >= MAX_SCAN:
                if i < len(rows):
                    cur = _encode_cursor(s_cursor, i, fp)
                else:
                    cur = _encode_cursor(nxt, 0, fp) if nxt else None
                return {'items': items, 'next_cursor': cur, 'scan_truncated': len(items) < limit and cur is not None}
        if not nxt:
            return {'items': items, 'next_cursor': None, 'scan_truncated': False}
        s_cursor, offset = nxt, 0


def get_analysis(ctx, analysis_id: str, storage) -> dict:
    identity.validate_object_id(analysis_id, 'analysis_id')
    try:
        return with_explain(storage.get_analysis(ctx, analysis_id))
    except ScienceError:
        raise
    except Exception as exc:
        raise StorageUnavailable(f'Analysis storage failed: {type(exc).__name__}') from exc
