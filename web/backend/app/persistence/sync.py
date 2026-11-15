"""Durable outbox + authenticated, idempotent receiver; TLS verifies remote identity."""
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pydantic import Field
from app import auth, db
from app.schemas_15 import StrictModel, MeasurementCreate, DeviceCreate, SessionCreate, Identifier
from .common import APIError, audit, dumps, uid, utcnow
from . import repository as repo


class DeviceSnapshot(DeviceCreate):
    id: Identifier


class SessionSnapshot(SessionCreate):
    id: Identifier
    ended_at: str | None = None


class Envelope(StrictModel):
    measurement: MeasurementCreate
    device: DeviceSnapshot | None = None
    session: SessionSnapshot | None = None


class SyncBatch(StrictModel):
    events: list[Envelope] = Field(min_length=1,max_length=100)


def receive(user,payload):
    batch=SyncBatch.model_validate(payload)
    result=[]
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        for item in batch.events:
            d=item.measurement.model_dump()
            d['metadata']=unverified_metadata(d['metadata'])
            # Incoming IDs never choose the receiving user. Authenticated identity binds ownership.
            if d['astronaut_id'] not in (None,user['astronaut_id']):
                raise APIError(404,'not_found','Resource not found')
            aid=user['astronaut_id']; d['astronaut_id']=aid
            if not d['id']: raise APIError(422,'event_id_required','Synchronization requires a stable event ID')
            if item.device:
                dev=item.device.model_dump(); old=c.execute('SELECT * FROM devices WHERE id=?',(dev['id'],)).fetchone()
                if dev['id']!=d['device_id']: raise APIError(422,'device_mismatch','Device snapshot mismatch')
                if old:
                    if old['astronaut_id']!=aid or any(old[k]!=dev[k] for k in ('name','kind','external_id')):
                        raise APIError(409,'device_conflict','Device mapping conflict')
                else:
                    c.execute('INSERT INTO devices VALUES(?,?,?,?,?,?)',(dev['id'],aid,dev['name'],dev['kind'],dev['external_id'],utcnow()))
            if item.session:
                s=item.session.model_dump(); old=c.execute('SELECT * FROM sensor_sessions WHERE id=?',(s['id'],)).fetchone()
                if s['id']!=d['session_id']: raise APIError(422,'session_mismatch','Session snapshot mismatch')
                if s['origin']=='research': raise APIError(422,'research_separate','Use the research store')
                repo.acl.mission(c,user,s['mission_id'])
                if s['device_id']: repo.owned_device(c,aid,s['device_id'])
                if old:
                    if old['astronaut_id']!=aid or any(old[k]!=(dumps(s[k]) if k=='metadata' else s[k]) for k in ('mission_id','device_id','source','origin','started_at','metadata')):
                        raise APIError(409,'session_conflict','Session mapping conflict')
                    if s['ended_at']:
                        from .common import utc
                        ended=utc(s['ended_at'])
                        if old['ended_at'] and old['ended_at']!=ended: raise APIError(409,'session_conflict','Session end conflict')
                        c.execute('UPDATE sensor_sessions SET ended_at=? WHERE id=?',(ended,s['id']))
                else:
                    from .common import utc
                    ended=utc(s['ended_at']) if s['ended_at'] else None
                    c.execute('INSERT INTO sensor_sessions VALUES(?,?,?,?,?,?,?,?,?)',
                        (s['id'],aid,s['mission_id'],s['device_id'],s['source'],s['origin'],s['started_at'],ended,dumps(s['metadata'])))
            r=repo._insert(c,user,d,enqueue=False)
            result.append({'id':r['measurement']['id'],'created':r['created']})
        audit(c,user['id'],'receive','sync')
    return {'accepted':result}


def status(user):
    with db.connect() as c:
        counts={r[0]:r[1] for r in c.execute('SELECT status,COUNT(*) FROM sync_events WHERE user_id=? GROUP BY status',(user['id'],))}
        return {'counts':counts,'unsent':sum(v for k,v in counts.items() if k!='sent')}


