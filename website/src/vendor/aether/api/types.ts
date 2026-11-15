/**
 * AETHER API contract (v0.2). Mirrors web/backend/app (pydantic + service.py).
 * Both the HTTP client and the in-browser demo adapter implement `AetherApi`.
 */

export const METRIC_KEYS = ['heart_rate_bpm', 'sleep_hours', 'fatigue_1_10', 'reaction_ms', 'activity_minutes'] as const;
export type MetricKey = (typeof METRIC_KEYS)[number];

/** simulated = synthetic seed / model output · manual = entered by a person · estimated = derived by a model from other data */
export type DataSource = 'simulated' | 'manual' | 'estimated' | 'sensor' | 'research_prototype' | 'reference';

export type Astronaut = { id: string; name: string; role: string };
export type Measurement = { astronaut_id: string; day: number; source: DataSource } & Record<MetricKey, number | null>;
export type MeasurementInput = { day: number } & Partial<Record<MetricKey, number | null>>;

export type PhantomStatus = 'normal' | 'attention' | 'insufficient';
export type Signal = {
  key: MetricKey; label: string; unit: string; value: number; baseline: number; scale: number;
  deviation: number; adverse_deviation: number; flagged: boolean;
};
export type PhantomMethod = { name: string; baseline_window: string; flag_threshold_z: number; steps: string[]; limitations: string[] };
export type Analysis = {
  day: number; status: PhantomStatus; score: number | null; data_quality: string;
  uncertainty: 'low' | 'medium' | 'high'; signals: Signal[]; flagged_count: number;
  multi_signal_pattern: boolean; explanation: string; next_measurements: string[];
  source: DataSource; current_source: DataSource | null; baseline_days?: number;
  method: PhantomMethod; disclaimer: string;
};
export type PhantomPoint = { day: number; status: PhantomStatus; score: number | null; flagged: MetricKey[]; source?: DataSource };
export type PhantomAlert = { start_day: number; end_day: number; peak_score: number; signals: MetricKey[]; ongoing: boolean; label: string };
export type PhantomHistory = { points: PhantomPoint[]; alerts: PhantomAlert[]; source: DataSource };
export type CorrelationCell = { a: MetricKey; b: MetricKey; rho: number | null; n: number };
export type Correlations = { day: number; window_days: number; method: string; metrics: MetricKey[]; matrix: CorrelationCell[]; note: string; source: DataSource };

export type ZoneId = 'command' | 'habitat' | 'medical' | 'exercise' | 'systems';
export type EnvStatus = 'nominal' | 'attention' | 'high';
export type CabinEnvironment = { day: number; co2_ppm: number; temperature_c: number; humidity_pct: number; light_lux: number; source: DataSource; note: string };
export type ZoneEnvironment = {
  zone: ZoneId; day: number; hour: number; co2_ppm: number; temperature_c: number; humidity_pct: number;
  light_lux: number; occupants: number; status: EnvStatus; source: DataSource;
};
export type ModuleRoute = 'co-orbit' | 'body' | 'phantom' | 'recovery' | 'symbiosis';
export type Zone = { id: ZoneId; name: string; module: ModuleRoute; volume_m3: number; description: string; environment: ZoneEnvironment };
export type ReferenceBands = {
  co2_ppm: { attention: number; high: number; unit: string };
  temperature_c: { low: number; high: number; unit: string };
  humidity_pct: { low: number; high: number; unit: string };
  light_lux: { unit: string };
  note: string;
};
export type Availability = 'resting' | 'on task' | 'exercise' | 'available' | 'check-in';
export type CrewLocation = {
  id: string; name: string; zone: ZoneId; activity: string; availability: Availability;
  reduced_load_suggested: boolean; location_source: 'schedule';
};
export type ShipState = { day: number; hour: number; zones: Zone[]; crew: CrewLocation[]; reference: ReferenceBands; source: DataSource; note: string };
export type ZoneHistory = { zone: ZoneId; points: ZoneEnvironment[]; source: DataSource };

