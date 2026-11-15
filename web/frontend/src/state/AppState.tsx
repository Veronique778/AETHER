import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { createDemoApi } from '../mocks/demoApi';
import { navigate } from '../lib/router';
import { ApiError, createHttpApi } from '../api/httpClient';
import type { AetherApi, Astronaut, EngineRun, ScenarioParams, ZoneId } from '../api/types';
import { desktop, isDesktop } from '../desktop/bridge';
import { resolveApiBase } from './runtimeConfig';

export type DataMode = 'live' | 'demo';
export type Connection = 'checking' | 'online' | 'offline';
/** UI presentation preview only – it never grants backend permissions. */
export type Role = 'crew' | 'flight-surgeon';
export type ThemePref = 'dark' | 'light' | 'auto';
export type TextScale = '1' | '1.12' | '1.25';
export type Density = 'expanded' | 'compact';
/** Auto: light (positive polarity) during the mission work day, dark in the pre-sleep / sleep window. */
export const autoThemeAt = (hour: number): 'dark' | 'light' => (hour >= 7 && hour < 20 ? 'light' : 'dark');

/** Desktop: the bundled backend's localhost address (injected at runtime); browser: build-time setting. */
export const IS_MOBILE_BUILD = import.meta.env.VITE_MOBILE_APP === '1';
const configuredApiBase = import.meta.env.VITE_API_URL?.trim();
export const MOBILE_API_CONFIGURED = Boolean(desktop?.apiBase?.trim() || configuredApiBase);
export const API_BASE = resolveApiBase({
  desktopApiBase: desktop?.apiBase,
  configuredApiBase,
  mobileBuild: IS_MOBILE_BUILD,
  browserOrigin: globalThis.location?.origin,
});
/** Desktop only: how long to wait for the bundled backend to become ready before reporting it offline. */
const DESKTOP_STARTUP_MS = 45000;
export const MAX_DAY = 67;
/** Mission length used for the progress indicator (the synthetic dataset covers days 1–67 of the transit). */
export const MISSION_DAYS = 180;
export const MISSION_ID = 'AETHER-M1';
/**
 * Scenario applied to the whole mission from MISSION LAB. Modules show its effect next to the actual
 * data, computed by the existing simulator (POST /api/mission-lab/run) – never mixed into measurements.
 */
export type ActiveScenario = { id: string; title: string; params: ScenarioParams; note?: string };

type AppState = {
  api: AetherApi;
  mode: DataMode;
  setMode: (m: DataMode) => void;
  connection: Connection;
  backendVersion: string | null;
  personalApiAvailable: boolean;
  retry: () => void;
  astronauts: Astronaut[];
  astronautId: string;
  setAstronautId: (id: string) => void;
  day: number;
  setDay: (d: number) => void;
  hour: number;
  setHour: (h: number) => void;
  role: Role;
  setRole: (r: Role) => void;
  reducedMotion: boolean;
  setReducedMotion: (v: boolean) => void;
  theme: ThemePref;
  setTheme: (t: ThemePref) => void;
  effectiveTheme: 'dark' | 'light';
  textScale: TextScale;
  setTextScale: (s: TextScale) => void;
  /** Live mode: endpoint groups the connected backend advertises. Demo mode: everything. */
  hasCapability: (c: string) => boolean;
  dataVersion: number;
  bumpData: () => void;
  /* ---- Shared cross-module context (v0.4) ---- */
  /** Selected spacecraft compartment, shared by Mission Control, SYMBIOSIS, CO-ORBIT. */
  zoneId: ZoneId;
  setZoneId: (z: ZoneId) => void;
  /** Scenario applied from MISSION LAB (null = actual mission data only). */
  scenario: ActiveScenario | null;
  applyScenario: (s: ActiveScenario | null) => void;
  /** Id of the applied scenario (kept for v0.4 callers). */
  scenarioId: string | null;
  setScenarioId: (s: string | null) => void;
  /**
   * Latest Mission Systems engine run (MISSION LAB → engine tab). Shared so CO-ORBIT (MILP schedule), SYMBIOSIS
   * (modelled cabin series), PHANTOM (detection evaluation) and BODY (crew time series) show the same run.
   * The last run id is remembered and re-loaded from the backend on the next start.
   */
  engineRun: EngineRun | null;
  setEngineRun: (r: EngineRun | null) => void;
  /** Compact hides secondary panels and descriptions; expanded shows everything. */
  density: Density;
  setDensity: (d: Density) => void;
  /** Set several context fields at once and navigate (state travels with the user, not the URL). */
  openWith: (path: string, ctx: Partial<{ astronautId: string; day: number; hour: number; zoneId: ZoneId; scenarioId: string | null }>) => void;
};

