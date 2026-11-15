"""AETHER 0.9 reproducible validation experiments (synthetic data only).

    python validation/run_validation.py --out validation/results [--seeds 101-130] [--engine-seeds 101-110]

Held-out seeds 101–130 were NOT used for any design decision (design used seeds 1–10). All data come from the
Mission Systems synthetic generator (or, for experiment 3b, from a stated constructed distribution) – nothing
here is clinical validation. Every experiment writes CSV + JSON; summary.json collects the aggregates.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics as st
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mission_systems.co_orbit.optimization import alternatives  # noqa: E402
from mission_systems.contracts import PlanningInput, Scenario  # noqa: E402
from mission_systems.mission_lab.experiments import phantom_input  # noqa: E402
from mission_systems.mission_lab.generator import generate  # noqa: E402
from mission_systems.mission_lab.scenarios import SCENARIOS, demo  # noqa: E402

from app import phantom2 as p2, phantom2_engine as pe  # noqa: E402

DETECTION_TEMPLATES = ['sleep_loss', 'fatigue_rise', 'pulse_shift', 'cognitive_decline', 'workload_rise', 'environment', 'multifactor']
QUALITY_TEMPLATES = ['normal', 'missing', 'corrupt', 'noise']
PROTOCOL = {'duration_minutes': 2880, 'event_minute': 1800, 'baseline_minutes': 1440, 'evaluate_from_minute': 1440, 'sample_minutes': 'template default (30)'}


def seeds_of(s: str) -> list[int]:
    a, b = s.split('-')
    return list(range(int(a), int(b) + 1))


_sched: dict[str, dict] = {}


def dataset(template: str, seed: int, transform=None) -> dict:
    d = demo(template, seed=seed).model_dump(mode='json')
    d['duration_minutes'] = PROTOCOL['duration_minutes']
    for e in d['events']:
        e['minute'] = PROTOCOL['event_minute']
    sc = Scenario.model_validate(d)
    key = sc.planning.model_dump_json()
    if key not in _sched:
        _sched[key] = alternatives(sc.planning)['alternatives'][1]
    return generate(sc, _sched[key])


def score(ds, with_env=False, transform=None):
    pin = phantom_input if transform is None else (lambda x: transform(phantom_input(x)))
    return pe.compare(ds, pin, with_env=with_env, baseline_minutes=PROTOCOL['baseline_minutes'],
                      evaluate_from_minute=PROTOCOL['evaluate_from_minute'])['detectors']


def agg(rows: list[dict], key: str):
    v = [r[key] for r in rows if r.get(key) is not None]
    return {'mean': round(st.mean(v), 3), 'sd': round(st.stdev(v), 3) if len(v) > 1 else 0.0, 'n': len(v)} if v else {'mean': None, 'sd': None, 'n': 0}


def write(out: Path, name: str, rows: list[dict], meta: dict):
    with open(out / f'{name}.csv', 'w', newline='', encoding='utf-8') as f:
        if rows:
            keys = list(dict.fromkeys(k for r in rows for k in r))
            w = csv.DictWriter(f, fieldnames=keys, restval=''); w.writeheader(); w.writerows(rows)
    (out / f'{name}.json').write_text(json.dumps({'meta': meta, 'rows': rows}, indent=1), encoding='utf-8')


def summarise(rows, group_keys, detectors=p2.DETECTORS):
    out = {}
    for g in sorted({tuple(r[k] for k in group_keys) for r in rows}):
        sel = [r for r in rows if tuple(r[k] for k in group_keys) == g]
        out[' / '.join(map(str, g))] = {d: {m: agg([r for r in sel if r['detector'] == d], m) for m in ('precision', 'recall', 'f1', 'fpr', 'fp')} for d in detectors}
    return out


def confusion_rows(base: dict, det: dict):
    return [{**base, 'detector': d, **{k: c[k] for k in ('tp', 'fp', 'tn', 'fn', 'precision', 'recall', 'f1', 'fpr', 'abstained')}} for d, c in det.items()]


# ---------------------------------------------------------------- experiments 1–3, 5 (one detection sweep)
def detection_sweep(seeds):
    rows = []
    for t in DETECTION_TEMPLATES + QUALITY_TEMPLATES:
        for s in seeds:
            ds = dataset(t, s)
            for env in (False, True):
                rows += confusion_rows({'template': t, 'seed': s, 'channels': 'physiology+environment' if env else 'physiology'}, score(ds, env))
    return rows


# ---------------------------------------------------------------- experiment 3b: constructed correlation break
def correlation_break(seeds, n_base=400, n_test=200, rho=0.85):
    """Two correlated signals; in the test window their correlation is broken while each marginal stays within
    its normal range. Constructed data (bivariate normal) – shows *what kind* of anomaly multivariate distance can
    see and univariate z cannot. Not mission data."""
    rows = []
    for s in seeds:
        rng = np.random.default_rng(s)
        cov = np.array([[1, rho], [rho, 1]])
        Xb = rng.multivariate_normal([0, 0], cov, n_base)
        normal = rng.multivariate_normal([0, 0], cov, n_test)
        broken = rng.multivariate_normal([0, 0], [[1, -rho], [-rho, 1]], n_test)       # same marginals, opposite coupling
        X = np.vstack([normal, broken]); truth = [False] * n_test + [True] * n_test
        base = p2.fit_baseline(Xb, ['a', 'b'], {'a': 0.05, 'b': 0.05})
        res = p2.run_detectors(X, base, np.array([1.0, 1.0]), prewhiten=False)
        zabs = np.abs((X - base.median) / base.scale)
        two_sided_z = list((zabs >= p2.Z_FLAG).any(1))
        for d, pred in (('zscore_two_sided', two_sided_z), ('zscore', res['flags']['zscore']), ('mahalanobis', res['flags']['mahalanobis'])):
            c = p2.confusion(pred, truth)
            rows.append({'seed': s, 'detector': d, **{k: c[k] for k in ('tp', 'fp', 'tn', 'fn', 'precision', 'recall', 'f1', 'fpr')}})
    return rows


# ---------------------------------------------------------------- experiment 7: missing data / noise
def degrade(missing: float, noise: float, seed: int):
    rng = np.random.default_rng(seed)

    def f(payload):
        for smp in payload['samples']:
            keep = []
            for r in smp['measurements']:
                if rng.random() < missing:
                    continue
                if noise and r['metric'] in pe.FLOORS:
                    r = {**r, 'value': r['value'] + rng.normal(0, noise * pe.FLOORS[r['metric']])}
                keep.append(r)
            smp['measurements'] = keep
        return payload
    return f


def robustness(seeds):
    rows = []
    for t in ('sleep_loss', 'pulse_shift', 'multifactor'):
        for s in seeds:
            ds = dataset(t, s)
            for miss in (0.0, 0.1, 0.3, 0.5):
                for noise in (0.0, 1.0, 2.0):
                    if miss and noise:
                        continue
                    det = score(ds, transform=degrade(miss, noise, s * 7 + int(miss * 100) + int(noise * 10)))
                    rows += confusion_rows({'template': t, 'seed': s, 'missing_share': miss, 'noise_x_floor': noise}, {d: det[d] for d in ('zscore', 'cusum', 'mahalanobis', 'phantom2')})
    return rows


# ---------------------------------------------------------------- experiment 6: radiation consistency checks
def radiation_checks():
    from app.science import radiation as R
    rows = []
    cases = [
        ('Round trip 2×180 d deep space vs Zeitlin 2013 (0.66 ± 0.12 Sv)', [{'environment': 'deep_space', 'days': 360}], 660.0, 120.0, 'circular: the rate and its spread were taken from the same paper'),
        ('ISS 182 d at 0.731 mSv/d (Zhang 2020 ISS value)', [{'environment': 'iss', 'days': 182}], 182 * 0.731, None, 'arithmetic consistency only'),
        ('Mars surface 500 d at 0.64 mSv/d (Hassler 2014)', [{'environment': 'mars_surface', 'days': 500}], 500 * 0.64, None, 'arithmetic consistency only'),
        ('Lunar surface 30 d at 1.369 mSv/d (Zhang 2020)', [{'environment': 'lunar_surface', 'days': 30}], 30 * 1.369, None, 'arithmetic consistency only'),
    ]
    for title, seg, ref, ref_sd, kind in cases:
        r = R.simulate(seg, runs=4000, seed=1)
        rows.append({'case': title, 'reference_msv': round(ref, 1), 'reference_sd_msv': ref_sd, 'model_p50_msv': r['final']['p50'], 'model_p5_msv': r['final']['p5'],
                     'model_p95_msv': r['final']['p95'], 'rel_error_median': round((r['final']['p50'] - ref) / ref, 4),
                     'reference_inside_5_95': r['final']['p5'] <= ref <= r['final']['p95'], 'type': kind})
    spe = R.simulate([{'environment': 'deep_space', 'days': 100}], [{'day': 10, 'dose_msv': 300}], runs=1000, seed=2)
    base = R.simulate([{'environment': 'deep_space', 'days': 100}], runs=1000, seed=2)
    rows.append({'case': 'SPE additivity (300 mSv on day 10)', 'reference_msv': 300.0, 'reference_sd_msv': None, 'model_p50_msv': round(spe['final']['p50'] - base['final']['p50'], 1),
                 'model_p5_msv': None, 'model_p95_msv': None, 'rel_error_median': round((spe['final']['p50'] - base['final']['p50'] - 300) / 300, 4),
                 'reference_inside_5_95': None, 'type': 'bookkeeping'})
    return rows


# ---------------------------------------------------------------- experiments 4 and 8: engine runs
def engine_experiments(seeds):
    from app import db, mission_engine as me, service
    from tests.test_coorbit_phantom import _independent_violations
    db.DB_PATH = Path(tempfile.mkdtemp()) / 'validation.sqlite3'
    rows4, rows8 = [], []
    for t in ('normal', 'sleep_loss', 'pulse_shift', 'multifactor'):
        for s in seeds:
            run = me.run(me.EngineRunRequest(template=t, seed=s))
            sim = me._sim(run['id'])
            labelled = sorted({g['crew_id'] for g in sim.dataset['ground_truth'] if g['anomaly']})
            recs = me.coorbit_recommendations(run['id'])['recommendations']
            on_labelled = [r for r in recs if r['crew_id'] in labelled]
            row = {'template': t, 'seed': s, 'labelled_crew': ' '.join(map(str, labelled)) or '-', 'recommendations': len(recs),
                   'recs_on_labelled_crew': len(on_labelled), 'recs_on_unlabelled_crew': len(recs) - len(on_labelled),
                   'kinds': ' '.join(sorted({r['kind'] for r in recs})) or '-'}
            if recs:
                dec = me.coorbit_apply(run['id'], me.CoorbitApply(approved_ids=[r['id'] for r in recs], approved_by='validation script'))
                b, a = dec['before'], dec['after']
                crew_ids = sorted({r['crew_id'] for r in recs})
                data = sim.plan.model_dump()                      # rebuild the constrained plan independently of replan()
                for u in dec['constraints']:
                    next(c for c in data['crew'] if c['id'] == u['id']).update(u)
                plan_after = PlanningInput.model_validate(data)
                wm = lambda m, c: m['work_minutes'].get(str(c), m['work_minutes'].get(c, 0))
                used = lambda asg: {x for z in asg for x in z['crew_ids']}
                row.update({'valid_reported': dec['valid'], 'independent_violations_after': len(_independent_violations(plan_after, a['assignments'])),
                            'priority_score_delta': dec['comparison']['delta']['priority_score'], 'scheduled_tasks_delta': dec['comparison']['delta']['scheduled_tasks'],
                            'target_work_min_before': sum(wm(b['metrics'], c) for c in crew_ids), 'target_work_min_after': sum(wm(a['metrics'], c) for c in crew_ids),
                            'crew_removed_from_schedule': bool(used(b['assignments']) - used(a['assignments']))})
            rows4.append(row)
            if t == 'multifactor':
                summ = run
                flags = summ.get('phantom_flags', {})
                sym = me.symbiosis_analytics(run['id'], 'co2', 'fatigue', labelled[0] if labelled else 1)
                rows8.append({'seed': s, 'mission_lab_run': True,
                              'body_series_present': bool(summ.get('crew')) and bool(summ.get('series')),
                              'phantom_flags_on_labelled_crew': sum(len(flags.get(str(c), flags.get(c, []))) for c in labelled),
                              'phantom_flags_on_other_crew': sum(len(v) for k, v in flags.items() if int(k) not in labelled),
                              'symbiosis_relationship_pairs': sym['relationship'][0]['pairs'],
                              'coorbit_recs_on_labelled': len(on_labelled), 'coorbit_recs_elsewhere': len(recs) - len(on_labelled),
                              'coorbit_replan_valid': row.get('valid_reported'),
                              'recovery_link': 'UI only – verified in browser E2E (engine flag count + PHANTOM 2.0 drivers)'})
    return rows4, rows8


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(ROOT / 'validation' / 'results'))
    ap.add_argument('--seeds', default='101-130')
    ap.add_argument('--engine-seeds', default='101-110')
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    seeds, eseeds = seeds_of(a.seeds), seeds_of(a.engine_seeds)
    t0 = time.time(); summary = {'protocol': PROTOCOL, 'seeds': a.seeds, 'engine_seeds': a.engine_seeds, 'data': 'synthetic (Mission Systems generator, educational-1.0)', 'experiments': {}}
    meta = lambda d, **k: {'description': d, 'protocol': PROTOCOL, 'seeds': a.seeds, **k}

    det = detection_sweep(seeds)
    write(out, 'detection_all', det, meta('Per-template, per-seed confusion of every detector (experiments 1, 2, 3, 5).'))
    phys = [r for r in det if r['channels'] == 'physiology']
    summary['experiments']['1_phantom1_vs_phantom2'] = summarise([r for r in phys if r['detector'] in ('zscore', 'phantom2')], ['template'], ('zscore', 'phantom2'))
    summary['experiments']['2_z_vs_ewma_vs_cusum'] = summarise([r for r in phys if r['detector'] in ('zscore', 'ewma', 'adaptive', 'cusum')], ['template'], ('zscore', 'ewma', 'adaptive', 'cusum'))
    summary['experiments']['3a_univariate_vs_multivariate_engine'] = summarise([r for r in phys if r['detector'] in ('zscore', 'mahalanobis')], ['template'], ('zscore', 'mahalanobis'))
    cb = correlation_break(seeds)
    write(out, 'exp3b_correlation_break', cb, meta('Constructed bivariate data: coupling reversed, marginals unchanged.', rho=0.85))
    summary['experiments']['3b_correlation_break_constructed'] = {d: {m: agg([r for r in cb if r['detector'] == d], m) for m in ('precision', 'recall', 'f1', 'fpr')} for d in ('zscore_two_sided', 'zscore', 'mahalanobis')}
    single = [r for r in det if r['template'] in DETECTION_TEMPLATES and r['detector'] in ('zscore', 'phantom2')]
    for r in single:
        r['hazard_mix'] = 'multi-stressor' if r['template'] == 'multifactor' else 'single-stressor'
    summary['experiments']['5_single_vs_multi_stressor'] = summarise(single, ['hazard_mix', 'channels'], ('zscore', 'phantom2'))

    rad = radiation_checks()
    write(out, 'exp6_radiation', rad, meta('Radiation simulator consistency checks against the published values it uses.'))
    summary['experiments']['6_radiation'] = rad

    rob = robustness(seeds)
    write(out, 'exp7_robustness', rob, meta('Random removal of readings / added Gaussian noise (multiples of the metric floor).'))
    summary['experiments']['7_missing_noise'] = summarise(rob, ['template', 'missing_share', 'noise_x_floor'], ('zscore', 'cusum', 'mahalanobis', 'phantom2'))

    r4, r8 = engine_experiments(eseeds)
    write(out, 'exp4_coorbit_constraints', r4, meta('CO-ORBIT schedule before vs after approving all PHANTOM recommendations (app protocol: 1-day run, preceding nominal day as baseline).', seeds=a.engine_seeds))
    write(out, 'exp8_propagation', r8, meta('Propagation MISSION LAB → BODY → PHANTOM → SYMBIOSIS → CO-ORBIT → RECOVERY for the multifactor template.', seeds=a.engine_seeds))
    summary['experiments']['4_coorbit_with_without_constraints'] = r4
    summary['experiments']['8_end_to_end_propagation'] = r8
    summary['runtime_s'] = round(time.time() - t0, 1)
    (out / 'summary.json').write_text(json.dumps(summary, indent=1), encoding='utf-8')
    print('done', summary['runtime_s'], 's →', out)


if __name__ == '__main__':
    main()