export type Skill = 'command' | 'science' | 'engineering' | 'medical';
export type CrewMember = { id: string; name: string; skills: Skill[]; capacity: number; home_zone: ZoneId };
export type Task = { id: string; title: string; skill: Skill; hours: number; priority: 1 | 2 | 3; zone?: ZoneId | null };
export type Assignment = Task & { astronaut_id: string | null };
export type Schedule = {
  assignments: Assignment[]; loads: Record<string, number>; capacity: Record<string, number>; unassigned: number;
  method: string; source: DataSource; peak_utilisation?: number; greedy_peak_utilisation?: number; local_search_moves?: number;
};
export type CrewResponse = { crew: CrewMember[]; schedule: Schedule };
export type BlockKind = 'sleep' | 'work' | 'exercise' | 'meal' | 'personal' | 'health';
export type CalendarBlock = { start: number; end: number; kind: BlockKind; title: string; zone: ZoneId };
export type CrewCalendar = { day: number; blocks: Record<string, CalendarBlock[]>; source: DataSource };
export type PlanRequest = { tasks?: Task[]; capacity?: Record<string, number>; unavailable?: string[]; optimise?: boolean };

export type ScenarioParams = { sleep_delta: number; workload: number; co2_ppm: number; temperature_c: number; crew_available: number };
export type Scenario = ScenarioParams & { id: string; title: string; detail: string };
export type SimulationRequest = ScenarioParams & { astronaut_id: string; day: number };
export type SimulationResult = {
  day: number; input: ScenarioParams; metrics: Record<MetricKey, number>; phantom: Analysis;
  environment: { co2_ppm: number; temperature_c: number }; crew: Schedule; source: DataSource; assumptions: string;
};
export type Band = { p10: number; p50: number; p90: number };
export type ProjectionDay = { day: number; attention_share: number; score: Band } & Record<MetricKey, Band>;
export type ProjectionRequest = ScenarioParams & { astronaut_id: string; start_day: number; horizon_days: number; runs?: number; seed?: number };
export type Projection = {
  start_day: number; horizon_days: number; runs: number; seed: number; input: ScenarioParams;
  derived: { planned_sleep_h: number; sleep_deficit_h: number; workload_index: number; environment_index: number; baseline: Record<MetricKey, number> };
  days: ProjectionDay[]; assumptions: string[]; source: DataSource; note: string;
};

export type RecoveryActivity = 'zero-g-garden' | 'earth-window' | 'orbit-flow' | 'mind-pulse';
export type SessionDetails = Record<string, number | string | boolean | null>;
export type RecoverySessionInput = {
  astronaut_id: string; activity: RecoveryActivity; before_mood: number; after_mood: number; duration_seconds: number; details?: SessionDetails;
};
export type RecoverySession = RecoverySessionInput & { id: number; created_at: string; details: SessionDetails };
/** GET /api/symbiosis/crew-association?day&zone (implemented in v0.8 – app.service.crew_association). */
export type EnvironmentAssociation = {
  day: number; zone: ZoneId; environment_metric: 'co2_ppm'; outcome_metric: MetricKey; method: string;
  rows: { astronaut_id: string; rho: number | null; n: number }[]; note: string; source: DataSource;
};
/** GET /api/recovery/biofeedback?astronaut_id – v0.8 serves a SIMULATED frame (no sensor connected); a sensor service can replace it. */
export type BiofeedbackFrame = {
  astronaut_id: string; t: string; breathing_rate_bpm: number | null; heart_rate_bpm: number | null;
  coherence_0_1: number | null; quality: 'good' | 'degraded' | 'none'; source: DataSource;
};
export type Health = {
  status: string;
  project: string;
  version?: string;
  release_version?: string;
  data: string;
  capabilities?: string[];
  mission_engine?: EngineStatus;
  api_contract_version?: string;
  personal_api_contract_version?: string;
};

/* ---- Saved MISSION LAB experiments (GET/POST/DELETE /api/mission-lab/experiments) ---- */
export type ExperimentEnd = { score_p50: number; score_p10: number; score_p90: number; attention_share: number; fatigue_p50: number };
export type SavedExperiment = {
  id: string; name: string; created_at: string; astronaut_id: string; start_day: number; horizon_days: number; runs: number; seed: number;
  scenarios: { key: string; title: string; params: ScenarioParams; end: ExperimentEnd }[];
};

