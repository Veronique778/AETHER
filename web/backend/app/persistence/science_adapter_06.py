"""Canonical BE2 adapter extending BE3_03A without editing its algorithms."""
from app.science_storage_be2 import Be2ScienceStorage, Be2Error, _call as _be3_call, to_be2_item, from_be2_row
from app import db, signals
from app.persistence import repository as repo
from app.access_control.session import principal
from app.science_errors import InvalidInput

def _call(fn, *args, **kwargs):
    import sqlite3
    from app.science_errors import StorageUnavailable
    try:
        return _be3_call(fn, *args, **kwargs)
    except Be2Error as exc:
        if exc.status==409 and exc.code=='idempotency_conflict':
            from app.science_errors import Conflict
            raise Conflict(exc.message,code=exc.code) from None
        raise
    except sqlite3.DatabaseError:
        raise StorageUnavailable('Scientific storage unavailable') from None


class CanonicalScienceStorage(Be2ScienceStorage):
    def save_measurements(self,ctx,items):
        self._user(ctx)
        if not isinstance(items,list) or not 1<=len(items)<=500:raise InvalidInput('Expected 1–500 measurements')
        from app.schemas_15 import MeasurementCreate
        payload=[_call(MeasurementCreate.model_validate,to_be2_item(signals.validate_item(x,i))).model_dump() for i,x in enumerate(items)]
        def save():
            with db.connect() as c:
                c.execute('BEGIN IMMEDIATE');user=principal(c,ctx._token)
                for d in payload:
                    if d['origin']=='real':
                        if not (d['device_id'] and d['session_id']):raise InvalidInput('Wearable rows require a device and session')
                        session=repo.session_row(c,user,d['session_id'],write=True)
                        import json
                        device=c.execute('SELECT * FROM devices WHERE id=? AND astronaut_id=?',(d['device_id'],user['astronaut_id'])).fetchone()
                        if not device or device['kind'] not in ('ble','ble_hrs') or json.loads(session['metadata']).get('source_type')!='live_sensor' or d['source']!=session['source']:
                            raise InvalidInput('Wearable provenance requires a live BLE recording session')
                result=[repo._insert(c,user,d,writer=repo._DEVICE_WRITER) for d in payload]
                from app.persistence.common import utcnow
                for did in {d['device_id'] for d in payload if d['device_id']}:
                    c.execute('INSERT INTO device_lifecycle(device_id,last_seen_at) VALUES(?,?) ON CONFLICT(device_id) DO UPDATE SET last_seen_at=excluded.last_seen_at',(did,utcnow()))
            return result
        result=_call(save)
        return {'saved':sum(r['created'] for r in result),'duplicates':sum(not r['created'] for r in result),
                'items':[from_be2_row(r['measurement']) for r in result],'record_id':None}

    def finish_session(self,ctx,session_id,status,metadata=None):
        terminal={'interrupted':'interrupted','recovered':'recovered','failed':'failed','connection_failed':'failed','saved_with_unstored_rows':'failed', 'saved':'saved','saved_after_connection_loss':'saved','saved_on_shutdown':'saved'}
        if status not in terminal:raise InvalidInput('Unknown terminal session status')
        _call(repo.close_session,self._user(ctx),session_id,terminal[status],metadata)

    @staticmethod
    def _session_out(row):
        result=Be2ScienceStorage._session_out(row)
        with db.connect() as c:r=c.execute('SELECT * FROM session_end_states WHERE session_id=?',(row['id'],)).fetchone()
        if r:
            import json
            result['status']=r['status'];result['end_metadata']=json.loads(r['metadata'])
        return result

    def save_analysis_bundle(self,ctx,kind,astronaut_id,payload,*,record,audit,idempotency_key,input_ids=None):
        from app.science_storage_be2 import PHANTOM_MODELS
        user=self._user(ctx);ids=sorted(set(input_ids or []))
        if payload.get('astronaut_id')!=astronaut_id or payload.get('diagnosis') is not None or payload['method']['id'] not in PHANTOM_MODELS:
            raise InvalidInput('Invalid analysis scope or model')
        if record.get('astronaut_id')!=astronaut_id:raise InvalidInput('History owner mismatch')
        result=self._stored_result({**payload,'input_scope':{'input_ids_complete':True,'input_count':len(ids)}})
        data={'astronaut_id':astronaut_id,'mission_id':payload.get('mission_id'),'session_id':payload['input'].get('session_id'),
              'model':payload['method']['id'],'processing_version':payload['processing_version'],'idempotency_key':idempotency_key,'input_ids':ids,'result':result}
        row=_call(repo.save_analysis,user,data,session_token=ctx._token,bundle={'record':{'kind':kind,'input_count':len(ids)},'audit':{'outcome':payload['outcome'],'analysis_digest':payload['reproducibility']['analysis_digest']}})
        return {'analysis_id':row['id'],'created':row['_created'],'record_id':row['id'],'payload':self._payload(row)}

    @staticmethod
    def _payload(row):
        result=Be2ScienceStorage._payload(row)
        with db.connect() as c:e=c.execute('SELECT input_digest,input_count FROM analysis_evidence WHERE analysis_id=?',(row['id'],)).fetchone()
        if e:result['storage'].update(input_digest=e['input_digest'],input_count=e['input_count'])
        return result

    def touch_device(self,ctx,device_id,last_seen_at=None):
        return _call(repo.touch_device,self._user(ctx),device_id)

    def upsert_device(self,ctx,device):
        user=self._user(ctx)
        if not device.get('device_id'):return super().upsert_device(ctx,device)
        old=self.get_device(ctx,device['device_id'])
        if device.get('astronaut_id',old['astronaut_id'])!=old['astronaut_id'] or device.get('hardware_address',old['hardware_address'])!=old['hardware_address']:
            raise InvalidInput('Device ownership and hardware identity are immutable')
        if device.get('removed'):_call(repo.remove_device,user,device['device_id']);return {**old,'removed':True}
        if device.get('name',old['name'])!=old['name']:_call(repo.update_device,user,device['device_id'],{'name':device['name']})
        return self.get_device(ctx,device['device_id'])

    def list_devices(self,ctx,astronaut_id=None):
        result=super().list_devices(ctx,astronaut_id)
        with db.connect() as c:
            for d in result:
                row=c.execute('SELECT last_seen_at FROM device_lifecycle WHERE device_id=?',(d['device_id'],)).fetchone()
                if row:d['last_seen_at']=row['last_seen_at']
                if d['kind']=='ble_hrs' and not d['hardware_address']:
                    old=c.execute('SELECT * FROM science_devices WHERE device_id=?',(d['device_id'],)).fetchone()
                    if old:
                        d.update(hardware_address=old['hardware_address'],signals=['heart_rate','rr_interval'],support_status='automated_tested',profile=old['profile'])
        return result

    def _sessions(self,ctx):
        self._user(ctx)
        with db.connect() as c:
            user=principal(c,ctx._token)
            return [repo.rowdict(r) for r in c.execute('SELECT * FROM sensor_sessions WHERE astronaut_id=? ORDER BY started_at,id',(user['astronaut_id'],))]


    def query_measurements(self, ctx, astronaut_id, signals=None, start=None, end=None,
                           session_id=None, include_invalid=False, limit=1000, cursor=None,
                           mission_id=None, **_ignored):
        """Half-open UTC interval; filtering precedes stable keyset pagination.

        Cursors are scoped measurement IDs, not offsets. A cursor from a different
        astronaut/filter is rejected. New late arrivals preceding the cursor require
        a fresh query; an existing row is never skipped because of insertion order.
        """
        from app import access_control as acl
        from app.persistence.common import utc, audit
        from app.signal_compat import BE2_STORAGE
        self._user(ctx)
        if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=10000:
            raise InvalidInput('limit must be an integer from 1 to 10000')
        if signals is not None and (not isinstance(signals,list) or not signals or any(x not in BE2_STORAGE for x in signals)):
            raise InvalidInput('Use canonical signal identifiers')
        try: start,end=utc(start) if start else None,utc(end) if end else None
        except (ValueError,TypeError):raise InvalidInput('UTC timestamp with timezone required') from None
        if start and end and start>=end:raise InvalidInput('Empty or reversed interval')
        def read():
            with db.connect() as c:
                user=principal(c,ctx._token)
                aid=acl.profile(c,user,astronaut_id,mission_id=mission_id)
                if session_id:
                    session=repo.session_row(c,user,session_id)
                    if session['astronaut_id']!=aid or (mission_id is not None and session['mission_id']!=mission_id):
                        from app.science_errors import NotFound
                        raise NotFound('Resource not found')
                where=['astronaut_id=?','measured_at IS NOT NULL'];args=[aid]
                for name,value in [('mission_id',mission_id),('session_id',session_id)]:
                    if value is not None:where.append(name+'=?');args.append(value)
                if start:where.append('measured_at>=?');args.append(start)
                if end:where.append('measured_at<?');args.append(end)
                if signals:
                    where.append('signal IN ('+','.join('?' for _ in signals)+')');args.extend(signals)
                if not include_invalid:
                    where.append('signal IN ('+','.join('?' for _ in BE2_STORAGE)+')');args.extend(BE2_STORAGE)
                base=' AND '.join(where)
                if cursor:
                    previous=c.execute('SELECT measured_at,id FROM raw_measurements WHERE '+base+' AND id=?',(*args,cursor)).fetchone()
                    if previous is None:raise InvalidInput('Cursor does not belong to this query')
                    where.append('(measured_at,id)>(?,?)');args.extend(previous)
                rows=c.execute('SELECT * FROM raw_measurements WHERE '+' AND '.join(where)+' ORDER BY measured_at,id LIMIT ?',(*args,limit+1)).fetchall()
                audit(c,user['id'],'list','measurement',aid)
                return {'items':[from_be2_row(repo.rowdict(r)) for r in rows[:limit]],
                        'next_cursor':rows[limit-1]['id'] if len(rows)>limit else None}
        return _call(read)

    def log_record(self,ctx,kind,ref_ids,astronaut_id,data_class,summary):
        """Persist referenced history without copying arbitrary medical/free text."""
        from app import access_control as acl
        from app.persistence.common import uid,utcnow,dumps
        self._user(ctx)
        if not isinstance(ref_ids,list) or not 1<=len(ref_ids)<=500:
            raise InvalidInput('History requires 1–500 owned references')
        if kind not in ('measurement','sensor_session','device','phantom_analysis'):
            raise InvalidInput('Unsupported history kind')
        if data_class not in ('manual','synthetic','real_wearable','derived'):
            raise InvalidInput('Unsupported history data class')
        table={'measurement':'raw_measurements','sensor_session':'sensor_sessions','device':'devices','phantom_analysis':'analysis_runs'}[kind]
        def save():
            with db.connect() as c:
                c.execute('BEGIN IMMEDIATE');user=principal(c,ctx._token)
                aid=acl.profile(c,user,astronaut_id,write=True)
                for rid in ref_ids:
                    if not c.execute('SELECT 1 FROM '+table+' WHERE id=? AND astronaut_id=?',(rid,aid)).fetchone():
                        from app.science_errors import NotFound
                        raise NotFound('Resource not found')
                rid=uid()
                c.execute('INSERT INTO science_records VALUES(?,?,?,?,?,?,?,?,?)',(rid,kind,dumps(ref_ids),aid,None,data_class,kind+' recorded',user['id'],utcnow()))
                return rid
        return _call(save)
