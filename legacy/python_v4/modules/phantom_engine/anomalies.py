"""Transparent multi-factor research rule, not a medical diagnosis."""
from .baseline import baseline
from .timeseries import trend
from .uncertainty import data_uncertainty
from .measurements import suggest
REQUIRED=['resting_hr','sleep_hours','fatigue','reaction_ms','activity_minutes']
DIRECTIONS={'resting_hr':1,'sleep_hours':-1,'fatigue':1,'reaction_ms':1}
def analyze(records,crew_id='demo'):
 report={'crew_id':crew_id,'algorithm':'robust_mad_v1','research_only':True,'alerts':[],'baselines':{},'trends':{},'threshold_comparison':{},'required_metrics':REQUIRED}
 recent={}
 for metric in DIRECTIONS:
  rs=[r for r in sorted(records,key=lambda x:x['timestamp']) if r['metric']==metric and r.get('quality','accepted')=='accepted']
  if len(rs)<6:continue
  b=baseline(rs[:-1],metric,min_samples=5);report['baselines'][metric]=b
  report['trends'][metric]=trend(rs,metric,window=3)
  if b['status']!='ok':continue
  last=float(rs[-1]['value']);scale=max(1.4826*b['mad'],abs(b['median'])*0.03,0.01)
  z=(last-b['median'])/scale*DIRECTIONS[metric]
  recent[metric]={'last':last,'robust_deviation':round(z,3),'baseline':b['median']}
  if z>=3:report['alerts'].append({'type':'single_metric','metric':metric,'evidence':recent[metric],'explanation':'Latest value differs from personal historical median in a concerning direction; verify measurement and context.'})
 flagged=[m for m,v in recent.items() if v['robust_deviation']>=1.5]
 if len(flagged)>=2:report['alerts'].append({'type':'multifactor','metrics':flagged,'explanation':'Several indicators changed together relative to personal history; not a diagnosis.'})
 # A fixed threshold comparator for demonstration only; not clinical cutoffs.
 limits={'resting_hr':100,'sleep_hours':5,'fatigue':8,'reaction_ms':500}
 for metric,lim in limits.items():
  if metric in recent:report['threshold_comparison'][metric]=recent[metric]['last']>lim if DIRECTIONS[metric]>0 else recent[metric]['last']<lim
 report['latest_evidence']=recent
 report['uncertainty']=data_uncertainty(records,REQUIRED)
 report['suggested_measurements']=suggest(report['uncertainty']['missing_metrics'])
 report['status']='review_pattern' if report['alerts'] else 'no_pattern_detected_or_insufficient_data'
 return report
