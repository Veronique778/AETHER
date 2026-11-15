import { SourceControl, useBiosignal } from '../features/biosignals/BiosignalPage';
import { useEffect, useState, type ReactNode } from 'react';
import type { ZoneId } from '../api/types';
import { CREW_HEX, hourLabel, initials } from '../lib/format';
import { navigate } from '../lib/router';
import { Link, useRoute } from '../lib/router';
import { API_BASE, MAX_DAY, MISSION_DAYS, MISSION_ID, useApp } from '../state/AppState';
import { ScenarioBanner } from '../state/scenario';
import { desktop, isDesktop } from '../desktop/bridge';
import { useResource } from '../lib/useResource';
import { Button, cx, Icon, Pill, ToastProvider, Tooltip, type IconName } from '../ui';
import { useAuth } from '../state/AuthState';
import { CREW_SEED } from '../mocks/missionSystemsMock';
import { missionNeedsSyntheticAdapter } from '../state/personalAccess';

/** Module registry. `accent` gives each module its own functional identity colour. */
export const MODULES: { path: string; name: string; sub: string; icon: IconName; accent: string }[] = [
  { path: '/', name: 'Mission Control', sub: 'Spacecraft twin', icon: 'ship', accent: 'var(--color-cyan)' },
  { path: '/biosignals', name: 'BIOSIGNALS', sub: 'Research Data & Live Sensors', icon: 'bluetooth', accent: 'var(--color-cyan)' },
  { path: '/body', name: 'BODY', sub: 'Human digital twin', icon: 'body', accent: 'var(--color-blue)' },
  { path: '/phantom', name: 'PHANTOM', sub: 'Predictive intelligence', icon: 'brain', accent: 'var(--color-violet)' },
  { path: '/symbiosis', name: 'SYMBIOSIS', sub: 'Environmental intelligence', icon: 'waves', accent: 'var(--color-good)' },
  { path: '/co-orbit', name: 'CO-ORBIT', sub: 'Crew coordination', icon: 'users', accent: 'var(--color-amber)' },
  { path: '/recovery', name: 'RECOVERY', sub: 'Recovery environment', icon: 'leaf', accent: 'var(--color-sage)' },
  { path: '/mission-lab', name: 'MISSION LAB', sub: 'Simulation lab', icon: 'flask', accent: 'var(--color-blue)' },
  { path: '/science', name: 'SCIENCE', sub: 'NASA hazards & evidence', icon: 'layers', accent: 'var(--color-amber)' },
];

export const ZONE_NAMES: Record<ZoneId, string> = {
  command: 'Command deck', habitat: 'Habitat ring', medical: 'Medical bay', exercise: 'Exercise & recovery', systems: 'Life support',
};

function isActive(path: string, current: string) {
  return path === '/' ? current === '/' : current === path || current.startsWith(path + '/');
}

export function moduleFor(path: string) {
  return MODULES.find((m) => isActive(m.path, path));
}

function Nav({ onNavigate, rail }: { onNavigate?: () => void; rail: boolean }) {
  const { path } = useRoute();
  return (
    <nav aria-label="Modules" className="flex flex-col gap-1">
      {MODULES.map((m) => {
        const active = isActive(m.path, path);
        const link = (describedBy?: string) => (
          <Link to={m.path} onClick={onNavigate} aria-current={active ? 'page' : undefined} aria-describedby={describedBy} aria-label={rail ? m.name : undefined}
            className={cx('group relative flex min-h-12 items-center gap-3 rounded-xl border px-3 py-2 transition-all duration-200',
              active ? 'border-[color-mix(in_srgb,currentColor_45%,transparent)] bg-[linear-gradient(90deg,color-mix(in_srgb,currentColor_22%,transparent),color-mix(in_srgb,currentColor_4%,transparent))] text-ink shadow-[0_0_22px_-8px_currentColor]'
                : 'border-transparent text-ink-2 hover:border-line hover:bg-raised/60 hover:text-ink', rail && 'justify-center px-0')}>
            <span aria-hidden className={cx('absolute left-0 top-2 bottom-2 w-[3px] rounded-full transition-opacity', active ? 'opacity-100' : 'opacity-0')} style={{ background: m.accent }} />
            <Icon name={m.icon} size={19} className={cx('shrink-0 transition-colors', !active && 'text-ink-3 group-hover:text-ink-2')} />
            {!rail && (
              <span className="min-w-0">
                <span className="block text-[13px] font-semibold tracking-[0.06em] text-ink">{m.name}</span>
                <span className="block truncate text-xs text-ink-3">{m.sub}</span>
              </span>
            )}
          </Link>
        );
        return <div key={m.path} style={active ? { color: m.accent } : undefined}>{rail ? <Tooltip text={`${m.name} · ${m.sub}`}>{(id) => link(id)}</Tooltip> : link()}</div>;
      })}
    </nav>
  );
}

