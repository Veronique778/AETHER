"""AETHER 1.0 · B4 — ground-truth audit + environment-event detector evaluation (synthetic data only).

    python validation/environment_study.py --out validation/results_1_0

1. Label audit: how many samples each label marks per template (0.9 `anomaly` vs 1.0 `physiological_change` /
   `environment_exposure`), and the modelled physiological effect of a cabin change (template − `normal`, same seed ⇒
   same noise draws, so the difference is the deterministic model effect), in units of the metric floor.
2. Environment detector (app.environment_detector) against the generator's frame label `environment_event`
   (cabin event strength ≥ 0.25), monitoring from minute 1440, at cabin noise 0 / 1 / 2 × floor
   (the generator's cabin model is noiseless, so noise 0 is trivially easy – reported, not hidden).
3. Sensor corruption (normal + environment templates): spikes (3 % of readings, +8 floors), 20 % random dropouts, and a
   6-hour flat-line (sensor stuck at its last value) – faults must be reported as sensor faults, not as cabin events.
Seeds 5101–5120 (fresh).
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'validation'))
import run_validation as rv  # noqa: E402
from app import environment_detector as ed, phantom2_engine as pe  # noqa: E402

SEEDS = range(5101, 5121)
TEMPLATES = ['environment', 'multifactor', 'normal', 'sleep_loss']


def label_audit(seeds=range(5101, 5106)):
    rows = []
    for t in ['normal', 'sleep_loss', 'pulse_shift', 'environment', 'multifactor']:
        counts = {'anomaly': 0, 'physiological_change': 0, 'environment_exposure': 0, 'exposed_but_not_anomaly': 0,
                  'anomaly_without_physiological_change': 0, 'samples': 0}
        eff = {}
        for s in seeds:
            ds, ref = rv.dataset(t, s), rv.dataset('normal', s)
            for g in ds['ground_truth']:
                if g['minute'] < 1440:
                    continue
                counts['samples'] += 1
                counts['anomaly'] += g['anomaly']; counts['physiological_change'] += g['physiological_change']
                counts['environment_exposure'] += g['environment_exposure']
                counts['exposed_but_not_anomaly'] += g['environment_exposure'] and not g['anomaly']
                counts['anomaly_without_physiological_change'] += g['anomaly'] and not g['physiological_change']
            for fa, fb in zip(ds['frames'], ref['frames']):
                if fa['minute'] < 2400:        # last 8 h: event fully ramped and physiology settled
                    continue
                va = {(r['crew_id'], r['metric']): r['value'] for r in fa['measurements']}
                vb = {(r['crew_id'], r['metric']): r['value'] for r in fb['measurements']}
                for k, v in va.items():
                    if v is not None and vb.get(k) is not None:
                        eff.setdefault(k, []).append((v - vb[k]) / pe.FLOORS[k[1]] * pe.DIRECTION[k[1]])
        rows.append({'template': t, **counts,
                     'modelled_effect_floors_last_8h': {f'crew {c}': {m: round(float(np.mean(eff[(c, m)])), 2) for m in pe.PHYS if (c, m) in eff}
                                                         for c in (1, 2, 3)}})
    return rows


def add_noise(frames, level, rng):
    out = copy.deepcopy(frames)
    if level:
        for f in out:
            for r in f['environment']:
                if r['metric'] in ed.FLOORS and r['value'] is not None:
                    r['value'] = r['value'] + float(rng.normal(0, level * ed.FLOORS[r['metric']]))
    return out


def corrupt(frames, kind, rng):
    out = copy.deepcopy(frames)
    injected = set()
    env_rows = [(i, r) for i, f in enumerate(out) if f['minute'] >= 1440 for r in f['environment'] if r['metric'] in ed.FLOORS]
    if kind == 'spikes':
        for i, r in env_rows:
            if rng.random() < .03:
                r['value'] = r['value'] + 8 * ed.FLOORS[r['metric']]; injected.add(i)
    elif kind == 'dropout':
        for i, r in env_rows:
            if rng.random() < .2:
                r['value'] = None; r['quality'] = 'missing'; injected.add(i)
    elif kind == 'flat_line':
        start = int(rng.integers(60, 80))       # a frame index in the monitoring window
        for i in range(start, min(len(out), start + 12)):
            for r in out[i]['environment']:
                if r['metric'] in ed.FLOORS:
                    prev = next(x for x in out[start - 1]['environment'] if x['metric'] == r['metric'])
                    r['value'] = prev['value']; injected.add(i)
    return out, injected


CAL_SEEDS = range(2001, 2031)
CAL_TARGET = 0.01


def calibrate_h(grid=np.round(np.arange(5.0, 20.01, 0.5), 2)):
    """Smallest h with per-frame FPR ≤ 1 % on nominal calibration runs at every cabin noise level (0, 1, 2 × floor)."""
    data = []
    for s in CAL_SEEDS:
        ds = rv.dataset('normal', s)
        for level in (0.0, 1.0, 2.0):
            fr = add_noise(ds['frames'], level, np.random.default_rng(s * 53 + int(level * 10)))
            data.append((level, *ed.series_from_frames(fr)))
    table = []
    for h in grid:
        fpr = {}
        for level in (0.0, 1.0, 2.0):
            f = [fr['environment_event'] for lv, m, ser in data if lv == level for fr in ed.detect(m, ser, h=float(h))['frames'] if fr['minute'] >= 1440]
            fpr[level] = float(np.mean(f))
        table.append({'h': float(h), 'fpr_by_noise': fpr, 'worst': max(fpr.values())})
        if max(fpr.values()) <= CAL_TARGET:
            break
    ok = [t for t in table if t['worst'] <= CAL_TARGET]
    return {'h': ok[0]['h'] if ok else None, 'table': table, 'target': CAL_TARGET, 'seeds': '2001-2030'}


def detector_eval():
    rows = []
    for t in TEMPLATES:
        for s in SEEDS:
            ds = rv.dataset(t, s)
            for level in (0.0, 1.0, 2.0):
                rng = np.random.default_rng(s * 31 + int(level * 10))
                fr = add_noise(ds['frames'], level, rng)
                m, ser = ed.series_from_frames(fr)
                res = ed.detect(m, ser)
                rows.append({'template': t, 'seed': s, 'noise_x_floor': level, **ed.evaluate(res['frames'], ds['frames'], 1440)})
    return rows


def corruption_eval():
    rows = []
    for t in ('normal', 'environment'):
        for s in SEEDS:
            ds = rv.dataset(t, s)
            for kind in ('spikes', 'dropout', 'flat_line'):
                rng = np.random.default_rng(s * 17 + len(kind))
                noisy = add_noise(ds['frames'], 1.0, rng)          # flat-line can only be seen on a varying signal
                fr, injected = corrupt(noisy, kind, rng)
                m, ser = ed.series_from_frames(fr)
                res = ed.detect(m, ser)
                frames = res['frames']
                inj = [i for i in sorted(injected)]
                fault_hit = sum(frames[i]['sensor_fault'] for i in inj)
                # cabin events raised on corrupted frames that are NOT labelled cabin events
                false_env = sum(frames[i]['environment_event'] and not ds['frames'][i]['environment_event'] for i in inj)
                ev = ed.evaluate(frames, ds['frames'], 1440)
                rows.append({'template': t, 'seed': s, 'fault': kind, 'injected_frames': len(inj),
                             'fault_detected_share': fault_hit / len(inj) if inj else None,
                             'false_environment_event_on_faulty_frames': false_env, 'env_f1_with_fault': ev['f1'], 'env_fpr_with_fault': ev['fpr']})
    return rows


def summarise(rows, keys, metrics):
    out = []
    for g in sorted({tuple(r[k] for k in keys) for r in rows}, key=str):
        sel = [r for r in rows if tuple(r[k] for k in keys) == g]
        rec = dict(zip(keys, g)); rec['n'] = len(sel)
        for m in metrics:
            v = [r[m] for r in sel if r.get(m) is not None]
            rec[m] = round(float(np.mean(v)), 4) if v else None
        out.append(rec)
    return out


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    cal = calibrate_h()
    if cal['h'] != ed.CUSUM_H:
        print(f"WARNING: calibrated h = {cal['h']} differs from app.environment_detector.CUSUM_H = {ed.CUSUM_H}")
    audit = label_audit()
    det = detector_eval()
    cor = corruption_eval()
    res = {'doc': __doc__, 'seeds': f'{min(SEEDS)}-{max(SEEDS)}', 'calibration': cal, 'label_audit': audit,
           'detector_summary': summarise(det, ('template', 'noise_x_floor'), ('precision', 'recall', 'f1', 'fpr', 'delay_min')),
           'corruption_summary': summarise(cor, ('template', 'fault'), ('fault_detected_share', 'false_environment_event_on_faulty_frames', 'env_f1_with_fault', 'env_fpr_with_fault'))}
    (out / 'b4_results.json').write_text(json.dumps(res, indent=1, default=str), encoding='utf-8')
    print(json.dumps({k: res[k] for k in ('detector_summary', 'corruption_summary')}, indent=1))
    return res


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default=str(ROOT / 'validation' / 'results_1_0'))
    main(Path(ap.parse_args().out))
