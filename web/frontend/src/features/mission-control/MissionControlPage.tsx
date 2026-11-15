import { useMemo, useState, type ReactNode } from 'react';
import { CAPABILITIES, type Analysis, type CrewLocation, type PhantomHistory, type ShipState, type Zone, type ZoneId } from '../../api/types';
import { Sparkline } from '../../charts';
import { MODULES } from '../../layout/AppShell';
import { CREW_HEX, dayLabel, fmt, hourLabel, initials, METRICS } from '../../lib/format';
import { navigate } from '../../lib/router';
import { useResource } from '../../lib/useResource';
import { MAX_DAY, useApp } from '../../state/AppState';
import { Async, Button, cx, Icon, Notice, PhantomPill, Pill, SourceBadge, Tooltip, type IconName } from '../../ui';
import { DeckPlan } from '../shared/DeckPlan';
import { MissionDashboard } from './Dashboard';
import { ENV_ICON, ENV_TEXT, ShipTwin } from '../shared/ShipTwin';

const MODULE_OF_ZONE: Record<Zone['module'], { name: string; path: string; icon: IconName }> = {
  'co-orbit': { name: 'CO-ORBIT', path: '/co-orbit', icon: 'users' },
  body: { name: 'BODY', path: '/body', icon: 'body' },
  phantom: { name: 'PHANTOM', path: '/phantom', icon: 'brain' },
  recovery: { name: 'RECOVERY', path: '/recovery', icon: 'leaf' },
  symbiosis: { name: 'SYMBIOSIS', path: '/symbiosis', icon: 'waves' },
};

type CrewHistory = { id: string; name: string; h: PhantomHistory };

/**
 * MISSION CONTROL – the visual centre of AETHER.
 * One composition: the spacecraft twin in the middle, mission KPIs on the left, the selected
 * compartment / crew member on the right, the mission timeline underneath, then the crew map,
 * alerts & events and today's work. Selection is shared with every module via AppState.
 */
export function MissionControlPage() {
  const { api, day, hour, role, astronauts, zoneId, setZoneId, density, dataVersion, hasCapability } = useApp();
  const ship = useResource(`ship-${api.mode}-${day}-${hour}-${dataVersion}`, () => api.ship(day, hour));
  const [crewId, setCrewId] = useState<string | null>(null);
  const surgeon = role === 'flight-surgeon';
  const ids = astronauts.map((a) => a.id).join(',');
  const analyses = useResource(surgeon && ids ? `phall-${api.mode}-${day}-${ids}-${dataVersion}` : null,
    () => Promise.all(astronauts.map((a) => api.phantom(a.id, day).then((r) => [a, r] as const))));
  const histories = useResource<CrewHistory[]>(surgeon && ids && hasCapability(CAPABILITIES.phantomHistory) ? `phhall-${api.mode}-${ids}-${dataVersion}` : null,
    () => Promise.all(astronauts.map((a) => api.phantomHistory(a.id, MAX_DAY, 41).then((h) => ({ id: a.id, name: a.name, h })))));
  const plan = useResource(`crew-${api.mode}`, () => api.crew(false));

  const selectZone = (z: ZoneId) => { setZoneId(z); setCrewId(null); };
  const selectCrew = (id: string) => { setCrewId(id); const z = ship.data?.crew.find((c) => c.id === id)?.zone; if (z) setZoneId(z); };
  const compact = density === 'compact';

  return (
    <div className="space-y-5">
      <MissionDashboard ship={ship.data} />

      <div className="flex flex-wrap items-end justify-between gap-3 pt-4">
        <div><div className="mono-label text-cyan">Spacecraft & operations</div><h2 className="text-xl font-semibold text-ink">Spacecraft twin, crew map and alerts</h2>
          {!compact && <p className="text-sm text-ink-2">Pick a compartment or a crew member on the model, the deck plan or the timeline – every module opens with that context.</p>}</div>
        <div className="flex gap-2"><Button icon="waves" onClick={() => navigate('/symbiosis')}>Environment</Button><Button variant="primary" icon="flask" onClick={() => navigate('/mission-lab')}>Explore scenarios</Button></div>
      </div>

      <section id="spacecraft-twin" tabIndex={-1} aria-label="Spacecraft digital twin" className="always-dark stage relative scroll-mt-40 overflow-hidden rounded-2xl border border-line">
        <div className={cx('grid gap-3 p-3', compact ? 'xl:grid-cols-[220px_minmax(0,1fr)_300px]' : 'xl:grid-cols-[250px_minmax(0,1fr)_340px]')}>
          <KpiRail ship={ship.data} analyses={analyses.data?.map((x) => x[1])} plan={plan.data?.schedule} compact={compact} />
          <div className="relative min-w-0">
            <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-start justify-between p-3">
              <div>
                <div className="flex items-center gap-2"><span className="mono-label text-cyan">Mission twin · {dayLabel(day)} · {hourLabel(hour)}</span><span className="pointer-events-auto"><SourceBadge source="simulated" /></span></div>
                <div className="mt-0.5 text-xs text-ink-3">Earth → Mars transit · crew positions follow the synthetic schedule</div>
              </div>
            </div>
            <Async res={ship} loadingLabel="Loading spacecraft">
              {(s) => <ShipTwin ship={s} zoneId={zoneId} crewId={crewId} onZone={selectZone} onCrew={selectCrew} focusSelected colourByStatus height={compact ? 'clamp(380px, 52vh, 500px)' : 'clamp(420px, 58vh, 600px)'} className="!rounded-xl border border-line/60 !bg-transparent" />}
            </Async>
          </div>
          <Async res={ship} loadingLabel="Loading inspector">
            {(s) => {
              const person = crewId ? s.crew.find((c) => c.id === crewId) : undefined;
              return person
                ? <CrewInspector person={person} zone={s.zones.find((z) => z.id === person.zone)!} onBack={() => setCrewId(null)} analysis={analyses.data?.find((x) => x[0].id === person.id)?.[1]} />
                : <ZoneInspector zone={s.zones.find((z) => z.id === zoneId)!} crew={s.crew.filter((c) => c.zone === zoneId)} onCrew={selectCrew} ship={s} compact={compact} />;
            }}
          </Async>
        </div>
        <MissionTimeline histories={histories.data} restricted={!surgeon} />
      </section>

      <div className={cx('grid gap-5', compact ? 'xl:grid-cols-3' : 'xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]')}>
        <CrewMap ship={ship.data} crewId={crewId} onZone={selectZone} onCrew={selectCrew} />
        <AlertsPanel ship={ship.data} analyses={analyses.data} histories={histories.data} plan={plan.data} />
        {compact && <CurrentTasks ship={ship.data} onCrew={selectCrew} />}
      </div>
      {!compact && <CurrentTasks ship={ship.data} onCrew={selectCrew} />}
      <ModuleTiles compact={compact} />
      {ship.data && <p className="text-xs text-ink-3">{ship.data.note} {ship.data.reference.note}</p>}
    </div>
  );
}

