import type { AetherApi } from './types';
import type * as T from './types';

export class ApiError extends Error {
  constructor(public status: number, message: string, public path: string) {
    super(message);
    this.name = 'ApiError';
  }
  get isNetwork() { return this.status === 0; }
}

function describe(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => {
      const e = d as { loc?: (string | number)[]; msg?: string };
      return `${(e.loc ?? []).filter((x) => x !== 'body').join('.')}: ${e.msg ?? 'invalid'}`;
    }).join('; ');
  }
  return 'Request failed';
}

/** Single HTTP client for the FastAPI backend (or the stdlib fallback server). */
export function createHttpApi(base: string): AetherApi {
  async function request<R>(path: string, init?: RequestInit): Promise<R> {
    let response: Response;
    try {
      response = await fetch(`${base}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) } });
    } catch {
      throw new ApiError(0, `Cannot reach the AETHER backend at ${base}`, path);
    }
    if (!response.ok) {
      let msg = response.statusText || 'Request failed';
      try { msg = describe(((await response.json()) as { detail?: unknown }).detail); } catch { /* not json */ }
      if (response.status === 404 && msg === 'Not Found') msg = 'This endpoint is not available on the connected backend (requires API v0.2).';
      throw new ApiError(response.status, msg, path);
    }
    return response.json() as Promise<R>;
  }
  const post = <R>(path: string, body: unknown) => request<R>(path, { method: 'POST', body: JSON.stringify(body) });
  const del = <R>(path: string) => request<R>(path, { method: 'DELETE' });
  const enc = encodeURIComponent;
  return {
    mode: 'live',
    health: () => request<T.Health>('/api/health'),
    astronauts: () => request<T.Astronaut[]>('/api/astronauts'),
    timeline: (id, day) => request<T.Measurement[]>(`/api/astronauts/${encodeURIComponent(id)}/timeline?day=${day}`),
    saveMeasurement: (id, m) => post(`/api/astronauts/${encodeURIComponent(id)}/measurements`, m),
    phantom: (id, day) => request<T.Analysis>(`/api/phantom/${encodeURIComponent(id)}?day=${day}`),
    phantomHistory: (id, day, start = 41) => request<T.PhantomHistory>(`/api/phantom/${encodeURIComponent(id)}/history?day=${day}&start=${start}`),
    correlations: (id, day, window = 30) => request<T.Correlations>(`/api/phantom/${encodeURIComponent(id)}/correlations?day=${day}&window=${window}`),
    symbiosis: (day) => request<T.CabinEnvironment>(`/api/symbiosis?day=${day}`),
    zoneHistory: (zone, start, end) => request<T.ZoneHistory>(`/api/symbiosis/history?zone=${zone}&start=${start}&end=${end}`),
    ship: (day, hour) => request<T.ShipState>(`/api/ship?day=${day}&hour=${hour}`),
    crew: (reduce = false) => request<T.CrewResponse>(`/api/co-orbit?reduce_a01=${reduce}`),
    calendar: (day) => request<T.CrewCalendar>(`/api/co-orbit/calendar?day=${day}`),
    plan: (req) => post<T.Schedule>('/api/co-orbit/plan', req),
    scenarios: () => request<T.Scenario[]>('/api/mission-lab/scenarios'),
    simulate: (req) => post<T.SimulationResult>('/api/mission-lab/run', req),
    project: (req) => post<T.Projection>('/api/mission-lab/project', req),
    recovery: (id) => request<T.RecoverySession[]>(`/api/recovery/sessions/${encodeURIComponent(id)}`),
    saveRecovery: (s) => post('/api/recovery/sessions', s),
    environmentAssociation: (day, zone) => request<T.EnvironmentAssociation>(`/api/symbiosis/crew-association?day=${day}&zone=${zone}`),
    biofeedback: (id) => request<T.BiofeedbackFrame>(`/api/recovery/biofeedback?astronaut_id=${encodeURIComponent(id)}`),
    experiments: () => request<T.SavedExperiment[]>('/api/mission-lab/experiments'),
    saveExperiment: (e) => post('/api/mission-lab/experiments', e),
    deleteExperiment: (id) => del(`/api/mission-lab/experiments/${enc(id)}`),
    engineTemplates: () => request<T.EngineTemplate[]>('/api/engine/templates'),
    engineRun: (req) => post<T.EngineRun>('/api/engine/runs', req),
    engineGet: (id) => request<T.EngineRun>(`/api/engine/runs/${enc(id)}`),
    engineControl: (id, action, value = 0) => post<T.EngineState>(`/api/engine/runs/${enc(id)}/control`, { action, value }),
    engineCompare: (a, b) => post<T.EngineComparison>('/api/engine/compare', { a, b }),
    engineCoorbit: (id) => request<T.CoorbitRecommendations>(`/api/engine/runs/${enc(id)}/coorbit`),
    engineCoorbitApply: (id, body) => post<T.CoorbitDecision>(`/api/engine/runs/${enc(id)}/coorbit/apply`, body),
    phantom2: (id, day) => request<T.Phantom2Daily>(`/api/phantom2/${enc(id)}?day=${day}`),
    scienceEvidence: () => request<T.EvidenceLibrary>('/api/science/evidence'),
    scienceHazards: () => request<T.HazardsResponse>('/api/science/hazards'),
    scienceGraph: (p) => post<T.HazardGraph>('/api/science/graph', p),
    radiationPresets: () => request<T.RadiationPresets>('/api/science/radiation/presets'),
    radiation: (req) => post<T.RadiationResult>('/api/science/radiation', req),
    engineSymbiosis: (id, e, m, c) => request<T.SymbiosisAnalytics>(`/api/engine/runs/${enc(id)}/symbiosis?env_metric=${enc(e)}&metric=${enc(m)}&crew_id=${c}`),
    compareConditions: (body) => post<T.ConditionComparison>('/api/symbiosis/compare-conditions', body),
    engineReplan: (id, body) => post<T.ReplanResult>(`/api/engine/runs/${enc(id)}/replan`, body),
    engineCoorbitReject: (id, body) => post<T.CoorbitRejection>(`/api/engine/runs/${enc(id)}/coorbit/reject`, body),
    engineEnvironment: (id, p = 760) => request<T.EnvironmentAnalysis>(`/api/engine/runs/${enc(id)}/environment?cabin_pressure_mmhg=${p}`),
  };
}
