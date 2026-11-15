"""Versioned mission contracts. Minutes are relative to scenario start; UTC on the wire."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

API_VERSION = '1.0'
MODEL_VERSION = 'educational-1.0'
Origin = Literal['real', 'estimated', 'synthetic']
Quality = Literal['valid', 'missing', 'invalid', 'stale']

class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, validate_default=True)

class Window(Model):
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode='after')
    def ordered(self):
        if self.end <= self.start:
            raise ValueError('Window end must be after start')
        return self

class Reading(Model):
    metric: Literal['temperature', 'humidity', 'co2', 'light', 'heart_rate', 'sleep_hours',
                    'sleep_quality', 'activity', 'fatigue', 'cognition', 'workload']
    value: float | None
    unit: str
    timestamp: datetime
    origin: Origin
    source_id: str = Field(min_length=1)
    quality: Quality = 'valid'
    crew_id: int | None = Field(default=None, ge=1)
    zone_id: str | None = None
    sensor_id: str | None = None
    model_version: str | None = None
    processing: list[str] = Field(default_factory=list)

    @field_validator('timestamp')
    @classmethod
    def utc(cls, v):
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError('A timezone is required')
        return v.astimezone(timezone.utc)

    @model_validator(mode='after')
    def units_quality(self):
        units = {'temperature': 'degC', 'humidity': '%', 'co2': 'ppm', 'light': 'lux',
                 'heart_rate': 'bpm', 'sleep_hours': 'h', 'sleep_quality': 'score_0_100',
                 'activity': 'min/day', 'fatigue': 'score_0_10', 'cognition': 'score_0_100',
                 'workload': 'h/day'}
        if self.unit != units[self.metric]:
            raise ValueError(f'{self.metric} requires unit {units[self.metric]}')
        if self.quality in ('missing', 'invalid') and self.value is not None:
            raise ValueError('Missing/invalid values must be null; keep raw data outside analysis')
        if self.quality in ('valid', 'stale') and self.value is None:
            raise ValueError('A valid/stale reading requires a value')
        limits = {'temperature': (-100, 100), 'humidity': (0, 100), 'co2': (0, 1000000),
                  'light': (0, 200000), 'heart_rate': (20, 250), 'sleep_hours': (0, 24),
                  'sleep_quality': (0, 100), 'activity': (0, 1440), 'fatigue': (0, 10),
                  'cognition': (0, 100), 'workload': (0, 24)}
        if self.value is not None and not limits[self.metric][0] <= self.value <= limits[self.metric][1]:
            raise ValueError('Value outside input plausibility bounds')
        return self

class Baseline(Model):
    heart_rate: float = Field(default=65, ge=40, le=100)
    sleep_hours: float = Field(default=8, ge=4, le=12)
    sleep_quality: float = Field(default=85, ge=30, le=100)
    activity: float = Field(default=60, ge=0, le=240)
    fatigue: float = Field(default=2, ge=0, le=8)
    cognition: float = Field(default=90, ge=40, le=100)

class Crew(Model):
    id: int = Field(ge=1)
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    skills: set[str] = Field(default_factory=set)
    available: list[Window] = Field(default_factory=lambda: [Window(start=480, end=1200)])
    rest: list[Window] = Field(default_factory=list)
    max_work_minutes_per_day: int = Field(default=480, ge=0, le=1440)
    max_continuous_minutes: int = Field(default=120, ge=1, le=1440)
    break_minutes: int = Field(default=15, ge=0, le=240)
    max_load_per_day: float = Field(default=8, ge=0, le=24)

    @field_validator('available', 'rest')
    @classmethod
    def disjoint(cls, v):
        ordered = sorted(v, key=lambda w: w.start)
        if any(a.end > b.start for a, b in zip(ordered, ordered[1:])):
            raise ValueError('Windows in a list must not overlap')
        return ordered

class Task(Model):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = ''
    priority: int = Field(default=3, ge=1, le=5)
    duration_minutes: int = Field(ge=1, le=1440)
    required_skills: set[str] = Field(default_factory=set)
    people: int = Field(default=1, ge=1, le=12)
    earliest: int = Field(default=480, ge=0)
    deadline: int = Field(default=1200, gt=0)
    dependencies: list[str] = Field(default_factory=list)
    equipment: dict[str, int] = Field(default_factory=dict)
    physical_load: float = Field(default=.5, ge=0, le=1)
    cognitive_load: float = Field(default=.5, ge=0, le=1)
    # 1.0 (B1, team decision 2026-11-14): every task is mandatory by default – a schedule is valid only if it contains
    # all required tasks. A task can be marked optional explicitly (required=False); optional tasks that do not fit
    # are listed in `unscheduled` with a reason, never dropped silently.
    required: bool = True

    @model_validator(mode='after')
    def valid(self):
        if self.deadline <= self.earliest:
            raise ValueError('Deadline must be after earliest start')
        if self.id in self.dependencies or len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError('Invalid task dependencies')
        if any(n < 1 for n in self.equipment.values()):
            raise ValueError('Equipment quantities must be positive')
        return self

class Equipment(Model):
    id: str = Field(min_length=1)
    capacity: int = Field(default=1, ge=0, le=20)
    unavailable: list[Window] = Field(default_factory=list)

class PlanningInput(Model):
    crew: list[Crew] = Field(min_length=1, max_length=12)
    tasks: list[Task] = Field(default_factory=list, max_length=60)
    equipment: list[Equipment] = Field(default_factory=list)
    horizon_minutes: int = Field(default=1440, ge=1, le=10080)
    step_minutes: int = Field(default=15, ge=1, le=120)
    time_limit_seconds: float = Field(default=10, gt=0, le=60)

    @model_validator(mode='after')
    def references(self):
        for values in (self.crew, self.tasks, self.equipment):
            if len({v.id for v in values}) != len(values):
                raise ValueError('Duplicate identifiers')
        tasks = {t.id: t for t in self.tasks}
        eq = {e.id for e in self.equipment}
        for t in self.tasks:
            if set(t.dependencies) - tasks.keys():
                raise ValueError('Unknown dependency')
            if set(t.equipment) - eq:
                raise ValueError('Unknown equipment')
        seen, visiting = set(), set()
        def visit(key):
            if key in visiting:
                raise ValueError('Cyclic task dependencies')
            if key in seen:
                return
            visiting.add(key)
            for dep in tasks[key].dependencies:
                visit(dep)
            visiting.remove(key); seen.add(key)
        for key in tasks:
            visit(key)
        return self

class Assignment(Model):
    task_id: str
    crew_ids: list[int]
    start: int = Field(ge=0)
    end: int = Field(gt=0)

class Environment(Model):
    temperature: float = Field(default=22, ge=10, le=35)
    humidity: float = Field(default=45, ge=5, le=95)
    co2: float = Field(default=800, ge=250, le=10000)
    light: float = Field(default=500, ge=0, le=10000)
    night_light: float = Field(default=5, ge=0, le=1000)
    lights_on_hour: float = Field(default=7, ge=0, lt=24)
    lights_off_hour: float = Field(default=22, ge=0, lt=24)
    zone_id: str = Field(default='habitat', min_length=1)

    @model_validator(mode='after')
    def cycle(self):
        if self.lights_on_hour >= self.lights_off_hour:
            raise ValueError('Daylight interval must be within one model day')
        return self

class Event(Model):
    minute: int = Field(ge=0)
    kind: Literal['sleep_loss', 'fatigue_rise', 'pulse_shift', 'cognitive_decline',
                  'workload_rise', 'environment', 'multifactor', 'missing', 'corrupt', 'noise']
    intensity: float = Field(default=1, ge=0, le=3)
    crew_id: int | None = Field(default=None, ge=1)
    ramp_minutes: int = Field(default=360, ge=0)

class Scenario(Model):
    id: str = Field(default='mars_day_67', min_length=1)
    title: str = 'Mars flight — day 67'
    seed: int = Field(default=67, ge=0, le=2**32-1)
    start: datetime = datetime(2035, 1, 1, tzinfo=timezone.utc)
    mission_day: int = Field(default=67, ge=1)
    duration_minutes: int = Field(default=1440, ge=1, le=43200)
    sample_minutes: int = Field(default=30, ge=1, le=1440)
    environment: Environment = Field(default_factory=Environment)
    planning: PlanningInput
    baselines: dict[int, Baseline] = Field(default_factory=dict)
    sleep_hours: float = Field(default=8, ge=0, le=12)
    extra_rest_hours: float = Field(default=0, ge=0, le=8)
    workload_hours: float = Field(default=0, ge=0, le=12)
    intensity: float = Field(default=1, ge=0, le=3)
    noise: float = Field(default=.2, ge=0, le=3)
    events: list[Event] = Field(default_factory=list, max_length=100)
    model_version: Literal['educational-1.0'] = MODEL_VERSION

    @field_validator('start')
    @classmethod
    def utc(cls, v):
        if v.tzinfo is None:
            raise ValueError('Scenario start requires timezone')
        return v.astimezone(timezone.utc)

    @model_validator(mode='after')
    def valid(self):
        ids = {c.id for c in self.planning.crew}
        if set(self.baselines) - ids or any(e.crew_id is not None and e.crew_id not in ids for e in self.events):
            raise ValueError('Unknown crew in baseline or event')
        if any(e.minute >= self.duration_minutes for e in self.events):
            raise ValueError('Event must occur before end of scenario')
        if self.duration_minutes // self.sample_minutes * len(ids) > 20000:
            raise ValueError('Too many samples; increase sample_minutes')
        return self

class PhantomResult(Model):
    sample_id: str
    anomaly: bool | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    summary: str = ''
    # Deliberately no medical details in this scheduling-only projection.
    unavailable: dict[int, list[Window]] = Field(default_factory=dict)
    planning_authorized: bool = False
