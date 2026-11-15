"""One route registry, validator and permission layer for both HTTP servers."""
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from pydantic import ValidationError, TypeAdapter
from . import auth, db, schemas_15 as s
from .persistence import repository as repo, missions, accounts
from . import schemas_integration as si
from .storage.api import StorageAPI
from .science_integration import service as science
from .persistence.common import APIError


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    model: object
    handler: object
    public: bool = False
    status: int = 200
    query: object = False


def _logout(user, token):
    """AUTH-02: stop & save this session's BLE recordings while the token is still valid, then revoke it."""
    try:
        from .devices.api import on_logout
        on_logout(token)
    except Exception:
        pass
    return auth.logout(user, token)


ROUTES = [
 Route('POST','/api/auth/register',s.Register,lambda u,b,p,q,ctx:auth.register(**b,peer=ctx['peer']),True,201),
 Route('POST','/api/auth/login',s.Login,lambda u,b,p,q,ctx:auth.login(**b,peer=ctx['peer']),True),
 Route('POST','/api/auth/recover',s.Recover,lambda u,b,p,q,ctx:auth.recover(**b,peer=ctx['peer']),True),
 Route('POST','/api/auth/logout',None,lambda u,b,p,q,ctx:_logout(u,ctx['token'])),
 Route('GET','/api/auth/me',None,lambda u,b,p,q,ctx:{'user':u}),
 Route('POST','/api/auth/change-password',s.ChangePassword,lambda u,b,p,q,ctx:auth.change_password(u,**b,peer=ctx['peer'])),
 Route('GET','/api/profile',None,lambda u,b,p,q,ctx:repo.get_profile(u)),
 Route('PATCH','/api/profile',s.ProfilePatch,lambda u,b,p,q,ctx:repo.patch_profile(u,b)),
 Route('GET','/api/missions',None,lambda u,b,p,q,ctx:missions.list_missions(u)),
 Route('POST','/api/missions',s.MissionCreate,lambda u,b,p,q,ctx:missions.create_mission(u,b),status=201),
 Route('GET','/api/missions/{id}/crew',None,lambda u,b,p,q,ctx:missions.crew(u,p['id'])),
 Route('POST','/api/missions/{id}/crew',s.Membership,lambda u,b,p,q,ctx:missions.membership(u,p['id'],b)),
 Route('DELETE','/api/missions/{id}/crew/{user_id}',None,lambda u,b,p,q,ctx:missions.remove_member(u,p['id'],p['user_id'])),
 Route('POST','/api/missions/{id}/medical-access',s.MedicalGrant,lambda u,b,p,q,ctx:missions.grant(u,p['id'],b)),
 Route('DELETE','/api/missions/{id}/medical-access/{officer_id}/{astronaut_id}',None,
       lambda u,b,p,q,ctx:missions.revoke(u,p['id'],p['officer_id'],p['astronaut_id'])),
 Route('POST','/api/measurements/batch',si.MeasurementBatch,lambda u,b,p,q,ctx:{'items':StorageAPI(ctx['token']).append_biosignals(b['measurements'])},status=200),
 Route('POST','/api/measurements',s.MeasurementCreate,lambda u,b,p,q,ctx:repo.add_measurements(u,[b])[0],status=201),
 Route('GET','/api/measurements/latest',None,lambda u,b,p,q,ctx:repo.latest_measurements(u)),
 Route('GET','/api/measurements',None,lambda u,b,p,q,ctx:repo.list_measurements(u,q),query=True),
 Route('GET','/api/measurements/aggregates',None,lambda u,b,p,q,ctx:repo.aggregates(u,q),query=True),
 Route('GET','/api/measurements/export',None,lambda u,b,p,q,ctx:repo.export_measurements(u,q),query=True),
 Route('GET','/api/measurements/{id}',None,lambda u,b,p,q,ctx:repo.get_measurement(u,p['id'])),
 Route('GET','/api/devices',None,lambda u,b,p,q,ctx:repo.list_devices(u)),
 Route('POST','/api/devices',s.DeviceCreate,lambda u,b,p,q,ctx:repo.create_device(u,b),status=201),
 Route('PATCH','/api/devices/{id}',si.DevicePatch,lambda u,b,p,q,ctx:repo.update_device(u,p['id'],b)),
 Route('DELETE','/api/devices/{id}',None,lambda u,b,p,q,ctx:repo.remove_device(u,p['id'])),
 Route('GET','/api/devices/{id}/sessions',None,lambda u,b,p,q,ctx:repo.device_sessions(u,p['id'],q),query=True),
 Route('POST','/api/sensor-sessions',s.SessionCreate,lambda u,b,p,q,ctx:repo.create_session(u,b),status=201),
 Route('POST','/api/sensor-sessions/{id}/close',None,lambda u,b,p,q,ctx:repo.close_session(u,p['id'])),
 Route('GET','/api/analyses',None,lambda u,b,p,q,ctx:repo.list_records(u,q,'analysis_runs'),query=True),
 Route('POST','/api/analyses',s.AnalysisRequest,lambda u,b,p,q,ctx:repo.run_summary(u,b),status=201),
 Route('GET','/api/analyses/{id}',None,lambda u,b,p,q,ctx:repo.get_analysis(u,p['id'])),
 Route('GET','/api/alerts',None,lambda u,b,p,q,ctx:repo.list_records(u,q,'alerts'),query=True),
 Route('POST','/api/alerts/{id}/review',s.Review,lambda u,b,p,q,ctx:repo.review_alert(u,p['id'],b['status'])),
 Route('GET','/api/recovery/sessions',None,lambda u,b,p,q,ctx:repo.list_records(u,q,'recovery_sessions'),query=True),
 Route('POST','/api/recovery/sessions',s.RecoveryCreate,lambda u,b,p,q,ctx:repo.create_recovery(u,b),status=201),
]
ROUTES += [
 Route('GET','/api/admin/users',None,lambda u,b,p,q,ctx:accounts.list_users(ctx['token'],q),query=si.PageQuery),
 Route('PATCH','/api/admin/users/{id}',si.AccountPatch,lambda u,b,p,q,ctx:accounts.patch_user(ctx['token'],p['id'],b)),
 Route('GET','/api/admin/audit-logs',None,lambda u,b,p,q,ctx:accounts.audit_history(ctx['token'],q),query=si.PageQuery),
]
COMPILED = [(r,re.compile('^'+re.sub(r'\{(\w+)\}',r'(?P<\1>[^/]+)',r.path)+'$')) for r in ROUTES]