/* ───────────────────────────── HUD panels ───────────────────────────── */

function Hud({ title, children, className, actions, label }: { title: ReactNode; children: ReactNode; className?: string; actions?: ReactNode; label?: string }) {
  return (
    <section aria-label={label} className={cx('hud rounded-xl p-3', className)}>
      <div className="mb-2 flex items-center justify-between gap-2"><div className="mono-label text-ink-3">{title}</div>{actions}</div>
      {children}
    </section>
  );
}

function Kpi({ label, value, sub, tone, icon, onClick, tip }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'good' | 'attention' | 'high' | 'muted'; icon: IconName; onClick?: () => void; tip: string }) {
  const toneCls = tone === 'good' ? 'text-good' : tone === 'attention' ? 'text-attention' : tone === 'high' ? 'text-high' : 'text-ink';
  const body = (
    <>
      <span className={cx('grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-line bg-raised/60', toneCls)}><Icon name={icon} size={17} /></span>
      <span className="min-w-0 flex-1">
        <span className="mono-label block text-ink-3">{label}</span>
        <span className={cx('tabular block truncate font-semibold', toneCls)}>{value}</span>
        {sub && <span className="block truncate text-xs text-ink-3">{sub}</span>}
      </span>
      {onClick && <Icon name="chevronRight" size={15} className="text-ink-3" />}
    </>
  );
  return (
    <Tooltip text={tip} block>
      {(id) => onClick
        ? <button type="button" aria-describedby={id} onClick={onClick} className="interactive flex w-full items-center gap-3 rounded-lg border border-transparent px-2 py-2 text-left hover:border-line-strong hover:bg-raised/40">{body}</button>
        : <div aria-describedby={id} tabIndex={0} className="flex items-center gap-3 rounded-lg px-2 py-2 outline-none focus-visible:ring-2 focus-visible:ring-cyan">{body}</div>}
    </Tooltip>
  );
}

