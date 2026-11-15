import { useMemo, useState, type ReactNode } from 'react';
import { METRIC_KEYS, type Analysis, type Measurement, type ShipState } from '../../api/types';
import { Sparkline } from '../../charts';
import { MODULES } from '../../layout/AppShell';
import { BODY_SYSTEMS, CREW_HEX, dayLabel, fmt, fmtMetric, hourLabel, initials, METRIC_COLOR, METRICS, type BodySystem } from '../../lib/format';
import { navigate } from '../../lib/router';
import { useResource } from '../../lib/useResource';
import { DEMO_CHANNEL_NOTE, demoCabin, demoVitals, demoVitalsSeries } from '../../mocks/demoChannels';
import { hexToRgb } from '../../scene3d/engine';
import { SYSTEM_FOCUS } from '../../scene3d/models';
import { readBodyModel, useHumanModel } from '../../scene3d/useHumanModel';
import { Viewport } from '../../scene3d/Viewport';
import { MAX_DAY, MISSION_DAYS, MISSION_ID, useApp, useAstronaut } from '../../state/AppState';
import { Async, Button, cx, Icon, PhantomPill, SourceBadge, Tooltip, type IconName } from '../../ui';
import { TrendPrediction } from '../shared/TrendPrediction';

const SYSTEMS: BodySystem[] = ['cardiovascular', 'respiratory', 'nervous', 'musculoskeletal', 'metabolic'];
const SYS_ICON: Record<BodySystem, IconName> = { cardiovascular: 'heart', respiratory: 'wind', nervous: 'brain', musculoskeletal: 'body', metabolic: 'zap' };

/* ───────────────────────────── shared panel chrome ───────────────────────────── */

function Panel({ title, module, children, className, action, label }: { title: ReactNode; module?: string; children: ReactNode; className?: string; action?: ReactNode; label: string }) {
  const m = MODULES.find((x) => x.path === module);
  return (
    <section aria-label={label} className={cx('card glow-hover flex min-w-0 flex-col p-4', className)}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="flex min-w-0 items-center gap-2 text-[15px] font-semibold text-ink">
          {m && <Icon name={m.icon} size={17} style={{ color: m.accent }} />}
          <span className="truncate">{title}</span>
          {m && m.path !== '/' && <span className="text-xs font-normal text-ink-3">({m.name})</span>}
        </h2>
        {action ?? (m && (
          <button type="button" onClick={() => navigate(m.path)} aria-label={`Go to ${m.name} module`} className="grid h-7 w-7 place-items-center rounded-lg text-ink-3 hover:bg-raised hover:text-ink"><Icon name="chevronRight" size={16} /></button>
        ))}
      </div>
      {children}
    </section>
  );
}

/** Circular progress ring (SVG). Value 0–100. Text carries the meaning; colour reinforces it. */
export function Ring({ value, size = 120, color = 'var(--color-cyan)', children, label }: { value: number | null; size?: number; color?: string; children: ReactNode; label: string }) {
  const r = size / 2 - 9, c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(100, value ?? 0));
  return (
    <div className="relative grid shrink-0 place-items-center" style={{ width: size, height: size }} role="img" aria-label={label}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-line)" strokeWidth={8} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={8} strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)}
          style={{ transition: 'stroke-dashoffset 700ms var(--ease-out)', filter: `drop-shadow(0 0 6px ${color})` }} />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">{children}</div>
    </div>
  );
}

function Bar({ value, max, color = 'var(--color-cyan)', label }: { value: number | null; max: number; color?: string; label: string }) {
  const p = value == null ? 0 : Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-line" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value ?? undefined}>
      <div className="h-full rounded-full transition-[width] duration-700" style={{ width: `${p}%`, background: color, boxShadow: `0 0 8px ${color}` }} />
    </div>
  );
}

function DemoTag() {
  return <Tooltip text={DEMO_CHANNEL_NOTE}>{(id) => <span aria-describedby={id} tabIndex={0} className="rounded border border-dashed border-attention/70 px-1 text-[9px] uppercase tracking-wide text-attention">demo</span>}</Tooltip>;
}

/* ───────────────────────────── hero ───────────────────────────── */