def legacy_allowed():
    if os.environ.get('AETHER_LEGACY_DEMO')!='1' or os.environ.get('AETHER_RELEASE')=='1' or os.environ.get('AETHER_REMOTE')=='1': return False
    with db.connect() as c:
        return c.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0


def _token(headers):
    auth_header=headers.get('authorization','')
    return auth_header[7:] if auth_header.startswith('Bearer ') else ''


def error_response(exc):
    if type(exc).__module__=='app.science_errors': return exc.status,{'error':{'code':exc.code,'detail':exc.message}}
    if isinstance(exc,APIError): return exc.status,{'error':{'code':exc.code,'detail':exc.detail}}
    if isinstance(exc,ValidationError):
        return 422,{'error':{'code':'validation_error','detail':'Request validation failed',
                    'fields':[{'loc':list(e['loc']),'type':e['type']} for e in exc.errors(include_input=False,include_url=False,include_context=False)]}}
    if isinstance(exc,(ValueError,TypeError,json.JSONDecodeError)):
        return 400,{'error':{'code':'invalid_request','detail':'Invalid JSON request'}}
    if isinstance(exc,sqlite3.IntegrityError): return 409,{'error':{'code':'constraint_conflict','detail':'Data constraint conflict'}}
    if isinstance(exc,sqlite3.OperationalError): return 503,{'error':{'code':'storage_unavailable','detail':'Storage temporarily unavailable; retry safely'}}
    return 500,{'error':{'code':'internal_error','detail':'Operation failed'}}


