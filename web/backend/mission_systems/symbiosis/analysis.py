"""Descriptive statistics only: aligned observations are not causal evidence."""
from collections import defaultdict
import numpy as np
from ..contracts import Reading


def trends(readings):
    groups=defaultdict(list)
    for raw in readings:
        r=Reading.model_validate(raw)
        if r.quality=='valid':groups[(r.metric,r.origin,r.source_id,r.crew_id,r.zone_id)].append(r)
    out=[]
    for key,rows in groups.items():
        rows.sort(key=lambda r:r.timestamp)
        x=np.array([(r.timestamp-rows[0].timestamp).total_seconds()/3600 for r in rows]);y=np.array([r.value for r in rows])
        slope=float(np.polyfit(x,y,1)[0]) if len(rows)>=3 and np.ptp(x)>0 else None
        out.append({'metric':key[0],'origin':key[1],'source_id':key[2],'crew_id':key[3],'zone_id':key[4],
                    'count':len(rows),'mean':float(y.mean()),'min':float(y.min()),'max':float(y.max()),
                    'slope_per_hour':slope,'unit':rows[0].unit,'method':'OLS descriptive trend',
                    'limitation':'Autocorrelated time series; no causal or significance claim.'})
    return out


def relationship(environment, physiology, *, env_metric, metric, crew_id, zone_id, lag_minutes=0):
    from datetime import timedelta
    env=[Reading.model_validate(r) for r in environment];phys=[Reading.model_validate(r) for r in physiology]
    origins={r.origin for r in env+phys}
    if len(origins)>1:raise ValueError('Filter one origin before calculating a relationship')
    xs=[r for r in env if r.metric==env_metric and r.zone_id==zone_id and r.quality=='valid']
    ys=[r for r in phys if r.metric==metric and r.crew_id==crew_id and r.quality=='valid']
    if len({r.source_id for r in xs})>1 or len({r.source_id for r in ys})>1:
        raise ValueError('Choose one source per series')
    def unique(rows):
        if len({r.timestamp for r in rows})!=len(rows):raise ValueError('Duplicate timestamps')
        return {r.timestamp:r.value for r in rows}
    x=unique(xs);y=unique(ys);pairs=[(v,y[t+timedelta(minutes=lag_minutes)]) for t,v in x.items() if t+timedelta(minutes=lag_minutes) in y]
    coefficient=None;reason=None
    if len(pairs)<3:reason='Fewer than three exactly aligned valid pairs'
    else:
        a,b=np.array(pairs).T
        if np.ptp(a)==0 or np.ptp(b)==0:reason='Constant series: correlation undefined'
        else:coefficient=float(np.corrcoef(a,b)[0,1])
    return {'pearson_r':coefficient,'pairs':len(pairs),'lag_minutes':lag_minutes,'reason':reason,
            'causal':False,'uncertainty':'Exploratory correlation; autocorrelation and confounding are not controlled.'}


def compare_periods(readings, start_a, end_a, start_b, end_b):
    if any(t.tzinfo is None for t in (start_a,end_a,start_b,end_b)):raise ValueError('Periods require timezone-aware timestamps')
    if start_a>=end_a or start_b>=end_b:raise ValueError('Period end must follow start')
    rows=[Reading.model_validate(r) for r in readings]
    return {'a':trends([r for r in rows if start_a<=r.timestamp<end_a]),
            'b':trends([r for r in rows if start_b<=r.timestamp<end_b]),
            'intervals':'start inclusive, end exclusive'}