/* ---- Mission Systems engine (web/backend/mission_systems via /api/engine/*) ---- */
export type EngineStatus = { available: boolean; error: string | null; engine_api_version: string | null; model_version: string | null; origin: 'synthetic'; provides: string[] };
export type EngineTemplate = { id: string; title: string; detail: string };
export type EngineRunRequest = {
  template: string; seed?: number; duration_minutes?: number; sample_minutes?: number; sleep_hours?: number; extra_rest_hours?: number;
  workload_hours?: number; intensity?: number; noise?: number; co2_ppm?: number; temperature_c?: number; humidity_pct?: number; light_lux?: number; phantom?: boolean;
  plan_profile?: PlanProfile;
};
export type PlanProfile = 'standard' | 'high_workload' | 'reduced_availability' | 'extended_rest';
export type EngineMetric = 'heart_rate' | 'sleep_hours' | 'sleep_quality' | 'activity' | 'fatigue' | 'cognition' | 'workload';
export type EngineEnvMetric = 'temperature' | 'humidity' | 'co2' | 'light';
export type EngineAssignment = { task_id: string; crew_ids: number[]; start: number; end: number };
/** API 1.0: unscheduled tasks are objects (they always were – the 0.9 type said string[]). */
export type UnscheduledTask = { task_id: string; title?: string; priority?: number; required?: boolean; reason: string };
/** API 1.0 solver status (docs/API_CONTRACTS.md). `optimal` = optimality proven; `feasible` = valid but not proven optimal. */
export type SolverStatus = 'optimal' | 'feasible' | 'infeasible' | 'time_limit_no_solution' | 'unbounded' | 'error' | 'invalid_output';
export type EngineStrategy = {
  strategy: string; status: string; assignments: EngineAssignment[]; unscheduled: UnscheduledTask[]; criteria?: string;
  solver_status?: SolverStatus; valid?: boolean; has_feasible_solution?: boolean; optimality_proven?: boolean; objective_value?: number | null;
  reason?: string; validation_errors?: string[]; required_tasks?: string[]; mip_gap?: number | null;
  metrics: { scheduled_tasks: number; priority_score: number; work_minutes: Record<string, number>; load_hours: Record<string, number>; total_work_minutes: number;
    load_std: number; max_load: number; conflicts: number; violations: string[]; rest_constraints_met: boolean };
};
export type Confusion = { tp: number; fp: number; tn: number; fn: number; precision: number | null; recall: number | null; f1: number | null; abstained: number; coverage: number; definition: string; limitation: string };
export type EngineEvaluation = { threshold: Confusion; phantom: Confusion | null; phantom_status: 'evaluated' | 'not_connected'; model_version: string; seed: number };
export type EngineState = { scenario_id: string; status: 'ready' | 'running' | 'paused' | 'finished'; minute: number; duration_minutes: number; speed: number; phantom_status: string; sample_policy: string; frame_minute: number };
export type EngineRun = {
  id: string; title: string; template: string; seed: number; mission_day: number; duration_minutes: number; sample_minutes: number;
  params: EngineRunRequest | null; origin: 'synthetic'; model_version: string;
  events: { minute: number; kind: string; intensity: number; crew_id: number | null; ramp_minutes: number }[];
  crew: { id: number; name: string; role: string; skills: string[] }[];
  times: number[]; series: Record<string, Record<EngineMetric, (number | null)[]>>; quality_gaps: Record<string, number[]>;
  environment: Record<EngineEnvMetric, (number | null)[]>; phantom_flags: Record<string, number[]>;
  schedules: { strategies: EngineStrategy[]; explanation: string; identical: boolean;
    tasks: { id: string; title: string; priority: number; duration_minutes: number; people: number; skills: string[]; dependencies: string[]; equipment: Record<string, number> }[];
    has_feasible_solution?: boolean };
  evaluation: EngineEvaluation; state: EngineState; bridge: ScenarioParams & { note: string }; limitations: string[];
  phantom2: { physiology: DetectorComparison; exposure_aware: DetectorComparison; flags: Record<string, number[]>; method: string; note: string;
    regimes?: Record<string, PhantomRegime>; states?: Record<PhantomState, number> };
  plan_profile: PlanProfile; plan_profile_detail: string;
};
export type DetectorName = 'zscore' | 'ewma' | 'adaptive' | 'cusum' | 'mahalanobis' | 'phantom2' | 'phantom2_v09';
export type PhantomState = 'flag' | 'no_flag' | 'insufficient_data';
/** API 1.0: noise regime of the PHANTOM 2.0 decision for one crew member (engine runs). */
export type PhantomRegime = { decision_rule: string; nu: number | null; regime: 'clean' | 'noisy'; nu_star: number; ewma_l_noisy: number; covariance: string };
export type DetectorScore = { tp: number; fp: number; tn: number; fn: number; precision: number | null; recall: number | null; f1: number | null; fpr: number | null; abstained: number };
export type DetectorComparison = { detectors: Partial<Record<DetectorName, DetectorScore>>; samples_scored: number; with_environment_channels: boolean; baseline: string;
  detectors_physiological_labels?: Partial<Record<DetectorName, DetectorScore>> | null; states?: Record<PhantomState, number> };

