"""Render markdown tables from validation/results/summary.json (used for VALIDATION_REPORT.md)."""
import json
import sys
from pathlib import Path

S = json.loads((Path(__file__).parent / 'results' / 'summary.json').read_text(encoding='utf-8'))
E = S['experiments']
f = lambda x, d=2: '—' if x['mean'] is None else f"{x['mean']:.{d}f} ± {x['sd']:.{d}f}"
p = lambda x: '—' if x['mean'] is None else f"{100 * x['mean']:.1f} %"
out = []
out.append('### Exp 1 – PHANTOM 1.0 (robust z) vs PHANTOM 2.0, physiology only\n\n| Template | F1 1.0 | F1 2.0 | FPR 1.0 | FPR 2.0 | FP/run 1.0 | FP/run 2.0 |\n|---|---|---|---|---|---|---|')
for t, v in E['1_phantom1_vs_phantom2'].items():
    out.append(f"| {t} | {f(v['zscore']['f1'])} | {f(v['phantom2']['f1'])} | {p(v['zscore']['fpr'])} | {p(v['phantom2']['fpr'])} | {v['zscore']['fp']['mean']:.2f} | {v['phantom2']['fp']['mean']:.2f} |")
out.append('\n### Exp 2 – z vs EWMA vs adaptive baseline vs CUSUM (same data)\n\n| Template | z F1 | EWMA F1 | Adaptive F1 | CUSUM F1 | z FPR | EWMA FPR | Adaptive FPR | CUSUM FPR |\n|---|---|---|---|---|---|---|---|---|')
for t, v in E['2_z_vs_ewma_vs_cusum'].items():
    out.append(f"| {t} | {f(v['zscore']['f1'])} | {f(v['ewma']['f1'])} | {f(v['adaptive']['f1'])} | {f(v['cusum']['f1'])} | {p(v['zscore']['fpr'])} | {p(v['ewma']['fpr'])} | {p(v['adaptive']['fpr'])} | {p(v['cusum']['fpr'])} |")
out.append('\n### Exp 3a – univariate z vs robust Mahalanobis (engine data)\n\n| Template | z F1 | Mahalanobis F1 | z FPR | Mahalanobis FPR |\n|---|---|---|---|---|')
for t, v in E['3a_univariate_vs_multivariate_engine'].items():
    out.append(f"| {t} | {f(v['zscore']['f1'])} | {f(v['mahalanobis']['f1'])} | {p(v['zscore']['fpr'])} | {p(v['mahalanobis']['fpr'])} |")
out.append('\n### Exp 3b – constructed correlation break (ρ 0.85 → −0.85, marginals unchanged)\n\n| Detector | Precision | Recall | F1 | FPR |\n|---|---|---|---|---|')
for d, v in E['3b_correlation_break_constructed'].items():
    out.append(f"| {d} | {f(v['precision'])} | {f(v['recall'])} | {f(v['f1'])} | {p(v['fpr'])} |")
out.append('\n### Exp 5 – single-stressor vs multi-stressor templates\n\n| Group | z F1 | PHANTOM 2.0 F1 | z FPR | PHANTOM 2.0 FPR |\n|---|---|---|---|---|')
for g, v in E['5_single_vs_multi_stressor'].items():
    out.append(f"| {g} | {f(v['zscore']['f1'])} | {f(v['phantom2']['f1'])} | {p(v['zscore']['fpr'])} | {p(v['phantom2']['fpr'])} |")
out.append('\n### Exp 6 – radiation simulator consistency\n\n| Case | Reference mSv | Model median (5–95 %) | Rel. error | Ref. inside 5–95 % | Type |\n|---|---|---|---|---|---|')
for r in E['6_radiation']:
    band = f"{r['model_p50_msv']}" + (f" ({r['model_p5_msv']}–{r['model_p95_msv']})" if r['model_p5_msv'] is not None else '')
    out.append(f"| {r['case']} | {r['reference_msv']}{' ± ' + str(r['reference_sd_msv']) if r['reference_sd_msv'] else ''} | {band} | {100 * r['rel_error_median']:.1f} % | {r['reference_inside_5_95']} | {r['type']} |")
out.append('\n### Exp 7 – missing readings / added noise\n\n| Template / missing share / noise (× floor) | z F1 / FPR | CUSUM F1 / FPR | Mahalanobis F1 / FPR | PHANTOM 2.0 F1 / FPR |\n|---|---|---|---|---|')
for g, v in E['7_missing_noise'].items():
    out.append(f"| {g} | " + ' | '.join(f"{f(v[d]['f1'])} / {p(v[d]['fpr'])}" for d in ('zscore', 'cusum', 'mahalanobis', 'phantom2')) + ' |')
out.append('\n### Exp 4 – CO-ORBIT before/after approving all PHANTOM recommendations (seeds ' + S['engine_seeds'] + ')\n\n| Template | Runs | Runs with recs | Recs on labelled / other crew | Kinds | Valid (solver) | Independent violations | Target work before → after (min, mean) | Priority-score Δ (mean) | Scheduled-tasks Δ (mean) | Anyone removed |\n|---|---|---|---|---|---|---|---|---|---|---|')
import statistics as st
for t in ('normal', 'sleep_loss', 'pulse_shift', 'multifactor'):
    rows = [r for r in E['4_coorbit_with_without_constraints'] if r['template'] == t]
    w = [r for r in rows if r['recommendations']]
    kinds = sorted({k for r in w for k in r['kinds'].split()})
    m = lambda k: st.mean(r[k] for r in w) if w else None
    out.append(f"| {t} | {len(rows)} | {len(w)} | {sum(r['recs_on_labelled_crew'] for r in rows)} / {sum(r['recs_on_unlabelled_crew'] for r in rows)} | {', '.join(kinds) or '—'} | "
               f"{sum(bool(r.get('valid_reported')) for r in w)}/{len(w)} | {sum(r.get('independent_violations_after', 0) for r in w)} | "
               + (f"{m('target_work_min_before'):.0f} → {m('target_work_min_after'):.0f} | {m('priority_score_delta'):.0f} | {m('scheduled_tasks_delta'):.1f} | {sum(r['crew_removed_from_schedule'] for r in w)}" if w else '— | — | — | —') + ' |')
out.append('\n### Exp 8 – propagation across modules (multifactor, seeds ' + S['engine_seeds'] + ')\n\n| Seed | PHANTOM flags labelled / other crew | SYMBIOSIS pairs | CO-ORBIT recs labelled / other | Re-plan valid | RECOVERY |\n|---|---|---|---|---|---|')
for r in E['8_end_to_end_propagation']:
    out.append(f"| {r['seed']} | {r['phantom_flags_on_labelled_crew']} / {r['phantom_flags_on_other_crew']} | {r['symbiosis_relationship_pairs']} | {r['coorbit_recs_on_labelled']} / {r['coorbit_recs_elsewhere']} | {r['coorbit_replan_valid']} | UI E2E |")
sys.stdout.write('\n'.join(out) + '\n')
