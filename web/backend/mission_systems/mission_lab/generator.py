"""Seeded correlated trajectories. Ground truth is kept separate from PHANTOM inputs."""
from datetime import timedelta
from hashlib import sha256
import json
from datetime import datetime
import numpy as np
from ..contracts import Baseline, Reading, Scenario, MODEL_VERSION, Environment
from ..symbiosis.environment import sample_environment
from ..symbiosis.scenarios import effects, LIMITATION

UNITS={'heart_rate':'bpm','sleep_hours':'h','sleep_quality':'score_0_100','activity':'min/day',
       'fatigue':'score_0_10','cognition':'score_0_100','workload':'h/day'}
BOUNDS={'heart_rate':(35,180),'sleep_hours':(0,12),'sleep_quality':(0,100),'activity':(0,240),
        'fatigue':(0,10),'cognition':(0,100),'workload':(0,24)}


def event_strength(event,minute,global_intensity):
    if minute<event.minute:return 0.0
    fraction=1 if not event.ramp_minutes else min(1,(minute-event.minute)/event.ramp_minutes)
    return fraction*event.intensity*global_intensity


def generate(scenario:Scenario, schedule=None):
    scenario=Scenario.model_validate(scenario)
    def canonical(value):
        if isinstance(value, dict): return {str(k):canonical(v) for k,v in value.items()}
        if isinstance(value, set): return sorted(canonical(v) for v in value)
        if isinstance(value, (list,tuple)): return [canonical(v) for v in value]
        if isinstance(value, datetime): return value.isoformat()
        return value
    fingerprint=sha256(json.dumps(canonical(scenario.model_dump()),sort_keys=True).encode()).hexdigest()[:20]
    rng=np.random.default_rng(scenario.seed);previous={};correlated_noise={};frames=[];truth=[]
    tasks={t.id:t for t in scenario.planning.tasks}
    rows=(schedule or {}).get('assignments',[])
    # Planning horizon is replayed periodically during longer mission experiments.
    for minute in range(0,scenario.duration_minutes+1,scenario.sample_minutes):
        timestamp=scenario.start+timedelta(minutes=minute)
        active=[(e,event_strength(e,minute,scenario.intensity)) for e in scenario.events]
        env_change=sum(s for e,s in active if e.kind in ('environment','multifactor'))
        env=sample_environment(scenario.environment,timestamp,source_id='sim:'+fingerprint,changes=env_change)
        env_values={r.metric:r.value for r in env}
        changed_env=scenario.environment.model_copy(update={k:env_values[k] for k in ('temperature','humidity','co2')})
        measurements=[];sample_ids=[]
        for crew in scenario.planning.crew:
            base=scenario.baselines.get(crew.id,Baseline())
            strengths={}
            for e,s in active:
                if e.crew_id is None or e.crew_id==crew.id:strengths[e.kind]=strengths.get(e.kind,0)+s
            multi=strengths.get('multifactor',0)
            phase=minute%scenario.planning.horizon_minutes;day_start=phase//1440*1440;day_end=day_start+1440
            assigned=sum(max(0,min(a['end'],day_end)-max(a['start'],day_start))/60 for a in rows if crew.id in a['crew_ids'])
            working=any(crew.id in a['crew_ids'] and a['start']<=phase<a['end'] for a in rows)
            rest_minutes=sum(max(0,min(w.end,day_end)-max(w.start,day_start)) for w in crew.rest)
            rest=scenario.extra_rest_hours+rest_minutes/60
            sleep=max(0,min(12,base.sleep_hours+scenario.sleep_hours-8-1.6*(strengths.get('sleep_loss',0)+multi)+rest*.2))
            workload=min(24,scenario.workload_hours+assigned+2*(strengths.get('workload_rise',0)+multi))
            effect=effects(changed_env,sleep,rest,workload)
            previous_fatigue=previous.get((crew.id,'fatigue'),base.fatigue)
            targets={'sleep_hours':sleep,'sleep_quality':effect['sleep_quality']+base.sleep_quality-88,
                     'workload':workload,
                     'fatigue':effect['fatigue']+base.fatigue-2+2*(strengths.get('fatigue_rise',0)+multi),
                     'heart_rate':base.heart_rate+previous_fatigue*.7+(8 if working else 0)+8*(strengths.get('pulse_shift',0)+multi),
                     'activity':base.activity+assigned*5+ (10 if working else 0)-rest*4,
                     'cognition':effect['cognition']+base.cognition-92-12*(strengths.get('cognitive_decline',0)+multi)}
            sample_id=sha256(f'{fingerprint}:{minute}:{crew.id}'.encode()).hexdigest()[:24];sample_ids.append(sample_id)
            corrupted=[];missing=[]
            for metric,target in targets.items():
                key=(crew.id,metric)
                # Exponential response with a two-hour time constant.
                alpha=1-np.exp(-scenario.sample_minutes/120)
                value=previous.get(key,target)+alpha*(target-previous.get(key,target));previous[key]=value
                noise_scale=scenario.noise*(1+strengths.get('noise',0)*4)
                jitter=.7*correlated_noise.get(key,0)+rng.normal(0,noise_scale)
                correlated_noise[key]=jitter
                scale=.15 if metric in ('sleep_hours','fatigue','workload') else 1
                value=float(np.clip(value+jitter*scale,*BOUNDS[metric]));quality='valid'
                if rng.random()<min(.8,strengths.get('missing',0)*.35):quality='missing';value=None;missing.append(metric)
                elif rng.random()<min(.8,strengths.get('corrupt',0)*.25):quality='invalid';value=None;corrupted.append(metric)
                measurements.append(Reading(metric=metric,value=value,unit=UNITS[metric],timestamp=timestamp,
                         origin='synthetic',source_id='sim:'+fingerprint,crew_id=crew.id,quality=quality,
                         model_version=MODEL_VERSION,processing=['correlated trajectory','input plausibility bounds']).model_dump(mode='json'))
            anomaly_kinds=[k for k,v in strengths.items() if v>=.25 and k not in ('missing','corrupt','noise')]
            # 1.0 (B4 audit): separate the injected crew-level physiological change from cabin exposure. The cabin
            # (environment / multifactor events) changes for EVERY crew member, while `anomaly` labels only the
            # event's crew_id - so equal modelled effects were labelled differently across templates.
            physio_kinds=[k for k in anomaly_kinds if k!='environment']
            truth.append({'sample_id':sample_id,'anomaly':bool(anomaly_kinds),'injected_changes':anomaly_kinds,
                          'physiological_change':bool(physio_kinds),'physiological_kinds':physio_kinds,
                          'environment_exposure':bool(env_change>=.25),
                          'missing_metrics':missing,'invalid_metrics':corrupted,'crew_id':crew.id,'minute':minute,
                          'definition':'Injected event strength >= 0.25; not a clinical diagnosis. '
                                       'physiological_change: crew-level injected change (excl. cabin environment); '
                                       'environment_exposure: shared cabin change >= 0.25 (affects all crew).'})
        frames.append({'minute':minute,'mission_day':scenario.mission_day+minute//1440,
                       'environment_event':bool(env_change>=.25),
                       'timestamp':timestamp.isoformat(),'sample_ids':sample_ids,
                       'environment':[r.model_dump(mode='json') for r in env], 'measurements':measurements,
                       'events':[{'kind':e.kind,'strength':s,'crew_id':e.crew_id} for e,s in active if s>0]})
    return {'scenario_id':scenario.id,'seed':scenario.seed,'model_version':MODEL_VERSION,'origin':'synthetic',
            'frames':frames,'ground_truth':truth,'limitations':[LIMITATION,
            'Bounds are model guardrails, not clinical reference intervals. Sleep/activity/workload are rolling daily indicators.']}