function KpiRail({ ship, analyses, plan, compact }: { ship?: ShipState; analyses?: Analysis[]; plan?: { assignments: { astronaut_id: string | null }[]; unassigned: number }; compact: boolean }) {
  const { day, hour, role, mode, openWith } = useApp();
  const off = ship?.zones.filter((z) => z.environment.status !== 'nominal').length;
  const count = (a: string) => ship?.crew.filter((c) => c.availability === a).length ?? 0;
  const flags = ship?.crew.filter((c) => c.reduced_load_suggested).length ?? 0;
  const review = analyses?.filter((a) => a.status === 'attention').length;
  const progress = Math.round((day / MAX_DAY) * 100);
  return (
    <Hud title="Mission metrics" label="Mission metrics" className="flex flex-col">
      <div className="mb-2 rounded-lg border border-line bg-raised/40 p-2.5">
        <div className="flex items-baseline justify-between"><span className="tabular text-2xl font-semibold text-ink">{dayLabel(day)}</span><span className="tabular text-sm text-ink-2">{hourLabel(hour)}</span></div>
        <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-line" role="progressbar" aria-label="Mission timeline position" aria-valuemin={1} aria-valuemax={MAX_DAY} aria-valuenow={day}>
          <div className="h-full rounded-full bg-cyan" style={{ width: `${progress}%` }} />
        </div>
        {!compact && <div className="mt-1 text-xs text-ink-3">{progress}% of the recorded mission window · {mode === 'demo' ? 'Demo Mode' : 'Backend connected · synthetic mission'}</div>}
      </div>
      <div className="space-y-0.5">
        <Kpi icon="users" label="Crew now" tip="Derived availability from the crew schedule at this time"
          value={ship ? `${count('on task')} on task · ${count('resting')} resting` : '…'} sub={ship ? `${count('available') + count('exercise') + count('check-in')} available / other` : undefined}
          onClick={() => openWith('/co-orbit', {})} />
        <Kpi icon={off ? 'info' : 'checkCircle'} label="Environment" tone={off == null ? 'muted' : off ? 'attention' : 'good'} tip="Compartments compared with the demo reference bands"
          value={ship ? (off ? `${off} of 5 above reference` : 'All within reference') : '…'} sub="demo reference bands" onClick={() => openWith('/symbiosis', {})} />
        {role === 'flight-surgeon'
          ? <Kpi icon="brain" label="PHANTOM" tone={review == null ? 'muted' : review ? 'attention' : 'good'} tip="Research analysis of deviation from personal baseline — not a diagnosis"
            value={review == null ? '…' : review ? `${review} review suggested` : 'No reviews'} sub="research prototype" onClick={() => openWith('/phantom', {})} />
          : <Kpi icon="lock" label="PHANTOM" tip="Individual analysis is visible only in the flight-surgeon role (Settings)" value="Restricted" sub={`${flags} reduced-load flag${flags === 1 ? '' : 's'}`} />}
        <Kpi icon="calendar" label="Tasks today" tone={plan?.unassigned ? 'attention' : undefined} tip="Assignments from the CO-ORBIT planner"
          value={plan ? `${plan.assignments.length - plan.unassigned}/${plan.assignments.length} assigned` : '…'} sub={plan?.unassigned ? `${plan.unassigned} need an owner` : 'no conflicts'}
          onClick={() => navigate('/co-orbit?tab=tasks')} />
        {!compact && <Kpi icon="database" label="Data source" tip="Where the numbers on this screen come from" value={mode === 'demo' ? 'Synthetic (demo mock)' : 'Backend API'} sub="all values synthetic" onClick={() => navigate('/settings')} />}
      </div>
    </Hud>
  );
}

function EnvRow({ icon, label, value, unit, refText, status }: { icon: IconName; label: string; value: string; unit: string; refText?: string; status?: 'attention' | 'high' | null }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-line bg-raised/40 px-2.5 py-2">
      <Icon name={icon} size={15} className={status ? ENV_TEXT[status] : 'text-cyan'} />
      <span className="flex-1 text-xs text-ink-3">{label}</span>
      <span className={cx('tabular text-sm font-semibold', status ? ENV_TEXT[status] : 'text-ink')}>{value}<span className="ml-0.5 text-xs font-normal text-ink-3">{unit}</span></span>
      {refText && <span className="hidden text-[11px] text-ink-3 2xl:inline">{refText}</span>}
    </div>
  );
}