function OrbitArt() {
  return (
    <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1200 260" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <defs>
        <radialGradient id="mcEarth" cx="50%" cy="0%" r="80%"><stop offset="0" stopColor="#1f6fa8" /><stop offset=".55" stopColor="#0b3557" /><stop offset="1" stopColor="#04182c" /></radialGradient>
        <linearGradient id="mcAtmo" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#5fd6ff" stopOpacity=".7" /><stop offset="1" stopColor="#5fd6ff" stopOpacity="0" /></linearGradient>
        <linearGradient id="mcFade" x1="0" x2="1"><stop offset="0" stopColor="#030b17" /><stop offset=".45" stopColor="#030b17" stopOpacity=".55" /><stop offset="1" stopColor="#030b17" stopOpacity="0" /></linearGradient>
      </defs>
      {Array.from({ length: 70 }, (_, i) => <circle key={i} cx={(i * 173) % 1200} cy={(i * 61) % 170} r={i % 7 ? 0.8 : 1.4} fill="#dff6ff" opacity={0.25 + ((i * 13) % 10) / 20} />)}
      <ellipse cx="760" cy="760" rx="820" ry="560" fill="url(#mcAtmo)" opacity=".55" />
      <ellipse cx="760" cy="770" rx="800" ry="550" fill="url(#mcEarth)" />
      <path d="M260 250 C 420 215, 560 200, 700 214 S 980 240, 1200 236" stroke="#2f8a63" strokeWidth="18" fill="none" opacity=".35" />
      <path d="M200 238 C 480 196, 860 192, 1200 222" stroke="#ffffff" strokeWidth="3" fill="none" opacity=".18" />
      {/* original station line art */}
      <g className="hidden md:inline" transform="translate(700 118) rotate(-8) scale(.8)" stroke="#a9d8ff" strokeWidth="1.4" fill="none" opacity=".85">
        <line x1="-120" y1="0" x2="120" y2="0" strokeWidth="2.4" />
        {[-110, -70, 70, 110].map((x) => <g key={x}><rect x={x - 14} y="-34" width="28" height="26" fill="#0f3a5c" /><rect x={x - 14} y="8" width="28" height="26" fill="#0f3a5c" />
          {[0, 1, 2].map((k) => <line key={k} x1={x - 14} x2={x + 14} y1={-34 + 8.6 * (k + 1)} y2={-34 + 8.6 * (k + 1)} opacity=".5" />)}</g>)}
        <rect x="-26" y="-9" width="52" height="18" rx="6" fill="#123b5d" />
        <rect x="-8" y="-24" width="16" height="15" rx="4" fill="#123b5d" />
        <circle cx="0" cy="18" r="6" fill="#123b5d" />
      </g>
      <rect width="1200" height="260" fill="url(#mcFade)" />
    </svg>
  );
}

