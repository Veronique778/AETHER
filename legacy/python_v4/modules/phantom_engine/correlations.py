"""Exploratory same-day Pearson correlation; not causality."""
from math import sqrt
from modules.biometric.preprocessing import daily_series
def correlation(records,a,b,min_pairs=5):
 x={v['day']:v['mean'] for v in daily_series(records,a)};y={v['day']:v['mean'] for v in daily_series(records,b)}
 days=sorted(x.keys()&y.keys())
 if len(days)<min_pairs:return {'status':'insufficient_data','pairs':len(days)}
 vx=[x[d] for d in days];vy=[y[d] for d in days];mx=sum(vx)/len(vx);my=sum(vy)/len(vy)
 num=sum((u-mx)*(v-my) for u,v in zip(vx,vy));den=sqrt(sum((u-mx)**2 for u in vx)*sum((v-my)**2 for v in vy))
 return {'status':'ok' if den else 'undefined','pairs':len(days),'pearson_r':num/den if den else None,'caution':'Association is not causation'}
