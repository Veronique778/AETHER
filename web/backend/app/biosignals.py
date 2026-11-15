"""Local biosignal storage and conservative partial-signal analysis, version 1.1.
Research clocks with no published date/zone remain relative; UTC is NULL.
Never inserts into astronaut/simulation tables. No automatic crew decisions.
"""
import csv
import io
import json
import math
import statistics as st
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from . import db

VERSION = 'aether-biosignal-1.4'
LIMIT = 2_000_000

def now():
    return datetime.now(timezone.utc).isoformat()

def init():
    with db.connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS bio_sessions (
          id TEXT PRIMARY KEY, participant TEXT NOT NULL, source_type TEXT NOT NULL,
          source TEXT NOT NULL, created_utc TEXT NOT NULL, status TEXT NOT NULL,
          metadata TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS bio_measurements (
          id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, t REAL,
          timestamp_utc TEXT, original_timestamp TEXT, timezone TEXT,
          signal TEXT NOT NULL, value REAL, unit TEXT NOT NULL,
          sampling_hz REAL, quality TEXT NOT NULL, valid INTEGER NOT NULL,
          missing INTEGER NOT NULL, connection TEXT, provenance TEXT NOT NULL,
          processing_version TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS bio_time ON bio_measurements(session_id,signal,t,id);
        CREATE TABLE IF NOT EXISTS bio_analysis (
          session_id TEXT PRIMARY KEY, created_utc TEXT NOT NULL, result TEXT NOT NULL);
        ''')

def create(participant, source_type, source, metadata=None):
    init()
    sid = uuid.uuid4().hex
    with db.connect() as c:
        c.execute('INSERT INTO bio_sessions VALUES (?,?,?,?,?,?,?)',
                  (sid, participant, source_type, source, now(), 'recording' if source_type == 'live_sensor' else 'importing', json.dumps(metadata or {})))
    return sid

def measurement(t, signal, value, unit, original=None, utc=None, quality='screened', provenance=None, connection=None):
    missing = value is None
    valid = not missing and math.isfinite(value) and quality not in ('rejected','corrupt','no_contact')
    return (t, utc, original, None, signal, value if value is not None and math.isfinite(value) else None,
            unit, None, quality, int(valid), int(missing), connection, json.dumps(provenance or {}), VERSION)

def append(sid, rows):
    with db.connect() as c:
        if not c.execute('SELECT 1 FROM bio_sessions WHERE id=?', (sid,)).fetchone():
            raise ValueError('Session does not exist')
        c.executemany('INSERT INTO bio_measurements(session_id,t,timestamp_utc,original_timestamp,timezone,signal,value,unit,sampling_hz,quality,valid,missing,connection,provenance,processing_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      ((sid, *r) for r in rows))

def finish(sid, status='ready', metadata=None):
    with db.connect() as c:
        if metadata is None:
            c.execute('UPDATE bio_sessions SET status=? WHERE id=?', (status,sid))
        else:
            c.execute('UPDATE bio_sessions SET status=?,metadata=? WHERE id=?',(status,json.dumps(metadata),sid))

def sessions():
    init()
    with db.connect() as c:
        return [dict(r) for r in c.execute('SELECT * FROM bio_sessions ORDER BY created_utc DESC')]

def session(sid):
    init()
    with db.connect() as c:
        r = c.execute('SELECT * FROM bio_sessions WHERE id=?',(sid,)).fetchone()
        if not r: raise ValueError('Session does not exist')
        result = dict(r)
        result['metadata'] = json.loads(result['metadata'])
        result['channels'] = [dict(x) for x in c.execute('SELECT signal,unit,COUNT(*) total,SUM(valid) valid,SUM(missing) missing,MIN(t) start,MAX(t) end FROM bio_measurements WHERE session_id=? GROUP BY signal,unit',(sid,))]
        return result

def delete(sid):
    from .ble_sensor import sensor
    if sensor.state.get('session_id') == sid and sensor.state['connection'] in ('connected','connecting'):
        raise ValueError('Disconnect the sensor before deleting its session')
    with db.connect() as c:
        for table in ('bio_measurements','bio_analysis','bio_sessions'):
            c.execute(f'DELETE FROM {table} WHERE '+('id' if table=='bio_sessions' else 'session_id')+'=?',(sid,))
    return {'deleted':sid}

def points(sid, signal='heart_rate', limit=1200, before=None):
    session(sid)
    limit = max(1,min(int(limit),5000))
    with db.connect() as c:
        # Retain both extrema per time bucket; bounded output covers the entire recording.
        span=c.execute('SELECT MIN(t),MAX(t) FROM bio_measurements WHERE session_id=? AND signal=?',(sid,signal)).fetchone()
        if span[0] is None: return []
        step=max(1,(span[1]-span[0])/max(1,limit//2))
        rows=c.execute('''SELECT CAST((t-?)/? AS INTEGER) bucket,MIN(t) t,MIN(value) low,MAX(value) high,
          COUNT(*) samples,SUM(valid) valid FROM bio_measurements WHERE session_id=? AND signal=? AND valid=1
          GROUP BY bucket ORDER BY bucket''',(span[0],step,sid,signal)).fetchall()
        return [dict(r) for r in rows]

def export(sid):
    session(sid)
    # Export paginated at API level for large recordings; <=5000 rows per page.
    return session(sid)

def csv_page(sid, offset=0):
    """Paged CSV export. Text cells are neutralised against formula injection."""
    from .security import csv_safe
    session(sid)
    offset=max(0,int(offset))
    with db.connect() as c:
        rows=c.execute('SELECT * FROM bio_measurements WHERE session_id=? ORDER BY id LIMIT 5000 OFFSET ?', (sid,offset)).fetchall()
    buf=io.StringIO(); w=csv.writer(buf)
    if rows:
        w.writerow(rows[0].keys()); w.writerows(tuple(csv_safe(v) for v in r) for r in rows)
    return {'csv':buf.getvalue(), 'rows':len(rows),'next_offset':offset+len(rows)}


def demo_recording(confirm_simulated=False, minutes=90, seed=1404):
    """DEMO MODE: deterministic SIMULATED HR/RR recording for presentations.

    Created only on explicit confirmation; source_type 'simulated_demo' and the
    participant label make it impossible to confuse with a real recording.
    First 60 min: resting ~62 bpm; then a step to ~74 bpm; a 3-minute sensor
    dropout at minute 75 is stored as missing rows.
    """
    if confirm_simulated is not True:
        raise ValueError('DEMO MODE requires explicit confirmation that the recording is simulated')
    minutes=max(65,min(int(minutes),240))
    import random
    rng=random.Random(seed)
    sid=create('DEMO · simulated participant','simulated_demo','AETHER DEMO MODE generator',
               {'data_class':'synthetic','generator':'aether-demo-hr-1.4','seed':seed,'minutes':minutes,
                'design':'60 min resting baseline (~62 bpm), then sustained step (~74 bpm); dropout minutes 75-78 stored as missing',
                'warning':'SIMULATED — not a human measurement'})
    rows=[]; t0=1_800_000_000.0
    for second in range(0,minutes*60,2):
        t=t0+second; minute=second/60
        if 75<=minute<78:
            rows.append(measurement(t,'heart_rate',None,'bpm',None,None,'connection_lost',{'demo':True,'event':'simulated_dropout'},'disconnected'))
            continue
        base=62.0 if minute<60 else 74.0
        hr=round(base+1.5*math.sin(second/300)+rng.gauss(0,1.2),1)
        rows.append(measurement(t,'heart_rate',hr,'bpm',None,None,'screened',{'demo':True},'simulated'))
        rr=60000/hr
        rows.append(measurement(t,'rr_interval',round(rr+rng.gauss(0,18),1),'ms',None,None,'screened',{'demo':True},'simulated'))
    append(sid,rows); finish(sid,'ready')
    return session(sid)

def rr_features(rows, window_seconds=300):
    """Exploratory RR variability; no claim that screened intervals are validated NN.
    Reject 300..2000ms violations and >20% local jumps. Never bridge rejected beats.
    """
    good=[]; pairs=[]; previous=None; previous_accepted=False; rejected=0
    for t,v,valid in rows:
        ok=valid and v is not None and 300<=v<=2000
        if ok and previous is not None and abs(v-previous[1])>0.2*previous[1]: ok=False
        if ok:
            good.append(v)
            if previous_accepted and previous is not None and 0<=t-previous[0]<=3: pairs.append(v-previous[1])
        else: rejected+=1
        previous_accepted=ok
        previous=(t,v) if valid and v is not None and 300<=v<=2000 else None
    enough=len(good)>=100 and rows and rows[-1][0]-rows[0][0]>=240 and rejected/max(1,len(rows))<=0.2
    return {'window_seconds':window_seconds,'valid_intervals':len(good),'rejected_intervals':rejected,
            'mean_rr_ms':st.mean(good) if good else None,
            'sdnn_ms':st.stdev(good) if enough else None,
            'rmssd_ms':math.sqrt(st.mean(x*x for x in pairs)) if enough and len(pairs)>=80 else None,
            'quality':'exploratory' if enough else 'insufficient_data',
            'limitation':'RR screening does not establish normal sinus rhythm; HRV is exploratory, not validated NN.'}

def analyze(sid):
    s=session(sid)
    groups=defaultdict(list); rr=defaultdict(list); origin=None
    with db.connect() as c:
        # Relative seconds and Unix seconds are never mixed within a session.
        for r in c.execute('SELECT t,signal,value,valid FROM bio_measurements WHERE session_id=? AND t IS NOT NULL ORDER BY t,id',(sid,)):
            if origin is None: origin=r['t']
            bucket=int((r['t']-origin)//300)
            if r['signal']=='rr_interval': rr[bucket].append((r['t'],r['value'],bool(r['valid'])))
            if r['signal']=='heart_rate': groups[bucket].append((r['t'],r['value'],bool(r['valid'])))
    windows=[]
    for b,items in sorted(groups.items()):
        valid=[v for t,v,ok in items if ok]
        # 1.5.1 (QA 02A-1, audit D10): coverage only from VALID samples; invalid rows never extend the span
        vt=[t for t,v,ok in items if ok]
        span=vt[-1]-vt[0] if vt else 0.0
        max_gap=max((y-x for x,y in zip(vt,vt[1:])),default=None)
        enough=len(valid)>=20 and span>=240 and (max_gap is None or max_gap<=60) and len(valid)/len(items)>=0.8
        windows.append({'start':origin+b*300,'end':origin+(b+1)*300,'mean_hr_bpm':st.mean(valid) if enough else None,
                        'samples':len(items),'valid':len(valid),'valid_span_s':round(span,3),'max_valid_gap_s':None if max_gap is None else round(max_gap,3),
                        'quality':'screened' if enough else 'insufficient_data',
                        'hrv':rr_features(rr[b]) if b in rr else None})
    baseline=[w for w in windows if w['start'] < (origin or 0)+3600 and w['mean_hr_bpm'] is not None]
    eligible=len(baseline)>=10
    med=st.median(w['mean_hr_bpm'] for w in baseline) if eligible else None
    scale=max(3.0,1.4826*st.median(abs(w['mean_hr_bpm']-med) for w in baseline)) if eligible else None
    for w in windows:
        test=eligible and w['start']>=(origin or 0)+3600 and w['mean_hr_bpm'] is not None
        w['score']=abs(w['mean_hr_bpm']-med)/scale if test else None
        w['outcome']=('flag' if w['score']>=3.5 else 'no_flag') if test else 'insufficient_data'
    scored=[w for w in windows if w['score'] is not None]
    available=[r['signal'] for r in s['channels'] if r['valid']]
    data_class={'simulated_demo':'synthetic','live_sensor':'real_wearable','research':'terrestrial_research'}.get(s['source_type'],'unknown')
    result={'session_id':sid,'source_type':s['source_type'],'data_class':data_class,'source':s['source'], 'participant':s['participant'],
      'simulated':s['source_type']=='simulated_demo',
      'processing_version':VERSION,'method':'PHANTOM adapter: exploratory univariate HR robust baseline',
      'multivariate_phantom':'insufficient_data: real channels are not mapped to synthetic fatigue/cognition/workload',
      'available_channels':available,'missing_channels':[x for x in ('sleep_duration','fatigue','cognition','workload') if x not in available],
      'baseline_period':[origin,(origin+3600) if origin is not None else None],
      'baseline_criteria':'At least ten valid 5-minute windows in first hour; per window >=20 valid samples, valid samples spanning >=240 s, no gap >60 s between valid samples, >=80% valid.',
      'baseline_hr_bpm':med,'noise_scale_bpm':scale,'threshold':3.5,'baseline_policy':'Frozen first hour; no adaptation or threshold fitting on later data.',
      'outcome':('flag' if any(w['outcome']=='flag' for w in scored) else 'no_flag') if scored else 'insufficient_data',
      'flag_rate':sum(w['outcome']=='flag' for w in scored)/len(scored) if scored else None,
      'quality_status':'screened, not clinical quality','windows':windows,
      'explanation':'Absolute deviation of five-minute mean HR from personal first-hour median divided by max(3 bpm, 1.4826 MAD).',
      'uncertainty':'Uncalibrated exploratory threshold; activity, posture, artifacts and circadian rhythms may cause flags. No diagnostic or astronaut validation.',
      'suggested_next_measurement':'Collect a longer resting HR recording with verified contact and contextual activity notes.',
      'limitations':['No known event ground truth: flag rate is not false-positive rate.','No cabin exposure inferred. No schedule changes.', 'UTC is unavailable for MMASH: original relative days retained.']
                    + (['SIMULATED DEMO recording: the step change is built into the generator; a flag here demonstrates the pipeline, not detection performance.'] if s['source_type']=='simulated_demo' else []),
      'gap_rows':sum(w['samples']-w['valid'] for w in windows),
      'nasa_reference':'Human NASA OSDR imports, when present, are shown beside this result as context only; they do not set this baseline or threshold.'}
    with db.connect() as c:
        c.execute('INSERT OR REPLACE INTO bio_analysis VALUES (?,?,?)',(sid,now(),json.dumps(result,allow_nan=False)))
    return result
