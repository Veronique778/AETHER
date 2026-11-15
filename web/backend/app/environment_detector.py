"""SYMBIOSIS environment-event detector + PHANTOM environmental context (AETHER 1.0, spec B4).

Separates three things that 0.9 mixed up:
  1. conditions in the cabin            – this module, cabin channels only (CO₂, temperature, humidity);
  2. measured physiological change       – PHANTOM 2.0 on crew channels only;
  3. a hypothesised link between the two – stated as a hypothesis, never as a finding or a diagnosis.

Detectors (per zone, on the sampled cabin series):
  * co2_increase       one-sided winsorised CUSUM on robust-standardised CO₂ (k 0.5, increments clipped to ±3,
                       h calibrated to ≤ 1 % false frames on nominal runs – see CUSUM_H).
  * temperature_drift  two-sided winsorised CUSUM on temperature (same k, clip, h).
  * humidity           sensor-fault checks and CUSUM statistics are reported, but humidity raises no cabin event.
  * co2_above_limit    1-hour rolling mean ppCO₂ > 3 mmHg: NASA-STD-3001 Vol. 2 Rev D [V2 6004] (evidence id OCHMO-TB-004).
                       ppCO₂ = ppm × 1e-6 × cabin pressure; the pressure is an input (default 760 mmHg, as in SCIENCE).
  * sensor faults      missing / invalid / out-of-bounds readings; isolated spikes (Hampel identifier, window ±3, t = 3);
                       flat-line (no change for ≥ 4 h) – only when the baseline itself varies: a deterministic (synthetic)
                       source has zero variance and cannot be told apart from a stuck sensor, which is reported instead.
Baseline = the first `baseline_minutes` of the series (default: first day); scale = max(1.4826·MAD, floor) with the same
floors as the exposure-aware PHANTOM variant. No temperature or humidity limit is used: none is in the evidence library.
"""
from __future__ import annotations

from statistics import median

CHANNELS = ('co2', 'temperature', 'humidity')
# Event statistics run on CO₂ and temperature only (spec B4.2); humidity is checked for sensor faults but raises no
# cabin event: fewer simultaneous statistics = fewer false alarms (the multiplicity effect found in PHANTOM, B2).
EVENT_CHANNELS = ('co2', 'temperature')
FLOORS = {'co2': 50.0, 'temperature': 0.3, 'humidity': 1.5}      # = app.phantom2_engine.FLOORS (cabin channels)
BOUNDS = {'co2': (0, 1_000_000), 'temperature': (-100, 100), 'humidity': (0, 100)}   # = contracts.Reading plausibility bounds
CUSUM_K = 0.5
WINSOR = 3.0
# h calibrated (validation/environment_study.py → calibrate_h) on nominal calibration runs, seeds 2001–2030, cabin
# noise 0 / 1 / 2 × floor: the smallest h with per-frame FPR ≤ 1 % at every noise level (same method as PHANTOM B2).
CUSUM_H = 14.0
CO2_LIMIT_MMHG = 3.0
CO2_LIMIT_SOURCE = 'NASA-STD-3001 Vol. 2 Rev D [V2 6004] via OCHMO-TB-004: 1-hour average ppCO2 ≤ 3 mmHg'
HAMPEL_WINDOW, HAMPEL_T = 3, 3.0
FLATLINE_MINUTES = 240
DIRECTION = {'co2': 1, 'temperature': 0, 'humidity': 0}           # 1 = one-sided (increase), 0 = two-sided
KIND = {'co2': 'co2_increase', 'temperature': 'temperature_drift', 'humidity': 'humidity_shift'}
# Physiological signals that the SYMBIOSIS response model links to cabin conditions (mission_systems.symbiosis.scenarios.effects).
# These are MODEL ASSUMPTIONS with illustrative coefficients – used only to suggest what to measure, never as evidence.
MODEL_LINKED_SIGNALS = ['fatigue', 'cognition', 'sleep_quality']


def _robust(values: list[float], floor: float):
    if len(values) < 3:
        return None, None, None
    m = median(values)
    mad = median(abs(v - m) for v in values)
    return m, max(1.4826 * mad, floor), 1.4826 * mad


