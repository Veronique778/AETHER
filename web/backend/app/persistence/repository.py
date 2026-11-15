"""Object-scoped data access; all mutations are transactional, raw events append-only."""
import csv
import io
import json
import sqlite3
from app import db
from app import access_control as acl
from app.schemas_15 import MeasurementCreate, SessionCreate, AnalysisSave, ProcessedValue, AlertCreate
from .common import APIError, audit, digest, dumps, uid, utcnow


def rowdict(row):
    result = dict(row)
    for k in ('metadata','result','input_ids','details','end_metadata'):
        if k in result and isinstance(result[k],str): result[k] = json.loads(result[k] or '{}')
    for k in ('payload_hash','idempotency_key'): result.pop(k,None)
    if 'written_via' in result and (result['written_via']=='legacy_unverified' or (result['origin']=='real' and result['written_via']!='device_manager')):
        result['metadata']={k:v for k,v in result['metadata'].items() if k not in ('data_class','contact','be3_quality','client_measurement_id') and not k.startswith('be3_')}

    if 'missing' in result: result['missing'] = bool(result['missing'])
    return result


def get_profile(user):
    with db.connect() as c:
        aid = acl.profile(c,user)
        audit(c,user['id'],'read','profile',aid)
        return dict(c.execute('SELECT id,user_id,display_name,language,created_at FROM astronaut_profiles WHERE id=?',(aid,)).fetchone())


def patch_profile(user, data):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE'); aid = acl.profile(c,user,write=True)
        for key in ('display_name','language'):
            if key in data: c.execute(f'UPDATE astronaut_profiles SET {key}=? WHERE id=?',(data[key],aid))
        audit(c,user['id'],'update','profile',aid)
    return get_profile(user)


def create_device(user,data):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE'); aid = acl.profile(c,user,write=True)
        did = uid()
        try:
            c.execute('INSERT INTO devices VALUES(?,?,?,?,?,?)',(did,aid,data['name'],data['kind'],data.get('external_id'),utcnow()))
        except sqlite3.IntegrityError:
            raise APIError(409,'device_exists','Device already registered') from None
        audit(c,user['id'],'create','device',did)
        return dict(c.execute('SELECT * FROM devices WHERE id=?',(did,)).fetchone())


def owned_device(c,aid,did,include_removed=False):
    sql='SELECT 1 FROM devices WHERE id=? AND astronaut_id=?'
    if not include_removed: sql+=' AND id NOT IN (SELECT device_id FROM device_lifecycle WHERE removed_at IS NOT NULL)'
    if not c.execute(sql,(did,aid)).fetchone():
        raise APIError(404,'not_found','Resource not found')


def list_devices(user):
    with db.connect() as c:
        audit(c,user['id'],'list','device',user['astronaut_id'])
        return {'items':[dict(r) for r in c.execute('SELECT * FROM devices WHERE astronaut_id=? AND id NOT IN (SELECT device_id FROM device_lifecycle WHERE removed_at IS NOT NULL) ORDER BY created_at',(user['astronaut_id'],))]}


def create_session(user,data):
    data = SessionCreate.model_validate(data).model_dump()
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        return _create_session(c,user,data)


def _create_session(c,user,data):
    """Shared by HTTP repository and token-bound transactional adapter."""
    if data['origin']=='research': raise APIError(422,'research_separate','Use the research store')
    aid = acl.profile(c,user,write=True)
    acl.mission(c,user,data['mission_id'])
    if data['device_id']: owned_device(c,aid,data['device_id'])
    sid = uid()
    c.execute('INSERT INTO sensor_sessions VALUES(?,?,?,?,?,?,?,?,?)',
              (sid,aid,data['mission_id'],data['device_id'],data['source'],data['origin'],data['started_at'],None,dumps(data['metadata'])))
    audit(c,user['id'],'create','sensor_session',sid)
    return rowdict(c.execute('SELECT * FROM sensor_sessions WHERE id=?',(sid,)).fetchone())


def session_row(c,user,sid,write=False):
    row = c.execute('SELECT * FROM sensor_sessions WHERE id=?',(sid,)).fetchone()
    if not row: raise APIError(404,'not_found','Resource not found')
    acl.profile(c,user,row['astronaut_id'],write=write,mission_id=row['mission_id'])
    return row


