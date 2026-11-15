"""Evaluation against injected labels; PHANTOM is provided by its owning module."""
from collections import defaultdict
from typing import Protocol
import numpy as np
from ..contracts import PhantomResult, API_VERSION

class PhantomAdapter(Protocol):
    def analyze(self, payload: dict) -> list[PhantomResult]: ...


def phantom_input(dataset):
    samples=[]
    sample_ids={(t['minute'],t['crew_id']):t['sample_id'] for t in dataset['ground_truth']}
    for frame in dataset['frames']:
        crew_ids=sorted({r['crew_id'] for r in frame['measurements']})
        # IDs are attached by original crew ordering in frames, reconstructed by truth mapping.
        ids={cid:sample_ids[frame['minute'],cid] for cid in crew_ids}
        for cid in crew_ids:
            samples.append({'sample_id':ids[cid], 'crew_id':cid,'timestamp':frame['timestamp'],
                            'measurements':[r for r in frame['measurements'] if r['crew_id']==cid],
                            'environment':frame['environment']})
    return {'api_version':API_VERSION,'origin':'synthetic','samples':samples}


def validate_results(dataset, results):
    values=[PhantomResult.model_validate(r) for r in results]
    allowed={t['sample_id'] for t in dataset['ground_truth']};seen=set()
    for r in values:
        if r.sample_id not in allowed:raise ValueError('Unknown PHANTOM sample_id')
        if r.sample_id in seen:raise ValueError('Duplicate PHANTOM sample_id')
        seen.add(r.sample_id)
    return values


def evaluate(dataset, results):
    rows=validate_results(dataset,results);pred={r.sample_id:r.anomaly for r in rows}
    tp=fp=tn=fn=abstained=0
    for label in dataset['ground_truth']:
        p=pred.get(label['sample_id']);actual=label['anomaly']
        if p is None:abstained+=1
        detected=p is True
        tp+=bool(detected and actual);fp+=bool(detected and not actual)
        fn+=bool(not detected and actual);tn+=bool(not detected and not actual)
    precision=tp/(tp+fp) if tp+fp else None;recall=tp/(tp+fn) if tp+fn else None
    total=tp+fp+tn+fn
    return {'tp':tp,'fp':fp,'tn':tn,'fn':fn,'precision':precision,'recall':recall,
            'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,'abstained':abstained,
            'coverage':(total-abstained)/total if total else 0,
            'definition':'Per crew/time sample. Missing/abstaining predictions count as no alert; missed positive labels count as FN.',
            'limitation':'Scores measure detection of injected synthetic events, not clinical accuracy.'}


def threshold_monitor(dataset, thresholds=None):
    thresholds=thresholds or {'heart_rate':('high',90),'fatigue':('high',6),'cognition':('low',70),'sleep_hours':('low',6)}
    results=[]
    for sample in phantom_input(dataset)['samples']:
        alerts=[]
        for r in sample['measurements']:
            if r['quality']!='valid' or r['metric'] not in thresholds:continue
            direction,value=thresholds[r['metric']]
            alerts.append(r['value']>=value if direction=='high' else r['value']<=value)
        results.append(PhantomResult(sample_id=sample['sample_id'],anomaly=any(alerts) if alerts else None,
                                     summary='Illustrative fixed threshold comparator'))
    return results


def experiment_report(dataset, phantom_results=None):
    return {'threshold':evaluate(dataset,threshold_monitor(dataset)),
            'phantom':evaluate(dataset,phantom_results) if phantom_results is not None else None,
            'phantom_status':'evaluated' if phantom_results is not None else 'not_connected',
            'model_version':dataset['model_version'],'seed':dataset['seed']}


def summarize(dataset):
    values=defaultdict(list);quality=defaultdict(int)
    for frame in dataset['frames']:
        for r in frame['measurements']+frame['environment']:
            quality[r['quality']]+=1
            if r['quality']=='valid':values[f"{r['crew_id'] or r['zone_id']}:{r['metric']}"].append(r['value'])
    return {'means':{k:float(np.mean(v)) for k,v in values.items()},'quality_counts':dict(quality),
            'uncertainty':dataset['limitations'],'model_version':dataset['model_version']}


def compare_runs(a,b):
    sa=summarize(a.dataset);sb=summarize(b.dataset)
    return {'a':sa,'b':sb,'delta_means':{k:sb['means'][k]-sa['means'][k] for k in sa['means'].keys()&sb['means'].keys()},
            'schedule_a':a.schedules['alternatives'][1]['metrics'],
            'schedule_b':b.schedules['alternatives'][1]['metrics'],
            'evaluation_a':experiment_report(a.dataset,a.phantom_results),
            'evaluation_b':experiment_report(b.dataset,b.phantom_results),
            'same_seed':a.scenario.seed==b.scenario.seed,
            'note':'Use the same seed, baselines and duration for controlled parameter comparisons.'}
