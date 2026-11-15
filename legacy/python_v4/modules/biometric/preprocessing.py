"""Explicit daily grouping and coverage; never silently impute gaps."""
from collections import defaultdict
def daily_series(records,metric):
 days=defaultdict(list)
 for r in records:
  if r['metric']==metric and r.get('quality','accepted')=='accepted':
   days[r['timestamp'][:10]].append(float(r['value']))
 return [{'day':k,'mean':sum(v)/len(v),'count':len(v)} for k,v in sorted(days.items())]
def coverage(records,required_metrics):
 present={r['metric'] for r in records if r.get('quality','accepted')=='accepted'}
 missing=sorted(set(required_metrics)-present)
 return {'present':sorted(present),'missing':missing,'fraction':(len(set(required_metrics)&present)/len(set(required_metrics))) if required_metrics else 1.0}
