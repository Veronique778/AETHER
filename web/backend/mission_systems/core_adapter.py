"""Loss-aware bridge to the original, unchanged AETHER dataclass contracts."""
try:  # original Kivy V2 CORE (legacy/kivy_v2_mission_systems/core)
    from core.module_contracts import Measurement
except ImportError:  # integrated AETHER backend: identical dataclass, kept local so the bridge works standalone
    from dataclasses import dataclass
    from datetime import datetime
    from typing import Optional

    @dataclass
    class Measurement:
        metric: str
        value: float
        unit: str
        origin: str
        timestamp: datetime
        crew_id: Optional[int] = None
from .contracts import Reading


def to_core_measurements(readings):
    result=[];rejected=[]
    for raw in readings:
        r=Reading.model_validate(raw)
        if r.quality!='valid' or r.value is None:
            rejected.append(r.model_dump(mode='json'));continue
        item=Measurement(metric=r.metric,value=r.value,unit=r.unit,origin=r.origin,
                         timestamp=r.timestamp,crew_id=r.crew_id)
        result.append({'measurement':item,'metadata':{'source_id':r.source_id,'zone_id':r.zone_id,
                       'sensor_id':r.sensor_id,'quality':r.quality,'model_version':r.model_version,'processing':r.processing}})
    return {'items':result,'rejected':rejected}
