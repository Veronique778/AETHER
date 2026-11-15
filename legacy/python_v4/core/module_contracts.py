"""Shared contracts between modules. Keep these stable as modules evolve."""
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

DataOrigin = Literal["real", "estimated", "synthetic"]

@dataclass
class Measurement:
    metric: str
    value: float
    unit: str
    origin: DataOrigin
    timestamp: datetime
    crew_id: Optional[int] = None

@dataclass
class AnalysisResult:
    metric: str
    status: str
    summary: str
    confidence: Optional[float] = None
    timestamp: Optional[datetime] = None