/* ---- PHANTOM → CO-ORBIT (human-approved constraints) ---- */
export type CoorbitRecommendation = {
  id: string; crew_id: number; crew_name: string; kind: 'reduce_workload' | 'protected_rest' | 'shorter_blocks'; summary: string;
  flagged_share: number; signals: { metric: string; mean_unfavourable_z: number }[]; reason: string; requires_human_approval: true; evidence_level: string;
  environment_context?: { environment_stressor: boolean; stressor_kinds: string[]; statement: string; evidence: string } | null;
};
export type CoorbitRecommendations = { run_id: string; recommendations: CoorbitRecommendation[]; rules: Record<string, string>; policy: string; environment_context?: CrewEnvironmentContext[] };
export type DecisionStatus = 'proposal_ready' | 'rejected_no_feasible_schedule';
export type DroppedTask = { task_id: string; title: string; reason: string };
/** Fields shared by coorbit/apply and replan responses in API 1.0. */
export type ProposalOutcome = {
  valid: boolean; decision_status?: DecisionStatus; reason?: string; applied?: false; previous_schedule_preserved?: boolean;
  proposal?: EngineStrategy; dropped_tasks?: DroppedTask[]; requires_review?: boolean; next_actions?: string[];
};
export type CoorbitDecision = ProposalOutcome & {
  approved_by: string; approved_at: string; note: string; approved: CoorbitRecommendation[]; constraints: Record<string, unknown>[];
  before: EngineStrategy; after: EngineStrategy; policy: string;
  comparison: { changes: { task_id: string; change: string }[]; explanations: string[]; metrics_before: EngineStrategy['metrics']; metrics_after: EngineStrategy['metrics'];
    delta: Record<string, number>; work_minutes_before: Record<string, number>; work_minutes_after: Record<string, number> };
};

/* ---- PHANTOM 2.0 on the daily record (GET /api/phantom2/{id}?day) ---- */
export type Phantom2Daily = {
  astronaut_id: string; day: number; status: 'ok' | 'insufficient_baseline'; detail?: string; origin: 'synthetic'; baseline_window: string;
  today: Partial<Record<DetectorName, boolean | null>>;
  today_state?: PhantomState;
  decision_rule?: { rule: string; note: string; baseline_noise_index: number | null; covariance: string };
  multivariate: { d2: number | null; threshold: number | null; df: number | null; attribution: Record<string, number> | null;
    uncertainty: { flag_probability: number; d2_interval_90: [number, number]; bootstrap_replicates: number } | null };
  cusum: Record<string, { S: number; alarm: boolean; start_index: number | null }> | null; cusum_change_start_day: Record<string, number>;
  z: Record<string, number> | null; autocorrelation: Record<string, number>;
  next_best_measurement: { metric: string; p_decision_change: number; expected_z: number; conditional_sd: number }[];
  series: ({ day: number; d2: number | null; threshold: number | null; state?: PhantomState } & Partial<Record<DetectorName, boolean | null>>)[];
  labels: Record<string, { label: string; unit: string }>; method: string; parameters: Record<string, number>; references: string[]; limitations: string[];
};
export type EngineControlAction = 'start' | 'pause' | 'resume' | 'reset' | 'seek' | 'speed' | 'tick';
export type EngineComparison = {
  delta_means: Record<string, number>; same_seed: boolean; note: string;
  schedule_a: EngineStrategy['metrics']; schedule_b: EngineStrategy['metrics']; evaluation_a: EngineEvaluation; evaluation_b: EngineEvaluation;
};