def dispatch(method,path,headers,raw,query,peer='local'):
    """Returns (status,JSON) for 1.5, None for deliberately isolated legacy demo routes."""
    if path=='/api/health' and method=='GET':
        from . import service
        from .persistence.capabilities_06 import capabilities
        return 200,{**service.health(),'feature_status':capabilities()}
    if path in ('/api/health','/api/session'): return None
    user = None
    try:
        if path=='/api/recovery/sessions' and method=='POST' and not headers.get('authorization') and legacy_allowed(): return None
        matched=[(r,rx.fullmatch(path)) for r,rx in COMPILED if rx.fullmatch(path)]
        if path.startswith('/api/sync/'):
            from .persistence.sync import dispatch_sync
            return dispatch_sync(method,path,headers,raw,query,peer)
        if not any(r.method==method for r,m in matched):
            from .science_http import handle as science_handle
            scientific_result=science_handle(method,path,headers,raw,query,peer)
            if scientific_result is not None: return scientific_result
        if not matched:
            if path=='/api/contract' and method=='GET': return 200,contract()
            if legacy_allowed(): return None
            auth.authenticate(_token(headers))
            raise APIError(410,'legacy_isolated','Legacy routes are isolated; use the AETHER 1.5 personal API')
        route=next(((r,m) for r,m in matched if r.method==method),None)
        if not route: raise APIError(405,'method_not_allowed','Method not allowed')
        r,m=route
        for value in m.groupdict().values(): TypeAdapter(s.Identifier).validate_python(value)
        user=None if r.public else auth.authenticate(_token(headers))
        if any(len(v)!=1 for v in query.values()): raise APIError(422,'query_duplicate','Duplicate query parameter')
        query_model=s.HistoryQuery if r.query is True else r.query
        q=query_model.model_validate({k:v[0] for k,v in query.items()}) if query_model else None
        if query and not r.query: raise APIError(422,'query_unexpected','Unexpected query parameter')
        if raw and headers.get('content-type','').split(';')[0].strip().lower()!='application/json':
            raise APIError(415,'content_type','Content-Type must be application/json')
        payload=json.loads(raw) if raw else {}
        if not isinstance(payload,dict): raise APIError(422,'json_object','Expected a JSON object')
        if r.model is dict: pass
        elif r.model: payload=r.model.model_validate(payload).model_dump(exclude_unset=isinstance(r.model,type) and r.model in (s.ProfilePatch,si.AccountPatch))
        elif payload: raise APIError(422,'body_unexpected','This route takes no JSON fields')
        result=r.handler(user,payload,m.groupdict(),q,{'peer':peer,'token':_token(headers)})
        status=r.status
        if r.path in ('/api/measurements','/api/phantom-analyses') and method=='POST' and not result['created']: status=200
        return status,result
    except Exception as exc:
        response = error_response(exc)
        try:
            from .persistence.common import audit
            with db.connect() as c: audit(c,user['id'] if user else None,'request_denied','api',outcome=str(response[0]))
        except sqlite3.Error:
            pass
        return response