def series_from_frames(frames: list[dict]) -> tuple[list[int], dict[str, list[dict]]]:
    minutes = [f['minute'] for f in frames]
    out = {m: [] for m in CHANNELS}
    for f in frames:
        rows = {r['metric']: r for r in f.get('environment', [])}
        for m in CHANNELS:
            r = rows.get(m)
            out[m].append({'value': None if r is None else r.get('value'), 'quality': 'missing' if r is None else r.get('quality', 'valid')})
    return minutes, out


def detect(minutes: list[int], series: dict[str, list[dict]], *, baseline_minutes: int = 1440,
           cabin_pressure_mmhg: float = 760.0, h: float | None = None) -> dict:
    """Per-frame states and merged events for one zone. Labels (if any) are never read here."""
    h = CUSUM_H if h is None else h
    if not 200 <= cabin_pressure_mmhg <= 800:
        raise ValueError('cabin_pressure_mmhg outside 200..800')
    n = len(minutes)
    step = (minutes[1] - minutes[0]) if n > 1 else 30
    t0 = minutes[0] if minutes else 0
    nb = sum(1 for m in minutes if m - t0 < baseline_minutes)
    frames = [{'minute': m, 'faults': [], 'alarms': [], 'statistics': {}} for m in minutes]
    baseline_info, applicability = {}, {}
    for ch in CHANNELS:
        rows = series[ch]
        vals = [r['value'] if r['quality'] == 'valid' and r['value'] is not None else None for r in rows]
        # ---- sensor faults
        for i, r in enumerate(rows):
            if r['quality'] in ('missing', 'invalid') or r['value'] is None:
                frames[i]['faults'].append({'channel': ch, 'kind': 'missing' if r['quality'] != 'invalid' else 'invalid'})
            elif not BOUNDS[ch][0] <= r['value'] <= BOUNDS[ch][1]:
                frames[i]['faults'].append({'channel': ch, 'kind': 'out_of_bounds'}); vals[i] = None
        base_vals = [v for v in vals[:nb] if v is not None]
        med, scale, raw_sd = _robust(base_vals, FLOORS[ch])
        baseline_info[ch] = {'median': med, 'scale': scale, 'n': len(base_vals), 'raw_robust_sd': raw_sd}
        if med is None:
            applicability[ch] = 'insufficient baseline (< 3 valid readings)'
            for f in frames:
                f['statistics'][ch] = None
            continue
        flat_ok = raw_sd is not None and raw_sd > 0
        applicability[ch] = 'ok' if flat_ok else ('flat-line check not applicable: the baseline has zero variance '
                                                  '(deterministic / synthetic source cannot be told apart from a stuck sensor)')
        # Hampel spikes (isolated outliers): flagged and excluded from the CUSUM
        clean = list(vals)
        for i, v in enumerate(vals):
            if v is None:
                continue
            nb_vals = [vals[j] for j in range(max(0, i - HAMPEL_WINDOW), min(n, i + HAMPEL_WINDOW + 1)) if j != i and vals[j] is not None]
            if len(nb_vals) >= 4:
                m_loc = median(nb_vals)
                s_loc = max(1.4826 * median(abs(x - m_loc) for x in nb_vals), FLOORS[ch])
                neighbours_agree = max(nb_vals) - min(nb_vals) <= 2 * HAMPEL_T * s_loc
                if abs(v - m_loc) > HAMPEL_T * s_loc and neighbours_agree:
                    frames[i]['faults'].append({'channel': ch, 'kind': 'spike'}); clean[i] = None
        # flat-line: a run of identical values lasting ≥ FLATLINE_MINUTES (only if the baseline varies). Batch analysis:
        # once a run qualifies, ALL its frames are marked, so a stuck sensor never feeds the CUSUM.
        if flat_ok:
            i = 0
            while i < n:
                j = i
                while j + 1 < n and vals[j + 1] is not None and vals[i] is not None and vals[j + 1] == vals[i]:
                    j += 1
                if vals[i] is not None and (j - i) * step >= FLATLINE_MINUTES:
                    for x in range(i, j + 1):
                        frames[x]['faults'].append({'channel': ch, 'kind': 'flat_line'}); clean[x] = None
                i = j + 1
        # winsorised CUSUM (one- or two-sided): each increment is clipped to ±WINSOR so that a single undetected
        # spike cannot raise an alarm on its own (robust CUSUM, Lucas & Crosier 1982)
        up = down = 0.0
        for i, v in enumerate(clean):
            if v is None:
                frames[i]['statistics'][ch] = {'z': None, 'cusum_up': round(up, 2), 'cusum_down': round(down, 2)}
                continue
            z = (v - med) / scale
            zc = max(-WINSOR, min(WINSOR, z))
            up = max(0.0, up + zc - CUSUM_K)
            down = max(0.0, down - zc - CUSUM_K) if DIRECTION[ch] == 0 else 0.0
            alarm = up > h or down > h
            frames[i]['statistics'][ch] = {'z': round(z, 2), 'cusum_up': round(up, 2), 'cusum_down': round(down, 2)}
            if alarm and ch in EVENT_CHANNELS:
                frames[i]['alarms'].append({'kind': KIND[ch], 'channel': ch, 'direction': 'increase' if up > h else 'decrease'})
    # absolute CO₂ limit: 1-hour rolling mean ppCO₂
    win = max(1, round(60 / step))
    co2 = [r['value'] if r['quality'] == 'valid' and r['value'] is not None and not any(
        x['channel'] == 'co2' for x in frames[i]['faults']) else None for i, r in enumerate(series['co2'])]
    for i in range(n):
        w = [v for v in co2[max(0, i - win + 1):i + 1] if v is not None]
        if len(w) == win:
            pp = sum(w) / len(w) * 1e-6 * cabin_pressure_mmhg
            frames[i]['statistics']['ppco2_1h_mmhg'] = round(pp, 3)
            if pp > CO2_LIMIT_MMHG:
                frames[i]['alarms'].append({'kind': 'co2_above_limit', 'channel': 'co2', 'value_mmhg': round(pp, 2)})
    for f in frames:
        f['environment_event'] = bool(f['alarms'])
        f['sensor_fault'] = bool(f['faults'])
        f['state'] = 'environment_event' if f['alarms'] else ('sensor_fault' if f['faults'] else 'nominal')
    return {'frames': frames, 'events': _events(frames, step), 'baseline': baseline_info, 'applicability': applicability,
            'parameters': {'cusum_k': CUSUM_K, 'cusum_h': h, 'winsor': WINSOR, 'floors': FLOORS, 'hampel_window': HAMPEL_WINDOW,
                           'hampel_t': HAMPEL_T, 'flatline_minutes': FLATLINE_MINUTES, 'baseline_minutes': baseline_minutes,
                           'cabin_pressure_mmhg': cabin_pressure_mmhg},
            'co2_limit': {'mmhg': CO2_LIMIT_MMHG, 'averaging': '1 hour', 'source': CO2_LIMIT_SOURCE, 'evidence_id': 'OCHMO-TB-004'},
            'scope': 'Cabin conditions only. Says nothing about crew physiology.'}


