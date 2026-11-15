def trend(records,metric,window=5):
 values=[float(r['value']) for r in sorted(records,key=lambda x:x['timestamp']) if r['metric']==metric]
 if len(values)<window*2:return {'status':'insufficient_data','count':len(values)}
 old=sum(values[-2*window:-window])/window;new=sum(values[-window:])/window
 return {'status':'ok','previous_mean':old,'recent_mean':new,'delta':new-old,'direction':'up' if new>old else 'down' if new<old else 'stable'}
