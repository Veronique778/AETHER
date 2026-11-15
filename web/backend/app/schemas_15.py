"""Strict, shared request contracts; timestamps are normalized to UTC before storage."""
import json
import re
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .persistence.common import utc

Identifier = Annotated[str, Field(min_length=1,max_length=80,pattern=r'^[a-zA-Z0-9_.:-]+$')]
LoginName = Annotated[str, Field(min_length=3,max_length=64,pattern=r'^[a-zA-Z0-9_.-]+$')]
Password = Annotated[str, Field(min_length=12,max_length=128)]
Origin = Literal['real','manual','research','simulated']
# Values outside physical ranges are rejected; poor sensor quality may be stored as NULL.
SIGNALS = {
 'heart_rate':('bpm',0,300), 'heart_rate_bpm':('bpm',0,300),
 'rr_interval':('ms',100,5000), 'sleep_hours':('h',0,24),
 'sleep_duration':('s',0,86400), 'fatigue_1_10':('score',1,10),
 'reaction_ms':('ms',0,10000), 'activity_minutes':('min',0,1440),
 'temperature':('degC',-100,100), 'humidity':('%',0,100),
 'co2':('ppm',0,100000), 'light':('lux',0,200000),
 'spo2':('%',0,100), 'respiratory_rate':('breaths/min',0,120),
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True,str_strip_whitespace=False,allow_inf_nan=False)


class Register(StrictModel):
    login: LoginName
    password: Password
    display_name: str = Field(min_length=1,max_length=80)
    language: Literal['uk','en'] = 'uk'


class Login(StrictModel):
    login: LoginName
    password: str = Field(min_length=1,max_length=128)


class ChangePassword(StrictModel):
    current_password: str = Field(min_length=1,max_length=128)
    new_password: Password


class Recover(StrictModel):
    login: LoginName
    recovery_code: str = Field(min_length=32,max_length=128)
    new_password: Password


class ProfilePatch(StrictModel):
    display_name: str | None = Field(default=None,min_length=1,max_length=80)
    language: Literal['uk','en'] | None = None

    @model_validator(mode='after')
    def non_null(self):
        if not self.model_fields_set or any(getattr(self,k) is None for k in self.model_fields_set):
            raise ValueError('Supply at least one non-null profile field')
        return self


class DeviceCreate(StrictModel):
    name: str = Field(min_length=1,max_length=80)
    kind: Literal['ble','manual','wearable','other']
    external_id: str | None = Field(default=None,min_length=1,max_length=128)


class SessionCreate(StrictModel):
    device_id: Identifier | None = None
    mission_id: Identifier | None = None
    source: str = Field(min_length=1,max_length=120)
    origin: Origin
    started_at: str
    metadata: dict = Field(default_factory=dict)

    @field_validator('started_at')
    @classmethod
    def timestamp(cls,v): return utc(v)

    @field_validator('metadata')
    @classmethod
    def bounded(cls,v):
        if len(json.dumps(v,allow_nan=False).encode())>8192: raise ValueError('Metadata exceeds 8192 bytes')
        return v


class MeasurementCreate(StrictModel):
    id: Identifier | None = None
    astronaut_id: Identifier | None = None
    mission_id: Identifier | None = None
    device_id: Identifier | None = None
    session_id: Identifier | None = None
    idempotency_key: str = Field(min_length=1,max_length=128)
    source: str = Field(min_length=1,max_length=120)
    signal: Literal[tuple(SIGNALS)]
    value: float | None = None
    unit: str = Field(min_length=1,max_length=24)
    measured_at: str
    origin: Origin
    quality: Literal['unverified','screened','validated','rejected','corrupt','no_contact','connection_lost'] = 'unverified'
    confidence: float | None = Field(default=None,ge=0,le=1)
    processing_version: str = Field(default='raw-1.5',min_length=1,max_length=64)
    metadata: dict = Field(default_factory=dict)
    supersedes_id: Identifier | None = None

    @field_validator('measured_at')
    @classmethod
    def timestamp(cls,v): return utc(v)

    @field_validator('metadata')
    @classmethod
    def bounded(cls,v): return SessionCreate.bounded(v)

    @model_validator(mode='after')
    def units_and_range(self):
        unit,lo,hi = SIGNALS[self.signal]
        if self.unit != unit: raise ValueError('Incorrect unit for signal')
        if self.value is not None and not lo<=self.value<=hi: raise ValueError('Value outside accepted signal range')
        if self.origin == 'research': raise ValueError('Research data belongs in the separate research store')
        if self.origin == 'real' and (not self.device_id or not self.session_id):
            raise ValueError('Real measurements require a device and sensor session')
        return self


class HistoryQuery(StrictModel):
    model_config = ConfigDict(extra='forbid',strict=False,allow_inf_nan=False)
    astronaut_id: Identifier | None = None
    mission_id: Identifier | None = None
    device_id: Identifier | None = None
    session_id: Identifier | None = None
    signal: str | None = Field(default=None,max_length=64)
    start: str | None = None
    end: str | None = None
    limit: int = Field(default=100,ge=1,le=500)
    after: int = Field(default=0,ge=0)

    @field_validator('start','end')
    @classmethod
    def timestamp(cls,v): return utc(v) if v is not None else v

    @model_validator(mode='after')
    def period(self):
        if self.start and self.end and self.start>self.end: raise ValueError('start must not follow end')
        return self


class MissionCreate(StrictModel):
    name: str = Field(min_length=1,max_length=100)


class Membership(StrictModel):
    user_id: Identifier
    role: Literal['astronaut','medical_officer']


class MedicalGrant(StrictModel):
    officer_id: Identifier
    astronaut_id: Identifier
    can_review: bool = False


class Review(StrictModel):
    status: Literal['confirmed','rejected']


class AnalysisSave(StrictModel):
    astronaut_id: Identifier | None = None
    mission_id: Identifier | None = None
    session_id: Identifier | None = None
    model: str = Field(min_length=1,max_length=100)
    processing_version: str = Field(min_length=1,max_length=64)
    idempotency_key: str = Field(min_length=1,max_length=128)
    input_ids: list[Identifier] = Field(default_factory=list,max_length=400000)
    result: dict

    @field_validator('result')
    @classmethod
    def result_size(cls,v):
        if len(json.dumps(v,allow_nan=False).encode())>128000: raise ValueError('Result too large')
        return v


class AnalysisRequest(StrictModel):
    session_id: Identifier
    model: Literal['summary-v1'] = 'summary-v1'
    idempotency_key: str = Field(min_length=1,max_length=128)


class RecoveryCreate(StrictModel):
    astronaut_id: Identifier | None = None
    mission_id: Identifier | None = None
    activity: Literal['zero-g-garden','earth-window','orbit-flow','mind-pulse']
    before_mood: int = Field(ge=1,le=10)
    after_mood: int = Field(ge=1,le=10)
    duration_seconds: int = Field(ge=0,le=86400)
    details: dict = Field(default_factory=dict)

    @field_validator('details')
    @classmethod
    def bounded(cls,v): return SessionCreate.bounded(v)

class ProcessedValue(StrictModel):
    raw_id: Identifier
    signal: str = Field(min_length=1,max_length=64)
    value: float | None = None
    unit: str = Field(min_length=1,max_length=24)


class AlertCreate(StrictModel):
    analysis_id: Identifier
    severity: Literal['info','warning','critical']
    message: str = Field(min_length=1,max_length=1000)
