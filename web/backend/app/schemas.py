"""Pydantic request models shared by the FastAPI app and the stdlib fallback server."""
from typing import Literal

from pydantic import BaseModel, Field

Skill = Literal['command', 'science', 'engineering', 'medical']
Activity = Literal['zero-g-garden', 'earth-window', 'orbit-flow', 'mind-pulse']


class Measurement(BaseModel):
    day: int = Field(ge=1, le=9999)
    heart_rate_bpm: float | None = Field(default=None, ge=20, le=240)
    sleep_hours: float | None = Field(default=None, ge=0, le=24)
    fatigue_1_10: float | None = Field(default=None, ge=1, le=10)
    reaction_ms: float | None = Field(default=None, ge=50, le=2000)
    activity_minutes: float | None = Field(default=None, ge=0, le=1440)


class SimulationRequest(BaseModel):
    astronaut_id: str = 'A01'
    day: int = Field(default=67, ge=1, le=9999)
    sleep_delta: float = Field(default=0, ge=-5, le=5)
    workload: int = Field(default=50, ge=0, le=100)
    co2_ppm: int = Field(default=850, ge=350, le=5000)
    temperature_c: float = Field(default=22, ge=10, le=35)
    crew_available: int = Field(default=4, ge=1, le=4)


class ProjectionRequest(BaseModel):
    astronaut_id: str = 'A01'
    start_day: int = Field(default=67, ge=41, le=9999)
    horizon_days: int = Field(default=21, ge=1, le=90)
    sleep_delta: float = Field(default=0, ge=-5, le=5)
    workload: float = Field(default=50, ge=0, le=100)
    co2_ppm: float = Field(default=850, ge=350, le=5000)
    temperature_c: float = Field(default=22, ge=10, le=35)
    crew_available: int = Field(default=4, ge=1, le=4)
    runs: int = Field(default=200, ge=20, le=1000)
    seed: int = Field(default=67, ge=0, le=2**31 - 1)


class RecoverySession(BaseModel):
    astronaut_id: str = 'A01'
    activity: Activity
    before_mood: int = Field(ge=1, le=10)
    after_mood: int = Field(ge=1, le=10)
    duration_seconds: int = Field(ge=0, le=86400)
    details: dict[str, float | int | str | bool | None] | None = None


class Task(BaseModel):
    id: str = Field(min_length=1, max_length=24)
    title: str = Field(min_length=1, max_length=80)
    skill: Skill
    hours: float = Field(gt=0, le=12)
    priority: int = Field(ge=1, le=3)
    zone: str | None = None


class PlanRequest(BaseModel):
    tasks: list[Task] | None = Field(default=None, max_length=40)
    capacity: dict[str, float] = Field(default_factory=dict)
    unavailable: list[str] = Field(default_factory=list)
    optimise: bool = True


class ExperimentScenarioEnd(BaseModel):
    score_p50: float
    score_p10: float
    score_p90: float
    attention_share: float
    fatigue_p50: float


class ExperimentScenario(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=120)
    params: dict[str, float]
    end: ExperimentScenarioEnd


class Experiment(BaseModel):
    """Saved MISSION LAB experiment (same shape as the frontend's SavedExperiment)."""
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    created_at: str = Field(min_length=1, max_length=40)
    astronaut_id: str = Field(min_length=1, max_length=16)
    start_day: int = Field(ge=1, le=9999)
    horizon_days: int = Field(ge=1, le=365)
    runs: int = Field(ge=1, le=100000)
    seed: int = Field(ge=0)
    scenarios: list[ExperimentScenario] = Field(min_length=1, max_length=12)



class RadiationSegment(BaseModel):
    environment: str = Field(pattern='^(earth|iss|deep_space|lunar_surface|mars_surface)$')
    days: int = Field(ge=1, le=3000)


class RadiationSPE(BaseModel):
    day: int = Field(ge=0)
    dose_msv: float = Field(ge=0, le=2000)


class RadiationRequest(BaseModel):
    preset: str | None = None
    title: str | None = Field(default=None, max_length=120)
    segments: list[RadiationSegment] = Field(default_factory=list, max_length=20)
    spe: list[RadiationSPE] = Field(default_factory=list, max_length=20)
    shielding_factor: float = Field(default=1.0, ge=0.3, le=1.5)
    prior_career_msv: float = Field(default=0, ge=0, le=2000)
    runs: int = Field(default=500, ge=50, le=5000)
    seed: int = Field(default=67, ge=0)
