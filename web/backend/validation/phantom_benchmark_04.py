"""AETHER 1.5 — BE3_04 controlled SYNTHETIC benchmark of the personal PHANTOM HR detector.

Implements the pre-registered protocol docs/validation/EXPERIMENT_PROTOCOL_BE3_04.md exactly; every parameter comes from
validation/protocol_config_04.json. The detector is NOT re-implemented here: generated rows go through the production
path app.signals.validate_item → app.phantom_analyses._screen → app.phantom_analyses.compute.

    cd web/backend && python -I validation/phantom_benchmark_04.py --split dev  --out /tmp/dev.json
    cd web/backend && python -I validation/phantom_benchmark_04.py --split test --out ../../docs/validation/phantom_benchmark_04_test.json

DATA CLASS: SYNTHETIC. These numbers describe an engineering property on a generator, not accuracy on people,
astronauts or in spaceflight.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import platform
import random
import statistics as st
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent)]

from app import phantom_analyses as pa  # noqa: E402
from app import signals as reg  # noqa: E402

CONFIG = json.loads((HERE / 'protocol_config_04.json').read_text(encoding='utf-8'))
AID = '0f0e0d0c-0b0a-4908-8706-050403020100'          # synthetic profile id (never a real account)
T0 = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)   # arbitrary fixed synthetic epoch
DUR_S = CONFIG['recording']['duration_min'] * 60
TEST_START_S = CONFIG['recording']['test_start_min'] * 60
WIN_S = CONFIG['recording']['window_min'] * 60
SCEN = CONFIG['scenarios']
ORDER = list(SCEN)


def detector_fingerprint() -> str:
    fns = [pa.contact_rule, pa._screen, pa.window_coverage, pa.window_usable, pa._windows, pa._baseline, pa.compute]
    src = ''.join(inspect.getsource(f) for f in fns) + json.dumps(pa.PARAMETERS, sort_keys=True) + pa.PROCESSING_VERSION
    return hashlib.sha256(src.encode()).hexdigest()


# ------------------------------------------------------------------------------------------------ generator
def _times(rng: random.Random, cadence: str | None) -> list[float]:
    spec = cadence or '2 s ± 0.3 s'
    out, t = [], rng.uniform(0, 1.0)
    if spec.startswith('exponential'):
        while t < DUR_S:
            out.append(t)
            t += rng.expovariate(1 / 2.0)
        return out
    step, jit = {'1 s ± 0.15 s': (1.0, 0.15), '2 s ± 0.3 s': (2.0, 0.3), '5 s ± 0.5 s': (5.0, 0.5),
                 '15 s ± 1.5 s': (15.0, 1.5)}[spec]
    while t < DUR_S:
        out.append(t)
        t += step + rng.uniform(-jit, jit)
    return out


def subject_params(seed: int) -> dict:
    r = random.Random(seed)
    s = CONFIG['subjects']
    return {'mu': r.uniform(*s['resting_hr_bpm_uniform']), 'beat_sd': r.uniform(*s['beat_noise_sd_bpm_uniform']),
            'slow_sd': r.uniform(*s['slow_component']['stationary_sd_bpm_uniform']), 'phi': s['slow_component']['phi']}


def generate(seed: int, scenario: str) -> dict:
    """→ {'samples': [(t_s, hr_int|None, contact)], 'onset_s', 'offset(t)'-description, 'kind'} — deterministic."""
    sp = subject_params(seed)
    cfg = SCEN[scenario]
    rng = random.Random(seed * 1000 + ORDER.index(scenario))
    times = _times(rng, cfg.get('cadence'))
    # slow AR(1) component on a 60 s grid (same construction for every scenario of one subject + its own seed)
    slow, x = [], rng.gauss(0, sp['slow_sd'])
    innov = sp['slow_sd'] * math.sqrt(1 - sp['phi'] ** 2)
    for _ in range(DUR_S // 60 + 2):
        slow.append(x)
        x = sp['phi'] * x + rng.gauss(0, innov)
    kind = cfg['kind']
    onset = None
    if 'onset_min_uniform' in cfg:
        onset = rng.uniform(*cfg['onset_min_uniform']) * 60
    bursts, bouts, dropout, closs = [], [], None, None
    if kind == 'spikes':
        for _ in range(cfg['bursts']):
            b0 = rng.uniform(TEST_START_S, DUR_S - cfg['burst_s'])
            bursts.append((b0, b0 + cfg['burst_s']))
    if kind == 'bouts':
        for i in range(cfg['bouts']):
            seg = (DUR_S - TEST_START_S) / cfg['bouts']
            ln = rng.uniform(*cfg['bout_min_uniform']) * 60
            b0 = TEST_START_S + i * seg + rng.uniform(0, seg - ln)
            bouts.append((b0, b0 + ln))
    if kind in ('baseline_missing', 'baseline_missing_with_step'):
        d0 = rng.uniform(5 * 60, TEST_START_S - cfg['dropout_min'] * 60 - 5 * 60)
        dropout = (d0, d0 + cfg['dropout_min'] * 60)
    if kind == 'step_with_contact_loss':
        w_on = TEST_START_S + math.ceil((onset - TEST_START_S) / WIN_S) * WIN_S
        closs = (w_on, w_on + cfg['contact_loss_windows_after_onset'] * WIN_S)
        dropout = (closs[1], closs[1] + cfg['dropout_min'] * 60)

    def offset(t: float) -> float:
        if kind in ('step', 'step_with_contact_loss', 'baseline_missing_with_step'):
            return cfg['delta_bpm'] if t >= onset else 0.0
        if kind == 'drift':
            return max(0.0, (t - cfg['start_min'] * 60) / 60 * cfg['slope_bpm_per_min'])
        if kind == 'bouts':
            return cfg['delta_bpm'] if any(a <= t < b for a, b in bouts) else 0.0
        return 0.0

    samples = []
    for t in times:
        if dropout and dropout[0] <= t < dropout[1]:
            continue
        hr = sp['mu'] + slow[int(t // 60)] + rng.gauss(0, sp['beat_sd']) + offset(t)
        contact = True
        if kind == 'spikes' and any(a <= t < b for a, b in bursts):
            hr += cfg['delta_bpm']
            contact = cfg['contact']
        if closs and closs[0] <= t < closs[1] and rng.random() < cfg['contact_false_share']:
            contact = False
        samples.append((round(t, 3), int(round(min(255, max(0, hr)))), contact))
    return {'samples': samples, 'onset_s': onset, 'kind': kind, 'cfg': cfg, 'offset': offset}


def rows_for(seed: int, scenario: str, samples: list) -> list[dict]:
    rows = []
    for i, (t, hr, contact) in enumerate(samples):
        cid = f'bench04-{seed}-{scenario}-{i}'
        item = reg.validate_item({'astronaut_id': AID, 'signal': 'heart_rate', 'value': float(hr), 'unit': 'bpm',
                                  'recorded_at': reg.iso_utc(T0 + timedelta(seconds=t)), 'data_class': 'synthetic',
                                  'source': 'BE3_04 synthetic benchmark', 'quality': 'good',
                                  'provenance': {'contact': contact, 'generator': CONFIG['protocol_id']},
                                  'client_measurement_id': cid})
        item.update(measurement_id=cid, status='active', mission_id=None, session_id=None, supersedes_id=None)
        rows.append(item)
    return rows


# ------------------------------------------------------------------------------------------------ labels / comparators
def label(gen: dict, w0: float, w1: float) -> str | None:
    """'pos' | 'neg' | None (ambiguous), per the pre-registered rule."""
    k, cfg = gen['kind'], gen['cfg']
    if k in ('step', 'step_with_contact_loss', 'baseline_missing_with_step'):
        on = gen['onset_s']
        return 'pos' if w0 >= on else ('neg' if w1 <= on else None)
    if k == 'drift':
        if gen['offset'](w0) >= cfg['positive_offset_bpm']:
            return 'pos'
        if gen['offset'](w1) < cfg['negative_offset_bpm']:
            return 'neg'
        return None
    return 'neg'


def comparators(windows: list[dict]) -> tuple[dict, dict]:
    c1, c2, hist = {}, {}, []
    for i, w in enumerate(windows):
        m = w['mean_hr_bpm']
        if m is None:
            continue
        if w['role'] == 'test':
            c1[i] = m > 100 or m < 40
            c2[i] = (abs(m - st.median(hist[-12:])) >= 10) if hist else None
        hist.append(m)
    return c1, c2


# ------------------------------------------------------------------------------------------------ one recording
def analyse(seed: int, scenario: str) -> dict:
    gen = generate(seed, scenario)
    rows = rows_for(seed, scenario, gen['samples'])
    snap = hashlib.sha256(json.dumps(gen['samples'], separators=(',', ':')).encode()).hexdigest()
    req = pa.parse_request({'astronaut_id': AID, 'from': reg.iso_utc(T0), 'to': reg.iso_utc(T0 + timedelta(seconds=DUR_S)),
                            'data_classes': ['synthetic']})
    counts = Counter()
    items = pa._screen(rows, AID, ['synthetic'], counts)
    res = pa.compute(req, items, None, counts)
    windows = res['windows']
    c1, c2 = comparators(windows)
    out_w = []
    t0 = T0.timestamp()
    for i, w in enumerate(windows):
        if w['role'] != 'test':
            continue
        w0 = reg.parse_utc(w['start']).timestamp() - t0
        w1 = reg.parse_utc(w['end']).timestamp() - t0
        out_w.append({'w0': w0, 'w1': w1, 'label': label(gen, w0, w1), 'scored': w['score'] is not None,
                      'phantom': (w['outcome'] == 'flag') if w['score'] is not None else None,
                      'c1': c1.get(i), 'c2': c2.get(i), 'reason': w['unusable_reason']})
    return {'seed': seed, 'scenario': scenario, 'outcome': res['outcome'],
            'reasons': [r['code'] for r in res['reasons']], 'onset_s': gen['onset_s'], 'snapshot_sha256': snap,
            'n_samples': len(gen['samples']), 'excluded': dict(counts), 'windows': out_w,
            'baseline': None if res['baseline'] is None else {k: res['baseline'][k] for k in
                                                                ('median_hr_bpm', 'mad_bpm', 'scale_bpm', 'windows_used')}}


# ------------------------------------------------------------------------------------------------ statistics
def wilson(k: int, n: int, z: float = 1.959964) -> list | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def window_counts(recs: list[dict], det: str) -> dict:
    tp = fp = tn = fn = neg_scored = 0
    total = scored = 0
    for r in recs:
        for w in r['windows']:
            total += 1
            dec = w[det] if det != 'phantom' else w['phantom']
            if det != 'phantom' and not w['scored']:
                dec = None
            if dec is None or w['label'] is None:
                if w['scored']:
                    scored += 1
                continue
            scored += 1
            if w['label'] == 'pos':
                tp += dec; fn += not dec
            else:
                fp += dec; tn += not dec; neg_scored += 1
    return {'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn, 'neg_scored': neg_scored, 'scored': scored, 'total': total}


def derived(c: dict) -> dict:
    prec = c['tp'] / (c['tp'] + c['fp']) if c['tp'] + c['fp'] else None
    rec = c['tp'] / (c['tp'] + c['fn']) if c['tp'] + c['fn'] else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else (0.0 if prec == 0 or rec == 0 else None)
    fah = c['fp'] / (c['neg_scored'] * WIN_S / 3600) if c['neg_scored'] else None
    return {'precision': prec, 'recall': rec, 'f1': f1, 'false_alarms_per_hour': fah,
            'coverage': c['scored'] / c['total'] if c['total'] else None}


def bootstrap(recs: list[dict], det: str, metric: str, B: int, seed: int) -> list | None:
    rng = random.Random(seed)
    vals = []
    for _ in range(B):
        sample = [recs[rng.randrange(len(recs))] for _ in recs]
        v = derived(window_counts(sample, det))[metric]
        if v is not None:
            vals.append(v)
    if len(vals) < B * 0.9:
        return None
    vals.sort()
    return [round(vals[int(0.025 * len(vals))], 4), round(vals[int(0.975 * len(vals)) - 1], 4)]


def recording_metrics(recs: list[dict], det: str) -> dict:
    n = len(recs)
    if det == 'phantom':
        outcomes = Counter(r['outcome'] for r in recs)
        anyflag = sum(r['outcome'] == 'flag' for r in recs)
    else:
        outcomes = None
        anyflag = sum(any(w[det] for w in r['windows'] if w['scored'] and w[det] is not None) for r in recs)
    det_flags, delays = 0, []
    event = recs and recs[0]['onset_s'] is not None or (recs and SCEN[recs[0]['scenario']]['kind'] == 'drift')
    if event:
        for r in recs:
            hit = [w for w in r['windows'] if w['label'] == 'pos' and w['scored'] and
                   (w['phantom'] if det == 'phantom' else w[det])]
            if hit:
                det_flags += 1
                ref = r['onset_s'] if r['onset_s'] is not None else None
                if ref is not None:
                    delays.append((min(w['w1'] for w in hit) - ref) / 60)
    out = {'n': n, 'any_flag': anyflag, 'any_flag_rate': round(anyflag / n, 4) if n else None,
           'any_flag_wilson95': wilson(anyflag, n)}
    if outcomes is not None:
        out['outcomes'] = dict(outcomes)
        out['insufficient_rate'] = round(outcomes.get('insufficient_data', 0) / n, 4) if n else None
    if event:
        out.update(detected=det_flags, detection_rate=round(det_flags / n, 4), detection_wilson95=wilson(det_flags, n),
                   delay_min_median=round(st.median(delays), 2) if delays else None,
                   delay_min_iqr=[round(q, 2) for q in st.quantiles(delays, n=4)[::2]] if len(delays) >= 4 else None)
    return out


def summarise(recs_by_s: dict, B: int, seed: int) -> dict:
    out = {}
    for s, recs in recs_by_s.items():
        block = {}
        for det in ('phantom', 'c1', 'c2'):
            c = window_counts(recs, det)
            d = derived(c)
            ci = {m: bootstrap(recs, det, m, B, seed) for m in ('recall', 'false_alarms_per_hour')
                  if d[m] is not None} if B else {}
            block[det] = {'window': {**c, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()},
                                     'bootstrap95': ci},
                          'recording': recording_metrics(recs, det)}
        block['unusable_reasons'] = dict(Counter(w['reason'] for r in recs for w in r['windows'] if w['reason']))
        out[s] = block
    return out


def acceptance(summary: dict) -> dict:
    st15 = summary['ST15']['phantom']['recording']
    n0 = summary['N0']['phantom']
    a1 = st15['detection_rate'] >= 0.90 and st15['detection_wilson95'][0] >= 0.80
    fah = n0['window']['false_alarms_per_hour']
    a2 = (fah is not None and fah <= 0.10) and n0['recording']['any_flag_rate'] <= 0.10
    a3 = all(summary[s]['phantom']['recording']['outcomes'] == {'insufficient_data': summary[s]['phantom']['recording']['n']}
             for s in ('BM', 'BMS'))
    a4 = summary['SPC']['phantom']['recording']['any_flag_rate'] <= n0['recording']['any_flag_rate'] + 0.05
    return {'A1': a1, 'A2': a2, 'A3': a3, 'A4': a4, 'H1_supported': a1 and a2 and a3 and a4}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', choices=['dev', 'test'], required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--bootstrap', type=int, default=None)
    ap.add_argument('--scenarios', default=','.join(ORDER))
    a = ap.parse_args(argv)
    fp = detector_fingerprint()
    if fp != CONFIG['detector']['fingerprint_sha256']:
        print(f'REFUSED: detector fingerprint {fp} differs from the pre-registered one', file=sys.stderr)
        return 2
    lo, hi = CONFIG['subjects']['development_seeds' if a.split == 'dev' else 'test_seeds']
    seeds = list(range(lo, hi + 1))
    scen = a.scenarios.split(',')
    B = CONFIG['uncertainty'] and (a.bootstrap if a.bootstrap is not None else 2000)
    t = time.time()
    recs = {s: [analyse(sd, s) for sd in seeds] for s in scen}
    summary = summarise(recs, B, 20261115)
    snap = hashlib.sha256(''.join(r['snapshot_sha256'] for s in scen for r in recs[s]).encode()).hexdigest()
    result = {'data_label': 'SYNTHETIC', 'protocol_id': CONFIG['protocol_id'], 'split': a.split, 'seeds': [lo, hi],
              'n_subjects': len(seeds), 'detector': {**CONFIG['detector'], 'fingerprint_runtime': fp},
              'environment': {'python': platform.python_version(), 'platform': platform.platform()},
              'config_sha256': hashlib.sha256((HERE / 'protocol_config_04.json').read_bytes()).hexdigest(),
              'data_snapshot_sha256': snap, 'bootstrap_resamples': B, 'runtime_s': None,
              'summary': summary, 'acceptance': acceptance(summary) if {'ST15', 'N0', 'BM', 'BMS', 'SPC'} <= set(scen) else None,
              'recordings': [{k: v for k, v in r.items() if k != 'windows'} for s in scen for r in recs[s]]}
    result['runtime_s'] = round(time.time() - t, 1)
    Path(a.out).write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'split': a.split, 'acceptance': result['acceptance'], 'runtime_s': result['runtime_s'],
                      'data_snapshot_sha256': snap}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