def contract():
    from .api_contract_15 import response as original_response, ERROR, schema
    from .science_integration.contracts import response as integration_response
    def response(method,path):
        return integration_response(method,path) or original_response(method,path)
    paths={}
    for r in ROUTES:
        operation={'summary':r.method+' '+r.path,'security':[] if r.public else [{'personalBearer':[]}],
            'responses':{str(r.status):{'description':'Success'},'401':{'description':'Invalid/expired session'},
                         '404':{'description':'Missing or inaccessible resource'},'422':{'description':'Invalid input'},
                         '409':{'description':'Conflict'},'429':{'description':'Rate limited'}}}
        operation['responses'][str(r.status)]['content']={'application/json':{'schema':response(r.method,r.path)}}
        if r.method=='POST' and r.path in ('/api/measurements','/api/phantom-analyses'):
            operation['responses']['200']={'description':'Idempotent replay','content':operation['responses'][str(r.status)]['content']}
        for code in ('400','401','403','404','405','409','413','415','422','429','502','503','500'):
            operation['responses'].setdefault(code,{'description':'Request error'})['content']={'application/json':{'schema':ERROR}}
        if r.model:
            operation['requestBody']={'required':True,'content':{'application/json':{'schema':schema(r.model)}}}
        parameters=[{'name':name,'in':'path','required':True,'schema':{'type':'string'}} for name in re.findall(r'\{(\w+)\}',r.path)]
        if r.query:
            parameters += [{'name':name,'in':'query','schema':field} for name,field in (s.HistoryQuery if r.query is True else r.query).model_json_schema()['properties'].items()]
        if parameters: operation['parameters']=parameters
        paths.setdefault(r.path,{})[r.method.lower()]=operation
    from .persistence.sync import SyncBatch
    from .api_contract_15 import obj, paged, STRING, BOOLEAN
    sync_paths = {
        '/api/sync/status': ('get', obj({'counts':{'type':'object','additionalProperties':{'type':'integer'}},'unsent':{'type':'integer'}})),
        '/api/sync/history': ('get', paged(obj({'id':{'type':'integer'},'event_id':STRING,'created_at':STRING,'outcome':STRING,'error_code':{'type':['string','null']}}))),
        '/api/sync/pending': ('get', paged(obj({'seq':{'type':'integer'},'id':STRING,'measurement_id':STRING,'status':STRING,'attempts':{'type':'integer'},'last_error':{'type':['string','null']},'created_at':STRING}))),
        '/api/sync/receive': ('post', obj({'accepted':{'type':'array','items':obj({'id':STRING,'created':BOOLEAN})}})),
        '/api/sync/retry/{id}': ('post', obj({'queued':BOOLEAN})),
    }
    for path,(method,result_schema) in sync_paths.items():
        op={'summary':method.upper()+' '+path,'security':[{'personalBearer':[]}],
            'responses':{'200':{'description':'Success','content':{'application/json':{'schema':result_schema}}}}}
        if path.endswith('/receive'):
            op['requestBody']={'required':True,'content':{'application/json':{'schema':schema(SyncBatch)}}}
        if '{id}' in path: op['parameters']=[{'name':'id','in':'path','required':True,'schema':STRING}]
        if path.endswith(('/history','/pending')):
            op['parameters']=[{'name':key,'in':'query','schema':s.HistoryQuery.model_json_schema()['properties'][key]} for key in ('after','limit')]
        for code in ('400','401','403','404','409','413','415','422','503'):
            op['responses'][code]={'description':'Error','content':{'application/json':{'schema':ERROR}}}
        paths[path]={method:op}
    from .persistence.science_contract_06 import paths as scientific_paths
    paths.update(scientific_paths())
    return {'openapi':'3.1.0','info':{'title':'AETHER Personal API','version':'1.5.0'},'paths':paths,
        'components':{'securitySchemes':{'personalBearer':{'type':'http','scheme':'bearer'}}}}


class PersonalAPI:
    def __init__(self,app): self.app=app

    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or not scope['path'].startswith('/api/'):
            return await self.app(scope,receive,send)
        from urllib.parse import parse_qs
        from starlette.concurrency import run_in_threadpool
        chunks=[]
        while True:
            message=await receive()
            if message['type']=='http.disconnect': return
            chunks.append(message.get('body',b''))
            if not message.get('more_body'): break
        raw=b''.join(chunks)
        headers={k.decode('latin-1').lower():v.decode('latin-1') for k,v in scope['headers']}
        result=await run_in_threadpool(dispatch,scope['method'],scope['path'],headers,raw,
                    parse_qs(scope.get('query_string',b'').decode('utf-8'),keep_blank_values=True), (scope.get('client') or ('local',0))[0])
        if result is None:
            async def replay(): return {'type':'http.request','body':raw,'more_body':False}
            return await self.app(scope,replay,send)
        status,payload=result; data=json.dumps(payload,allow_nan=False).encode()
        await send({'type':'http.response.start','status':status,'headers':[
            (b'content-type',b'application/json'),(b'content-length',str(len(data)).encode()),
            (b'cache-control',b'no-store'),(b'x-content-type-options',b'nosniff'),(b'referrer-policy',b'no-referrer')]})
        await send({'type':'http.response.body','body':data})