def close_session(user,sid,status="saved",metadata=None):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE'); session_row(c,user,sid,write=True)
        if status not in ('saved','interrupted','recovered','failed'): raise APIError(422,'session_status','Invalid terminal status')
        meta=dumps(metadata or {})
        if len(meta.encode())>8192: raise APIError(422,'metadata_size','Session end metadata exceeds 8 KB')
        c.execute('INSERT INTO session_end_states VALUES(?,?,?) ON CONFLICT(session_id) DO NOTHING',(sid,status,meta))
        c.execute('UPDATE sensor_sessions SET ended_at=COALESCE(ended_at,?) WHERE id=?',(utcnow(),sid))
        audit(c,user['id'],'close','sensor_session',sid)
    return {'closed':True}


def device_sessions(user,did,q):
    if any(getattr(q,k) is not None for k in ('astronaut_id','mission_id','device_id','session_id','signal','start','end')):
        raise APIError(422,'filter_unsupported','Only after and limit are supported here')
    with db.connect() as c:
        owned_device(c,user['astronaut_id'],did,include_removed=True)
        rows = c.execute('SELECT s.rowid AS seq,s.*,e.status AS end_status,e.metadata AS end_metadata FROM sensor_sessions s LEFT JOIN session_end_states e ON e.session_id=s.id WHERE s.device_id=? AND s.rowid>? ORDER BY s.rowid LIMIT ?',
                         (did,q.after,q.limit+1)).fetchall()
        audit(c,user['id'],'list','sensor_session',did)
        return page(rows,q.limit)


def page(rows,limit):
    more = len(rows)>limit
    result = [rowdict(r) for r in rows[:limit]]
    return {'items':result,'next_cursor':result[-1]['seq'] if more and result else None}


def add_measurements(user,items,*,enqueue=True):
    validated = [MeasurementCreate.model_validate(x).model_dump() for x in items]
    if not 1<=len(validated)<=1000: raise APIError(422,'batch_size','Batch must contain 1–1000 measurements')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        return [_insert(c,user,d,enqueue=enqueue) for d in validated]


_DEVICE_WRITER = object()

def _reserved(value):
    if isinstance(value,dict):
        return any(k in ('data_class','contact','be3_quality','client_measurement_id','written_via') or k.startswith('be3_') or _reserved(v) for k,v in value.items())
    if isinstance(value,list): return any(_reserved(v) for v in value)
    return False