def _events(frames: list[dict], step: int) -> list[dict]:
    """Merge consecutive frames with the same alarm/fault kind into events."""
    out, open_ = [], {}
    for f in frames:
        kinds = {(a['kind'], a['channel']) for a in f['alarms']} | {('sensor_' + x['kind'], x['channel']) for x in f['faults']}
        for key in list(open_):
            if key not in kinds:
                ev = open_.pop(key); out.append(ev)
        for key in kinds:
            if key in open_:
                open_[key]['end_minute'] = f['minute'] + step
            else:
                open_[key] = {'kind': key[0], 'channel': key[1], 'start_minute': f['minute'], 'end_minute': f['minute'] + step,
                              'category': 'sensor_fault' if key[0].startswith('sensor_') else 'environment'}
    out += open_.values()
    for ev in out:
        ev['duration_minutes'] = ev['end_minute'] - ev['start_minute']
        ev['sustained'] = ev['category'] == 'environment' and ev['duration_minutes'] >= 120
    return sorted(out, key=lambda e: (e['start_minute'], e['kind']))


# ------------------------------------------------------------------ PHANTOM environmental context (B4.3)
def crew_context(env: dict, phantom_flags: dict[int, list[int]], phantom_states: dict[int, dict] | None = None,
                 window: tuple[int, int] | None = None) -> list[dict]:
    """Per crew member: environmental stressor vs measured physiological deviation vs hypothesis. No diagnosis.

    phantom_flags: crew_id -> minutes flagged by PHANTOM 2.0 (physiology channels only).
    phantom_states: crew_id -> {'scored': n, 'insufficient': n} for the same window (optional)."""
    frames = env['frames']
    lo, hi = window or (frames[0]['minute'], frames[-1]['minute'] + 1)
    sel = [f for f in frames if lo <= f['minute'] < hi]
    stress = [f['minute'] for f in sel if f['environment_event']]
    faults = [f['minute'] for f in sel if f['sensor_fault']]
    kinds = sorted({a['kind'] for f in sel for a in f['alarms']})
    out = []
    for cid, minutes in sorted(phantom_flags.items()):
        flagged = [m for m in minutes if lo <= m < hi]
        during = [m for m in flagged if m in set(stress)]
        st = (phantom_states or {}).get(cid, {})
        insufficient = st.get('scored', 1) == 0
        if insufficient:
            statement, conf = 'Insufficient physiological data in this window – no statement about the crew member.', 'none'
        elif stress and not flagged:
            statement, conf = ('Environmental stressor detected in the cabin; no confirmed physiological change in this crew '
                               'member’s measured signals.'), 'environment: detected / physiology: not changed'
        elif stress and during:
            statement, conf = ('Environmental stressor and physiological deviation co-occur. A link is a hypothesis to check, '
                               'not an established cause.'), 'co-occurrence only'
        elif stress and flagged:
            statement, conf = ('Physiological deviation outside the environmental-stressor period; the cabin change is unlikely '
                               'to explain it on its own.'), 'no temporal overlap'
        elif flagged:
            statement, conf = 'Physiological deviation without a detected environmental stressor.', 'environment ruled out by the cabin detector (within its sensitivity)'
        else:
            statement, conf = 'No environmental stressor and no physiological deviation detected.', 'nothing detected'
        suggest = []
        if stress and not insufficient:
            suggest = [{'signal': s, 'why': 'linked to cabin conditions in the SYMBIOSIS response model (illustrative coefficients – model assumption)'}
                       for s in MODEL_LINKED_SIGNALS]
        if faults:
            conf += '; cabin sensor faults in this window lower confidence in the environment assessment'
        out.append({'crew_id': cid, 'environment_stressor': bool(stress), 'stressor_kinds': kinds,
                    'stressor_minutes': len(stress) and [min(stress), max(stress)], 'physiology_flagged_samples': len(flagged),
                    'flagged_during_stressor': len(during), 'cabin_sensor_faults': len(faults),
                    'statement': statement, 'evidence': conf, 'suggested_measurements': suggest,
                    'diagnosis': None, 'note': 'Statistical / rule-based signals on synthetic data – not a medical assessment.'})
    return out


def evaluate(frames_pred: list[dict], frames_truth: list[dict], from_minute: int = 0) -> dict:
    """Frame-level confusion of `environment_event` against the generator's cabin label (frames[i]['environment_event'])."""
    tp = fp = tn = fn = 0
    onset = first = None
    for p, t in zip(frames_pred, frames_truth):
        if t['minute'] < from_minute:
            continue
        y, f = bool(t.get('environment_event')), bool(p['environment_event'])
        tp += y and f; fp += f and not y; fn += y and not f; tn += not y and not f
        if y and onset is None:
            onset = t['minute']
        if y and f and first is None:
            first = t['minute']
    return {'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn, 'precision': tp / (tp + fp) if tp + fp else None,
            'recall': tp / (tp + fn) if tp + fn else None, 'f1': 2 * tp / (2 * tp + fp + fn) if tp + fn else None,
            'fpr': fp / (fp + tn) if fp + tn else None, 'delay_min': (first - onset) if onset is not None and first is not None else None}
