"""Response JSON schemas shared with generated OpenAPI and integration tests."""
from typing import Any, Literal
from pydantic import BaseModel


class User(BaseModel):
    id: str
    login: str
    role: Literal['astronaut','administrator']
    astronaut_id: str


class Profile(BaseModel):
    id: str
    user_id: str
    display_name: str
    language: Literal['uk','en']
    created_at: str


class Device(BaseModel):
    id: str
    astronaut_id: str
    name: str
    kind: str
    external_id: str | None
    created_at: str


class SensorSession(BaseModel):
    end_status: str | None = None
    end_metadata: dict | None = None
    seq: int
    id: str
    astronaut_id: str
    mission_id: str | None
    device_id: str | None
    source: str
    origin: str
    started_at: str
    ended_at: str | None
    metadata: dict


class Measurement(BaseModel):
    seq: int
    id: str
    astronaut_id: str
    mission_id: str | None
    device_id: str | None
    session_id: str | None
    source: str
    signal: str
    value: float | None
    unit: str
    measured_at: str | None
    received_at: str
    origin: str
    quality: str
    confidence: float | None
    missing: bool
    processing_version: str
    metadata: dict
    supersedes_id: str | None


class Aggregate(BaseModel):
    day: str
    signal: str
    unit: str
    origin: str
    mission_id: str | None
    sample_count: int
    valid_count: int
    missing_count: int
    mean: float | None
    minimum: float | None
    maximum: float | None


class Analysis(BaseModel):
    id: str
    astronaut_id: str
    mission_id: str | None
    session_id: str | None
    model: str
    processing_version: str
    created_at: str
    result: dict
    input_ids: list[str]


class Alert(BaseModel):
    id: str
    astronaut_id: str
    mission_id: str | None
    analysis_id: str | None
    severity: str
    message: str
    status: str
    reviewed_by: str | None
    reviewed_at: str | None
    created_at: str


class Recovery(BaseModel):
    id: int
    astronaut_id: str
    activity: str
    before_mood: int
    after_mood: int
    duration_seconds: int
    created_at: str
    details: dict
    profile_id: str | None
    mission_id: str | None


def obj(properties,required=None):
    return {'type':'object','properties':properties,'required':list(properties) if required is None else required}


def schema(model):
    # Inline Pydantic defs so nested JSON schemas remain valid OpenAPI schema objects.
    s=model.model_json_schema();defs=s.pop('$defs',{})
    def expand(x):
        if isinstance(x,list): return [expand(v) for v in x]
        if not isinstance(x,dict): return x
        if '$ref' in x: return expand(defs[x['$ref'].split('/')[-1]])
        return {k:expand(v) for k,v in x.items()}
    return expand(s)


def paged(item):
    return obj({'items':{'type':'array','items':item},'next_cursor':{'type':['integer','null']}})


STRING={'type':'string'}; BOOLEAN={'type':'boolean'}
MISSION=obj({'id':STRING,'name':STRING,'created_at':STRING})
CREW=obj({'astronaut_id':STRING,'display_name':STRING,'user_id':STRING,'role':{'enum':['astronaut','medical_officer']}})
ERROR=obj({'error':obj({'code':STRING,'detail':STRING,'fields':{'type':'array','items':obj({'loc':{'type':'array','items':{}},'type':STRING})}},['code','detail'])})

ERROR={'oneOf':[ERROR,obj({'detail':STRING})]}


def response(method,path):
    if path=='/api/auth/register': return obj({'user':schema(User),'recovery_code':STRING})
    if path=='/api/auth/login': return obj({'user':schema(User),'access_token':STRING,'token_type':{'const':'Bearer'},'expires_at':STRING,'idle_timeout_seconds':{'type':'integer'}})
    if path=='/api/auth/me': return obj({'user':schema(User)})
    if path=='/api/auth/logout': return obj({'logged_out':BOOLEAN})
    if path in ('/api/auth/change-password','/api/auth/recover'): return obj({'changed':BOOLEAN,'login_required':BOOLEAN,'recovery_code':STRING})
    if path=='/api/profile': return schema(Profile)
    if path=='/api/missions': return MISSION if method=='POST' else obj({'items':{'type':'array','items':MISSION}})
    if path.endswith('/crew'):
        return obj({'saved':BOOLEAN}) if method=='POST' else obj({'items':{'type':'array','items':CREW}})
    if '/crew/{user_id}' in path: return obj({'removed':BOOLEAN})
    if '/medical-access' in path: return obj({'granted' if method=='POST' else 'revoked':BOOLEAN})
    if path=='/api/measurements/latest':
        sample = schema(Measurement)
        sample['properties']['written_via'] = {'type': ['string','null']}
        return obj({'items':{'type':'array','items':sample},
                    'counts':{'type':'object','additionalProperties':obj({'samples':{'type':'integer'},'usable':{'type':'integer'}})},
                    'source':{'const':'authenticated_personal_sqlite'},
                    'clinical_validation':{'const':False}})
    if path=='/api/measurements':
        return obj({'measurement':schema(Measurement),'created':BOOLEAN}) if method=='POST' else paged(schema(Measurement))
    if path=='/api/measurements/{id}': return schema(Measurement)
    if path.endswith('/aggregates'):
        result=paged(schema(Aggregate));result['properties']['processing_version']=STRING;result['required'].append('processing_version');return result
    if path.endswith('/export'): return obj({'csv':STRING,'rows':{'type':'integer'},'next_cursor':{'type':['integer','null']}})
    if path=='/api/devices': return schema(Device) if method=='POST' else obj({'items':{'type':'array','items':schema(Device)}})
    if path=='/api/devices/{id}' and method=='PATCH': return schema(Device)
    if path=='/api/devices/{id}' and method=='DELETE': return obj({'removed':BOOLEAN,'device_id':STRING,'measurements_retained':BOOLEAN})
    if path=='/api/devices/{id}/sessions': return paged(schema(SensorSession))
    if path=='/api/sensor-sessions':
        result=schema(SensorSession);result['properties'].pop('seq');result['required'].remove('seq');return result
    if path.endswith('/close'): return obj({'closed':BOOLEAN})
    if path=='/api/analyses': return schema(Analysis) if method=='POST' else paged(schema(Analysis))
    if path=='/api/analyses/{id}': return schema(Analysis)
    if path=='/api/alerts': return paged(schema(Alert))
    if path.endswith('/review'): return obj({'id':STRING,'status':{'enum':['confirmed','rejected']}})
    if path=='/api/recovery/sessions': return schema(Recovery) if method=='POST' else paged(schema(Recovery))
    raise ValueError('Undocumented response: '+method+' '+path)