const Ctx = createContext<AppState | null>(null);

function readPref<T extends string>(key: string, fallback: T): T {
  try { return (localStorage.getItem(key) as T | null) ?? fallback; } catch { return fallback; }
}
function writePref(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* storage unavailable */ }
}

function initialMode(): DataMode {
  // Mobile bundles cannot run the Python HTTP server inside the WebView.
  // Force the validated synthetic JS adapter; never silently connect to a localhost backend.
  if (IS_MOBILE_BUILD) return 'demo';
  const q = new URLSearchParams((location.hash.split('?')[1] ?? '') || location.search).get('mode');
  if (q === 'demo' || q === 'live') return q;
  return readPref<DataMode>('aether.mode', import.meta.env.VITE_DATA_MODE === 'demo' ? 'demo' : 'live');
}

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<DataMode>(initialMode);
  const api = useMemo(() => (mode === 'demo' ? createDemoApi() : createHttpApi(API_BASE)), [mode]);
  const [connection, setConnection] = useState<Connection>('checking');
  const [backendVersion, setBackendVersion] = useState<string | null>(null);
  const [personalApiAvailable, setPersonalApiAvailable] = useState(false);
  const [astronauts, setAstronauts] = useState<Astronaut[]>([]);
  const [attempt, setAttempt] = useState(0);
  const [astronautId, setAstronautIdState] = useState<string>(() => readPref<string>('aether.astronaut', 'A01'));
  const [day, setDay] = useState(MAX_DAY);
  const [hour, setHour] = useState(10);
  const [role, setRoleState] = useState<Role>(() => readPref<Role>('aether.role', 'crew'));
  const systemReduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const [reducedMotion, setReducedMotionState] = useState(() => readPref('aether.reducedMotion', systemReduced ? '1' : '0') === '1');
  const [dataVersion, setDataVersion] = useState(0);
  const [theme, setThemeState] = useState<ThemePref>(() => readPref<ThemePref>('aether.theme', 'dark'));
  const [textScale, setTextScaleState] = useState<TextScale>(() => readPref<TextScale>('aether.textScale', '1'));
  const [caps, setCaps] = useState<string[]>([]);
  const [zoneId, setZoneIdState] = useState<ZoneId>(() => readPref<ZoneId>('aether.zone', 'habitat'));
  const [scenario, setScenario] = useState<ActiveScenario | null>(null);
  const [engineRun, setEngineRunState] = useState<EngineRun | null>(null);
  const [density, setDensityState] = useState<Density>(() => readPref<Density>('aether.density', 'expanded'));
  const effectiveTheme = theme === 'auto' ? autoThemeAt(hour) : theme;

  useEffect(() => {
    let alive = true;
    setConnection('checking');
    const started = Date.now();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const attemptOnce = async () => {
      try {
        const health = await api.health();
        if (!alive) return;
        setBackendVersion(health.version ?? '0.1');
        setCaps(health.capabilities ?? []);
        const hasPersonalApi = mode === 'live' && health.personal_api_contract_version === '1.5';
        setPersonalApiAvailable(hasPersonalApi);
        const hasLegacyApi = !health.personal_api_contract_version && health.api_contract_version !== '1.5';
        if (mode === 'demo' || hasLegacyApi) {
          try {
            setAstronauts(await api.astronauts());
          } catch (error) {
            if (!(error instanceof ApiError && error.status === 401)) throw error;
            setAstronauts([]);
          }
        } else {
          setAstronauts([]);
        }
        setConnection('online');
      } catch {
        if (!alive) return;
        setPersonalApiAvailable(false);
        setAstronauts([]);
        // Desktop Live Mode: the bundled backend may still be starting – keep waiting (state stays "checking").
        if (isDesktop && mode === 'live' && !desktop?.backendError && Date.now() - started < DESKTOP_STARTUP_MS) timer = setTimeout(attemptOnce, 400);
        else setConnection('offline');
      }
    };
    void attemptOnce();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [api, attempt]);

  // Restore the last Mission Systems engine run (persisted in the backend's SQLite store).
  useEffect(() => {
    if (connection !== 'online' || mode !== 'live' || !caps.includes('mission-engine') || engineRun) return;
    const id = readPref('aether.engineRun', '');
    if (id) api.engineGet(id).then(setEngineRunState, () => writePref('aether.engineRun', ''));
  }, [connection, mode, caps, api]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { document.documentElement.classList.toggle('reduce-motion', reducedMotion); }, [reducedMotion]);
  useEffect(() => { document.documentElement.classList.toggle('theme-light', effectiveTheme === 'light'); }, [effectiveTheme]);
  useEffect(() => { document.documentElement.style.setProperty('--text-scale', textScale); }, [textScale]);

  const value: AppState = {
    api, mode, connection, backendVersion, personalApiAvailable, astronauts, astronautId, day, setDay, hour, setHour, role, reducedMotion, dataVersion,
    theme, effectiveTheme, textScale,
    setTheme: (t) => { writePref('aether.theme', t); setThemeState(t); },
    setTextScale: (s) => { writePref('aether.textScale', s); setTextScaleState(s); },
    // Demo Mode emulates every endpoint in the browser except the Python Mission Systems engine.
    hasCapability: (c) => (mode === 'demo' ? !['mission-engine', 'phantom2', 'coorbit-phantom', 'science-core'].includes(c) : caps.includes('all') || caps.includes(c)),
    setMode: (m) => { const chosen = IS_MOBILE_BUILD ? 'demo' : m; writePref('aether.mode', chosen); setModeState(chosen); },
    retry: () => setAttempt((a) => a + 1),
    setAstronautId: (id) => { writePref('aether.astronaut', id); setAstronautIdState(id); },
    setRole: (r) => { writePref('aether.role', r); setRoleState(r); },
    setReducedMotion: (v) => { writePref('aether.reducedMotion', v ? '1' : '0'); setReducedMotionState(v); },
    bumpData: useCallback(() => setDataVersion((v) => v + 1), []),
    zoneId, density, scenario, applyScenario: setScenario,
    engineRun,
    setEngineRun: (r) => { writePref('aether.engineRun', r?.id ?? ''); setEngineRunState(r); },
    scenarioId: scenario?.id ?? null,
    setScenarioId: (id) => { if (id === null) setScenario(null); },
    setZoneId: (z) => { writePref('aether.zone', z); setZoneIdState(z); },
    setDensity: (d) => { writePref('aether.density', d); setDensityState(d); },
    openWith: (path, ctx) => {
      if (ctx.astronautId) { writePref('aether.astronaut', ctx.astronautId); setAstronautIdState(ctx.astronautId); }
      if (ctx.day != null) setDay(Math.max(1, Math.min(MAX_DAY, ctx.day)));
      if (ctx.hour != null) setHour(ctx.hour);
      if (ctx.zoneId) { writePref('aether.zone', ctx.zoneId); setZoneIdState(ctx.zoneId); }
      if (ctx.scenarioId === null) setScenario(null);
      navigate(path);
    },
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/**
 * Scoped research adapter used only for explicitly labelled mission simulation screens.
 * The global mode, account session and BE2 science storage remain unchanged.
 */
export function MissionPreviewProvider({ children, api, astronauts, astronautId }: {
  children: ReactNode; api: AetherApi; astronauts: Astronaut[]; astronautId: string;
}) {
  const outer = useApp();
  const preview = useMemo<AppState>(() => ({
    ...outer,
    api,
    mode: 'demo',
    astronauts,
    astronautId,
    hasCapability: (c) => !['mission-engine', 'phantom2', 'coorbit-phantom', 'science-core'].includes(c),
  }), [outer, api, astronauts, astronautId]);
  return <Ctx.Provider value={preview}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error('useApp must be used inside <AppStateProvider>');
  return v;
}

export function useAstronaut(id?: string): Astronaut | undefined {
  const { astronauts, astronautId } = useApp();
  return astronauts.find((a) => a.id === (id ?? astronautId));
}
