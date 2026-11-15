"""PHANTOM 1.0 vs 2.0 on Mission Systems engine datasets (label-free input, labels used only for scoring)."""
from __future__ import annotations

import numpy as np

from . import phantom2 as p2

PHYS = ['heart_rate', 'fatigue', 'cognition', 'sleep_hours', 'sleep_quality', 'activity', 'workload']
DIRECTION = {'heart_rate': 1, 'fatigue': 1, 'workload': 1, 'cognition': -1, 'sleep_hours': -1, 'sleep_quality': -1, 'activity': -1}
FLOORS = {'heart_rate': 2.8, 'fatigue': .55, 'workload': .6, 'cognition': 2.5, 'sleep_hours': .35, 'sleep_quality': 3.0, 'activity': 6.0,
          'co2': 50.0, 'temperature': .3, 'humidity': 1.5}
# Cabin channels (SYMBIOSIS) used by the exposure-aware variant. Light is excluded: it follows the day/night cycle.
ENV = ['co2', 'temperature', 'humidity']


def _rows(payload: dict, with_env: bool):
    metrics = PHYS + (ENV if with_env else [])
    by_crew: dict[int, list] = {}
    for s in payload['samples']:
        by_crew.setdefault(s['crew_id'], []).append(s)
    out = {}
    for cid, samples in by_crew.items():
        samples.sort(key=lambda s: s['timestamp'])
        X = np.full((len(samples), len(metrics)), np.nan)
        for i, s in enumerate(samples):
            vals = {r['metric']: r for r in s['measurements']}
            if with_env:
                vals.update({r['metric']: r for r in s.get('environment', [])})
            for j, m in enumerate(metrics):
                r = vals.get(m)
                if r is not None and r.get('quality', 'valid') == 'valid' and r.get('value') is not None:
                    X[i, j] = r['value']
        out[cid] = (samples, X)
    return metrics, out


def detect(payload: dict, *, with_env: bool = False, baseline_minutes: int | None = None, baseline_fraction: float = .25,
           bootstrap: int = 0, explain: bool = False, seed: int = 0, baseline_payload: dict | None = None) -> dict:
    """Run every detector per crew member. Returns {detector: {sample_id: flag}} and per-sample details.

    Baseline priority: `baseline_payload` (a preceding nominal day of the same crew) > `baseline_minutes` > first
    `baseline_fraction` of the samples."""
    metrics, crews = _rows(payload, with_env)
    base_rows = _rows(baseline_payload, with_env)[1] if baseline_payload else {}
    direction = np.array([DIRECTION.get(m, 1) for m in metrics], float)
    flags = {d: {} for d in p2.DETECTORS}
    details = {}
    states: dict[str, str] = {}
    regimes: dict[int, dict] = {}
    rng = np.random.default_rng(seed)
    for cid, (samples, X) in crews.items():
        if cid in base_rows:
            Xb = base_rows[cid][1]
            nb = None
        elif baseline_minutes is not None:
            t0 = samples[0]['timestamp']
            from datetime import datetime
            start = datetime.fromisoformat(t0)
            nb = sum((datetime.fromisoformat(s['timestamp']) - start).total_seconds() / 60 < baseline_minutes for s in samples)
        else:
            nb = max(6, int(len(samples) * baseline_fraction))
        if cid not in base_rows:
            Xb = None
        if nb is not None:
            Xb = X[:nb]
        base = p2.fit_baseline(Xb, metrics, FLOORS)
        res = p2.run_detectors(X, base, direction, bootstrap=bootstrap, rng=rng, explain=explain)
        for d in p2.DETECTORS:
            for s, f in zip(samples, res['flags'][d]):
                flags[d][s['sample_id']] = f
        for s, info in zip(samples, res['details']):
            details[s['sample_id']] = info
        for s, st in zip(samples, res['states']):
            states[s['sample_id']] = st
        regimes[cid] = res['regime']
    return {'metrics': metrics, 'flags': flags, 'details': details, 'states': states, 'regimes': regimes}


def compare(dataset: dict, phantom_input, *, with_env: bool = False, baseline_minutes: int | None = None,
            evaluate_from_minute: int = 0, baseline_fraction: float = .25, baseline_dataset: dict | None = None) -> dict:
    """Confusion metrics of every detector against the engine's hidden labels."""
    payload = phantom_input(dataset)
    res = detect(payload, with_env=with_env, baseline_minutes=baseline_minutes, baseline_fraction=baseline_fraction,
                 baseline_payload=phantom_input(baseline_dataset) if baseline_dataset else None)
    truth = [t for t in dataset['ground_truth'] if t['minute'] >= evaluate_from_minute]
    out = {}
    for d in p2.DETECTORS:
        out[d] = p2.confusion([res['flags'][d].get(t['sample_id']) for t in truth], [t['anomaly'] for t in truth])
    # 1.0 (B4 audit): the same detectors against the physiological-change label, cabin-exposed negatives excluded
    clean = [t for t in truth if t.get('physiological_change') or not t.get('environment_exposure')]
    audited = {d: p2.confusion([res['flags'][d].get(t['sample_id']) for t in clean], [bool(t.get('physiological_change')) for t in clean])
               for d in p2.DETECTORS} if truth and 'physiological_change' in truth[0] else None
    st = [res['states'].get(t['sample_id']) for t in truth]
    return {'detectors': out, 'detectors_physiological_labels': audited,
            'states': {k: st.count(k) for k in ('flag', 'no_flag', 'insufficient_data')},
            'regimes': {str(k): v for k, v in res['regimes'].items()},
            'samples_scored': len(truth), 'with_environment_channels': with_env,
            'baseline': 'preceding nominal day (same crew, no injected events)' if baseline_dataset else
                        (f'first {baseline_minutes} min' if baseline_minutes else f'first {int(baseline_fraction * 100)} % of samples')}
