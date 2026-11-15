export type View = 'overview' | 'body' | 'phantom' | 'symbiosis' | 'co-orbit' | 'recovery' | 'mission-lab';
export type MetricKey = 'heart_rate_bpm' | 'sleep_hours' | 'fatigue_1_10' | 'reaction_ms' | 'activity_minutes';
export type Measurement = {astronaut_id:string; day:number; source:string} & Record<MetricKey, number>;
export type Astronaut = {id:string;name:string;role:string};
export type Signal = { key:MetricKey;label:string;unit:string;value:number;baseline:number;deviation:number;flagged:boolean};
export type Analysis = {status:'normal'|'attention'|'insufficient';score:number|null;data_quality:string;uncertainty:string;signals:Signal[];flagged_count:number;multi_signal_pattern:boolean;explanation:string;next_measurements:string[];source:string;disclaimer:string};
export type Environment = {day:number; co2_ppm:number; temperature_c:number;humidity_pct:number;light_lux:number;source:string;note:string};
export type Crew = {id:string;name:string;skills:string[];capacity:number};
export type Assignment = {id:string;title:string;skill:string;hours:number;priority:number;astronaut_id:string|null};
export type Schedule = {assignments:Assignment[];loads:Record<string,number>;capacity:Record<string,number>;unassigned:number;method:string;source:string};
export type CrewResponse = {crew:Crew[];schedule:Schedule};
export type Scenario = {id:string;title:string;detail:string;sleep_delta:number;workload:number;co2_ppm:number;temperature_c:number};
export type SimulationResult = {day:number;input:Omit<Scenario,'id'|'title'|'detail'>;metrics:Record<MetricKey,number>;phantom:Analysis;environment:{co2_ppm:number;temperature_c:number};crew:Schedule;source:string;assumptions:string};
export type RecoverySession = {id:number;astronaut_id:string;activity:string;before_mood:number;after_mood:number;duration_seconds:number;created_at:string};

const BASE = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000';
async function request<T>(path:string, init?:RequestInit):Promise<T> {
 const response=await fetch(`${BASE}${path}`,{...init,headers:{'Content-Type':'application/json', ...(init?.headers ?? {})}});
 if(!response.ok){let msg='Request failed';try {const detail=await response.json();msg=JSON.stringify(detail.detail ?? detail);}catch{}throw new Error(`${response.status}: ${msg}`);}
 return response.json() as Promise<T>;
}
export const api={
 astronauts:()=>request<Astronaut[]>('/api/astronauts'),
 timeline:(id:string,day=67)=>request<Measurement[]>(`/api/astronauts/${id}/timeline?day=${day}`),
 phantom:(id:string,day=67)=>request<Analysis>(`/api/phantom/${id}?day=${day}`),
 symbiosis:(day=67)=>request<Environment>(`/api/symbiosis?day=${day}`),
 crew:(reduce=false)=>request<CrewResponse>(`/api/co-orbit?reduce_a01=${reduce}`),
 scenarios:()=>request<Scenario[]>('/api/mission-lab/scenarios'),
 simulate:(data:Record<string,string|number>)=>request<SimulationResult>('/api/mission-lab/run',{method:'POST',body:JSON.stringify(data)}),
 recovery:(id:string)=>request<RecoverySession[]>(`/api/recovery/sessions/${id}`),
 saveRecovery:(data:Record<string,string|number>)=>request<{id:number;saved:boolean}>('/api/recovery/sessions',{method:'POST',body:JSON.stringify(data)}),
};
export const metricInfo: Record<MetricKey, {label:string;unit:string;short:string}> = {
 heart_rate_bpm:{label:'Resting heart rate',unit:'bpm',short:'Heart rate'},
 sleep_hours:{label:'Sleep duration',unit:'hours',short:'Sleep'},
 fatigue_1_10:{label:'Perceived fatigue',unit:'/10',short:'Fatigue'},
 reaction_ms:{label:'Reaction time',unit:'ms',short:'Reaction'},
 activity_minutes:{label:'Activity',unit:'min',short:'Activity'},
};
