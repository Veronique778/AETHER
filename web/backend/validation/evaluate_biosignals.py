"""Reproduce independent MMASH evaluation, without copying recordings into release.
Usage (from project root): python web/backend/validation/evaluate_biosignals.py PATH/TO/MMASH.zip
Predeclared evaluation participants: user_1,user_10,user_20. Threshold never fitted.
"""
import argparse
import json
import math
import statistics
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import db,biosignals as bio,mmash

def main():
    parser=argparse.ArgumentParser();parser.add_argument('dataset');parser.add_argument('--out',default='validation_1_1');args=parser.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    results=[]
    with tempfile.TemporaryDirectory(prefix='aether-research-eval-') as temp:
        db.DB_PATH=Path(temp)/'evaluation.sqlite3';db.init_db()
        for participant in ['user_1','user_10','user_20']:
            start=time.perf_counter();s=mmash.import_mmash(args.dataset,participant,True);import_seconds=time.perf_counter()-start
            start=time.perf_counter();a=bio.analyze(s['id']);seconds=time.perf_counter()-start
            channels=s['channels'];hr=next(c for c in channels if c['signal']=='heart_rate');rr=next(c for c in channels if c['signal']=='rr_interval')
            means=[w['mean_hr_bpm'] for w in a['windows'] if w['mean_hr_bpm'] is not None]
            base={'participant':participant,'measurements':sum(c['total'] for c in channels),'channels':channels,
                  'import_seconds':import_seconds,'analysis_seconds':seconds,'corrupt_rows':s['metadata']['corrupt_rows'],
                  'out_of_order_rows':s['metadata']['out_of_order_rows'],'rr_rejection_rate':1-rr['valid']/rr['total'],
                  'baseline_hr_bpm':a['baseline_hr_bpm'],'flag_rate':a['flag_rate'],
                  'scored_windows':sum(w['score'] is not None for w in a['windows']),
                  'analysis_coverage':len(means)/len(a['windows']) if a['windows'] else 0,
                  'median_adjacent_window_change_bpm':statistics.median(abs(x-y) for x,y in zip(means,means[1:])) if len(means)>1 else None,
                  'source_files':s['metadata']['files'],'outcome':a['outcome']}
            (out/(participant+'-analysis.json')).write_text(json.dumps(a,indent=2),encoding='utf-8')
            # Deterministic corruption/missingness intervention on the same participant;
            # not independent test subjects and not event ground truth.
            with db.connect() as c:
                c.execute("UPDATE bio_measurements SET value=NULL,valid=0,missing=1,quality='rejected' WHERE session_id=? AND signal='heart_rate' AND id%5=0",(s['id'],))
            missing=bio.analyze(s['id'])
            with db.connect() as c:
                c.execute("UPDATE bio_measurements SET value=300,valid=0,quality='rejected' WHERE session_id=? AND signal='heart_rate' AND id%17=0",(s['id'],))
            artifacts=bio.analyze(s['id'])
            base['sensitivity']={'every_fifth_record_missing':{'outcome':missing['outcome'],'flag_rate':missing['flag_rate'],'scored_windows':sum(w['score'] is not None for w in missing['windows'])},
                                 'plus_every_seventeenth_record_artifact':{'outcome':artifacts['outcome'],'flag_rate':artifacts['flag_rate'],'scored_windows':sum(w['score'] is not None for w in artifacts['windows'])}}
            results.append(base)
            print(participant,base['measurements'],round(import_seconds,2),a['outcome'],a['flag_rate'],flush=True)
            bio.delete(s['id'])
    protocol={'dataset':mmash.SOURCE,'evaluation_participants':['user_1','user_10','user_20'],'threshold':3.5,'window_seconds':300,
              'baseline_seconds':3600,'threshold_fitting':'none; exploratory fixed rule','split':'No training; each participant uses its own first hour, only later windows scored.',
              'ground_truth':'No event ground truth. No precision, recall, F1, specificity, FPR or diagnostic accuracy claimed.',
              'uncertainty':'No binomial CI: adjacent within-person windows are dependent; only 3 participants, exploratory descriptive evaluation.',
              'results':results}
    (out/'mmash-evaluation.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
    # A standalone scientific figure using matplotlib, without publishing raw recordings.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(8,4))
    for participant in protocol['evaluation_participants']:
        a=json.loads((out/(participant+'-analysis.json')).read_text(encoding='utf-8'))
        origin=a['baseline_period'][0]
        ax.plot([(w['start']-origin)/3600 for w in a['windows']],[w['mean_hr_bpm'] if w['mean_hr_bpm'] is not None else float('nan') for w in a['windows']],label=participant,linewidth=1)
    ax.axvspan(0,1,color='gray',alpha=.15,label='Personal baseline (first hour)');ax.set(xlabel='Recording time (hours)',ylabel='Screened 5-minute mean HR (bpm)',title='MMASH: descriptive HR trends (3 participants)');ax.legend(fontsize=8);fig.tight_layout();fig.savefig(out/'mmash-hr-trends.png',dpi=150);plt.close(fig)

if __name__=='__main__':main()
