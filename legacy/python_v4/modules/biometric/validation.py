"""Offline-first metric validation; ranges are data-quality guards, NOT clinical limits."""
import math
from datetime import datetime, timezone
METRICS = {
 'heart_rate':('bpm',20,250), 'resting_hr':('bpm',20,200), 'hrv_rmssd':('ms',0,500),
 'body_temp':('C',25,45), 'sleep_hours':('h',0,24), 'activity_minutes':('min',0,1440),
 'recovery_minutes':('min',0,1440), 'fatigue':('score_0_10',0,10),
 'stress':('score_0_10',0,10), 'mood':('score_0_10',0,10),
 'sleep_quality':('score_0_10',0,10), 'reaction_ms':('ms',50,5000),
 'attention':('score_0_10',0,10), 'accuracy':('ratio',0,1),
 'memory_accuracy':('ratio',0,1), 'co2_ppm':('ppm',0,100000)
}
ORIGINS={'real','manual','estimated','synthetic','research'}
def validate(record):
 x=dict(record); metric=x['metric']; value=float(x['value']); unit=x['unit']
 if not math.isfinite(value): raise ValueError('Non-finite value')
 if metric in METRICS:
  expected,low,high=METRICS[metric]
  if unit!=expected: raise ValueError(f'{metric} expects {expected}, got {unit}')
  if not low<=value<=high: raise ValueError('Value outside plausible data-quality range')
 if x.get('origin') not in ORIGINS: raise ValueError('Unknown origin')
 ts=datetime.fromisoformat(x['timestamp'].replace('Z','+00:00'))
 if ts.tzinfo is None: raise ValueError('Timezone required')
 if ts>datetime.now(timezone.utc)+__import__('datetime').timedelta(minutes=5): raise ValueError('Future timestamp')
 x['value']=value; x['timestamp']=ts.astimezone(timezone.utc).isoformat()
 x.setdefault('context','unspecified'); x.setdefault('source_id','unspecified')
 x.setdefault('quality','accepted'); return x
