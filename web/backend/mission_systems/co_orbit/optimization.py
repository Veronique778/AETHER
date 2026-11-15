from copy import deepcopy
from ..contracts import PlanningInput, Crew, Task, PhantomResult
from .scheduler import solve, baseline_schedule, metrics, is_valid


def alternatives(plan):
    first=solve(plan,'earliest');second=solve(plan,'balanced')
    same=first['assignments']==second['assignments']
    if not first['valid'] and not second['valid']:
        explanation='No feasible schedule: '+second['reason']
    elif same:
        explanation='Both objectives selected the same schedule; constraints may leave no useful alternative.'
    else:
        explanation='Earlier starts versus lower maximum weighted crew load.'
    return {'baseline':baseline_schedule(plan),'alternatives':[first,second],
            'identical':same,'explanation':explanation,
            'has_feasible_solution':first['valid'] or second['valid'],
            # index of the schedule to use: balanced (1) unless only the earliest-start strategy found a valid one
            'preferred':1 if second['valid'] or not first['valid'] else 0}


def preferred(alts):
    """The schedule a caller should use from alternatives(): a valid one whenever one exists."""
    rows=alts['alternatives']
    return rows[alts.get('preferred',1)] if 'preferred' in alts else rows[1]


def dropped_tasks(before, after, plan=None):
    """Tasks scheduled in `before` that are missing from `after` – reported explicitly, never silently."""
    titles={t.id:t.title for t in plan.tasks} if plan is not None else {}
    reasons={u['task_id']:u.get('reason','') for u in after.get('unscheduled',[]) if isinstance(u,dict)}
    kept={a['task_id'] for a in after.get('assignments',[])}
    return [{'task_id':a['task_id'],'title':titles.get(a['task_id'],a['task_id']),'reason':reasons.get(a['task_id'],'')}
            for a in before.get('assignments',[]) if a['task_id'] not in kept]


def replan(plan, *, crew_updates=None, task_updates=None, equipment_updates=None):
    data=plan.model_dump()
    for key,updates in [('crew',crew_updates),('tasks',task_updates),('equipment',equipment_updates)]:
        for item in updates or []:
            existing=next((x for x in data[key] if x['id']==item['id']),None)
            if existing is None:data[key].append(item)
            else:existing.update(item)
    updated=PlanningInput.model_validate(data)
    return updated,alternatives(updated)


def apply_permitted_availability(plan, results):
    data=deepcopy(plan.model_dump());ids={c['id'] for c in data['crew']}
    for raw in results:
        r=PhantomResult.model_validate(raw)
        if r.unavailable and not r.planning_authorized:
            raise ValueError('PHANTOM planning projection is not authorized')
        for cid,windows in r.unavailable.items():
            if cid not in ids:raise ValueError('Unknown crew in PHANTOM projection')
            c=next(c for c in data['crew'] if c['id']==cid)
            all_windows=c['rest']+[w.model_dump() for w in windows]
            merged=[]
            for w in sorted(all_windows,key=lambda w:w['start']):
                if merged and w['start']<=merged[-1]['end']:merged[-1]['end']=max(merged[-1]['end'],w['end'])
                else:merged.append(w.copy())
            c['rest']=merged
    return PlanningInput.model_validate(data)


def compare(plan, before, after):
    a=metrics(plan,before);b=metrics(plan,after)
    return {'before':a,'after':b,'delta':{k:b[k]-a[k] for k in ['total_work_minutes','load_std','max_load','conflicts','high_priority_completed','priority_score']}}


def commit_if_valid(store, key, updated_plan, result):
    """Persist a re-planned plan + schedules only when a validated feasible schedule exists (B1.4).

    On failure nothing is written: the previously stored plan and schedules stay in force."""
    best=preferred(result)
    if not best['valid']:
        return {'persisted':False,'valid':False,'reason':best.get('reason',''),'previous_schedule_preserved':True}
    store.save('planning',key,updated_plan);store.save('schedules',key,result)
    return {'persisted':True,'valid':True,'reason':best.get('reason',''),'previous_schedule_preserved':False}