function MissionHero({ ship, next }: { ship?: ShipState; next?: { title: string; inH: number } | null }) {
  const { day, mode, reducedMotion } = useApp();
  const off = ship?.zones.filter((z) => z.environment.status !== 'nominal').length ?? 0;
  const pct = Math.round((day / MISSION_DAYS) * 100);
  return (
    <section aria-label="Mission overview" className="always-dark relative mb-4 overflow-hidden rounded-2xl border border-[rgb(0_229_255/0.18)]">
      <OrbitArt />
      <div className="relative grid gap-4 p-5 sm:p-7 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div>
          <div className="mono-label text-cyan">{MISSION_ID} · Earth → Mars transit · {mode === 'demo' ? 'Demo Mode (synthetic)' : 'Backend connected · synthetic mission'}</div>
          <h1 className="mt-1 text-3xl font-bold uppercase tracking-[0.12em] text-ink sm:text-4xl">Mission Control</h1>
          <p className="mt-1 text-ink-2">Crew health, environment and mission status at {dayLabel(day)}.</p>
          <ul className="mt-4 flex flex-wrap gap-2 text-sm" aria-label="Mission state">
            <li className="flex items-center gap-1.5 rounded-full border border-good/50 bg-good/10 px-3 py-1 text-good"><Icon name="checkCircle" size={15} />Crew {ship ? `${ship.crew.length}/4` : '…'} aboard</li>
            <li className={cx('flex items-center gap-1.5 rounded-full border px-3 py-1', off ? 'border-attention/50 bg-attention/10 text-attention' : 'border-good/50 bg-good/10 text-good')}><Icon name={off ? 'info' : 'checkCircle'} size={15} />{ship ? (off ? `${off} compartment${off > 1 ? 's' : ''} above reference` : 'Environment within reference') : 'Environment …'}</li>
            <li className="flex items-center gap-1.5 rounded-full border border-cyan/40 bg-cyan/10 px-3 py-1 text-cyan"><Icon name="clock" size={15} />Data window days 1–{MAX_DAY}</li>
          </ul>
          <div className="mt-4">
            <Button size="sm" variant="primary" icon="ship" onClick={() => document.getElementById('spacecraft-twin')?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' })}>
              View spacecraft twin
            </Button>
          </div>
        </div>
        <div className="hud flex items-center gap-4 rounded-2xl p-4">
          <Ring value={pct} size={112} label={`Mission progress ${pct} percent, day ${day} of ${MISSION_DAYS}`}><div><div className="tabular text-2xl font-bold text-ink">{pct}%</div><div className="text-[10px] text-ink-3">progress</div></div></Ring>
          <div className="min-w-0 text-sm">
            <div className="mono-label text-ink-3">Mission status</div>
            <div className="mt-1 text-ink">Day <span className="tabular font-semibold">{day}</span> of {MISSION_DAYS}</div>
            <div className="mt-2 mono-label text-ink-3">Next activity</div>
            <div className="truncate text-ink">{next ? next.title : '—'}</div>
            <div className="text-xs text-ink-3">{next ? (next.inH <= 0 ? 'in progress' : `in ${Math.floor(next.inH)} h ${Math.round((next.inH % 1) * 60)} min`) : 'from the crew calendar'}</div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ───────────────────────────── dashboard ───────────────────────────── */

/**
 * Mission Control dashboard (v0.5) – a single glance at the selected astronaut, crew, environment,
 * PHANTOM, recovery and the plan. Every value comes from the API (or labelled demo channels);
 * every control opens the module that owns the data.
 */
export function MissionDashboard({ ship }: { ship?: ShipState }) {
  const { api, astronautId, day, hour, dataVersion, role } = useApp();
  const key = `${api.mode}-${astronautId}-${day}-${dataVersion}`;
  const timeline = useResource(`tl-${key}`, () => api.timeline(astronautId, day));
  const analysis = useResource(role === 'flight-surgeon' ? `ph-${key}` : null, () => api.phantom(astronautId, day));
  const plan = useResource(`crew-${api.mode}`, () => api.crew(false));
  const cal = useResource(`cal-${api.mode}-${day}-${dataVersion}`, () => api.calendar(day));
  const next = useMemo(() => {
    const blocks = cal.data?.blocks[astronautId] ?? [];
    const cur = blocks.find((b) => b.start <= hour && hour < b.end);
    const nx = blocks.filter((b) => b.start > hour && b.kind !== 'sleep').sort((a, b) => a.start - b.start)[0];
    return nx ? { title: `${nx.title} · ${hourLabel(nx.start)}`, inH: nx.start - hour, current: cur } : cur ? { title: cur.title, inH: 0, current: cur } : null;
  }, [cal.data, astronautId, hour]);
  const row = timeline.data?.find((r) => r.day === day);

  return (
    <div>
      <MissionHero ship={ship} next={next} />
      <nav aria-label="Module shortcuts" className="mb-4 flex flex-wrap justify-center gap-1 rounded-2xl border border-line bg-surface/60 p-1">
        {MODULES.filter((m) => m.path !== '/').map((m) => (
          <button key={m.path} type="button" onClick={() => navigate(m.path)} className="interactive flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-semibold uppercase tracking-[0.12em] text-ink-2 hover:bg-raised hover:text-ink">
            <Icon name={m.icon} size={15} style={{ color: m.accent }} />{m.name}
          </button>
        ))}
      </nav>
      <div className="grid grid-cols-1 gap-4 md:max-[1399px]:grid-cols-2 min-[1400px]:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)_minmax(0,1fr)_minmax(0,1.1fr)]">
        <div className="flex min-w-0 flex-col gap-4">
          <ProfileCard analysis={analysis.data} ship={ship} />
          <MissionStatusCard ship={ship} analysis={analysis.data} />
          <CrewCard ship={ship} plan={plan.data} />
        </div>
        <TwinPreview analysis={analysis.data} />
        <div className="flex min-w-0 flex-col gap-4">
          <BiometricsCard rows={timeline.data} />
          <EnvironmentCard ship={ship} />
        </div>
        <div className="flex min-w-0 flex-col gap-4">
          <RiskCard analysis={analysis.data} />
          <Panel title="Trend & prediction" module="/phantom" label="Trend and prediction">
            {role === 'flight-surgeon' ? <><TrendPrediction horizon={7} height={150} compact />
              <p className="mt-1 text-[11px] text-ink-3">Solid: PHANTOM index (observed). Dashed + band: model projection, median and 10–90 % of runs – illustrative.</p></>
              : <p className="flex items-center gap-2 text-sm text-ink-2"><Icon name="lock" size={16} />Individual index trends are visible in the flight-surgeon role.</p>}
          </Panel>
          <RecoveryCard sleep={row?.sleep_hours ?? null} fatigue={row?.fatigue_1_10 ?? null} />
        </div>
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <NextActivity next={next} plan={plan.data} />
        <LabCta />
      </div>
    </div>
  );
}

function ProfileCard({ analysis, ship }: { analysis?: Analysis; ship?: ShipState }) {
  const { astronauts, astronautId, setAstronautId, role } = useApp();
  const a = useAstronaut();
  const loc = ship?.crew.find((c) => c.id === astronautId);
  const i = astronauts.findIndex((x) => x.id === astronautId);
  const step = (d: number) => astronauts.length && setAstronautId(astronauts[(i + d + astronauts.length) % astronauts.length].id);
  return (
    <section aria-label="Selected astronaut" className="card glow-hover flex items-center gap-4 p-4">
      <span className="relative grid h-16 w-16 shrink-0 place-items-center rounded-full text-lg font-bold text-white ring-2 ring-cyan/50 shadow-[0_0_24px_-6px_var(--color-cyan)]" style={{ background: CREW_HEX[astronautId] }}>{initials(a?.name ?? '?')}</span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-lg font-semibold text-ink">{a?.name ?? '…'}</div>
        <div className="truncate text-sm text-ink-2">{astronautId} · {a?.role}</div>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
          {role === 'flight-surgeon' && analysis ? <PhantomPill status={analysis.status} />
            : loc ? <span className={cx('flex items-center gap-1', loc.reduced_load_suggested ? 'text-attention' : 'text-good')}><span className="h-2 w-2 rounded-full bg-current" />{loc.reduced_load_suggested ? 'Reduced load suggested' : loc.availability}</span> : null}
          {loc && <span className="text-ink-3">· {loc.activity}</span>}
        </div>
      </div>
      <div className="flex flex-col gap-1">
        <button type="button" aria-label="Previous astronaut" onClick={() => step(-1)} className="grid h-7 w-7 place-items-center rounded-md border border-line text-ink-2 hover:border-line-strong hover:text-ink"><Icon name="chevronLeft" size={14} /></button>
        <button type="button" aria-label="Next astronaut" onClick={() => step(1)} className="grid h-7 w-7 place-items-center rounded-md border border-line text-ink-2 hover:border-line-strong hover:text-ink"><Icon name="chevronRight" size={14} /></button>
      </div>
    </section>
  );
}

function MissionStatusCard({ ship, analysis }: { ship?: ShipState; analysis?: Analysis }) {
  const { day, role } = useApp();
  const off = ship?.zones.filter((z) => z.environment.status !== 'nominal').length;
  const flags = ship?.crew.filter((c) => c.reduced_load_suggested).length;
  const pct = Math.round((day / MISSION_DAYS) * 100);
  const nominal = off === 0 && !flags;
  const rows: { label: string; value: string; tone: 'good' | 'attention' }[] = [
    { label: 'Crew', value: ship ? `${ship.crew.length} / 4` : '…', tone: 'good' },
    { label: 'Environment', value: off == null ? '…' : off ? `${off} above ref.` : 'Nominal', tone: off ? 'attention' : 'good' },
    { label: 'Planning flags', value: flags == null ? '…' : flags ? `${flags} reduced load` : 'None', tone: flags ? 'attention' : 'good' },
    { label: 'PHANTOM (selected)', value: role !== 'flight-surgeon' ? 'Restricted' : analysis ? analysis.status : '…', tone: analysis?.status === 'attention' ? 'attention' : 'good' },
  ];
  return (
    <Panel title="Mission status" label="Mission status" action={<span className={cx('flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs', nominal ? 'border-good/50 text-good' : 'border-attention/50 text-attention')}><Icon name={nominal ? 'checkCircle' : 'info'} size={13} />{nominal ? 'Nominal' : 'Attention'}</span>}>
      <div className="mb-1 flex justify-between text-sm"><span className="text-ink-2">Mission progress</span><span className="tabular font-semibold text-ink">{pct}%</span></div>
      <Bar value={day} max={MISSION_DAYS} label="Mission progress" />
      <ul className="mt-3 space-y-1.5 text-sm">
        {rows.map((r) => <li key={r.label} className="flex items-center gap-2"><span className={cx('h-2 w-2 rounded-full', r.tone === 'good' ? 'bg-good' : 'bg-attention')} aria-hidden /><span className="flex-1 text-ink-2">{r.label}</span><span className={r.tone === 'good' ? 'text-ink' : 'text-attention'}>{r.value}</span></li>)}
      </ul>
    </Panel>
  );
}

function CrewCard({ ship, plan }: { ship?: ShipState; plan?: { crew: { id: string; name: string; capacity: number }[]; schedule: { assignments: { astronaut_id: string | null; hours: number }[]; capacity: Record<string, number> } } }) {
  const { astronauts, astronautId, setAstronautId } = useApp();
  return (
    <Panel title="Crew" module="/co-orbit" label="Crew status and workload">
      <ul className="space-y-1.5">
        {astronauts.map((a) => {
          const loc = ship?.crew.find((c) => c.id === a.id);
          const load = plan ? plan.schedule.assignments.filter((x) => x.astronaut_id === a.id).reduce((s, x) => s + x.hours, 0) : null;
          const cap = plan?.schedule.capacity[a.id] ?? plan?.crew.find((c) => c.id === a.id)?.capacity ?? 8;
          const pct = load == null ? null : Math.round((load / cap) * 100);
          return (
            <li key={a.id}>
              <button type="button" onClick={() => setAstronautId(a.id)} aria-pressed={a.id === astronautId}
                className={cx('grid w-full grid-cols-[32px_minmax(0,1fr)_74px] items-center gap-2 rounded-lg border px-2 py-1.5 text-left', a.id === astronautId ? 'border-cyan/50 bg-cyan/10' : 'border-transparent hover:bg-raised/60')}>
                <span className="grid h-8 w-8 place-items-center rounded-full text-[10px] font-bold text-white" style={{ background: CREW_HEX[a.id] }}>{initials(a.name)}</span>
                <span className="min-w-0"><span className="block truncate text-sm text-ink">{a.name}</span>
                  <span className={cx('flex items-center gap-1 text-[11px]', loc?.reduced_load_suggested ? 'text-attention' : 'text-good')}><span className="h-1.5 w-1.5 rounded-full bg-current" />{loc ? (loc.reduced_load_suggested ? 'Reduced load' : loc.availability) : '…'}</span></span>
                <span className="text-right"><span className="tabular block text-xs text-ink-2">{pct == null ? '…' : `${pct}% load`}</span><Bar value={pct} max={100} color={pct != null && pct > 100 ? 'var(--color-attention)' : 'var(--color-aqua)'} label={`${a.name} task load`} /></span>
              </button>
            </li>
          );
        })}
      </ul>
      <p className="mt-2 text-[11px] text-ink-3">Load = assigned task hours ÷ task capacity (CO-ORBIT planner, synthetic).</p>
    </Panel>
  );
}

function TwinPreview({ analysis }: { analysis?: Analysis }) {
  const { reducedMotion, openWith } = useApp();
  const [system, setSystem] = useState<BodySystem | 'whole'>('whole');
  const { model, isAsset } = useHumanModel(useMemo(readBodyModel, []), true);
  const flagged = (s: BodySystem) => !!analysis?.signals.some((x) => x.flagged && METRICS[x.key].system === s);
  const highlight = useMemo(() => {
    const h: Record<string, { color: [number, number, number]; amount: number }> = {};
    for (const s of SYSTEMS) if (flagged(s)) h[s] = { color: hexToRgb('#ffbf69'), amount: 0.4 };
    if (system !== 'whole') h[system] = { color: hexToRgb('#00e5ff'), amount: 0.4 };
    return h;
  }, [system, analysis]); // eslint-disable-line react-hooks/exhaustive-deps
  const dim = useMemo(() => (id: string | null, layer?: string) => (system === 'whole' || layer === 'shell' || id === system ? 1 : 0.45), [system]);
  return (
    <Panel title="Digital twin" module="/body" label="Digital twin preview" className="always-dark !p-0 overflow-hidden">
      <div className="relative -mt-3">
        <div className="stage relative">
          <Viewport model={model} initialCamera={{ yaw: 0.25, pitch: 0.05, dist: 11, target: [0, 0.4, 0], fov: 0.72 }} focus={system === 'whole' ? null : SYSTEM_FOCUS[system]}
            highlight={highlight} dim={dim} reducedMotion={reducedMotion} height="clamp(400px, 55vh, 560px)" onPick={(id) => { if (id) setSystem(id as BodySystem); }}
            ariaLabel="3D human digital twin preview. Drag to rotate, scroll to zoom. Click a system to highlight it."
            instructions="Drag rotate · scroll zoom" />
          <div className="pointer-events-none absolute inset-x-0 bottom-24 mx-auto h-10 w-48 rounded-[50%] border border-cyan/50 shadow-[0_0_30px_rgba(0,229,255,.35)]" aria-hidden="true" />
        </div>
        <div role="radiogroup" aria-label="Body system" className="hud absolute left-2 top-2 flex flex-col gap-1 p-1">
          {(['whole', ...SYSTEMS] as const).map((s) => {
            const name = s === 'whole' ? 'Whole body' : BODY_SYSTEMS[s].label;
            return (
              <Tooltip key={s} text={`${name}${s !== 'whole' && flagged(s) ? ' · PHANTOM flag' : ''}`}>
                {(id) => (
                  <button type="button" role="radio" aria-checked={system === s} aria-label={name} aria-describedby={id} onClick={() => setSystem(s)}
                    className={cx('relative grid h-9 w-9 place-items-center rounded-lg', system === s ? 'bg-cyan/15 ring-1 ring-cyan/60' : 'hover:bg-white/5')}>
                    <Icon name={s === 'whole' ? 'body' : SYS_ICON[s]} size={17} style={{ color: s === 'whole' ? 'var(--color-cyan)' : BODY_SYSTEMS[s].color }} />
                    {s !== 'whole' && flagged(s) && <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-attention" aria-hidden />}
                  </button>
                )}
              </Tooltip>
            );
          })}
        </div>
        <div className="hud absolute bottom-9 left-2 right-2 flex items-center gap-2 p-2">
          <div className="min-w-0 flex-1"><div className="truncate text-xs font-semibold text-ink">{system === 'whole' ? 'Whole body' : BODY_SYSTEMS[system].label}</div>
            <div className="truncate text-[10px] text-ink-3">{system === 'whole' ? (isAsset ? 'Team GLB model · region mapping approximate' : 'Schematic model – not anatomical') : BODY_SYSTEMS[system].metrics.length ? BODY_SYSTEMS[system].metrics.map((k) => METRICS[k].short).join(' · ') : 'No API metric – visual layer'}</div></div>
          <Button size="sm" variant="primary" icon="body" onClick={() => openWith(`/body${system === 'whole' ? '' : `?system=${system}`}`, {})}>Open BODY</Button>
        </div>
      </div>
    </Panel>
  );
}

function BiometricsCard({ rows }: { rows?: Measurement[] }) {
  const { api, astronautId, day } = useApp();
  const recent = (rows ?? []).slice(-14);
  const today = recent.find((r) => r.day === day);
  const demo = api.mode === 'demo';
  const vit = demoVitals(astronautId, day);
  const vs = demoVitalsSeries(astronautId, day);
  return (
    <Panel title="Biometrics" module="/body" label="Biometrics" action={<SourceBadge source={today?.source ?? 'simulated'} />}>
      {!rows ? <div className="skeleton h-56 rounded-xl" /> : (
        <ul className="divide-y divide-line">
          {METRIC_KEYS.map((k) => (
            <li key={k} className="grid grid-cols-[minmax(0,88px)_minmax(0,1fr)_76px] items-center gap-2 py-2">
              <span className="flex items-center gap-1.5 text-xs text-ink-2"><span className="h-2 w-2 rounded-full" style={{ background: METRIC_COLOR[k] }} />{METRICS[k].short}</span>
              <Sparkline values={recent.map((r) => r[k])} color={METRIC_COLOR[k]} height={26} label={`${METRICS[k].label}, last 14 days`} />
              <span className="tabular text-right text-base font-semibold text-ink">{fmtMetric(k, today?.[k])}<span className="ml-0.5 text-[10px] font-normal text-ink-3">{METRICS[k].unit}</span></span>
            </li>
          ))}
          {([['SpO₂', demo ? `${vit.spo2_pct}` : '—', '%', vs.map((v) => v.spo2_pct)], ['Resp. rate', demo ? `${vit.resp_rate_min}` : '—', '/min', vs.map((v) => v.resp_rate_min)]] as const).map(([l, v, u, s]) => (
            <li key={l} className="grid grid-cols-[minmax(0,88px)_minmax(0,1fr)_76px] items-center gap-2 py-2">
              <span className="flex items-center gap-1.5 text-xs text-ink-2">{l}{demo ? <DemoTag /> : null}</span>
              {demo ? <Sparkline values={[...s]} color="var(--color-ink-3)" height={26} label={`${l} demo channel`} /> : <span className="text-[11px] text-ink-3">not provided by API</span>}
              <span className="tabular text-right text-base font-semibold text-ink-2">{v}<span className="ml-0.5 text-[10px] font-normal text-ink-3">{u}</span></span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function EnvironmentCard({ ship }: { ship?: ShipState }) {
  const { api, zoneId, day, hour, openWith } = useApp();
  const z = ship?.zones.find((x) => x.id === zoneId);
  const e = z?.environment;
  const ref = ship?.reference;
  const cab = demoCabin(zoneId, day, hour);
  const demo = api.mode === 'demo';
  const rows: { icon: IconName; label: string; value: string; bar: number | null; max: number; warn?: boolean; demo?: boolean }[] = e && ref ? [
    { icon: 'wind', label: 'CO₂', value: `${fmt(e.co2_ppm)} ppm`, bar: e.co2_ppm, max: ref.co2_ppm.high, warn: e.co2_ppm >= ref.co2_ppm.attention },
    { icon: 'thermo', label: 'Temp', value: `${fmt(e.temperature_c, 1)} °C`, bar: e.temperature_c, max: 30, warn: e.temperature_c < ref.temperature_c.low || e.temperature_c > ref.temperature_c.high },
    { icon: 'droplet', label: 'Humidity', value: `${fmt(e.humidity_pct)} %`, bar: e.humidity_pct, max: 100 },
    { icon: 'sun', label: 'Lighting', value: `${fmt(e.light_lux)} lux`, bar: e.light_lux, max: 1000 },
    { icon: 'wind', label: 'O₂', value: demo ? `${cab.o2_pct} %` : '—', bar: demo ? cab.o2_pct : null, max: 25, demo: true },
    { icon: 'gauge', label: 'Pressure', value: demo ? `${cab.pressure_kpa} kPa` : '—', bar: demo ? cab.pressure_kpa : null, max: 110, demo: true },
  ] : [];
  return (
    <Panel title="Environment" module="/symbiosis" label="Environment" action={<button type="button" onClick={() => openWith('/symbiosis', { zoneId })} aria-label="Open SYMBIOSIS for this compartment" className="grid h-7 w-7 place-items-center rounded-lg text-ink-3 hover:bg-raised hover:text-ink"><Icon name="chevronRight" size={16} /></button>}>
      <div className="mb-2 text-xs text-ink-3">{z ? `${z.name} · ${hourLabel(hour)}` : 'Loading…'}</div>
      {!e ? <div className="skeleton h-44 rounded-xl" /> : (
        <ul className="space-y-2">
          {rows.map((r) => (
            <li key={r.label} className="grid grid-cols-[96px_80px_minmax(0,1fr)] items-center gap-2 text-sm">
              <span className="flex items-center gap-1.5 text-ink-2"><Icon name={r.icon} size={14} className={r.warn ? 'text-attention' : 'text-aqua'} />{r.label}{r.demo && demo && <DemoTag />}</span>
              <span className={cx('tabular text-right font-semibold', r.warn ? 'text-attention' : r.demo && !demo ? 'text-ink-3' : 'text-ink')}>{r.value}</span>
              {r.bar == null ? <span className="text-[10px] text-ink-3">not in API</span> : <Bar value={r.bar} max={r.max} color={r.warn ? 'var(--color-attention)' : 'var(--color-aqua)'} label={`${r.label} ${r.value}`} />}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function RiskCard({ analysis }: { analysis?: Analysis }) {
  const { role, setRole } = useApp();
  if (role !== 'flight-surgeon') {
    return (
      <Panel title="Risk analytics" module="/phantom" label="Risk analytics">
        <div className="flex flex-col items-start gap-2 text-sm text-ink-2">
          <span className="flex items-center gap-2"><Icon name="lock" size={16} />Individual PHANTOM results are visible in the flight-surgeon role.</span>
          <Button size="sm" icon="heart" onClick={() => setRole('flight-surgeon')}>View as flight surgeon</Button>
          <span className="text-[11px] text-ink-3">Role switching simulates permissions in the UI; it is not authentication.</span>
        </div>
      </Panel>
    );
  }
  const by = (s: BodySystem) => {
    const sig = analysis?.signals.filter((x) => METRICS[x.key].system === s) ?? [];
    return sig.length ? Math.max(...sig.map((x) => Math.max(0, x.adverse_deviation))) : null;
  };
  const score = analysis?.score ?? null;
  const tone = analysis?.status === 'attention' ? 'var(--color-attention)' : 'var(--color-good)';
  return (
    <Panel title="Risk analytics" module="/phantom" label="Risk analytics">
      {!analysis ? <div className="skeleton h-36 rounded-xl" /> : (
        <div className="flex items-center gap-4">
          <Ring value={score} size={120} color={tone} label={`PHANTOM deviation index ${score ?? 'not available'} of 100, status ${analysis.status}`}>
            <div><div className="tabular text-2xl font-bold text-ink">{score ?? '—'}</div><div className="text-[10px] leading-tight text-ink-3">deviation<br />index /100</div><div className="mt-0.5 text-[11px] font-semibold capitalize" style={{ color: tone }}>{analysis.status}</div></div>
          </Ring>
          <ul className="min-w-0 flex-1 space-y-2">
            {SYSTEMS.map((s) => {
              const v = by(s);
              return (
                <li key={s} className="text-xs">
                  <div className="mb-0.5 flex items-center justify-between gap-2"><span className="flex items-center gap-1.5 truncate text-ink-2"><Icon name={SYS_ICON[s]} size={12} style={{ color: BODY_SYSTEMS[s].color }} />{BODY_SYSTEMS[s].label}</span><span className="tabular text-ink">{v == null ? 'n/a' : `${v.toFixed(1)}σ`}</span></div>
                  {v == null ? <div className="h-1.5 rounded-full border border-dashed border-line" aria-hidden /> : <Bar value={v} max={analysis.method.flag_threshold_z * 2} color={v >= analysis.method.flag_threshold_z ? 'var(--color-attention)' : 'var(--color-good)'} label={`${BODY_SYSTEMS[s].label} largest adverse deviation ${v.toFixed(1)} sigma`} />}
                </li>
              );
            })}
          </ul>
        </div>
      )}
      <p className="mt-2 text-[11px] text-ink-3">Per system: largest adverse deviation from personal baseline (robust z). Not a probability, not a diagnosis.</p>
    </Panel>
  );
}

function RecoveryCard({ sleep, fatigue }: { sleep: number | null; fatigue: number | null }) {
  const { api, astronautId, dataVersion } = useApp();
  const res = useResource(`rec-${api.mode}-${astronautId}-${dataVersion}`, () => api.recovery(astronautId));
  return (
    <Panel title="Recovery" module="/recovery" label="Recovery">
      <Async res={res}>{(ss) => {
        const mean = ss.length ? ss.reduce((t, x) => t + x.after_mood, 0) / ss.length : null;
        const change = ss.length ? ss.reduce((t, x) => t + x.after_mood - x.before_mood, 0) / ss.length : null;
        return (
          <div className="flex items-center gap-4">
            <Ring value={mean == null ? 0 : mean * 10} size={112} color="var(--color-aqua)" label={mean == null ? 'No recovery sessions yet' : `Mean self-rated mood after sessions ${mean.toFixed(1)} of 10`}>
              <div><div className="tabular text-xl font-bold text-ink">{mean == null ? '—' : mean.toFixed(1)}</div><div className="text-[10px] leading-tight text-ink-3">mood after<br />sessions /10</div></div>
            </Ring>
            <ul className="min-w-0 flex-1 space-y-2 text-xs">
              <li><div className="mb-0.5 flex justify-between"><span className="text-ink-2">Sleep (last night)</span><span className="tabular text-ink">{sleep == null ? '—' : `${sleep.toFixed(1)} h`}</span></div><Bar value={sleep} max={10} color="var(--color-aqua)" label="Sleep hours" /></li>
              <li><div className="mb-0.5 flex justify-between"><span className="text-ink-2">Fatigue (self-report)</span><span className="tabular text-ink">{fatigue == null ? '—' : `${fatigue.toFixed(1)}/10`}</span></div><Bar value={fatigue} max={10} color={fatigue != null && fatigue >= 6 ? 'var(--color-attention)' : 'var(--color-aqua)'} label="Fatigue" /></li>
              <li className="flex justify-between"><span className="text-ink-2">Sessions</span><span className="tabular text-ink">{ss.length}{change != null ? ` · mean change ${change >= 0 ? '+' : ''}${change.toFixed(1)}` : ''}</span></li>
            </ul>
          </div>
        );
      }}</Async>
      <p className="mt-2 text-[11px] text-ink-3">Self-ratings without a control condition – a personal pattern, not a clinical index.</p>
    </Panel>
  );
}

function NextActivity({ next, plan }: { next: { title: string; inH: number } | null; plan?: { schedule: { assignments: { astronaut_id: string | null; hours: number }[]; capacity: Record<string, number> } } }) {
  const { astronautId, openWith } = useApp();
  const load = plan ? plan.schedule.assignments.filter((x) => x.astronaut_id === astronautId).reduce((s, x) => s + x.hours, 0) : null;
  const cap = plan?.schedule.capacity[astronautId] ?? null;
  const pct = load != null && cap ? Math.round((load / cap) * 100) : null;
  return (
    <section aria-label="Next activity" className="card glow-hover flex flex-wrap items-center gap-4 p-4">
      <span className="grid h-11 w-11 place-items-center rounded-xl border border-line bg-raised text-cyan"><Icon name="calendar" size={20} /></span>
      <div className="min-w-0 flex-1"><div className="text-sm font-semibold text-ink">Next: {next?.title ?? '—'}</div><div className="text-xs text-ink-3">{next ? (next.inH <= 0 ? 'in progress' : `in ${Math.floor(next.inH)} h ${Math.round((next.inH % 1) * 60)} min (mission time)`) : 'no further blocks today'}</div></div>
      <div className="w-40"><div className="flex justify-between text-xs"><span className="text-ink-3">Today’s task load</span><span className="tabular font-semibold text-ink">{pct == null ? '…' : `${pct}%`}</span></div><Bar value={pct} max={100} label="Today's task load" /></div>
      <Button size="sm" variant="ghost" iconRight="arrowRight" onClick={() => openWith('/co-orbit?tab=schedule', {})}>Timeline</Button>
    </section>
  );
}

function LabCta() {
  const { scenario, applyScenario } = useApp();
  return (
    <section aria-label="Mission Lab" className="card glow-hover flex items-center gap-4 border-cyan/40 p-4">
      <span className="grid h-11 w-11 place-items-center rounded-xl border border-cyan/50 bg-cyan/10 text-cyan"><Icon name="flask" size={20} /></span>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold uppercase tracking-[0.1em] text-ink">Mission Lab</div>
        <div className="truncate text-xs text-ink-3">{scenario ? `Applied: ${scenario.title} – effects shown across modules` : 'Simulate scenarios and apply one to the whole mission view'}</div>
      </div>
      {scenario && <Button size="sm" variant="ghost" icon="reset" onClick={() => applyScenario(null)}>Reset</Button>}
      <Button size="sm" variant="primary" iconRight="arrowRight" onClick={() => navigate('/mission-lab')}>Open</Button>
    </section>
  );
}
