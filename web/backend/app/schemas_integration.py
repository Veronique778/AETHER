"""Additive BE2 integration proposal; existing 1.5 request schemas stay unchanged."""
from typing import Literal
from pydantic import ConfigDict, Field, model_validator
from app.schemas_15 import StrictModel, Identifier, MeasurementCreate, AnalysisSave


class PageQuery(StrictModel):
    model_config = ConfigDict(extra='forbid', strict=False)
    after: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)


class PhantomQuery(PageQuery):
    astronaut_id: Identifier | None = None
    mission_id: Identifier | None = None
    session_id: Identifier | None = None


class AccountPatch(StrictModel):
    active: bool | None = None
    role: Literal['astronaut', 'administrator'] | None = None

    @model_validator(mode='after')
    def supplied(self):
        if not self.model_fields_set or any(getattr(self, k) is None for k in self.model_fields_set):
            raise ValueError('Supply at least one non-null field')
        return self


class MeasurementBatch(StrictModel):
    measurements: list[MeasurementCreate] = Field(min_length=1, max_length=1000)


class PhantomRequest(StrictModel):
    astronaut_id: Identifier | None = None
    mission_id: Identifier | None = None
    session_id: Identifier
    algorithm: Identifier
    idempotency_key: str = Field(min_length=1, max_length=128)
    input_ids: list[Identifier] = Field(min_length=1, max_length=5000)
    allowed_origins: list[Literal['real', 'manual', 'simulated']] = Field(default_factory=lambda: ['real', 'manual'], min_length=1, max_length=3)

    @model_validator(mode='after')
    def unique(self):
        if len(set(self.input_ids)) != len(self.input_ids) or len(set(self.allowed_origins)) != len(self.allowed_origins):
            raise ValueError('Duplicate inputs or origins')
        return self


class ScienceResult(StrictModel):
    """Envelope only: scientific result semantics must be supplied by Backend #3."""
    algorithm_version: str = Field(min_length=1, max_length=64)
    status: Literal['ok', 'insufficient_data']
    result: dict

    @model_validator(mode='after')
    def bounded(self):
        AnalysisSave.result_size(self.result)
        return self

class DevicePatch(StrictModel):
    name: str = Field(min_length=1,max_length=80)
