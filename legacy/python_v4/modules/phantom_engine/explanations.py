import json
from datetime import datetime,timezone
from .anomalies import analyze
def report(records,crew_id='demo'):
 result=analyze(records,crew_id);result['analyzed_at']=datetime.now(timezone.utc).isoformat()
 result['period']={'from':min((r['timestamp'] for r in records),default=None),'to':max((r['timestamp'] for r in records),default=None)}
 result['source_ids']=sorted({r.get('source_id','unspecified') for r in records})
 result['limitations']=['Research demonstration only','No medical diagnosis','No calibrated probabilities','Synthetic evaluation does not establish real-world accuracy']
 return result
def export_json(result,path):
 with open(path,'w',encoding='utf8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