function DataModeBadge() {
  const { mode, connection, backendVersion } = useApp();
  if (mode === 'demo') return <Pill tone="attention" icon="database">Mission preview · offline</Pill>;
  if (connection === 'online') return <Pill tone="good" icon="link">Backend connected · API v{backendVersion}</Pill>;
  if (connection === 'checking') return <Pill tone="unknown" icon="clock">Connecting…</Pill>;
  return <Pill tone="high" icon="wifiOff">Backend offline</Pill>;
}

/**
 * Shared mission context. Every module reads these values, so moving between modules
 * keeps the same astronaut, time point, compartment and scenario.
 */
function ContextBar() {
  const app = useApp();
  const { path } = useRoute();
  const { source } = useBiosignal();
  if (source === 'personal' && ['/body', '/phantom', '/biosignals'].includes(path)) {
    return <p className="px-4 pb-3 text-xs text-ink-3 lg:px-8">Personal monitoring · private measurements from your account.</p>;
  }
  if (source !== 'synthetic' && ['/body','/phantom','/biosignals'].includes(path)) return <p className="px-4 pb-3 text-xs text-ink-3 lg:px-8">Recording view · select a sensor session in BIOSIGNALS.</p>;
  const missionPreview = app.mode === 'live' && missionNeedsSyntheticAdapter(path.replace(/^\//, ''), source === 'personal' || source === 'live_sensor');
  const visibleCrew = app.astronauts.length ? app.astronauts : missionPreview ? CREW_SEED : [];
  const visibleId = visibleCrew.some((person) => person.id === app.astronautId) ? app.astronautId : visibleCrew[0]?.id ?? '';
  const chip = 'flex min-h-9 items-center gap-2 rounded-xl border border-line bg-surface/80 px-2.5 text-sm';
  const related = MODULES.filter((m) => m.path !== '/' && !isActive(m.path, path));
  return (
    <div className="flex flex-wrap items-center gap-2 px-4 pb-2.5 lg:px-8" role="group" aria-label="Mission context shared by all modules">
      <span className="mono-label mr-1 hidden xl:inline">Context</span>
      <label className={chip}>
        <span className="grid h-6 w-6 place-items-center rounded-full text-[10px] font-bold text-white" style={{ background: CREW_HEX[visibleId] }} aria-hidden>{initials(visibleCrew.find((a) => a.id === visibleId)?.name ?? '?')}</span>
        <span className="sr-only">Astronaut</span>
        <select value={visibleId} onChange={(e) => app.setAstronautId(e.target.value)} className="min-h-7 bg-transparent pr-1 text-ink outline-none focus-visible:outline-2" aria-label="Astronaut">
          {visibleCrew.map((a) => <option key={a.id} value={a.id} className="bg-surface">{a.name}</option>)}
        </select>
      </label>
      <div className={chip}>
        <button type="button" aria-label="Previous mission day" disabled={app.day <= 41} onClick={() => app.setDay(app.day - 1)} className="grid h-8 w-8 place-items-center rounded-md text-ink-2 hover:text-ink disabled:opacity-30"><Icon name="chevronLeft" size={16} /></button>
        <label className="flex items-center gap-1.5">
          <span className="mono-label">Day</span>
          <input type="number" min={41} max={MAX_DAY} value={app.day} onChange={(e) => { const v = Number(e.target.value); if (v >= 41 && v <= MAX_DAY) app.setDay(v); }} className="tabular h-7 w-11 rounded bg-transparent text-center font-semibold text-ink" aria-label="Mission day" />
        </label>
        <button type="button" aria-label="Next mission day" disabled={app.day >= MAX_DAY} onClick={() => app.setDay(app.day + 1)} className="grid h-8 w-8 place-items-center rounded-md text-ink-2 hover:text-ink disabled:opacity-30"><Icon name="chevronRight" size={16} /></button>
      </div>
      <label className={chip}>
        <span className="mono-label">Time</span>
        <select aria-label="Mission time" value={Math.floor(app.hour)} onChange={(e) => app.setHour(Number(e.target.value))} className="tabular min-h-7 bg-transparent text-ink outline-none">
          {Array.from({ length: 24 }, (_, h) => <option key={h} value={h} className="bg-surface">{hourLabel(h)}</option>)}
        </select>
      </label>
      <label className={chip}>
        <span className="mono-label">Zone</span>
        <select aria-label="Compartment" value={app.zoneId} onChange={(e) => app.setZoneId(e.target.value as ZoneId)} className="min-h-7 bg-transparent text-ink outline-none">
          {(Object.keys(ZONE_NAMES) as ZoneId[]).map((z) => <option key={z} value={z} className="bg-surface">{ZONE_NAMES[z]}</option>)}
        </select>
      </label>
      <nav aria-label="Open this context in another module" className="ml-auto flex flex-wrap items-center gap-1">
        <span className="mono-label mr-1 hidden 2xl:inline">Open in</span>
        {related.map((m) => (
          <Tooltip key={m.path} text={`${m.name}: ${m.sub} for this context`}>
            {(id) => (
              <Link to={m.path} aria-describedby={id} aria-label={`Open ${m.name} with this context`} className="grid h-9 w-9 place-items-center rounded-lg border border-line bg-surface/70 text-ink-3 transition-colors hover:border-line-strong hover:text-ink" style={{ ['--tw-ring-color' as string]: m.accent }}>
                <Icon name={m.icon} size={17} />
              </Link>
            )}
          </Tooltip>
        ))}
      </nav>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { path } = useRoute();
  const { density, setDensity } = useApp();
  const [menu, setMenu] = useState(false);
  const rail = density === 'compact';
  const current = moduleFor(path);
  useEffect(() => { setMenu(false); window.scrollTo?.(0, 0); }, [path]);
  return (
    <ToastProvider>
    <div className={cx('min-h-screen lg:grid', rail ? 'lg:grid-cols-[76px_1fr]' : 'lg:grid-cols-[240px_1fr]')} style={{ ['--module-accent' as string]: current?.accent ?? 'var(--color-cyan)' }}>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-teal-300 focus:px-3 focus:py-2 focus:text-canvas">Skip to content</a>
      <aside className={cx('fixed inset-y-0 left-0 z-40 w-[240px] flex-col border-r border-line bg-surface/95 px-3 py-5 backdrop-blur lg:sticky lg:top-0 lg:flex lg:h-screen', menu ? 'flex' : 'hidden', rail && 'lg:w-[76px] lg:px-2')}>
        <Link to="/" className={cx('mb-7 flex items-center gap-3 px-2', rail && 'lg:justify-center lg:px-0')} aria-label="AETHER home">
          <span className="relative grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[radial-gradient(circle_at_30%_30%,#1d6f8a,#0b1c2c)] ring-1 ring-teal-600">
            <Icon name="orbit" size={22} className="text-teal-300" />
          </span>
          <span className={cx(rail && 'lg:hidden')}><span className="block text-lg font-semibold tracking-[0.28em] text-ink">AETHER</span><span className="mono-label block">Human adaptation system</span></span>
        </Link>
        <Nav onNavigate={() => setMenu(false)} rail={rail && !menu} />
        <div className={cx('mt-auto space-y-1 px-1 text-xs text-ink-3', rail && !menu && 'lg:hidden')}>
          <AccountFooter />
          <Link to="/settings" className="flex min-h-8 items-center gap-1.5 text-ink-2 hover:text-ink"><Icon name="settings" size={14} />Settings</Link>
          <Link to="/about" className="flex min-h-8 items-center gap-1.5 text-ink-2 hover:text-ink"><Icon name="info" size={14} />Data, methods & status</Link>
          <p className="pt-2">Research prototype · Not a medical device.</p>
          <p className="flex items-center gap-1.5 pt-1 text-ink-2"><span className="h-2 w-2 rounded-full bg-good shadow-[0_0_8px_var(--color-good)]" aria-hidden />AETHER 1.5 · Human adaptation system</p>
        </div>
      </aside>
      {menu && <div className="fixed inset-0 z-30 bg-black/60 lg:hidden" onClick={() => setMenu(false)} aria-hidden />}
      <div className="min-w-0">
        <header className="sticky top-0 z-20 border-b border-line bg-canvas/90 backdrop-blur-md no-print">
          <div className="flex flex-wrap items-center gap-3 px-4 py-2.5 lg:px-8">
            <button type="button" className="grid h-9 w-9 place-items-center rounded-lg text-ink-2 lg:hidden" aria-label="Open navigation" aria-expanded={menu} onClick={() => setMenu(true)}><Icon name="menu" size={20} /></button>
            <div className="mr-auto flex min-w-0 items-center gap-2 text-sm text-ink-3">
              <span className="mono-label hidden sm:inline">AETHER</span><span aria-hidden className="hidden sm:inline">/</span>
              <span className="font-semibold tracking-wide" style={{ color: current?.accent ?? 'var(--color-ink)' }}>{current?.name ?? (path === '/settings' ? 'Settings' : 'Data & methods')}</span>
            </div>
            <MissionClock />
            <DataModeBadge />
            <AlertBell />
            <RoleChip />
            <Tooltip text={rail ? 'Expanded layout: full navigation, secondary panels and descriptions' : 'Compact layout: icon navigation, fewer secondary panels'} side="bottom">
              {(id) => (
                <Button size="sm" variant="ghost" icon={rail ? 'layers' : 'minus'} aria-describedby={id} aria-pressed={rail} onClick={() => setDensity(rail ? 'expanded' : 'compact')}>
                  {rail ? 'Compact' : 'Expanded'}
                </Button>
              )}
            </Tooltip>
            <Link to="/settings" aria-label="Settings" className="grid h-9 w-9 place-items-center rounded-[10px] text-ink-2 hover:bg-raised hover:text-ink"><Icon name="settings" size={18} /></Link>
          </div>
          <SourceControl /><ContextBar />
          <ScenarioBanner />
        </header>
        <main id="main" key={path.split('/')[1] ?? ''} className="page-enter px-4 py-6 lg:px-8">{children}</main>
      </div>
    </div>
    </ToastProvider>
  );
}

function AccountFooter() {
  const { mode, personalApiAvailable } = useApp();
  const { status, user, signOut } = useAuth();
  const leave = () => {
    void signOut().catch(() => undefined).finally(() => navigate('/login'));
  };
  if (status !== 'signed-in' || !user) {
    if (mode !== 'live' || !personalApiAvailable) return null;
    return <div className="border-b border-line pb-2">
      <Link to="/login" className="flex min-h-9 items-center gap-1.5 text-ink-2 hover:text-ink"><Icon name="users" size={14} />Sign in to Personal Mode</Link>
    </div>;
  }
  return (
    <div className="border-b border-line pb-2">
      <Link to="/profile" className="flex min-h-9 items-center gap-1.5 text-ink-2 hover:text-ink"><Icon name="users" size={14} />My account · {user.login}</Link>
      <button type="button" className="flex min-h-9 w-full items-center gap-1.5 text-left text-ink-2 hover:text-ink" onClick={leave}><Icon name="x" size={14} />Sign out</button>
    </div>
  );
}

/** Mission identifier, selected mission day and elapsed mission time (derived from the shared day/hour). */
function MissionClock() {
  const { day, hour } = useApp();
  const hh = String(Math.floor(hour)).padStart(2, '0'), mm = hour % 1 ? '30' : '00';
  return (
    <div className="hidden items-center gap-3 rounded-xl border border-line bg-surface/70 px-3 py-1.5 text-xs md:flex" aria-label={`Mission ${MISSION_ID}, day ${day} of ${MISSION_DAYS}, elapsed ${day - 1} days ${hh}:${mm}`}>
      <span className="font-semibold tracking-wider text-ink">{MISSION_ID}</span>
      <span className="h-3 w-px bg-line-strong" aria-hidden />
      <span className="tabular text-ink-2">Day <span className="text-ink">{day}</span>/{MISSION_DAYS}</span>
      <span className="h-3 w-px bg-line-strong" aria-hidden />
      <span className="tabular font-mono text-cyan">T+ {String(day - 1).padStart(3, '0')}d {hh}:{mm}</span>
    </div>
  );
}

/** Count of open alerts (environment above reference, reduced-load flags); opens Mission Control alerts. */
function AlertBell() {
  const { api, day, hour, dataVersion } = useApp();
  const ship = useResource(`bell-${api.mode}-${day}-${hour}-${dataVersion}`, () => api.ship(day, hour));
  const n = ship.data ? ship.data.zones.filter((z) => z.environment.status !== 'nominal').length + ship.data.crew.filter((c) => c.reduced_load_suggested).length : 0;
  return (
    <Tooltip text={ship.data ? `${n} open item${n === 1 ? '' : 's'} – open Mission Control alerts` : 'Loading alerts'} side="bottom">
      {(id) => (
        <button type="button" aria-describedby={id} aria-label={`Alerts: ${n}`} onClick={() => { navigate('/'); setTimeout(() => document.getElementById('alerts')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 120); }}
          className="relative grid h-9 w-9 place-items-center rounded-[10px] text-ink-2 hover:bg-raised hover:text-ink">
          <Icon name="bell" size={18} />
          {n > 0 && <span className="tabular absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-magenta px-1 text-[10px] font-bold text-white">{n}</span>}
        </button>
      )}
    </Tooltip>
  );
}

/** UI-only preview mode – it never grants backend permissions. */
function RoleChip() {
  const { role } = useApp();
  const label = role === 'flight-surgeon' ? 'Flight surgeon preview' : 'Crew preview';
  return (
    <Link to="/settings" title="UI preview only · backend permissions are always enforced by the server" className="hidden items-center gap-2 rounded-xl border border-line bg-surface/70 py-1 pl-1 pr-3 text-xs hover:border-line-strong lg:flex" aria-label={`UI preview: ${label}. This does not grant access; change in Settings.`}>
      <span className="grid h-7 w-7 place-items-center rounded-full bg-raised text-cyan"><Icon name={role === 'flight-surgeon' ? 'heart' : 'users'} size={15} /></span>
      <span><span className="block text-ink-3">UI preview only</span><span className="block font-semibold text-ink">{label}</span></span>
    </Link>
  );
}

export function BackendUnavailable() {
  const { retry, setMode } = useApp();
  return (
    <div className="grid min-h-screen place-items-center p-6">
      <div className="card max-w-lg p-6">
        <div className="mb-2 flex items-center gap-2 text-high"><Icon name="wifiOff" size={22} /><h1 className="text-lg font-semibold text-ink">The AETHER backend is not reachable</h1></div>
        <p className="text-ink-2">Tried <code className="rounded bg-raised px-1">{API_BASE || (typeof location !== 'undefined' ? location.origin : 'the local backend')}</code>. AETHER does not invent data when the server is unavailable.</p>
        {isDesktop ? (
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-ink-2">
            <li>The backend bundled with the desktop app did not start{desktop?.backendError ? <>: <code className="rounded bg-raised px-1">{desktop.backendError}</code></> : ' in time'}.</li>
            {desktop?.logFile && <li>Details are in <code className="break-all rounded bg-raised px-1">{desktop.logFile}</code>.</li>}
            <li>Retry, restart AETHER, or continue with the <strong>in-app demo adapter</strong> (labelled synthetic data, works offline).</li>
          </ul>
        ) : (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-ink-2">
          <li>Start the API: <code className="rounded bg-raised px-1">uvicorn app.main:app --port 8000</code> (or <code className="rounded bg-raised px-1">python -m app.devserver</code>) in <code>web/backend</code>.</li>
          <li>Or continue with the <strong>in-browser demo adapter</strong>: the same synthetic models run locally and every screen is labelled “Demo adapter”.</li>
        </ul>
        )}
        <div className="mt-5 flex flex-wrap gap-2">
          <Button variant="primary" icon="reset" onClick={retry}>Retry connection</Button>
          <Button icon="database" onClick={() => setMode('demo')}>Use demo adapter</Button>
        </div>
      </div>
    </div>
  );
}