function ZoneInspector({ zone, crew, onCrew, ship, compact }: { zone: Zone; crew: CrewLocation[]; onCrew: (id: string) => void; ship: ShipState; compact: boolean }) {
  const { api, day, openWith } = useApp();
  const hist = useResource(`zh-${api.mode}-${zone.id}-${day}`, () => api.zoneHistory(zone.id, Math.max(1, day - 20), day));
  const e = zone.environment;
  const mod = MODULE_OF_ZONE[zone.module];
  const ref = ship.reference;
  const co2s = e.co2_ppm >= ref.co2_ppm.high ? 'high' : e.co2_ppm >= ref.co2_ppm.attention ? 'attention' : null;
  const ts = e.temperature_c < ref.temperature_c.low || e.temperature_c > ref.temperature_c.high ? 'attention' : null;
  const hs = e.humidity_pct < ref.humidity_pct.low || e.humidity_pct > ref.humidity_pct.high ? 'attention' : null;
  return (
    <Hud title="Selected compartment" label={`Selected compartment: ${zone.name}`} className="flex flex-col" actions={<SourceBadge source={e.source} />}>
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-lg font-semibold text-ink">{zone.name}</h2>
        <span className={cx('flex items-center gap-1 text-xs font-medium', ENV_TEXT[e.status])}><Icon name={ENV_ICON[e.status]} size={13} />{e.status}</span>
      </div>
      {!compact && <p className="mt-0.5 text-sm text-ink-2">{zone.description}</p>}
      <div className="mt-2 grid gap-1.5">
        <EnvRow icon="wind" label="CO₂" value={fmt(e.co2_ppm)} unit="ppm" refText={`ref < ${ref.co2_ppm.attention}`} status={co2s} />
        <EnvRow icon="thermo" label="Temperature" value={fmt(e.temperature_c, 1)} unit="°C" refText={`${ref.temperature_c.low}–${ref.temperature_c.high}`} status={ts} />
        <EnvRow icon="droplet" label="Humidity" value={fmt(e.humidity_pct, 0)} unit="%" refText={`${ref.humidity_pct.low}–${ref.humidity_pct.high}`} status={hs} />
        <EnvRow icon="sun" label="Lighting" value={fmt(e.light_lux)} unit="lux" />
      </div>
      <div className="mt-2">
        <div className="mb-1 text-xs text-ink-3">CO₂ · last 21 days</div>
        <Async res={hist}>{(h) => <Sparkline values={h.points.map((p) => p.co2_ppm)} label={`CO₂ trend for ${zone.name}`} height={36} />}</Async>
      </div>
      <div className="mt-2">
        <div className="mono-label mb-1 text-ink-3">Crew here · {crew.length}</div>
        {crew.length ? (
          <ul className="space-y-1">
            {crew.map((c) => (
              <li key={c.id}>
                <button type="button" onClick={() => onCrew(c.id)} className="interactive flex w-full items-center gap-2 rounded-lg border border-line px-2 py-1.5 text-left text-sm hover:border-line-strong">
                  <span className="grid h-6 w-6 place-items-center rounded-full text-[10px] font-bold text-white" style={{ background: CREW_HEX[c.id] }}>{initials(c.name)}</span>
                  <span className="min-w-0 flex-1 truncate"><span className="text-ink">{c.name}</span> <span className="text-xs text-ink-3">· {c.activity}</span></span>
                  <Icon name="chevronRight" size={15} className="text-ink-3" />
                </button>
              </li>
            ))}
          </ul>
        ) : <p className="text-sm text-ink-3">Nobody scheduled here now. Change the mission time to see crew arrive.</p>}
      </div>
      <div className="mt-auto flex flex-wrap gap-2 border-t border-line pt-3">
        <Button size="sm" variant="primary" icon="waves" onClick={() => openWith('/symbiosis', { zoneId: zone.id })}>Environment detail</Button>
        {mod.path !== '/symbiosis' && <Button size="sm" icon={mod.icon} onClick={() => openWith(mod.path, { zoneId: zone.id })}>Open {mod.name}</Button>}
      </div>
    </Hud>
  );
}