export interface AetherApi {
  readonly mode: 'live' | 'demo';
  health(): Promise<Health>;
  astronauts(): Promise<Astronaut[]>;
  timeline(id: string, day: number): Promise<Measurement[]>;
  saveMeasurement(id: string, m: MeasurementInput): Promise<{ saved: boolean; astronaut_id: string; day: number }>;
  phantom(id: string, day: number): Promise<Analysis>;
  phantomHistory(id: string, day: number, start?: number): Promise<PhantomHistory>;
  correlations(id: string, day: number, window?: number): Promise<Correlations>;
  symbiosis(day: number): Promise<CabinEnvironment>;
  zoneHistory(zone: ZoneId, start: number, end: number): Promise<ZoneHistory>;
  ship(day: number, hour: number): Promise<ShipState>;
  crew(reduceA01?: boolean): Promise<CrewResponse>;
  calendar(day: number): Promise<CrewCalendar>;
  plan(req: PlanRequest): Promise<Schedule>;
  scenarios(): Promise<Scenario[]>;
  simulate(req: SimulationRequest): Promise<SimulationResult>;
  project(req: ProjectionRequest): Promise<Projection>;
  recovery(id: string): Promise<RecoverySession[]>;
  saveRecovery(s: RecoverySessionInput): Promise<{ id: number; saved: boolean }>;
  environmentAssociation(day: number, zone: ZoneId): Promise<EnvironmentAssociation>;
  biofeedback(astronautId: string): Promise<BiofeedbackFrame>;
  experiments(): Promise<SavedExperiment[]>;
  saveExperiment(e: SavedExperiment): Promise<{ saved: boolean; id: string }>;
  deleteExperiment(id: string): Promise<{ deleted: boolean; id: string }>;
  engineTemplates(): Promise<EngineTemplate[]>;
  engineRun(req: EngineRunRequest): Promise<EngineRun>;
  engineGet(id: string): Promise<EngineRun>;
  engineControl(id: string, action: EngineControlAction, value?: number): Promise<EngineState>;
  engineCompare(a: string, b: string): Promise<EngineComparison>;
  engineCoorbit(id: string): Promise<CoorbitRecommendations>;
  engineCoorbitApply(id: string, body: { approved_ids: string[]; approved_by: string; note?: string }): Promise<CoorbitDecision>;
  engineCoorbitReject(id: string, body: { rejected_ids: string[]; reviewed_by: string; note?: string }): Promise<CoorbitRejection>;
  engineEnvironment(id: string, cabinPressureMmhg?: number): Promise<EnvironmentAnalysis>;
  phantom2(astronautId: string, day: number): Promise<Phantom2Daily>;
  scienceEvidence(): Promise<EvidenceLibrary>;
  scienceHazards(): Promise<HazardsResponse>;
  scienceGraph(p: MissionProfile): Promise<HazardGraph>;
  radiationPresets(): Promise<RadiationPresets>;
  radiation(req: RadiationRequest): Promise<RadiationResult>;
  engineSymbiosis(id: string, envMetric: string, metric: string, crewId: number): Promise<SymbiosisAnalytics>;
  compareConditions(body: { a: Record<string, number>; b: Record<string, number>; sleep_a?: number; sleep_b?: number; workload?: number }): Promise<ConditionComparison>;
  engineReplan(id: string, body: { crew_updates?: Record<string, unknown>[]; task_updates?: Record<string, unknown>[] }): Promise<ReplanResult>;
}