def history(user,after=0,limit=100):
    with db.connect() as c:
        rows=c.execute('''SELECT a.* FROM sync_attempts a JOIN sync_events e ON e.id=a.event_id
          WHERE e.user_id=? AND a.id>? ORDER BY a.id LIMIT ?''',(user['id'],after,limit+1)).fetchall()
        return {'items':[dict(r) for r in rows[:limit]],'next_cursor':rows[limit-1]['id'] if len(rows)>limit else None}


def pending(user,after=0,limit=100):
    with db.connect() as c:
        rows=c.execute('''SELECT rowid AS seq,id,measurement_id,status,attempts,last_error,created_at FROM sync_events
          WHERE user_id=? AND status!='sent' AND rowid>? ORDER BY rowid LIMIT ?''',(user['id'],after,limit+1)).fetchall()
        return repo.page(rows,limit)


def retry(user,event_id):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT * FROM sync_events WHERE id=? AND user_id=?',(event_id,user['id'])).fetchone()
        if not row: raise APIError(404,'not_found','Resource not found')
        if row['status']=='sending' and row['lease_until']>time.time(): raise APIError(409,'sync_busy','Event is currently being sent')
        if row['status']!='sent':
            c.execute("UPDATE sync_events SET status='pending',next_attempt_at=0,last_error=NULL WHERE id=?",(event_id,))
        audit(c,user['id'],'retry','sync',event_id)
    return {'queued':row['status']!='sent'}


def _claim(user):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE'); now=time.time()
        c.execute("UPDATE sync_events SET status='pending',claim_token=NULL WHERE user_id=? AND status='sending' AND lease_until<=?",(user['id'],now))
        row=c.execute("SELECT e.* FROM sync_events e JOIN raw_measurements r ON r.id=e.measurement_id WHERE e.user_id=? AND e.status='pending' AND e.next_attempt_at<=? ORDER BY r.seq LIMIT 1",(user['id'],now)).fetchone()
        if not row: return None
        claim=uid()
        c.execute("UPDATE sync_events SET status='sending',attempts=attempts+1,lease_until=?,claim_token=? WHERE id=?",(now+120,claim,row['id']))
        m=dict(c.execute('SELECT * FROM raw_measurements WHERE id=?',(row['measurement_id'],)).fetchone())
        data={k:m[k] for k in MeasurementCreate.model_fields if k in m}
        data['astronaut_id']=None; data['metadata']=json.loads(data['metadata'])
        env={'measurement':data}
        if m['device_id']:
            dev=dict(c.execute('SELECT * FROM devices WHERE id=?',(m['device_id'],)).fetchone())
            env['device']={k:dev[k] for k in DeviceSnapshot.model_fields}
        if m['session_id']:
            sess=dict(c.execute('SELECT * FROM sensor_sessions WHERE id=?',(m['session_id'],)).fetchone())
            sess['metadata']=json.loads(sess['metadata'])
            env['session']={k:sess[k] for k in SessionSnapshot.model_fields}
        return dict(row),claim,{'events':[env]}


def _finish(event,claim,state,error=None):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        delay=min(3600,2**min(event['attempts']+1,11))+random.random()
        cur=c.execute('''UPDATE sync_events SET status=?,last_error=?,lease_until=0,claim_token=NULL,next_attempt_at=?
                         WHERE id=? AND claim_token=?''',(state,error,time.time()+delay,event['id'],claim))
        if cur.rowcount:
            c.execute('INSERT INTO sync_attempts(event_id,created_at,outcome,error_code) VALUES(?,?,?,?)',(event['id'],utcnow(),state,error))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