function CrewInspector({ person, zone, onBack, analysis }: { person: CrewLocation; zone: Zone; onBack: () => void; analysis?: Analysis }) {
  const { role, openWith } = useApp();
  const surgeon = role === 'flight-surgeon';
  return (
    <Hud title="Crew member" label={`Crew member: ${person.name}`} className="flex flex-col" actions={<Button size="sm" variant="ghost" icon="chevronLeft" onClick={onBack}>Compartment</Button>}>
      <div className="flex items-center gap-3">
        <span className="grid h-12 w-12 place-items-center rounded-full text-sm font-bold text-white ring-2 ring-white/20" style={{ background: CREW_HEX[person.id] }}>{initials(person.name)}</span>
        <div className="min-w-0 text-sm"><div className="truncate text-base font-semibold text-ink">{person.name}</div><div className="text-ink-2">{person.activity}</div><div className="text-xs text-ink-3">{zone.name} · location from schedule</div></div>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        <Pill tone="info" icon="clock">{person.availability}</Pill>
        {person.reduced_load_suggested && <Pill tone="attention">Reduced load suggested</Pill>}
      </div>
      <div className="mt-3">
        {surgeon ? (
          analysis ? (
            <div className="rounded-lg border border-line bg-raised/40 p-2.5">
              <div className="mb-1 flex items-center justify-between"><span className="mono-label text-violet">PHANTOM</span><PhantomPill status={analysis.status} /></div>
              <ul className="mt-1 space-y-1">
                {analysis.signals.map((s) => (
                  <li key={s.key} className="flex items-center gap-2 text-xs">
                    <span className="w-24 shrink-0 truncate text-ink-3">{METRICS[s.key].short}</span>
                    <span className="relative h-1.5 flex-1 rounded-full bg-line" aria-hidden="true">
                      <span className="absolute top-0 h-1.5 rounded-full" style={{ left: '50%', width: `${Math.min(50, Math.abs(s.deviation) * 12.5)}%`, transform: s.deviation < 0 ? 'translateX(-100%)' : undefined, background: s.flagged ? 'var(--color-attention)' : 'var(--color-violet)' }} />
                    </span>
                    <span className={cx('tabular w-12 text-right', s.flagged ? 'text-attention' : 'text-ink-2')}>{s.deviation > 0 ? '+' : ''}{s.deviation.toFixed(1)}σ</span>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-ink-2">{analysis.explanation}</p>
            </div>
          ) : <p className="text-sm text-ink-3">Loading analysis…</p>
        ) : (
          <Notice tone="unknown" title="Physiological detail restricted">Crew view shows only derived availability. Switch to the flight-surgeon role in Settings to see PHANTOM results (UI simulation of permissions).</Notice>
        )}
      </div>
      <div className="mt-auto flex flex-wrap gap-2 border-t border-line pt-3">
        <Button size="sm" variant="primary" icon="body" onClick={() => openWith('/body', { astronautId: person.id })}>Open BODY twin</Button>
        {surgeon && <Button size="sm" icon="brain" onClick={() => openWith('/phantom', { astronautId: person.id })}>PHANTOM detail</Button>}
        <Button size="sm" icon="calendar" onClick={() => openWith('/co-orbit?tab=schedule', { astronautId: person.id })}>Schedule</Button>
      </div>
    </Hud>
  );
}

/* ───────────────────────────── Timeline ───────────────────────────── */

const HOURS = [0, 3, 6, 9, 12, 15, 18, 21];

/** Mission timeline: day track with PHANTOM alert episodes (flight-surgeon) and a time-of-day selector. */
function MissionTimeline({ histories, restricted }: { histories?: CrewHistory[]; restricted: boolean }) {
  const { day, setDay, hour, setHour, setAstronautId } = useApp();
  const pct = (d: number) => ((d - 1) / (MAX_DAY - 1)) * 100;
  const ticks = [1, 10, 20, 30, 40, 50, 60, MAX_DAY];
  return (
    <section aria-label="Mission timeline" className="border-t border-line/70 px-4 pb-4 pt-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="mono-label text-ink-3">Mission timeline · days 1–{MAX_DAY}</div>
        <div className="flex items-center gap-3 text-xs text-ink-3">
          {restricted ? <span className="flex items-center gap-1"><Icon name="lock" size={12} />PHANTOM episodes hidden in crew view</span>
            : <span className="flex items-center gap-1.5"><span className="inline-block h-2 w-4 rounded-sm bg-attention/70" />PHANTOM attention episode (research analysis)</span>}
        </div>
      </div>
      <div className="relative">
        {!restricted && histories && (
          <div className="mb-1 space-y-1" aria-label="PHANTOM attention episodes by crew member" role="group">
            {histories.map((c) => (
              <div key={c.id} className="relative flex h-4 items-center">
                <span className="absolute -left-0.5 z-10 grid h-4 w-4 -translate-x-full place-items-center rounded-full text-[8px] font-bold text-white" style={{ background: CREW_HEX[c.id] }} aria-hidden="true">{initials(c.name)}</span>
                <div className="absolute inset-x-0 top-1/2 h-px bg-line" aria-hidden="true" />
                {c.h.alerts.map((a, i) => (
                  <button key={i} type="button" onClick={() => { setAstronautId(c.id); setDay(a.end_day); }}
                    aria-label={`${c.name}: ${a.label}, days ${a.start_day}–${a.end_day}. Jump to day ${a.end_day}`} title={`${c.name} · ${a.label} · days ${a.start_day}–${a.end_day}`}
                    className="interactive absolute h-3 rounded-sm bg-attention/70 hover:bg-attention focus-visible:outline-2 focus-visible:outline-cyan"
                    style={{ left: `${pct(a.start_day)}%`, width: `max(8px, ${pct(a.end_day + 1) - pct(a.start_day)}%)` }} />
                ))}
              </div>
            ))}
          </div>
        )}
        <div className="relative h-8">
          <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-line" aria-hidden="true" />
          <div className="absolute left-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-gradient-to-r from-teal-600 to-cyan" style={{ width: `${pct(day)}%` }} aria-hidden="true" />
          <div className="absolute top-1/2 h-1.5 -translate-y-1/2 border-x border-dashed border-violet/60 bg-violet/10" style={{ left: `${pct(41)}%`, right: 0 }} aria-hidden="true" title="PHANTOM analysis window" />
          <span className="absolute top-1/2 z-10 h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-cyan shadow-[0_0_14px_var(--color-cyan)]" style={{ left: `${pct(day)}%` }} aria-hidden="true" />
          <input type="range" min={1} max={MAX_DAY} step={1} value={day} onChange={(e) => setDay(Number(e.target.value))}
            aria-label="Mission day on timeline" aria-valuetext={dayLabel(day)}
            className="absolute inset-0 z-20 h-full w-full cursor-pointer opacity-0" />
        </div>
        <div className="relative h-4 text-[10px] text-ink-3" aria-hidden="true">
          {ticks.map((t) => <span key={t} className="tabular absolute -translate-x-1/2" style={{ left: `${pct(t)}%` }}>{t}</span>)}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className="mono-label text-ink-3">Time of day</span>
        <div role="radiogroup" aria-label="Mission time window, 3 hours each" className="flex flex-wrap gap-1">
          {HOURS.map((h) => {
            const on = Math.floor(hour / 3) * 3 === h;
            return (
              <button key={h} type="button" role="radio" aria-checked={on} onClick={() => setHour(h)}
                className={cx('interactive tabular rounded-md border px-2 py-1 text-xs', on ? 'border-cyan bg-teal-600/30 text-ink' : 'border-line text-ink-3 hover:border-line-strong hover:text-ink')}>
                {hourLabel(h).slice(0, 2)}–{hourLabel((h + 3) % 24).slice(0, 2)}
              </button>
            );
          })}
        </div>
        <span className="ml-auto text-xs text-ink-3">Selected: <span className="tabular text-ink">{hourLabel(hour)}</span></span>
      </div>
    </section>
  );
}

/* ───────────────────────────── Crew map / alerts / tasks ───────────────────────────── */

function CrewMap({ ship, crewId, onZone, onCrew }: { ship?: ShipState; crewId: string | null; onZone: (z: ZoneId) => void; onCrew: (id: string) => void }) {
  const { zoneId } = useApp();
  return (
    <section aria-label="Crew status map" className="card p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div><div className="mono-label text-cyan">Crew status map</div><h2 className="text-base font-semibold text-ink">Who is where, and in what conditions</h2></div>
        <div className="flex flex-wrap gap-3 text-xs text-ink-3">
          <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm border border-good bg-good/20" />nominal</span>
          <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm border border-attention bg-attention/20" />attention</span>
          <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-attention" />reduced load</span>
        </div>
      </div>
      {ship ? (
        <DeckPlan title="Deck plan, stern to bow, with crew positions" selectedZone={zoneId} selectedCrew={crewId} onZone={onZone} onCrew={onCrew} crew={ship.crew}
          zones={ship.zones.map((z) => ({ id: z.id, name: z.name, status: z.environment.status, label: `${fmt(z.environment.co2_ppm)} ppm CO₂` }))} />
      ) : <div className="skeleton h-48 rounded-xl" />}
      {ship && (
        <ul className="mt-3 grid gap-1.5 sm:grid-cols-2">
          {ship.crew.map((c) => (
            <li key={c.id}>
              <button type="button" onClick={() => onCrew(c.id)} aria-pressed={c.id === crewId}
                className={cx('interactive flex w-full items-center gap-2 rounded-lg border px-2 py-1.5 text-left text-sm', c.id === crewId ? 'border-cyan bg-teal-600/20' : 'border-line hover:border-line-strong')}>
                <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full text-[10px] font-bold text-white" style={{ background: CREW_HEX[c.id] }}>{initials(c.name)}</span>
                <span className="min-w-0 flex-1 truncate"><span className="text-ink">{c.name.split(' ')[0]}</span> <span className="text-ink-3">· {c.activity}</span></span>
                {c.reduced_load_suggested && <Icon name="info" size={14} className="text-attention" title="Reduced load suggested" />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

type Alert = { id: string; level: 'attention' | 'high' | 'info'; icon: IconName; title: string; detail: string; source: string; action: { label: string; run: () => void } };

/** Alerts & events derived only from existing API data — nothing here is invented. */
function AlertsPanel({ ship, analyses, histories, plan }: { ship?: ShipState; analyses?: (readonly [{ id: string; name: string }, Analysis])[]; histories?: CrewHistory[]; plan?: { schedule: { unassigned: number } } }) {
  const { role, openWith, day } = useApp();
  const [filter, setFilter] = useState<'all' | 'environment' | 'crew' | 'phantom'>('all');
  const alerts = useMemo(() => {
    const out: (Alert & { kind: 'environment' | 'crew' | 'phantom' })[] = [];
    for (const z of ship?.zones ?? []) if (z.environment.status !== 'nominal') out.push({
      id: 'env-' + z.id, kind: 'environment', level: z.environment.status === 'high' ? 'high' : 'attention', icon: 'wind', source: 'SYMBIOSIS',
      title: `${z.name}: CO₂ ${fmt(z.environment.co2_ppm)} ppm`, detail: `Above the demo reference band at ${hourLabel(z.environment.hour)}; ${z.environment.occupants} crew present.`,
      action: { label: 'Inspect environment', run: () => openWith('/symbiosis', { zoneId: z.id }) },
    });
    for (const c of ship?.crew ?? []) if (c.reduced_load_suggested) out.push({
      id: 'load-' + c.id, kind: 'crew', level: 'attention', icon: 'users', source: 'CO-ORBIT', title: `${c.name}: reduced load suggested`,
      detail: 'Planning flag only — no physiological detail shown in this view.', action: { label: 'Plan tasks', run: () => openWith('/co-orbit?tab=tasks', { astronautId: c.id }) },
    });
    if (plan?.schedule.unassigned) out.push({
      id: 'tasks', kind: 'crew', level: 'attention', icon: 'calendar', source: 'CO-ORBIT', title: `${plan.schedule.unassigned} task(s) without an owner`,
      detail: 'The planner could not fit them within crew capacity.', action: { label: 'Resolve', run: () => navigate('/co-orbit?tab=tasks') },
    });
    if (role === 'flight-surgeon') {
      for (const [a, r] of analyses ?? []) if (r.status === 'attention') out.push({
        id: 'ph-' + a.id, kind: 'phantom', level: 'attention', icon: 'brain', source: 'PHANTOM', title: `${a.name}: review suggested`,
        detail: `${r.flagged_count} signal(s) outside personal baseline · uncertainty ${r.uncertainty}. Research analysis, not a diagnosis.`,
        action: { label: 'Explore', run: () => openWith('/phantom', { astronautId: a.id }) },
      });
      for (const c of histories ?? []) for (const ep of c.h.alerts) if (ep.end_day < day && ep.end_day >= day - 14) out.push({
        id: `ep-${c.id}-${ep.start_day}`, kind: 'phantom', level: 'info', icon: 'clock', source: 'PHANTOM · event', title: `${c.name}: ${ep.label}`,
        detail: `Days ${ep.start_day}–${ep.end_day} · ${ep.signals.map((s) => METRICS[s].short.toLowerCase()).join(', ')}`,
        action: { label: `Go to day ${ep.end_day}`, run: () => openWith('/phantom', { astronautId: c.id, day: ep.end_day }) },
      });
    }
    return out;
  }, [ship, analyses, histories, plan, role, day, openWith]);
  const shown = alerts.filter((a) => filter === 'all' || a.kind === filter);
  const lvl = { high: 'border-l-high text-high', attention: 'border-l-attention text-attention', info: 'border-l-line-strong text-ink-2' } as const;
  return (
    <section id="alerts" aria-label="Alerts and events" className="card flex scroll-mt-40 flex-col p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div><div className="mono-label text-attention">Alerts & events</div><h2 className="text-base font-semibold text-ink">{alerts.length ? `${alerts.length} item${alerts.length === 1 ? '' : 's'} to look at` : 'Nothing needs attention'}</h2></div>
        <div role="radiogroup" aria-label="Filter alerts" className="flex flex-wrap gap-1">
          {(['all', 'environment', 'crew', 'phantom'] as const).map((f) => (
            <button key={f} type="button" role="radio" aria-checked={filter === f} onClick={() => setFilter(f)} disabled={f === 'phantom' && role !== 'flight-surgeon'}
              className={cx('interactive rounded-md border px-2 py-1 text-xs capitalize disabled:opacity-40', filter === f ? 'border-cyan bg-teal-600/30 text-ink' : 'border-line text-ink-3 hover:text-ink')}>{f}</button>
          ))}
        </div>
      </div>
      {!ship ? <div className="skeleton h-40 rounded-xl" /> : shown.length ? (
        <ul className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
          {shown.map((a) => (
            <li key={a.id} className={cx('rounded-lg border border-line border-l-4 bg-raised/30 p-2.5', lvl[a.level])}>
              <div className="flex items-start gap-2">
                <Icon name={a.icon} size={16} className="mt-0.5 shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-2"><span className="text-sm font-medium text-ink">{a.title}</span><span className="mono-label text-ink-3">{a.source}</span></div>
                  <p className="mt-0.5 text-xs text-ink-2">{a.detail}</p>
                  <Button size="sm" variant="ghost" iconRight="arrowRight" className="-ml-2 mt-1" onClick={a.action.run}>{a.action.label}</Button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      ) : <p className="flex items-center gap-2 text-sm text-good"><Icon name="checkCircle" size={16} />No items in this category at {dayLabel(day)}.</p>}
      {role !== 'flight-surgeon' && <p className="mt-3 text-xs text-ink-3">PHANTOM items are visible in the flight-surgeon role.</p>}
    </section>
  );
}

function CurrentTasks({ ship, onCrew }: { ship?: ShipState; onCrew: (id: string) => void }) {
  const { api } = useApp();
  const plan = useResource(`crew-${api.mode}`, () => api.crew(false));
  return (
    <section aria-label="Today's tasks" className="card p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div><div className="mono-label text-amber">CO-ORBIT</div><h2 className="text-base font-semibold text-ink">Today’s tasks & owners</h2></div>
        <Button size="sm" variant="ghost" iconRight="arrowRight" onClick={() => navigate('/co-orbit?tab=tasks')}>Plan tasks</Button>
      </div>
      <Async res={plan}>{(p) => (
        <ul className="grid gap-1.5 md:grid-cols-2">
          {p.schedule.assignments.map((t) => {
            const owner = p.crew.find((c) => c.id === t.astronaut_id);
            return (
              <li key={t.id} className="flex items-center gap-2 rounded-lg border border-line bg-raised/30 px-2.5 py-1.5 text-sm">
                <span className={cx('h-8 w-1 rounded-full', t.priority === 1 ? 'bg-attention' : t.priority === 2 ? 'bg-cyan' : 'bg-line-strong')} aria-hidden="true" />
                <span className="min-w-0 flex-1"><span className="block truncate text-ink">{t.title}</span><span className="text-xs text-ink-3">{t.skill} · {t.hours} h · P{t.priority}</span></span>
                {owner
                  ? <button type="button" onClick={() => ship && onCrew(owner.id)} aria-label={`Show ${owner.name} on the spacecraft`} className="interactive grid h-7 w-7 place-items-center rounded-full text-[10px] font-bold text-white" style={{ background: CREW_HEX[owner.id] }}>{initials(owner.name)}</button>
                  : <Pill tone="attention">Unassigned</Pill>}
              </li>
            );
          })}
        </ul>
      )}</Async>
    </section>
  );
}

const MODULE_HINT: Record<string, string> = {
  '/body': 'Human twin, systems, history, compare',
  '/phantom': 'Deviations, relationships, event explorer',
  '/symbiosis': 'Compartment plan, conditions, what-if',
  '/co-orbit': 'Crew map, timeline, plan comparison',
  '/recovery': 'Garden, Earth Window, Orbit Flow, Mind Pulse',
  '/mission-lab': 'Scenarios, simulation, side-by-side',
  '/science': 'NASA hazards, HRP risks, evidence, radiation',
};

function ModuleTiles({ compact }: { compact: boolean }) {
  const { openWith } = useApp();
  return (
    <nav aria-label="Modules" className="grid gap-3 sm:grid-cols-3 xl:grid-cols-7">
      {MODULES.filter((m) => m.path !== '/').map((m) => (
        <button key={m.path} type="button" onClick={() => openWith(m.path, {})} className="card interactive group flex flex-col items-start gap-1.5 p-4 text-left hover:border-line-strong">
          <span className="grid h-9 w-9 place-items-center rounded-lg border transition-transform group-hover:scale-105" style={{ color: m.accent, borderColor: `color-mix(in srgb, ${m.accent} 40%, transparent)`, background: `color-mix(in srgb, ${m.accent} 10%, transparent)` }}><Icon name={m.icon} size={18} /></span>
          <span className="text-sm font-semibold tracking-wide text-ink">{m.name}</span>
          {!compact && <span className="text-xs text-ink-3">{MODULE_HINT[m.path]}</span>}
        </button>
      ))}
    </nav>
  );
}
