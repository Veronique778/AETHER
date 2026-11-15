import statistics

def baseline(records,metric,min_samples=5,context=None):
 values=[float(r['value']) for r in records if r['metric']==metric and (context is None or r.get('context')==context) and r.get('quality','accepted')=='accepted']
 if len(values)<min_samples:return {'metric':metric,'status':'insufficient_data','count':len(values),'minimum':min_samples}
 med=statistics.median(values);mad=statistics.median(abs(v-med) for v in values)
 return {'metric':metric,'status':'ok','count':len(values),'median':med,'mad':mad,'context':context}
