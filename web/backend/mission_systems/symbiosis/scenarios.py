"""Explicit educational response model; coefficients are not fitted to astronaut data."""
from ..contracts import Environment, MODEL_VERSION

LIMITATION=('Illustrative sensitivity model, not a validated physiological forecast. '
            'Intervals are coefficient-sensitivity ranges, not statistical confidence intervals.')


def effects(environment: Environment, sleep_hours=8, rest_hours=0, workload_hours=6, sensitivity=1):
    temperature=abs(environment.temperature-22)*.5
    co2=max(0,environment.co2-1000)/1000
    night_light=environment.night_light/50
    humidity=max(0,abs(environment.humidity-45)-15)/20
    sleep_debt=max(0,8-sleep_hours)
    fatigue=max(0,min(10,2+sensitivity*(sleep_debt*.8+workload_hours*.22+co2*.35+temperature*.15+humidity*.2-rest_hours*.5)))
    quality=max(0,min(100,88-sensitivity*(temperature*3+night_light*3+sleep_debt*3+humidity*2)+rest_hours*2))
    cognition=max(0,min(100,92-sensitivity*(fatigue*2+co2*3+sleep_debt*2)))
    return {'sleep_quality':quality,'fatigue':fatigue,'cognition':cognition}


def compare_conditions(a:Environment,b:Environment, *, sleep_a=8,sleep_b=8,rest_a=0,rest_b=0,workload=6):
    for x in (sleep_a,sleep_b,rest_a,rest_b,workload):
        if not 0<=x<=24:raise ValueError('Hours must be within 0..24')
    av=effects(a,sleep_a,rest_a,workload);bv=effects(b,sleep_b,rest_b,workload)
    bounds={}
    for key in bv:
        values=[effects(b,sleep_b,rest_b,workload,s)[key] for s in (.75,1.25)]
        bounds[key]={'low':min(values),'high':max(values)}
    recommendations=[]
    if bv['fatigue']<av['fatigue']:recommendations.append('Consider scenario B in simulation: its modeled fatigue is lower.')
    if bv['sleep_quality']>av['sleep_quality']:recommendations.append('Consider the sleep/light/temperature changes in B for human review.')
    if not recommendations:recommendations.append('No improvement on the selected model criteria; compare other settings.')
    return {'a':av,'b':bv,'delta':{k:bv[k]-av[k] for k in av},'sensitivity_range_b':bounds,
            'recommendations':recommendations,'origin':'estimated','model_version':MODEL_VERSION,
            'limitations':[LIMITATION],'human_review_required':True,'actuation':False}
