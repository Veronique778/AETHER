"""BE3 protocol on the canonical BE2 database. No fake/demo fallback."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from app import db, access_control as acl
from app.access_control.science_context import current, SYSTEM_CONTEXT
from app.persistence.common import APIError, audit as write_audit, dumps, digest, utc, utcnow
from app.persistence import repository as repo
from app.persistence.science_conversion import normalize, to_raw, project, uuid_identity, RAW_TO_SIGNAL

@contextmanager
def transaction(ctx, recovery=False):
    from app.science_errors import ScienceError, StorageUnavailable
    try:
        with db.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            user=None if recovery and ctx is SYSTEM_CONTEXT else current(c,ctx)
            yield c,user
    except APIError as e:
        raise ScienceError(e.detail,status=e.status,code=e.code) from None
    except sqlite3.Error:
        raise StorageUnavailable('Database transaction failed; retry with the same identifiers') from None


def scope(c,u,aid,mission=None,write=False):
    uuid_identity(aid)
    acl.profile(c,u,aid,write=write,mission_id=mission)
    if write: acl.mission(c,u,mission)


def projected(c,r):
    return project(r,c.execute('SELECT * FROM science_measurement_attrs WHERE measurement_id=?',(r['id'],)).fetchone(),
                   c.execute('SELECT * FROM science_invalidations WHERE measurement_id=?',(r['id'],)).fetchone())


class ScienceStorage:
    def save_measurements(self,ctx,items):
        if not isinstance(items,list) or not 1<=len(items)<=500:
            from app.science_errors import InvalidInput
            raise InvalidInput('Expected 1–500 measurements')
        with transaction(ctx) as (c,u):
            data=[normalize(x) for x in items]; out=[]; saved=0
            for d in data:
                scope(c,u,d['astronaut_id'],d.get('mission_id'),True)
                if d['data_class']=='real_wearable' and not (d.get('device_id') and d.get('session_id')):
                    raise APIError(422,'source_required','Wearable data require a device and session')
                raw=to_raw(d)
                raw['metadata']['science_attributes']={k:d.get(k) for k in ('quality','valid','original_timestamp','timezone','mission_day','sampling_hz')}
                old=c.execute('SELECT * FROM raw_measurements WHERE astronaut_id=? AND idempotency_key=?',(d['astronaut_id'],d['client_measurement_id'])).fetchone()
                raw['id']=old['id'] if old else uuid.uuid4().hex
                if d.get('session_id') and not old:
                    s=repo.session_row(c,u,d['session_id'],write=True)
                    if s['ended_at']: raise APIError(409,'session_closed','Session no longer accepts new events')
                result=repo._insert(c,u,raw)
                if result['created']:
                    c.execute('INSERT INTO science_measurement_attrs VALUES(?,?,?,?,?)',(raw['id'],d['quality'],int(d['valid']),dumps(raw['metadata']['science_attributes']),u['id']))
                    saved+=1
                out.append(projected(c,c.execute('SELECT * FROM raw_measurements WHERE id=?',(raw['id'],)).fetchone()))
            rid=digest(dumps([u['id'],[r['measurement_id'] for r in out]]))[:32]
            if not c.execute('SELECT 1 FROM science_records WHERE record_id=?',(rid,)).fetchone():
                self._record(c,u,rid,'measurement_batch',[r['measurement_id'] for r in out],u['astronaut_id'],None,'derived','Measurement batch')
            answer={'saved':saved,'duplicates':len(out)-saved,'items':out,'record_id':rid}
        return answer

    def query_measurements(self,ctx,astronaut_id,*,signals=None,start=None,end=None,session_id=None,include_invalid=False,limit=1000,cursor=None):
        with transaction(ctx) as (c,u):
            scope(c,u,astronaut_id,ctx.mission_id)
            if type(limit) is not int or not 1<=limit<=5000: raise APIError(422,'validation_error','Invalid limit')
            where=['astronaut_id=?','measured_at IS NOT NULL']; args=[astronaut_id]
            for key,val in [('session_id',session_id),('mission_id',ctx.mission_id)]:
                if val: where.append(key+'=?');args.append(val)
            if session_id:
                s=repo.session_row(c,u,session_id)
                if s['astronaut_id']!=astronaut_id: raise APIError(404,'not_found','Resource not found')
            if start: where.append('measured_at>=?');args.append(utc(start))
            if end: where.append('measured_at<?');args.append(utc(end))
            if signals:
                names=[k for k,v in RAW_TO_SIGNAL.items() if v[0] in signals]
                if not names: raise APIError(422,'unknown_signal','Unsupported signals')
                where.append('signal IN ('+','.join('?' for _ in names)+')');args.extend(names)
            else:
                where.append('signal IN ('+','.join('?' for _ in RAW_TO_SIGNAL)+')');args.extend(RAW_TO_SIGNAL)
            if not include_invalid: where.append('id NOT IN (SELECT measurement_id FROM science_invalidations)')
            fingerprint=digest(dumps([u['id'],where,args]))
            if cursor:
                try:
                    import base64
                    cur=json.loads(base64.urlsafe_b64decode(cursor))
                    if cur['f']!=fingerprint: raise ValueError
                    where.append('(measured_at,id)>(?,?)');args.extend([cur['t'],cur['id']])
                except Exception: raise APIError(422,'invalid_cursor','Cursor does not match query') from None
            rows=c.execute('SELECT * FROM raw_measurements WHERE '+' AND '.join(where)+' ORDER BY measured_at,id LIMIT ?',(*args,limit+1)).fetchall()
            page=rows[:limit]; nxt=None
            if len(rows)>limit:
                import base64
                nxt=base64.urlsafe_b64encode(dumps({'f':fingerprint,'t':page[-1]['measured_at'],'id':page[-1]['id']}).encode()).decode()
            result=[projected(c,r) for r in page]
            capture=ctx._capture.setdefault(fingerprint,{'rows':{},'start':start,'end':end,'session_id':session_id})
            capture['rows'].update({r['measurement_id']:r for r in result})
            write_audit(c,u['id'],'list','measurement',astronaut_id)
        return {'items':result,'next_cursor':nxt}

    def create_session(self,ctx,astronaut_id,source_type,source,*,device_id=None,mission_id=None,metadata=None):
        with transaction(ctx) as (c,u):
            scope(c,u,astronaut_id,mission_id,True)
            if source_type not in ('live_sensor','manual','synthetic'): raise APIError(422,'source_type','Unsupported personal source type')
            if device_id: repo.owned_device(c,astronaut_id,device_id)
            if source_type=='live_sensor' and not device_id: raise APIError(422,'device_required','Live sessions require a device')
            if not isinstance(source,str) or not 1<=len(source)<=120: raise APIError(422,'source','Invalid source')
            meta=dict(metadata or {});meta['science_managed']=True
            if len(dumps(meta))>16384: raise APIError(422,'metadata','Metadata too large')
            sid=uuid.uuid4().hex;origin={'live_sensor':'real','manual':'manual','synthetic':'simulated'}[source_type]
            c.execute('INSERT INTO sensor_sessions VALUES(?,?,?,?,?,?,?,?,?)',(sid,astronaut_id,mission_id,device_id,source,origin,utcnow(),None,dumps(meta)))
            c.execute('INSERT INTO science_sessions VALUES(?,?,?,?)',(sid,source_type,'recording',u['id']))
            write_audit(c,u['id'],'create','sensor_session',sid)
        return sid

    @staticmethod
    def _session(c,s):
        ext=c.execute('SELECT * FROM science_sessions WHERE session_id=?',(s['id'],)).fetchone()
        return {'session_id':s['id'],'astronaut_id':s['astronaut_id'],'device_id':s['device_id'],'mission_id':s['mission_id'],
          'source':s['source'],'source_type':ext['source_type'] if ext else 'legacy', 'status':ext['status'] if ext else ('saved' if s['ended_at'] else 'recording'),
          'created_at':s['started_at'],'finished_at':s['ended_at'],'metadata':json.loads(s['metadata']),'created_by':ext['created_by'] if ext else None}

    def get_session(self,ctx,session_id):
        with transaction(ctx) as (c,u): return self._session(c,repo.session_row(c,u,session_id))

    def list_sessions(self,ctx,status=None):
        with transaction(ctx,recovery=True) as (c,u):
            if u is None:
                rows=c.execute("SELECT s.* FROM sensor_sessions s JOIN science_sessions x ON x.session_id=s.id WHERE x.source_type='live_sensor' AND x.status='recording'").fetchall()
            else: rows=c.execute('SELECT * FROM sensor_sessions WHERE astronaut_id=? ORDER BY started_at,id',(u['astronaut_id'],)).fetchall()
            result=[self._session(c,r) for r in rows]
            return [r for r in result if status is None or r['status']==status]

    def finish_session(self,ctx,session_id,status,metadata=None):
        allowed=('saved','saved_with_unstored_rows','saved_after_connection_loss','saved_on_shutdown','connection_failed','interrupted')
        with transaction(ctx,recovery=True) as (c,u):
            if status not in allowed: raise APIError(422,'session_status','Invalid terminal status')
            s=c.execute('SELECT * FROM sensor_sessions WHERE id=?',(session_id,)).fetchone()
            if not s: raise APIError(404,'not_found','Session not found')
            ext=self._session(c,s)
            if u is None:
                if status!='interrupted' or ext['source_type']!='live_sensor': raise APIError(403,'forbidden','Recovery scope exceeded')
            else: scope(c,u,s['astronaut_id'],s['mission_id'],True)
            if s['ended_at']: return
            meta={**json.loads(s['metadata']),**(metadata or {})}
            if len(dumps(meta))>16384: raise APIError(422,'metadata','Metadata too large')
            c.execute('UPDATE sensor_sessions SET ended_at=?,metadata=? WHERE id=?',(utcnow(),dumps(meta),session_id))
            c.execute('UPDATE science_sessions SET status=? WHERE session_id=?',(status,session_id))
            write_audit(c,u['id'] if u else None,'finish','sensor_session',session_id)

    @staticmethod
    def _device(c,d):
        e=c.execute('SELECT * FROM science_devices WHERE device_id=?',(d['id'],)).fetchone()
        return {**dict(d),'device_id':d['id'],'hardware_address':e['hardware_address'] if e else d['external_id'],
          'profile':e['profile'] if e else None,'support_status':e['support_status'] if e else 'unverified',
          'signals':json.loads(e['signals']) if e else [],'registered_by':e['registered_by'] if e else None,
          'last_seen_at':e['last_seen_at'] if e else None,'removed':bool(e['removed']) if e else False,'hardware_verified':False}

    def upsert_device(self,ctx,device):
        with transaction(ctx) as (c,u):
            aid=device.get('astronaut_id');scope(c,u,aid,write=True)
            did=device.get('device_id') or uuid.uuid4().hex
            old=c.execute('SELECT * FROM devices WHERE id=?',(did,)).fetchone()
            if old and old['astronaut_id']!=aid: raise APIError(404,'not_found','Device not found')
            name=device.get('name','HRS monitor');addr=device.get('hardware_address')
            if not isinstance(name,str) or not 1<=len(name)<=80 or not isinstance(addr,str) or not 1<=len(addr)<=128:
                raise APIError(422,'device_fields','Invalid device fields')
            other=c.execute('SELECT device_id FROM science_devices WHERE hardware_address=? COLLATE NOCASE',(addr,)).fetchone()
            if other and other[0]!=did: raise APIError(409,'device_already_registered','Hardware address already registered')
            if old: c.execute('UPDATE devices SET name=? WHERE id=?',(name,did))
            else: c.execute('INSERT INTO devices VALUES(?,?,?,?,?,?)',(did,aid,name,'ble_hrs',None,utcnow()))
            c.execute('''INSERT INTO science_devices VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(device_id) DO UPDATE SET removed=excluded.removed''',
              (did,addr,'HRS','unverified',dumps(['heart_rate','rr_interval']),u['id'],None,int(bool(device.get('removed')))))
            write_audit(c,u['id'],'upsert','device',did)
            result=self._device(c,c.execute('SELECT * FROM devices WHERE id=?',(did,)).fetchone())
        return result

    def get_device(self,ctx,device_id):
        with transaction(ctx) as (c,u):
            repo.owned_device(c,u['astronaut_id'],device_id)
            result=self._device(c,c.execute('SELECT * FROM devices WHERE id=?',(device_id,)).fetchone())
            if result['removed']: raise APIError(404,'not_found','Device not found')
            return result

    def list_devices(self,ctx,astronaut_id=None):
        with transaction(ctx) as (c,u):
            aid=astronaut_id or u['astronaut_id'];scope(c,u,aid,write=True)
            rows=[self._device(c,r) for r in c.execute('SELECT * FROM devices WHERE astronaut_id=? ORDER BY created_at,id',(aid,))]
            return [r for r in rows if not r['removed']]

    @staticmethod
    def _record(c,u,rid,kind,refs,aid,mission,data_class,summary):
        c.execute('INSERT INTO science_records VALUES(?,?,?,?,?,?,?,?,?)',(rid,kind,dumps(refs),aid,mission,data_class,summary,u['id'],utcnow()))

    def log_record(self,ctx,kind,ref_ids,astronaut_id,data_class,summary):
        with transaction(ctx) as (c,u):
            scope(c,u,astronaut_id,ctx.mission_id,True)
            # Only identifiers are recorded; arbitrary caller text is not copied into audit/history.
            if kind not in ('measurement_batch','phantom_analysis'): raise APIError(422,'record_kind','Unsupported record kind')
            table='raw_measurements' if kind=='measurement_batch' else 'analysis_runs'
            for rid in ref_ids:
                r=c.execute(f'SELECT * FROM {table} WHERE id=? AND astronaut_id=?',(rid,astronaut_id)).fetchone()
                if not r: raise APIError(404,'not_found','Record input not found')
            rid=uuid.uuid4().hex;self._record(c,u,rid,kind,ref_ids,astronaut_id,ctx.mission_id,'derived',kind)
        return rid

    def audit(self,ctx,action,target_kind,target_id,outcome,details=None):
        with transaction(ctx,recovery=True) as (c,u):
            if u is None:
                if target_kind!='session' or action!='device.sessions_recovered' or target_id is not None: raise APIError(403,'forbidden','Recovery scope exceeded')
            elif target_id:
                tables={'device':'devices','sensor_session':'sensor_sessions','phantom_analysis':'analysis_runs'}
                table=tables.get(target_kind)
                if not table: raise APIError(422,'audit_target','Unsupported audit target')
                r=c.execute(f'SELECT * FROM {table} WHERE id=?',(target_id,)).fetchone()
                if not r: raise APIError(404,'not_found','Target not found')
                scope(c,u,r['astronaut_id'],r['mission_id'] if 'mission_id' in r.keys() else None)
            if len(action)>80 or len(outcome)>32: raise APIError(422,'audit_fields','Invalid audit fields')
            write_audit(c,u['id'] if u else None,action,target_kind,target_id,outcome)

    def save_analysis_bundle(self,ctx,kind,astronaut_id,payload,*,record,audit,idempotency_key):
        from app import phantom_analyses as p
        with transaction(ctx) as (c,u):
            scope(c,u,astronaut_id,payload.get('mission_id'),True)
            if kind!=p.KIND or payload.get('astronaut_id')!=astronaut_id or payload.get('created_by')!=u['id'] or payload.get('diagnosis') is not None:
                raise APIError(422,'analysis_scope','Invalid personal analysis scope')
            if payload.get('processing_version')!=p.PROCESSING_VERSION or payload.get('outcome') not in ('flag','no_flag','insufficient_data'):
                raise APIError(422,'analysis_version','Unsupported scientific result')
            if payload.get('analysis_id')!=idempotency_key or len(idempotency_key)!=32: raise APIError(422,'analysis_id','Invalid analysis identity')
            ph=digest(dumps({k:v for k,v in payload.items() if k!='created_at'}))
            old=c.execute('SELECT * FROM science_analysis_attrs WHERE analysis_id=?',(idempotency_key,)).fetchone()
            if old:
                if old['payload_hash']!=ph: raise APIError(409,'idempotency_conflict','Analysis key reused with different content')
                saved=c.execute('SELECT * FROM analysis_runs WHERE id=?',(idempotency_key,)).fetchone()
                return {'analysis_id':idempotency_key,'created':False,'record_id':old['record_id'],'payload':json.loads(saved['result'])}
            captures=list(ctx._capture.values())
            if not 1<=len(captures)<=2: raise APIError(422,'input_snapshot','Run queries inside a fresh RequestContext.analysis_scope')
            groups=[];ids=[]
            for cap in captures:
                rows=[]
                for mid in cap['rows']:
                    r=c.execute('SELECT * FROM raw_measurements WHERE id=?',(mid,)).fetchone()
                    if not r or r['astronaut_id']!=astronaut_id or r['mission_id']!=payload.get('mission_id'):
                        raise APIError(404,'not_found','Analysis input outside owner or mission')
                    if cap['session_id'] and r['session_id']!=cap['session_id']: raise APIError(422,'input_session','Input session mismatch')
                    scope(c,u,r['astronaut_id'],r['mission_id'],True)
                    rows.append(projected(c,r));ids.append(mid)
                groups.append(rows)
            md=p.measurement_digest(groups[0],groups[1] if len(groups)>1 else None)
            if md!=payload['input']['measurement_digest']: raise APIError(409,'input_changed','Analysis input digest differs from stored data')
            ad=payload['reproducibility']['analysis_digest']
            if p.analysis_id_for(astronaut_id,u['id'],ad)!=idempotency_key: raise APIError(422,'analysis_digest','Analysis identity mismatch')
            if record.get('astronaut_id')!=astronaut_id or record.get('ref_ids')!=[idempotency_key] or audit.get('target_id')!=idempotency_key:
                raise APIError(422,'bundle_scope','History or audit target differs')
            rid=uuid.uuid4().hex
            c.execute('INSERT INTO analysis_runs VALUES(?,?,?,?,?,?,?,?,?,?)',(idempotency_key,astronaut_id,payload.get('mission_id'),payload['input'].get('session_id'),kind,p.PROCESSING_VERSION,utcnow(),dumps(payload),dumps(sorted(set(ids))),idempotency_key))
            self._record(c,u,rid,'phantom_analysis',[idempotency_key],astronaut_id,payload.get('mission_id'),'derived','PHANTOM personal: '+payload['outcome'])
            c.execute('INSERT INTO science_analysis_attrs VALUES(?,?,?,?,?,?)',(idempotency_key,kind,payload['outcome'],rid,ph,ad))
            write_audit(c,u['id'],'phantom_analysis.create','phantom_analysis',idempotency_key,'success')
            result={'analysis_id':idempotency_key,'created':True,'record_id':rid,'payload':payload}
        return result

    def get_analysis(self,ctx,analysis_id):
        with transaction(ctx) as (c,u):
            r=c.execute('SELECT a.* FROM analysis_runs a JOIN science_analysis_attrs s ON s.analysis_id=a.id WHERE a.id=?',(analysis_id,)).fetchone()
            if not r: raise APIError(404,'not_found','Analysis not found')
            scope(c,u,r['astronaut_id'],r['mission_id']);write_audit(c,u['id'],'read','analysis',analysis_id)
            return json.loads(r['result'])

    def list_analyses(self,ctx,astronaut_id=None,kind=None,limit=100,cursor=None):
        with transaction(ctx) as (c,u):
            aid=astronaut_id or u['astronaut_id'];scope(c,u,aid,ctx.mission_id)
            if type(limit) is not int or not 1<=limit<=1000: raise APIError(422,'limit','Invalid limit')
            try: offset=int(cursor or 0)
            except (ValueError,TypeError): raise APIError(422,'cursor','Invalid cursor') from None
            if offset<0: raise APIError(422,'cursor','Invalid cursor')
            rows=c.execute('SELECT a.* FROM analysis_runs a JOIN science_analysis_attrs s ON s.analysis_id=a.id WHERE a.astronaut_id=? AND (? IS NULL OR s.kind=?) AND (? IS NULL OR a.mission_id=?) ORDER BY a.created_at DESC,a.id DESC LIMIT ? OFFSET ?',
              (aid,kind,kind,ctx.mission_id,ctx.mission_id,limit+1,offset)).fetchall()
            return {'items':[json.loads(r['result']) for r in rows[:limit]],'next_cursor':str(offset+limit) if len(rows)>limit else None}