/* ---- 0.9 scientific core (/api/science/*) ---- */
export type HazardId = 'radiation' | 'isolation' | 'distance' | 'gravity' | 'environment';
export interface EvidenceEntry { id: string; title: string; authors: string; year: number; url: string; doi: string | null; kind: string; hazards: HazardId[]; finding: string; limitation: string; metrics: string[]; verified_via: string; verified_on: string }
export interface EvidenceLibrary { verified_on: string; entries: EvidenceEntry[]; unreachable: { url: string; reason: string }[] }
export interface Hazard { id: HazardId; name: string; inputs: string[]; body_indicators: string[]; consequences: string[]; sources: string[]; limitations: string[]; modules: string[]; reference: string }
export interface HrpMapping { risk: string; group: string; aether: string[]; status: string; relation: 'evidence' | 'assumption' | 'hypothesis'; sources: string[] }
export interface HazardsResponse { hazards: Hazard[]; hrp_map: HrpMapping[]; destinations: Record<string, string> }
export interface MissionProfile { destination: 'iss' | 'moon' | 'mars'; mission_days: number; crew_size: number; co2_ppm: number; cabin_pressure_mmhg: number; temperature_c: number; sleep_hours: number; spe_dose_msv: number }
export interface HazardGraph {
  profile: MissionProfile; exposure: Record<HazardId, number>; exposure_detail: Record<string, number>; summary: string; note: string; legend: Record<string, string>;
  nodes: { id: string; label: string; kind: 'hazard' | 'risk'; group?: string; level: number; aether_status?: string }[];
  edges: { from: string; to: string; type: 'evidence' | 'assumption' | 'hypothesis'; sources: string[]; note: string; strength: number }[];
}
export interface RadiationRequest { preset?: string | null; title?: string; segments?: { environment: string; days: number }[]; spe?: { day: number; dose_msv: number }[]; shielding_factor?: number; prior_career_msv?: number; runs?: number; seed?: number }
export interface RadiationResult {
  title: string; days: number; series: { day: number; p5: number; p50: number; p95: number; environment: string }[];
  final: { p5: number; p50: number; p95: number }; fraction_of_career_limit: { p5: number; p50: number; p95: number }; probability_exceeds_career_limit: number;
  events: { day: number; kind: string; dose_msv: number; exceeds_spe_limit?: boolean }[];
  by_environment: Record<string, { days: number; rate_msv_per_day: number; source: string | null; uncertainty: string }>;
  limits: { career_msv: number; spe_msv: number; source: string }; not_modelled: string[]; inputs: RadiationRequest;
}
export interface RadiationPresets { presets: Record<string, string>; environments: Record<string, { label: string; rate_msv_per_day: number; source: string | null; uncertainty: string }>; limits: { career_msv: number; spe_msv: number } }
/* ---- 0.9 Mission Systems analytics ---- */
export interface SymbiosisAnalytics {
  run_id: string; env_metric: string; metric: string; crew_id: number; split_minute: number; split_basis: string; note: string; causal: false;
  relationship: { pearson_r: number | null; pairs: number; lag_minutes: number; reason: string | null }[];
  periods: Record<string, { a: { mean: number; slope_per_hour: number | null; count: number; unit: string } | null; b: { mean: number; slope_per_hour: number | null; count: number; unit: string } | null }>;
}
export interface ConditionComparison { a: Record<string, number>; b: Record<string, number>; delta: Record<string, number>; recommendations: string[]; a_input: Record<string, number>; b_input: Record<string, number>; [k: string]: unknown }
export type ReplanResult = ProposalOutcome & { run_id: string; before: EngineStrategy; after: EngineStrategy; comparison: { delta: Record<string, number>; [k: string]: unknown }; tasks: { id: string; title: string; priority: number; required?: boolean }[] };
/* ---- API 1.0: human rejection + cabin environment analysis ---- */
export type CoorbitRejection = { reviewed_by: string; reviewed_at: string; note: string; rejected: CoorbitRecommendation[]; decision_status: 'rejected_by_human'; changed: false; schedule: EngineStrategy; policy: string };
export type EnvFrameState = 'nominal' | 'environment_event' | 'sensor_fault';
export type EnvironmentEvent = { kind: string; channel: string; start_minute: number; end_minute: number; duration_minutes: number; category: 'environment' | 'sensor_fault'; sustained: boolean };
export type CrewEnvironmentContext = {
  crew_id: number; crew_name?: string; environment_stressor: boolean; stressor_kinds: string[]; stressor_minutes?: number[] | number;
  physiology_flagged_samples: number; flagged_during_stressor: number; cabin_sensor_faults: number; statement: string; evidence: string;
  suggested_measurements: { signal: string; why: string }[]; diagnosis: null; note: string;
};
export type EnvironmentAnalysis = {
  run_id: string; zone_id: string; origin: 'synthetic';
  frames: { minute: number; state: EnvFrameState; environment_event: boolean; sensor_fault: boolean; alarms: { kind: string; channel: string; [k: string]: unknown }[]; faults: { channel: string; kind: string }[]; ppco2_1h_mmhg: number | null }[];
  events: EnvironmentEvent[]; crew_context: CrewEnvironmentContext[];
  co2_limit: { mmhg: number; averaging: string; source: string; evidence_id: string };
  applicability: Record<string, string>; parameters: Record<string, unknown>; scope: string; note: string;
  evaluation_against_hidden_labels?: { precision: number | null; recall: number | null; f1: number | null; fpr: number | null; delay_min: number | null };
};

/** Capability names advertised by GET /api/health → `capabilities`. */
export const CAPABILITIES = {
  ship: 'ship', zoneHistory: 'symbiosis-history', phantomHistory: 'phantom-history', correlations: 'phantom-correlations',
  calendar: 'co-orbit-calendar', plan: 'co-orbit-plan', projection: 'mission-lab-project', recoveryDetails: 'recovery-details',
  envAssociation: 'symbiosis-crew-association', biofeedback: 'recovery-biofeedback', experiments: 'mission-lab-experiments',
  engine: 'mission-engine', phantom2: 'phantom2', coorbitPhantom: 'coorbit-phantom', science: 'science-core',
  coorbitReject: 'coorbit-reject', environmentDetector: 'environment-detector',
} as const;
