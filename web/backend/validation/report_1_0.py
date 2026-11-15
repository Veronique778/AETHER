"""Generate the result tables of VALIDATION_REPORT_1_0.md from validation/results_1_0 (no number typed by hand).

    python validation/report_1_0.py > validation/results_1_0/tables_1_0.md
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

R = Path(__file__).resolve().parent / 'results_1_0'


def pct(x):
    return '—' if x in (None, '') else f'{float(x) * 100:.1f} %'


def num(x, d=2):
    return '—' if x in (None, '') else f'{float(x):.{d}f}'


def ci(row, key, f=pct):
    c = row.get(key + '_ci95')
    if isinstance(c, str):
        c = json.loads(c) if c else None
    return f(row.get(key)) + (f' [{f(c[0])}–{f(c[1])}]' if c else '')


def b2():
    out = []
    sel = json.loads((R / 'b2_selection.json').read_text())
    th = json.loads((R / 'b2_thresholds.json').read_text())
    out.append('### B2 – calibrated thresholds (nominal calibration runs, seeds 2001–2030)\n')
    out.append('| Statistic | Threshold |\n|---|---|')
    for k in sorted(th):
        out.append(f'| `{k}` | {th[k]} |')
    for stage, key in (('Stage 1 (pre-registered, validation seeds 3001–3020)', 'stage1'), ('Stage 2 (validation seeds 3101–3120)', 'stage2')):
        out.append(f'\n### B2 – {stage}: chosen **{sel[key]["chosen"]}**\n\nRule: {sel[key]["rule"]}\n')
        out.append('| Candidate | mean F1 (detection templates) | worst-case FPR | median delay (min) |\n|---|---|---|---|')
        for t in sel[key]['table']:
            out.append(f"| {t['candidate']} | {t['mean_f1_detection']:.3f} | {pct(t['worst_fpr'])} | {t['median_delay_min']} |")
    out.append('\n### B2 – stage 2 design (development seeds 1001–1010)\n')
    for n, v in sel['stage2_design'].items():
        out.append(f"* {n}: ν* = {v['nu_star']} ({v['rule']})")
    rows = list(csv.DictReader(open(R / 'b2_test_summary.csv', encoding='utf-8')))
    focus = [sel['chosen'], 'mahalanobis (0.9)', 'phantom2 0.9 = mahalanobis OR cusum', sel['stage1']['chosen'], 'zscore (PHANTOM 1.0)', 'cusum (0.9)',
             'mahalanobis OR cusum, Bonferroni/Holm h', 'phantom2 0.9 + persistence 2-of-3']
    out.append('\n### B2 – FINAL TEST (untouched seeds 4001–4030), all detection + normal + noise + environment templates pooled\n')
    out.append('| Candidate | Condition | Precision | Recall | F1 [95 % CI] | FPR [95 % CI] | FPR (0.9 labels) | False alerts / h | Median delay | Events detected |\n|---|---|---|---|---|---|---|---|---|---|')
    for name in focus:
        for r in [x for x in rows if x['candidate'] == name]:
            out.append(f"| {name} | {r['condition']} | {pct(r['precision'])} | {pct(r['recall'])} | {ci(r, 'f1', lambda v: num(v))} | {ci(r, 'fpr')} | "
                       f"{pct(r['fpr_v09_labels'])} | {num(r['false_alerts_per_hour'], 3)} | {r['median_delay_min'] or '—'} | {r['events_detected'] or '—'} |")
    res = json.loads((R / 'b2_results.json').read_text())
    out.append('\n### B2 – final test, all conditions pooled\n\n| Candidate | F1 | FPR | Recall | false alerts / h |\n|---|---|---|---|---|')
    for r in sorted(res['final_test_overall'], key=lambda r: -(r['f1'] or 0)):
        out.append(f"| {r['candidate']} | {num(r['f1'], 3)} | {pct(r['fpr'])} | {pct(r['recall'])} | {num(r['false_alerts_per_hour'], 3)} |")
    by = list(csv.DictReader(open(R / 'b2_test_by_template.csv', encoding='utf-8')))
    out.append('\n### B2 – final test F1 by template (chosen rule vs references)\n')
    conds = sorted({r['condition'] for r in by}, key=lambda c: float(c.split()[1]))
    out.append('| Candidate | Template | ' + ' | '.join(conds) + ' |\n|---|---|' + '---|' * len(conds))
    for name in (sel['chosen'], 'mahalanobis (0.9)', 'phantom2 0.9 = mahalanobis OR cusum'):
        for t in sorted({r['template'] for r in by}):
            cells = []
            for c in conds:
                x = next((r for r in by if r['candidate'] == name and r['template'] == t and r['condition'] == c), None)
                cells.append('—' if x is None else (num(x['f1']) if x['f1'] else 'FPR ' + pct(x['fpr'])))
            out.append(f'| {name} | {t} | ' + ' | '.join(cells) + ' |')
    out.append('\nEmpirical SNR (positives vs clean negatives, max unfavourable z): ' +
               '; '.join(f'{k} {v}' for k, v in list(res['snr_final_test'].items())[:14]) + ' …')
    return out


def b3():
    p = R / 'b3_results.json'
    if not p.exists():
        return ['\n### B3 – not run']
    res = json.loads(p.read_text())
    out = [f"\n### B3 – missing data (seeds {res['protocol']['seeds']}, B2 rule: {res['protocol']['b2_chosen']})\n",
           '| Covariance | Candidate | Condition (mode / share / noise) | Recall | F1 | FPR | insufficient_data share | Median delay |\n|---|---|---|---|---|---|---|---|']
    for r in res['summary']:
        if r['candidate'] in ('mahalanobis (0.9)', res['protocol']['b2_chosen'], 'phantom2 0.9 = mahalanobis OR cusum'):
            out.append(f"| {r['stats']} | {r['candidate']} | {r['condition']} | {pct(r['recall'])} | {num(r['f1'])} | {pct(r['fpr'])} | {pct(r['insufficient_share'])} | {r['median_delay_min'] or '—'} |")
    return out


def b4():
    res = json.loads((R / 'b4_results.json').read_text())
    out = ['\n### B4 – label audit (last-8-hour modelled effect in units of the metric floor; seeds 5101–5105)\n',
           '| Template | samples | `anomaly` (0.9) | `physiological_change` | `environment_exposure` | exposed but not `anomaly` | crew 2 effect |\n|---|---|---|---|---|---|---|']
    for r in res['label_audit']:
        out.append(f"| {r['template']} | {r['samples']} | {r['anomaly']} | {r['physiological_change']} | {r['environment_exposure']} | {r['exposed_but_not_anomaly']} | "
                   f"{json.dumps(r['modelled_effect_floors_last_8h'].get('crew 2', {}))} |")
    out.append(f"\nCalibrated CUSUM h = {res['calibration']['h']} (target ≤ {pct(res['calibration']['target'])} false frames, seeds {res['calibration']['seeds']}).\n")
    out.append('| Template | Cabin noise × floor | Precision | Recall | F1 | FPR | Delay (min) |\n|---|---|---|---|---|---|---|')
    for r in res['detector_summary']:
        out.append(f"| {r['template']} | {r['noise_x_floor']} | {pct(r['precision'])} | {pct(r['recall'])} | {num(r['f1'])} | {pct(r['fpr'])} | {num(r['delay_min'], 0)} |")
    out.append('\n| Template | Injected fault | fault frames reported | false cabin events on faulty frames (mean / run) | F1 with fault | FPR with fault |\n|---|---|---|---|---|---|')
    for r in res['corruption_summary']:
        out.append(f"| {r['template']} | {r['fault']} | {pct(r['fault_detected_share'])} | {num(r['false_environment_event_on_faulty_frames'])} | {num(r['env_f1_with_fault'])} | {pct(r['env_fpr_with_fault'])} |")
    return out


def b5():
    p = R / 'b5_coorbit_hitl.json'
    if not p.exists():
        return ['\n### B5 – not run']
    res = json.loads(p.read_text())
    keys = ['profile', 'template', 'runs', 'base_schedule_valid', 'base_independent_violations', 'runs_with_recs', 'recs_on_labelled', 'recs_on_other',
            'reject_changes_nothing', 'first_approval_rejected', 'valid_after_subset_retry', 'valid_after_approval', 'independent_violations_after', 'optimality_proven', 'run_schedule_unchanged',
            'target_work_before_mean', 'target_work_after_mean', 'dropped_tasks_total', 'anyone_removed']
    out = ['\n### B5 – CO-ORBIT human-in-the-loop (fresh seeds 201–230 / 201–210)\n', '| ' + ' | '.join(keys) + ' |', '|' + '---|' * len(keys)]
    for r in res['summary']:
        out.append('| ' + ' | '.join(str(r.get(k, '—')) for k in keys) + ' |')
    keys = ['profile', 'template', 'cf_max_load_A', 'cf_max_load_B', 'cf_rest_target_A', 'cf_rest_target_B', 'cf_moved_tasks_mean', 'cf_unscheduled_A',
            'cf_unscheduled_B', 'cf_priority_score_delta_mean', 'replan_seconds_mean']
    out += ['\n### B6.3 – counterfactual planning comparison (A = current plan, B = approved constraints; planning quantities only)\n',
            '| ' + ' | '.join(keys) + ' |', '|' + '---|' * len(keys)]
    for r in res['summary']:
        out.append('| ' + ' | '.join(str(r.get(k, '—')) for k in keys) + ' |')
    return out


def _esc(lines):
    # candidate names contain '|' (adaptive rule) – keep markdown tables intact
    return [l.replace(' | ewma', ' ⟂ ewma').replace(' | mahalanobis OR', ' ⟂ mahalanobis OR') for l in lines]


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print('\n'.join(_esc(b2() + b3() + b4() + b5())))