def _insert(c,user,d,enqueue=True,writer=None):
    if writer is not _DEVICE_WRITER and _reserved(d['metadata']):
        raise APIError(422,'reserved_provenance','Provenance and sensor contact are server-controlled')
    aid = acl.profile(c,user,d['astronaut_id'],write=True)
    acl.mission(c,user,d['mission_id'])
    if d['device_id']: owned_device(c,aid,d['device_id'])
    if d['session_id']:
        s = session_row(c,user,d['session_id'],write=True)
        if (s['astronaut_id'],s['mission_id'],s['device_id'],s['origin']) != (aid,d['mission_id'],d['device_id'],d['origin']):
            raise APIError(422,'session_mismatch','Measurement must match its session owner, mission, device and origin')
    # The identity of the receiving user's local profile does not alter the event hash.
    payload = {k:v for k,v in d.items() if k not in ('id','astronaut_id','idempotency_key')}
    phash = digest(dumps(payload))
    old = c.execute('SELECT * FROM raw_measurements WHERE astronaut_id=? AND idempotency_key=?',(aid,d['idempotency_key'])).fetchone()
    if old:
        if old['payload_hash']!=phash or (d['id'] and d['id']!=old['id']):
            raise APIError(409,'idempotency_conflict','Idempotency key was used with different content')
        return {'measurement':rowdict(old),'created':False}
    if d['session_id'] and s['ended_at'] and (writer is _DEVICE_WRITER or d['measured_at'] > s['ended_at']):
        raise APIError(409,'session_closed','Measurement is later than session closure')
    if d['id'] and c.execute('SELECT 1 FROM raw_measurements WHERE id=?',(d['id'],)).fetchone():
        raise APIError(409,'id_conflict','Event identifier is already in use')
    if d['supersedes_id']:
        old = c.execute('SELECT * FROM raw_measurements WHERE id=?',(d['supersedes_id'],)).fetchone()
        if not old: raise APIError(404,'not_found','Resource not found')
        acl.profile(c,user,old['astronaut_id'],write=True)
        if any(old[k]!=d[k] for k in ('signal','unit','mission_id','origin','device_id','session_id')):
            raise APIError(422,'correction_scope','Correction must retain the original signal and source scope')
        if c.execute('SELECT 1 FROM raw_measurements WHERE supersedes_id=?',(old['id'],)).fetchone():
            raise APIError(409,'revision_conflict','Correct the latest revision of this event')
    mid = d['id'] or uid(); now = utcnow()
    c.execute('''INSERT INTO raw_measurements(id,astronaut_id,mission_id,device_id,session_id,source,signal,value,unit,
      measured_at,received_at,origin,quality,confidence,missing,processing_version,metadata,idempotency_key,payload_hash,supersedes_id,written_via)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
      (mid,aid,d['mission_id'],d['device_id'],d['session_id'],d['source'],d['signal'],d['value'],d['unit'],
       d['measured_at'],now,d['origin'],d['quality'],d['confidence'],int(d['value'] is None),d['processing_version'],
       dumps(d['metadata']),d['idempotency_key'],phash,d['supersedes_id'],
       ({'real':'device_manager','manual':'api','simulated':'synthetic_generator'}.get(d['origin'],'api') if writer is _DEVICE_WRITER else 'api')))
    if enqueue:
        c.execute('INSERT INTO sync_events(id,user_id,measurement_id,created_at) VALUES(?,?,?,?)',(uid(),user['id'],mid,now))
    audit(c,user['id'],'correct' if d['supersedes_id'] else 'create','measurement',mid)
    return {'measurement':rowdict(c.execute('SELECT * FROM raw_measurements WHERE id=?',(mid,)).fetchone()),'created':True}


def get_measurement(user,mid):
    with db.connect() as c:
        row = c.execute('SELECT * FROM raw_measurements WHERE id=?',(mid,)).fetchone()
        if not row: raise APIError(404,'not_found','Resource not found')
        acl.profile(c,user,row['astronaut_id'],mission_id=row['mission_id'])
        audit(c,user['id'],'read','measurement',mid)
        return rowdict(row)


def _where(c,user,q):
    aid = acl.profile(c,user,q.astronaut_id,mission_id=q.mission_id)
    where = ['astronaut_id=?']; args = [aid]
    # Medical officers must always supply a granted mission and cannot escape that filter.
    for key in ('mission_id','device_id','session_id','signal'):
        val = getattr(q,key)
        if val is not None: where.append(key+'=?'); args.append(val)
    for key,op in [('start','>='),('end','<=')]:
        if getattr(q,key): where.append('measured_at'+op+'?'); args.append(getattr(q,key))
    return aid,where,args


def list_measurements(user,q):
    with db.connect() as c:
        aid,where,args = _where(c,user,q)
        rows = c.execute('SELECT * FROM raw_measurements WHERE '+' AND '.join(where)+' AND seq>? ORDER BY seq LIMIT ?',
                         (*args,q.after,q.limit+1)).fetchall()
        audit(c,user['id'],'list','measurement',aid)
        return page(rows,q.limit)



def latest_measurements(user):
    # A bounded, one-row-per-signal view of recent usable personal measurements.
    # Unlike the history API it does not get stuck on the first 100 oldest rows.
    with db.connect() as c:
        aid = acl.profile(c, user)
        rows = c.execute("""
          WITH ranked AS (
            SELECT *, ROW_NUMBER() OVER (
              PARTITION BY signal ORDER BY measured_at DESC, seq DESC
            ) AS signal_rank
            FROM raw_measurements
            WHERE astronaut_id=? AND value IS NOT NULL AND missing=0
              AND measured_at IS NOT NULL
              AND quality NOT IN ('rejected','corrupt','no_contact','connection_lost')
          )
          SELECT * FROM ranked WHERE signal_rank=1 ORDER BY signal
        """, (aid,)).fetchall()
        totals = c.execute("""SELECT signal,COUNT(*) AS samples,
            SUM(CASE WHEN value IS NOT NULL AND missing=0 AND measured_at IS NOT NULL
                  AND quality NOT IN ('rejected','corrupt','no_contact','connection_lost')
                 THEN 1 ELSE 0 END) AS usable
            FROM raw_measurements WHERE astronaut_id=? GROUP BY signal""", (aid,)).fetchall()
        audit(c, user['id'], 'list', 'measurement_latest', aid)
        result = []
        for row in rows:
            data = rowdict(row)
            data.pop('signal_rank', None)
            result.append(data)
        return {'items': result, 'counts': {r['signal']: {'samples': r['samples'], 'usable': r['usable']} for r in totals},
                'source': 'authenticated_personal_sqlite', 'clinical_validation': False}


def export_measurements(user,q):
    from app.security import csv_safe
    result = list_measurements(user,q)
    out = io.StringIO(); writer = csv.writer(out)
    columns = ['id','astronaut_id','mission_id','device_id','session_id','source','signal','value','unit',
               'measured_at','received_at','origin','quality','confidence','missing','processing_version','supersedes_id']
    writer.writerow(columns)
    writer.writerows([csv_safe(r.get(k)) for k in columns] for r in result['items'])
    with db.connect() as c: audit(c,user['id'],'export','measurement',q.astronaut_id or user['astronaut_id'])
    return {'csv':out.getvalue(),'rows':len(result['items']),'next_cursor':result['next_cursor']}


def aggregates(user,q):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        aid,where,args = _where(c,user,q)
        # Never combine different units, origins or missions; ignore replaced events and rejected values.
        rows = c.execute('''SELECT substr(measured_at,1,10) AS day,signal,unit,origin,mission_id,
          COUNT(*) sample_count,SUM(missing) missing_count,
          COUNT(CASE WHEN quality NOT IN ('rejected','corrupt','no_contact') THEN value END) valid_count,
          AVG(CASE WHEN quality NOT IN ('rejected','corrupt','no_contact') THEN value END) mean,
          MIN(CASE WHEN quality NOT IN ('rejected','corrupt','no_contact') THEN value END) minimum,
          MAX(CASE WHEN quality NOT IN ('rejected','corrupt','no_contact') THEN value END) maximum
          FROM raw_measurements WHERE '''+' AND '.join(where)+'''
          AND measured_at IS NOT NULL AND id NOT IN (SELECT supersedes_id FROM raw_measurements WHERE supersedes_id IS NOT NULL)
          GROUP BY day,signal,unit,origin,mission_id ORDER BY day,signal,unit,origin,mission_id''',args).fetchall()
        # Cache only full-day/all-device computations; filtered queries must never corrupt the cache.
        if not any((q.start,q.end,q.device_id,q.signal,q.session_id)):
            if q.mission_id:
                c.execute('DELETE FROM daily_aggregates WHERE astronaut_id=? AND mission_key=?',(aid,q.mission_id))
            else: c.execute('DELETE FROM daily_aggregates WHERE astronaut_id=?',(aid,))
            c.executemany('INSERT INTO daily_aggregates VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                [(aid,r['day'],r['signal'],r['unit'],r['origin'],r['mission_id'] or '',r['sample_count'],r['valid_count'],r['missing_count'],
                  r['mean'],r['minimum'],r['maximum'],'daily-1.5',utcnow()) for r in rows])
        audit(c,user['id'],'aggregate','measurement',aid)
        result = [dict(r) for r in rows[q.after:q.after+q.limit]]
        return {'items':result,'next_cursor':q.after+q.limit if len(rows)>q.after+q.limit else None,'processing_version':'daily-1.5'}


def save_analysis(user,data,processed=None,*,session_token=None,bundle=None):
    """Trusted Python adapter for developer #3; user is an authenticated principal."""
    d = AnalysisSave.model_validate(data).model_dump()
    processed = [ProcessedValue.model_validate(p).model_dump() for p in (processed or [])]
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if session_token is not None:
            from app.access_control.session import principal
            user=principal(c,session_token)
        aid = acl.profile(c,user,d['astronaut_id'],write=True)
        acl.mission(c,user,d['mission_id'])
        if d['session_id']:
            s = session_row(c,user,d['session_id'],write=True)
            if s['mission_id']!=d['mission_id']: raise APIError(422,'session_mismatch','Mission differs from session')
        for mid in d['input_ids']:
            row = c.execute('SELECT * FROM raw_measurements WHERE id=? AND astronaut_id=?',(mid,aid)).fetchone()
            if not row or row['mission_id']!=d['mission_id'] or (d['session_id'] and row['session_id']!=d['session_id']):
                raise APIError(404,'not_found','Input record not found in analysis scope')
        old = c.execute('SELECT * FROM analysis_runs WHERE astronaut_id=? AND idempotency_key=?',(aid,d['idempotency_key'])).fetchone()
        if old:
            if any(old[k]!=(dumps(d[k]) if k in ('result','input_ids') else d[k]) for k in ('mission_id','session_id','model','processing_version','result','input_ids')):
                raise APIError(409,'idempotency_conflict','Analysis key already used')
            stored = [dict(r) for r in c.execute('SELECT raw_id,signal,value,unit FROM processed_measurements WHERE analysis_id=? ORDER BY rowid',(old['id'],))]
            if stored != processed:
                raise APIError(409,'idempotency_conflict','Analysis key was used with different processed values')
            return {**rowdict(old),'_created':False} if bundle is not None else rowdict(old)
        rid = uid()
        c.execute('INSERT INTO analysis_runs VALUES(?,?,?,?,?,?,?,?,?,?)',
                  (rid,aid,d['mission_id'],d['session_id'],d['model'],d['processing_version'],utcnow(),dumps(d['result']),dumps(d['input_ids']),d['idempotency_key']))
        for p in processed or []:
            if p['raw_id'] not in d['input_ids']: raise APIError(422,'input_mismatch','Processed row must reference an input')
            c.execute('INSERT INTO processed_measurements VALUES(?,?,?,?,?,?,?,?)',
                      (uid(),p['raw_id'],rid,p['signal'],p['value'],p['unit'],d['processing_version'],utcnow()))
        if bundle is not None:
            evidence=[]
            for mid in d['input_ids']:
                r=c.execute('SELECT id,payload_hash FROM raw_measurements WHERE id=?',(mid,)).fetchone()
                evidence.append([r['id'],r['payload_hash']])
            c.execute('INSERT INTO analysis_evidence VALUES(?,?,?,?,?)',(rid,digest(dumps(sorted(evidence))),len(evidence),dumps(bundle['record']),dumps(bundle['audit'])))
            c.execute('INSERT INTO science_records VALUES(?,?,?,?,?,?,?,?,?)',(uid(),'phantom_analysis',dumps([rid]),aid,d['mission_id'],'derived','PHANTOM personal: '+str(d['result'].get('outcome')),user['id'],utcnow()))
        audit(c,user['id'],'create','analysis',rid)
        result=rowdict(c.execute('SELECT * FROM analysis_runs WHERE id=?',(rid,)).fetchone())
        if bundle is not None: result['_created']=True
        return result


def run_summary(user,d):
    # A non-clinical data completeness summary. Existing PHANTOM algorithms are unchanged.
    with db.connect() as c:
        s = session_row(c,user,d['session_id'],write=True)
        rows = c.execute('SELECT id,signal,value,quality FROM raw_measurements WHERE session_id=? ORDER BY seq LIMIT 5001',(s['id'],)).fetchall()
        if len(rows)>5000: raise APIError(422,'analysis_size','Use the internal analysis adapter for recordings over 5000 samples')
        counts = {}
        for r in rows:
            cnt = counts.setdefault(r['signal'],{'samples':0,'missing':0})
            cnt['samples']+=1; cnt['missing']+=int(r['value'] is None)
    return save_analysis(user,{'mission_id':s['mission_id'],'session_id':s['id'],'model':'summary-v1',
           'processing_version':'summary-1.5','idempotency_key':d['idempotency_key'],
           'input_ids':[r['id'] for r in rows],'result':{'channels':counts,'diagnosis':None}})


def list_records(user,q,table):
    if table not in ('analysis_runs','alerts','recovery_sessions'): raise ValueError('Unknown collection')
    with db.connect() as c:
        aid = acl.profile(c,user,q.astronaut_id,mission_id=q.mission_id)
        owner = 'profile_id' if table=='recovery_sessions' else 'astronaut_id'
        where = owner+'=?'; args = [aid]
        if q.mission_id: where+=' AND mission_id=?'; args.append(q.mission_id)
        for k in ('device_id','session_id','signal','start','end'):
            if getattr(q,k) is not None: raise APIError(422,'filter_unsupported','Unsupported filter for this collection')
        rows = c.execute(f'SELECT rowid AS seq,* FROM {table} WHERE {where} AND rowid>? ORDER BY rowid LIMIT ?',
                         (*args,q.after,q.limit+1)).fetchall()
        audit(c,user['id'],'list',table,aid)
        return page(rows,q.limit)


def get_analysis(user,rid):
    with db.connect() as c:
        r = c.execute('SELECT * FROM analysis_runs WHERE id=?',(rid,)).fetchone()
        if not r: raise APIError(404,'not_found','Resource not found')
        acl.profile(c,user,r['astronaut_id'],mission_id=r['mission_id'])
        audit(c,user['id'],'read','analysis',rid)
        return rowdict(r)


def create_recovery(user,d):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE'); aid = acl.profile(c,user,d.get('astronaut_id'),write=True)
        acl.mission(c,user,d.get('mission_id'))
        cur = c.execute('''INSERT INTO recovery_sessions(astronaut_id,profile_id,mission_id,activity,before_mood,after_mood,duration_seconds,details,created_at)
          VALUES(?,?,?,?,?,?,?,?,?)''',
          (aid,aid,d.get('mission_id'),d['activity'],d['before_mood'],d['after_mood'],d['duration_seconds'],dumps(d['details']),utcnow()))
        audit(c,user['id'],'create','recovery',str(cur.lastrowid))
        return rowdict(c.execute('SELECT * FROM recovery_sessions WHERE id=?',(cur.lastrowid,)).fetchone())


def review_alert(user,alert_id,status):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM alerts WHERE id=?',(alert_id,)).fetchone()
        if not row: raise APIError(404,'not_found','Resource not found')
        acl.profile(c,user,row['astronaut_id'],mission_id=row['mission_id'],review=True)
        if row['status']!='pending': raise APIError(409,'already_reviewed','Recommendation already reviewed')
        c.execute('UPDATE alerts SET status=?,reviewed_by=?,reviewed_at=? WHERE id=?',(status,user['id'],utcnow(),alert_id))
        audit(c,user['id'],status,'alert',alert_id)
        return {'id':alert_id,'status':status}


def create_alert(user,data):
    d = AlertCreate.model_validate(data).model_dump()
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        run = c.execute('SELECT * FROM analysis_runs WHERE id=?',(d['analysis_id'],)).fetchone()
        if not run: raise APIError(404,'not_found','Analysis not found')
        acl.profile(c,user,run['astronaut_id'],write=True)
        alert_id = uid()
        c.execute('INSERT INTO alerts(id,astronaut_id,mission_id,analysis_id,severity,message,created_at) VALUES(?,?,?,?,?,?,?)',
                  (alert_id,run['astronaut_id'],run['mission_id'],run['id'],d['severity'],d['message'],utcnow()))
        audit(c,user['id'],'create','alert',alert_id)
        return rowdict(c.execute('SELECT * FROM alerts WHERE id=?',(alert_id,)).fetchone())


def update_device(user,did,data):
    if set(data)-{'name'}:raise APIError(422,'device_patch','Only name can be changed; device ownership is immutable')
    name=data.get('name')
    if not isinstance(name,str) or not 1<=len(name)<=80:raise APIError(422,'device_name','Name must contain 1–80 characters')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');owned_device(c,user['astronaut_id'],did)
        if c.execute('SELECT 1 FROM sensor_sessions WHERE device_id=? AND ended_at IS NULL',(did,)).fetchone():raise APIError(409,'device_busy','Finish recording before editing device')
        c.execute('UPDATE devices SET name=? WHERE id=?',(name,did));audit(c,user['id'],'update','device',did)
        return dict(c.execute('SELECT * FROM devices WHERE id=?',(did,)).fetchone())


def remove_device(user,did):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM devices WHERE id=? AND astronaut_id=?',(did,user['astronaut_id'])).fetchone():raise APIError(404,'not_found','Device not found')
        if c.execute('SELECT 1 FROM sensor_sessions WHERE device_id=? AND ended_at IS NULL',(did,)).fetchone():raise APIError(409,'device_busy','Disconnect before removal')
        c.execute('INSERT INTO device_lifecycle(device_id,removed_at) VALUES(?,?) ON CONFLICT(device_id) DO UPDATE SET removed_at=COALESCE(removed_at,excluded.removed_at)',(did,utcnow()))
        audit(c,user['id'],'remove','device',did)
    return {'removed':True,'device_id':did,'measurements_retained':True}


def touch_device(user,did,last_seen_at=None):
    # Caller timestamps are deliberately ignored. There is no public touch route.
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');owned_device(c,user['astronaut_id'],did)
        c.execute('INSERT INTO device_lifecycle(device_id,last_seen_at) VALUES(?,?) ON CONFLICT(device_id) DO UPDATE SET last_seen_at=excluded.last_seen_at',(did,utcnow()))