def send_https(url,token,payload):
    parts=urllib.parse.urlsplit(url)
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Central URL must be HTTPS without credentials, query or fragment')
    request=urllib.request.Request(url.rstrip('/')+'/api/sync/receive',data=dumps(payload).encode(),method='POST',
            headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
    # Default SSL context verifies CA and hostname; redirects cannot leak the bearer token.
    with urllib.request.build_opener(_NoRedirect()).open(request,timeout=30) as response:
        raw=response.read(262145)
        if len(raw)>262144: raise ValueError('Oversized synchronization response')
        return json.loads(raw)


def sync_once(user,url,remote_token,transport=None,mission_map=None):
    claimed=_claim(user)
    if claimed is None: return False
    event,claim,payload=claimed
    event_data=payload['events'][0]
    for context in (event_data['measurement'],event_data.get('session')):
        if context and context.get('mission_id') in (mission_map or {}):
            context['mission_id']=mission_map[context['mission_id']]
    try:
        result=(transport or send_https)(url,remote_token,payload)
        accepted=result.get('accepted',[])
        if len(accepted)!=1 or accepted[0].get('id')!=event['measurement_id']:
            raise ValueError('Invalid acknowledgement')
        _finish(event,claim,'sent')
    except urllib.error.HTTPError as exc:
        _finish(event,claim,'conflict' if exc.code in (403,404,409,422) else 'pending','http_'+str(exc.code))
    except APIError as exc:
        _finish(event,claim,'conflict' if exc.status in (403,404,409,422) else 'pending','http_'+str(exc.status))
    except Exception:
        # Never persist remote responses, URLs, bearer tokens or sensitive payloads.
        _finish(event,claim,'pending','transport_error')
    return True


def dispatch_sync(method,path,headers,raw,query,peer):
    from app.api_15 import _token
    user=auth.authenticate(_token(headers))
    if method=='GET' and path=='/api/sync/status':
        if query or raw: raise APIError(422,'unexpected_input','No parameters expected')
        return 200,status(user)
    if method=='GET' and path in ('/api/sync/history','/api/sync/pending'):
        if set(query)-{'after','limit'} or any(len(v)!=1 for v in query.values()): raise APIError(422,'query_invalid','Invalid query')
        from app.schemas_15 import HistoryQuery
        q=HistoryQuery.model_validate({k:v[0] for k,v in query.items()})
        return 200,(history if path.endswith('history') else pending)(user,q.after,q.limit)
    if method=='POST':
        if query: raise APIError(422,'unexpected_query','Unexpected query parameter')
        if headers.get('content-type','').split(';')[0]!='application/json': raise APIError(415,'content_type','Expected application/json')
        payload=json.loads(raw or b'{}')
        if path=='/api/sync/receive': return 200,receive(user,payload)
        if path.startswith('/api/sync/retry/'):
            if payload: raise APIError(422,'unexpected_input','No body fields expected')
            return 200,retry(user,path.rsplit('/',1)[-1])
    raise APIError(404,'not_found','Unknown sync route')


if __name__=='__main__':
    import argparse
    import getpass
    p=argparse.ArgumentParser(description='Synchronize this user’s pending measurements over verified HTTPS')
    p.add_argument('--central',required=True); p.add_argument('--once',action='store_true')
    p.add_argument('--mission-map',action='append',default=[],metavar='LOCAL_ID=CENTRAL_ID')
    a=p.parse_args(); db.init_db()
    mapping=dict(pair.split('=',1) for pair in a.mission_map)
    local_token=getpass.getpass('Local personal session token: ')
    remote_token=getpass.getpass('Central personal session token: ')
    try:
        while True:
            user=auth.authenticate(local_token)
            worked=sync_once(user,a.central,remote_token,mission_map=mapping)
            if a.once: break
            time.sleep(1 if worked else 5)
    except KeyboardInterrupt: pass
    except APIError: print('Local session expired. Sign in again and restart the worker.')


def unverified_metadata(value):
    """Authenticated delivery is not proof of sensor contact. Preserve claims under unverified keys."""
    if isinstance(value,list):return [unverified_metadata(v) for v in value]
    if not isinstance(value,dict):return value
    result={}
    for key,val in value.items():
        out='unverified_'+key if key in ('data_class','contact','be3_quality','client_measurement_id','written_via') or key.startswith('be3_') else key
        if out in result or (out!=key and out in value):raise APIError(422,'provenance_collision','Conflicting unverified metadata keys')
        result[out]=unverified_metadata(val)
    return result
