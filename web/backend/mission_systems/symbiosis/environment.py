"""Environment ingestion, history and visualization payloads; no actuator control."""
from datetime import datetime, timedelta, timezone
from ..contracts import Reading, Environment, MODEL_VERSION

ENV_UNITS={'temperature':'degC','humidity':'%','co2':'ppm','light':'lux'}


def sample_environment(config: Environment, timestamp: datetime, *, source_id='mission_lab', changes=0):
    hour=timestamp.hour+timestamp.minute/60
    daylight=config.lights_on_hour<=hour<config.lights_off_hour
    values={'temperature':min(35,config.temperature+changes*2),
            'humidity':min(95,config.humidity+changes*3),
            'co2':min(10000,config.co2+changes*700),
            'light':config.light if daylight else min(1000,config.night_light+changes*30)}
    return [Reading(metric=m,value=v,unit=ENV_UNITS[m],timestamp=timestamp,
                    origin='synthetic',source_id=source_id,zone_id=config.zone_id,
                    model_version=MODEL_VERSION,processing=['deterministic environment model']) for m,v in values.items()]


class EnvironmentService:
    def __init__(self,store):self.store=store

    def ingest(self, readings):return self.store.readings(readings)

    def history(self, zone_id, **kwargs):return self.store.history(zone_id,**kwargs)

    def state(self, zone_id, *, as_of=None, stale_minutes=120, origin=None):
        as_of=as_of or datetime.now(timezone.utc)
        if as_of.tzinfo is None:raise ValueError('as_of requires timezone')
        as_of=as_of.astimezone(timezone.utc)
        rows=self.store.history(zone_id,end=as_of,origin=origin,limit=100000)
        latest={}
        # Keep origins AND sources separate. Never silently replace real with synthetic.
        for raw in rows:
            r=Reading.model_validate(raw)
            key=(r.metric,r.origin,r.source_id)
            latest[key]=r
        values=[]
        for r in latest.values():
            d=r.model_dump(mode='json')
            if r.quality=='valid' and as_of-r.timestamp>timedelta(minutes=stale_minutes):d['quality']='stale'
            values.append(d)
        present={r['metric'] for r in values}
        return {'zone_id':zone_id,'as_of':as_of.isoformat(),'readings':values,
                'missing_metrics':sorted(set(ENV_UNITS)-present),'actuation':False,
                'visualization':{'zone_id':zone_id,'parameters':values,'display_source_and_quality':True}}
