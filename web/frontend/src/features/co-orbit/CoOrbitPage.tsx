import { useEffect, useMemo, useState, type DragEvent, type FormEvent } from 'react';
import type { Assignment, BlockKind, CalendarBlock, CrewCalendar, CrewMember, Schedule, ShipState, Skill, Task } from '../../api/types';
import { CREW_HEX, dayLabel, hourLabel, initials } from '../../lib/format';
import { navigate } from '../../lib/router';
import { useResource } from '../../lib/useResource';
import { MAX_DAY, useApp } from '../../state/AppState';
import { Async, Button, Card, cx, Dialog, Disclosure, Icon, MissingValue, Notice, PhantomPill, Pill, SourceBadge, TabPanel, Tabs, useTab, useToast, type TabDef } from '../../ui';
import { DeckPlan } from '../shared/DeckPlan';
import { ModuleHeader } from '../shared/ModuleHeader';
import { useScenarioRun } from '../../state/scenario';
import { EngineRunCard, EngineSchedule } from '../shared/EngineCards';
import { ReplanPanel } from './ReplanPanel';
import { PhantomConstraints } from './PhantomConstraints';

type CoTab = 'crew' | 'schedule' | 'tasks' | 'rest';
const TABS: TabDef<CoTab>[] = [
  { id: 'crew', label: 'Crew map & profiles', icon: 'users' },
  { id: 'schedule', label: 'Timeline & calendar', icon: 'calendar' },
  { id: 'tasks', label: 'Task board', icon: 'sliders' },
  { id: 'rest', label: 'Rest calendar', icon: 'moon' },
];

const KIND: Record<BlockKind, { label: string; fill: string; pattern?: boolean }> = {
  sleep: { label: 'Sleep', fill: '#2d3f66', pattern: true },
  work: { label: 'Work', fill: '#277f89' },
  exercise: { label: 'Exercise', fill: '#3f6d57' },
  meal: { label: 'Meal', fill: '#6a6342' },
  personal: { label: 'Personal', fill: '#3a4a5c' },
  health: { label: 'Check-in', fill: '#6b4d6e' },
};
const SKILLS: Skill[] = ['command', 'engineering', 'medical', 'science'];


export function CoOrbitPage() {
  const { api, day, hour, role, dataVersion } = useApp();
  const crew = useResource(`crew-${api.mode}`, () => api.crew(false));
  const ship = useResource(`ship-${api.mode}-${day}-${hour}-${dataVersion}`, () => api.ship(day, hour));
  const [tab, setTab] = useTab(TABS);
  return (
    <div>
      <ModuleHeader module="/co-orbit" title="Crew coordination"
        description="Where the crew is, what they do, and who owns which task. Medical detail is never shown here – only derived availability constraints." />
      {role !== 'flight-surgeon' && <Notice tone="unknown" className="mb-4" title="Privacy: crew view">Physiological values and PHANTOM results are hidden. A “reduced load suggested” flag is the only health-derived information shared with planning. (Permissions are simulated in the UI.)</Notice>}
      {crew.data && <ScenarioCrew crew={crew.data.crew} base={crew.data.schedule} />}
      <div className="mb-4"><EngineRunCard eyebrow="Mission Systems engine · MILP scheduler (HiGHS)" title="Optimised task schedule for the engine scenario">{(r) => <><EngineSchedule run={r} /><p className="mt-1 text-xs text-ink-3">Plan profile: {r.plan_profile_detail}</p><PhantomConstraints run={r} /><ReplanPanel run={r} /></>}</EngineRunCard></div>
      <Tabs label="CO-ORBIT sections" tabs={TABS} value={tab} onChange={setTab} />
      <TabPanel label={TABS.find((t) => t.id === tab)!.label}>
        <Async res={crew} loadingLabel="Loading crew">
          {(c) => (
            <>
              {tab === 'crew' && <div className="space-y-5"><CrewMapPanel ship={ship.data} /><CrewOverview crew={c.crew} ship={ship.data} /></div>}
              {tab === 'schedule' && <div className="space-y-5"><MissionCalendar crew={c.crew} /><CalendarPanel crew={c.crew} /></div>}
              {tab === 'rest' && <RestCalendar crew={c.crew} />}
              {tab === 'tasks' && <Planner crew={c.crew} reducedFlags={ship.data?.crew.filter((x) => x.reduced_load_suggested).map((x) => x.id) ?? []} />}
            </>
          )}
        </Async>
      </TabPanel>
    </div>
  );
}

/** Crew-plan implication of the applied MISSION LAB scenario (simulator's own planner output). */
function ScenarioCrew({ crew, base }: { crew: CrewMember[]; base: Schedule }) {
  const { scenario } = useApp();
  const run = useScenarioRun();
  if (!scenario) return null;
  const nm = (id: string | null) => (id ? crew.find((c) => c.id === id)?.name.split(' ')[0] ?? id : 'unassigned');
  return (
    <section aria-label="Scenario crew implications" className="card mb-4 border-violet/40 p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div><div className="mono-label text-violet">Scenario (model) · {scenario.title}</div><h2 className="text-base font-semibold text-ink">Modelled crew plan: {scenario.params.crew_available} of 4 crew available, workload {scenario.params.workload}/100</h2></div>
        <SourceBadge source="simulated" />
      </div>
      <Async res={run} loadingLabel="Running scenario">{(r) => {
        const moved = r.crew.assignments.filter((a) => base.assignments.find((b) => b.id === a.id)?.astronaut_id !== a.astronaut_id);
        return (
          <div className="grid gap-3 md:grid-cols-[repeat(3,minmax(0,1fr))_minmax(0,1.6fr)]">
            <div className="rounded-xl border border-line bg-raised/40 p-2.5 text-center"><div className="mono-label">Unassigned</div><div className={cx('tabular text-xl font-semibold', r.crew.unassigned ? 'text-attention' : 'text-ink')}>{r.crew.unassigned}</div><div className="text-[11px] text-ink-3">now {base.unassigned}</div></div>
            <div className="rounded-xl border border-line bg-raised/40 p-2.5 text-center"><div className="mono-label">Peak load</div><div className="tabular text-xl font-semibold text-ink">{Math.round((r.crew.peak_utilisation ?? 0) * 100)}%</div><div className="text-[11px] text-ink-3">now {Math.round((base.peak_utilisation ?? 0) * 100)}%</div></div>
            <div className="rounded-xl border border-line bg-raised/40 p-2.5 text-center"><div className="mono-label">Reassigned</div><div className="tabular text-xl font-semibold text-ink">{moved.length}</div><div className="text-[11px] text-ink-3">tasks</div></div>
            <ul className="space-y-1 text-xs text-ink-2">
              {moved.length ? moved.map((a) => <li key={a.id}>“{a.title}”: {nm(base.assignments.find((b) => b.id === a.id)?.astronaut_id ?? null)} → <span className="text-violet">{nm(a.astronaut_id)}</span></li>) : <li>No task changes owners under this scenario.</li>}
              <li className="text-[11px] text-ink-3">Planner rule: effective workload = workload × 4 ÷ available crew; above 70 the first crew member’s capacity is reduced, and unavailable crew get no tasks.</li>
            </ul>
          </div>
        );
      }}</Async>
    </section>
  );
}

/* ───────────────────────── Crew map ───────────────────────── */

function CrewMapPanel({ ship }: { ship?: ShipState }) {
  const { astronautId, setAstronautId, zoneId, setZoneId, hour, openWith } = useApp();
  const sel = ship?.crew.find((c) => c.id === astronautId);
  return (
    <section aria-label="Crew map" className="always-dark stage rounded-2xl border border-line p-3">
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="hud rounded-xl p-3">
          <div className="mb-1 flex items-center justify-between gap-2"><span className="mono-label text-amber">Crew map · {hourLabel(hour)}</span><span className="text-xs text-ink-3">positions from the synthetic schedule</span></div>
          {ship ? <DeckPlan title="Crew positions on the deck plan" zones={ship.zones.map((z) => ({ id: z.id, name: z.name, status: z.environment.status, label: `${z.environment.occupants} crew` }))}
            crew={ship.crew} selectedCrew={astronautId} selectedZone={zoneId} onCrew={setAstronautId} onZone={setZoneId} /> : <div className="skeleton h-48 rounded-xl" />}
        </div>
        <div className="hud flex flex-col rounded-xl p-4">
          <div className="mono-label text-ink-3">Selected crew member</div>
          {sel ? (
            <>
              <div className="mt-2 flex items-center gap-3">
                <span className="grid h-11 w-11 place-items-center rounded-full text-sm font-bold text-white" style={{ background: CREW_HEX[sel.id] }}>{initials(sel.name)}</span>
                <div><div className="font-semibold text-ink">{sel.name}</div><div className="text-sm text-ink-2">{sel.activity}</div></div>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5"><Pill tone="info" icon="clock">{sel.availability}</Pill>{sel.reduced_load_suggested && <Pill tone="attention">Reduced load suggested</Pill>}</div>
              <p className="mt-2 text-xs text-ink-3">In {ship?.zones.find((z) => z.id === sel.zone)?.name}. Click another marker or use the context bar to switch.</p>
              <div className="mt-auto flex flex-wrap gap-2 border-t border-line pt-3">
                <Button size="sm" variant="primary" icon="calendar" onClick={() => openWith('/co-orbit?tab=schedule', {})}>Their timeline</Button>
                <Button size="sm" icon="ship" onClick={() => openWith('/', { zoneId: sel.zone })}>On spacecraft</Button>
              </div>
            </>
          ) : <p className="mt-2 text-sm text-ink-3">Select a crew marker.</p>}
        </div>
      </div>
    </section>
  );
}

/* ───────────────────────── Mission calendar ───────────────────────── */

/** Days 41–67 (the PHANTOM analysis window) as a calendar; each cell shows scheduled sleep per crew member. */
function MissionCalendar({ crew }: { crew: CrewMember[] }) {
  const { api, day, setDay, dataVersion } = useApp();
  const days = Array.from({ length: MAX_DAY - 40 }, (_, i) => 41 + i);
  const cals = useResource(`calall-${api.mode}-${dataVersion}`, () => Promise.all(days.map((d) => api.calendar(d))));
  const sleep = (c: CrewCalendar, id: string) => (c.blocks[id] ?? []).filter((b) => b.kind === 'sleep').reduce((s, b) => s + b.end - b.start, 0);
  return (
    <Card eyebrow="Mission calendar" title="Days 41–67 · scheduled sleep per crew member" actions={<SourceBadge source="simulated" />}>
      <Async res={cals}>{(all) => (
        <div role="grid" aria-label="Mission calendar, select a day" className="grid grid-cols-4 gap-1.5 sm:grid-cols-7 xl:grid-cols-9">
          {all.map((c, i) => {
            const d = days[i];
            return (
              <button key={d} type="button" onClick={() => setDay(d)} aria-pressed={d === day} aria-label={`${dayLabel(d)}: ${crew.map((m) => `${m.name.split(' ')[0]} ${sleep(c, m.id).toFixed(1)} h`).join(', ')}`}
                className={cx('interactive rounded-lg border p-1.5 text-left', d === day ? 'border-amber bg-amber/10' : 'border-line bg-raised/30 hover:border-line-strong')}>
                <div className="tabular text-xs font-semibold text-ink">D{d}</div>
                <div className="mt-1 flex h-8 items-end gap-0.5" aria-hidden="true">
                  {crew.map((m) => <span key={m.id} className="flex-1 rounded-sm" style={{ height: `${Math.min(100, (sleep(c, m.id) / 9) * 100)}%`, background: CREW_HEX[m.id], opacity: sleep(c, m.id) < 6 ? 0.45 : 0.9 }} />)}
                </div>
              </button>
            );
          })}
        </div>
      )}</Async>
      <ul className="mt-3 flex flex-wrap gap-3 text-xs text-ink-2" aria-label="Legend">
        {crew.map((m) => <li key={m.id} className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: CREW_HEX[m.id] }} />{m.name.split(' ')[0]}</li>)}
        <li className="text-ink-3">bar height = scheduled sleep (0–9 h) · faded &lt; 6 h · select a day to load its timeline below</li>
      </ul>
    </Card>
  );
}

function CrewOverview({ crew, ship }: { crew: CrewMember[]; ship?: { crew: { id: string; activity: string; availability: string; reduced_load_suggested: boolean; zone: string }[]; zones: { id: string; name: string }[] } }) {
  const { api, day, hour, role, astronauts, setAstronautId, dataVersion } = useApp();
  const ph = useResource(role === 'flight-surgeon' ? `phall-${api.mode}-${day}-${dataVersion}` : null, () => Promise.all(crew.map((m) => api.phantom(m.id, day))));
  return (
    <Card eyebrow="Overview" title="Crew profiles" actions={<span className="text-xs text-ink-3">status at {hourLabel(hour)}</span>}>
      <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {crew.map((m, i) => {
          const now = ship?.crew.find((x) => x.id === m.id);
          const role_ = astronauts.find((a) => a.id === m.id)?.role;
          return (
            <li key={m.id} className="flex flex-col gap-2 rounded-xl border border-line bg-raised/40 p-3">
              <div className="flex items-center gap-3">
                <span className="grid h-10 w-10 place-items-center rounded-full text-sm font-bold text-white" style={{ background: CREW_HEX[m.id] }}>{initials(m.name)}</span>
                <div className="min-w-0"><div className="font-medium text-ink">{m.name}</div><div className="truncate text-xs text-ink-3">{role_}</div></div>
              </div>
              <div className="flex flex-wrap gap-1">{m.skills.map((s) => <span key={s} className="rounded-md bg-canvas px-1.5 py-0.5 text-[11px] text-ink-2">{s}</span>)}</div>
              <div className="text-xs text-ink-3">Task capacity {m.capacity} h/day · base: {ship?.zones.find((z) => z.id === m.home_zone)?.name ?? m.home_zone}</div>
              {now && <div className="text-sm text-ink-2">{now.activity} · {ship?.zones.find((z) => z.id === now.zone)?.name}</div>}
              <div className="flex flex-wrap gap-1">
                {now && <Pill tone="info" icon="clock">{now.availability}</Pill>}
                {now?.reduced_load_suggested && <Pill tone="attention">Reduced load suggested</Pill>}
              </div>
              {role === 'flight-surgeon' && ph.data && <div className="flex items-center gap-2 border-t border-line pt-2 text-xs text-ink-3">PHANTOM <PhantomPill status={ph.data[i].status} /></div>}
              {role === 'flight-surgeon' && <Button size="sm" variant="ghost" iconRight="arrowRight" onClick={() => { setAstronautId(m.id); navigate('/body'); }}>BODY twin</Button>}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function Gantt({ cal, crew, label, now, onBlock, selected }: { cal: CrewCalendar; crew: CrewMember[]; label: string; now?: number; onBlock: (b: CalendarBlock & { who: string }) => void; selected?: string }) {
  return (
    <div className="overflow-x-auto">
      <div className="min-w-[720px]">
      <div className="mb-1 text-xs font-medium text-ink-3">{label}</div>
      <div className="space-y-1.5">
        {crew.map((m) => (
          <div key={m.id} className="grid grid-cols-[110px_1fr] items-center gap-2">
            <span className="flex items-center gap-1.5 truncate text-sm text-ink-2"><span className="h-2.5 w-2.5 rounded-full" style={{ background: CREW_HEX[m.id] }} />{m.name.split(' ')[0]}</span>
            <div className="relative h-8 rounded-md bg-canvas">
              {cal.blocks[m.id].map((b) => {
                const id = `${m.id}-${b.start}`;
                return (
                  <button key={id} type="button" onClick={() => onBlock({ ...b, who: m.id })}
                    aria-label={`${m.name}: ${b.title}, ${hourLabel(b.start)}–${hourLabel(b.end)}`}
                    className={cx('absolute inset-y-0.5 overflow-hidden rounded px-1 text-left text-[10px] leading-7 text-white/90', selected === id && 'ring-2 ring-ink')}
                    // 1.0 a11y: ≥ 24 px target (WCAG 2.5.8); a block that ends at midnight is anchored right so it never overflows
                    style={{ ...(b.end >= 24 ? { right: 0 } : { left: `${(b.start / 24) * 100}%` }), width: `${((b.end - b.start) / 24) * 100}%`, minWidth: 24, background: KIND[b.kind].fill,
                      backgroundImage: KIND[b.kind].pattern ? 'repeating-linear-gradient(135deg, rgba(255,255,255,.07) 0 4px, transparent 4px 8px)' : undefined }}>
                    {b.end - b.start >= 1.6 ? KIND[b.kind].label : ''}
                  </button>
                );
              })}
              {now != null && <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-ink" style={{ left: `${(now / 24) * 100}%` }} />}
            </div>
          </div>
        ))}
      </div>
      </div>
    </div>
  );
}

function CalendarPanel({ crew }: { crew: CrewMember[] }) {
  const { api, day, hour, dataVersion } = useApp();
  const [compare, setCompare] = useState<number | null>(null);
  const [sel, setSel] = useState<(CalendarBlock & { who: string }) | null>(null);
  const cal = useResource(`cal-${api.mode}-${day}-${dataVersion}`, () => api.calendar(day));
  const cal2 = useResource(compare != null ? `cal-${api.mode}-${compare}-${dataVersion}` : null, () => api.calendar(compare!));
  const sleepH = (c: CrewCalendar, id: string) => c.blocks[id].filter((b) => b.kind === 'sleep').reduce((s, b) => s + b.end - b.start, 0);
  return (
    <Card eyebrow="Work calendar" title={`24-hour plan · day ${day}`} actions={<>
      <label className="flex items-center gap-2 text-sm text-ink-2">Compare with day
        <select className="field !w-auto !py-1" value={compare ?? ''} onChange={(e) => setCompare(e.target.value ? Number(e.target.value) : null)}>
          <option value="">—</option>
          {Array.from({ length: MAX_DAY - 40 }, (_, i) => 41 + i).filter((d) => d !== day).map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
      </label>
      <SourceBadge source="simulated" />
    </>}>
      <div className="mb-2 grid grid-cols-[110px_1fr] gap-2 text-[11px] text-ink-3"><span /><div className="flex justify-between tabular">{['00:00', '06:00', '12:00', '18:00', '24:00'].map((h) => <span key={h}>{h}</span>)}</div></div>
      <Async res={cal}>{(c) => (
        <div className="space-y-4">
          <Gantt cal={c} crew={crew} label={`Day ${day}`} now={hour} onBlock={setSel} selected={sel ? `${sel.who}-${sel.start}` : undefined} />
          {compare != null && <Async res={cal2}>{(c2) => (
            <>
              <Gantt cal={c2} crew={crew} label={`Day ${compare}`} onBlock={setSel} />
              <div className="rounded-xl border border-line p-3 text-sm">
                <div className="eyebrow mb-1">Sleep period comparison</div>
                <ul className="grid gap-1 sm:grid-cols-2">{crew.map((m) => { const d = sleepH(c, m.id) - sleepH(c2, m.id); return <li key={m.id} className="tabular text-ink-2">{m.name}: {sleepH(c, m.id).toFixed(1)} h vs {sleepH(c2, m.id).toFixed(1)} h <span className={d < -0.25 ? 'text-attention' : 'text-ink-3'}>({d > 0 ? '+' : ''}{d.toFixed(1)} h)</span></li>; })}</ul>
              </div>
            </>
          )}</Async>}
        </div>
      )}</Async>
      <ul className="mt-3 flex flex-wrap gap-3 text-xs text-ink-2" aria-label="Legend">{(Object.keys(KIND) as BlockKind[]).map((k) => <li key={k} className="flex items-center gap-1.5"><span className="h-3 w-4 rounded-sm" style={{ background: KIND[k].fill }} />{KIND[k].label}</li>)}</ul>
      <div className="mt-3"><Async res={cal}>{(c) => (
        <Disclosure summary="Schedule as a list (same information as the chart)">
          <div className="grid gap-4 md:grid-cols-2">{crew.map((m) => (
            <table key={m.id} className="tabular w-full text-xs">
              <caption className="mb-1 text-left font-medium text-ink">{m.name}</caption>
              <tbody>{c.blocks[m.id].map((b) => <tr key={b.start} className="border-t border-line"><td className="py-1 text-ink-3">{hourLabel(b.start)}–{hourLabel(b.end)}</td><td className="text-ink-2">{b.title}</td><td className="text-ink-3">{b.zone}</td></tr>)}</tbody>
            </table>
          ))}</div>
        </Disclosure>
      )}</Async></div>
      {sel && <div className="mt-3 rounded-xl border border-teal-600 bg-teal-600/10 p-3 text-sm text-ink-2"><strong className="text-ink">{crew.find((m) => m.id === sel.who)?.name}</strong> · {sel.title} · {hourLabel(sel.start)}–{hourLabel(sel.end)} ({(sel.end - sel.start).toFixed(1)} h) · zone: {sel.zone}</div>}
      <p className="mt-2 text-xs text-ink-3">Sleep blocks follow each astronaut’s recorded sleep duration for that day; the rest of the day is a synthetic template.</p>
    </Card>
  );
}

const PRESETS: { id: string; label: string; apply: (reduced: string[]) => { capacity: Record<string, number>; unavailable: string[] } }[] = [
  { id: 'all', label: 'Everyone at full capacity', apply: () => ({ capacity: {}, unavailable: [] }) },
  { id: 'reduced', label: 'Respect “reduced load” flags (2 h)', apply: (r) => ({ capacity: Object.fromEntries(r.map((id) => [id, 2])), unavailable: [] }) },
  { id: 'a02', label: 'Mira Chen unavailable', apply: () => ({ capacity: {}, unavailable: ['A02'] }) },
  { id: 'a03', label: 'Sam Okafor unavailable', apply: () => ({ capacity: {}, unavailable: ['A03'] }) },
];


const CONFIRM_KEY = 'aether.coorbit.confirmed';
type Confirmed = { day: number; at: string; assignments: { id: string; astronaut_id: string | null }[] };
function readConfirmed(): Confirmed[] { try { return JSON.parse(localStorage.getItem(CONFIRM_KEY) ?? '[]'); } catch { return []; } }

const DEFAULT_TASKS: Task[] = [
  { id: 'T1', title: 'Life-support check', skill: 'engineering', hours: 2, priority: 1, zone: 'systems' },
  { id: 'T2', title: 'Health assessment', skill: 'medical', hours: 2, priority: 1, zone: 'medical' },
  { id: 'T3', title: 'Navigation review', skill: 'command', hours: 2, priority: 2, zone: 'command' },
  { id: 'T4', title: 'Science experiment', skill: 'science', hours: 3, priority: 2, zone: 'habitat' },
  { id: 'T5', title: 'Equipment inspection', skill: 'engineering', hours: 2, priority: 3, zone: 'systems' },
];

function peak(assign: Assignment[], crew: CrewMember[], cap: Record<string, number>) {
  let p = 0;
  for (const c of crew) { const k = cap[c.id] ?? c.capacity; if (k > 0) p = Math.max(p, assign.filter((a) => a.astronaut_id === c.id).reduce((s, a) => s + a.hours, 0) / k); }
  return p;
}

/**
 * Task board. The optimiser (POST /api/co-orbit/plan) proposes; the planner drags cards between crew
 * columns (or uses the owner menu) and confirms. Confirmed plans are kept in this browser only until a
 * persistence endpoint exists.
 */
function Planner({ crew, reducedFlags }: { crew: CrewMember[]; reducedFlags: string[] }) {
  const { api, day, astronautId } = useApp();
  const toast = useToast();
  const [tasks, setTasks] = useState<Task[]>(DEFAULT_TASKS);
  const [capacity, setCapacity] = useState<Record<string, number>>({});
  const [unavailable, setUnavailable] = useState<string[]>([]);
  const [optimise, setOptimise] = useState(true);
  const [result, setResult] = useState<{ base: Schedule; plan: Schedule } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState({ title: '', skill: 'science' as Skill, hours: '2', priority: '2' });
  const [draftErr, setDraftErr] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Record<string, string | null>>({});
  const [dragId, setDragId] = useState<string | null>(null);
  const [dropCol, setDropCol] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmed, setConfirmed] = useState<Confirmed[]>(readConfirmed);
  const [stale, setStale] = useState(false);

  const run = async () => {
    setBusy(true); setError(null);
    try {
      const [base, plan] = await Promise.all([api.plan({ tasks, optimise: false }), api.plan({ tasks, capacity, unavailable, optimise })]);
      setResult({ base, plan }); setOverrides({}); setStale(false);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  useEffect(() => { void run(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const markStale = () => setStale(true);

  const addTask = (e: FormEvent) => {
    e.preventDefault();
    const h = Number(draft.hours);
    if (!draft.title.trim()) return setDraftErr('Give the task a title.');
    if (!(h > 0 && h <= 12)) return setDraftErr('Hours must be between 0 and 12.');
    const next = Math.max(0, ...tasks.map((t) => Number(t.id.replace(/\D/g, '')) || 0)) + 1;
    setTasks([...tasks, { id: `T${next}`, title: draft.title.trim().slice(0, 80), skill: draft.skill, hours: h, priority: Number(draft.priority) as 1 | 2 | 3 }]);
    setDraft({ ...draft, title: '' }); setDraftErr(null); markStale();
  };
  const effective: Assignment[] = useMemo(() => (result ? result.plan.assignments.map((a) => (a.id in overrides ? { ...a, astronaut_id: overrides[a.id] } : a)) : []), [result, overrides]);
  const cap = result?.plan.capacity ?? {};
  const loads = useMemo(() => Object.fromEntries(crew.map((c) => [c.id, effective.filter((a) => a.astronaut_id === c.id).reduce((s, a) => s + a.hours, 0)])), [effective, crew]);
  const conflicts = useMemo(() => (result ? findConflicts(effective, crew, result.plan.capacity, reducedFlags) : []), [effective, crew, result, reducedFlags]);
  const changes = useMemo(() => result ? effective.filter((a) => result.plan.assignments.find((b) => b.id === a.id)?.astronaut_id !== a.astronaut_id) : [], [result, effective]);
  const recos = useMemo(() => result ? effective.filter((a) => result.plan.assignments.find((b) => b.id === a.id)!.astronaut_id !== a.astronaut_id) : [], [result, effective]);
  const name = (id: string | null) => (id ? crew.find((c) => c.id === id)?.name ?? id : 'Unassigned');
  const totalCap = crew.reduce((s, c) => s + (unavailable.includes(c.id) ? 0 : capacity[c.id] ?? c.capacity), 0);
  const totalHours = tasks.reduce((s, t) => s + t.hours, 0);
  const move = (taskId: string, to: string | null) => {
    const orig = result?.plan.assignments.find((a) => a.id === taskId)?.astronaut_id ?? null;
    const next = { ...overrides };
    if (to === orig) delete next[taskId]; else next[taskId] = to;
    setOverrides(next);
  };
  const onDrop = (col: string) => (e: DragEvent<HTMLDivElement>) => { e.preventDefault(); const id = e.dataTransfer.getData('text/plain') || dragId; if (id) move(id, col === 'none' ? null : col); setDragId(null); setDropCol(null); };
  const confirmPlan = () => {
    const entry: Confirmed = { day, at: new Date().toISOString(), assignments: effective.map((a) => ({ id: a.id, astronaut_id: a.astronaut_id })) };
    const next = [entry, ...confirmed.filter((c) => c.day !== day)].slice(0, 10);
    try { localStorage.setItem(CONFIRM_KEY, JSON.stringify(next)); } catch { /* storage unavailable: keep in memory */ }
    setConfirmed(next); setConfirmOpen(false);
    toast({ tone: 'good', title: `Task plan confirmed for day ${day}`, body: `${changes.length} manual change${changes.length === 1 ? '' : 's'} · stored in this browser.` });
  };
  const thisDay = confirmed.find((c) => c.day === day);
  const cols = [...crew.map((c) => ({ id: c.id, label: c.name, member: c })), { id: 'none', label: 'Unassigned', member: undefined as CrewMember | undefined }];

  return (
    <div className="space-y-5">
      <Card eyebrow="Inputs" title="Tasks and crew availability" actions={<SourceBadge source="simulated" />}>
        <div className="grid gap-5 xl:grid-cols-2">
          <div>
            <h3 className="mb-2 text-sm font-medium text-ink">Tasks · {totalHours} h requested · {totalCap} h capacity</h3>
            <ul className="space-y-1.5">
              {tasks.map((t) => (
                <li key={t.id} className="flex items-center gap-2 rounded-lg border border-line px-2 py-1.5 text-sm">
                  <span className="tabular w-8 text-xs text-ink-3">{t.id}</span>
                  <span className="flex-1 text-ink">{t.title}</span>
                  <span className="rounded bg-canvas px-1.5 text-[11px] text-ink-2">{t.skill}</span>
                  <span className="tabular w-9 text-right text-ink-2">{t.hours} h</span>
                  <span className="text-[11px] text-ink-3">P{t.priority}</span>
                  <button type="button" aria-label={`Remove ${t.title}`} onClick={() => { setTasks(tasks.filter((x) => x.id !== t.id)); markStale(); }} className="grid h-7 w-7 place-items-center rounded text-ink-3 hover:text-high"><Icon name="x" size={15} /></button>
                </li>
              ))}
            </ul>
            <form onSubmit={addTask} className="mt-2 grid grid-cols-2 items-end gap-2 sm:grid-cols-[1fr_auto_auto_auto_auto]">
              <label className="col-span-2 flex flex-col text-xs text-ink-3 sm:col-span-1">Title<input className="field mt-0.5" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} placeholder="e.g. Water sample" /></label>
              <label className="flex flex-col text-xs text-ink-3">Skill<select className="field mt-0.5" value={draft.skill} onChange={(e) => setDraft({ ...draft, skill: e.target.value as Skill })}>{SKILLS.map((s) => <option key={s}>{s}</option>)}</select></label>
              <label className="flex flex-col text-xs text-ink-3">Hours<input className="field mt-0.5 !w-16" type="number" min={0.5} max={12} step={0.5} value={draft.hours} onChange={(e) => setDraft({ ...draft, hours: e.target.value })} /></label>
              <label className="flex flex-col text-xs text-ink-3">Priority<select className="field mt-0.5" value={draft.priority} onChange={(e) => setDraft({ ...draft, priority: e.target.value })}><option value="1">1 high</option><option value="2">2</option><option value="3">3 low</option></select></label>
              <Button type="submit" icon="plus">Add</Button>
            </form>
            {draftErr && <p className="mt-1 text-xs text-high">{draftErr}</p>}
          </div>
          <div>
            <h3 className="mb-2 text-sm font-medium text-ink">Reallocation scenario</h3>
            <div className="mb-2 flex flex-wrap gap-1.5">{PRESETS.map((p) => <Button key={p.id} size="sm" onClick={() => { const v = p.apply(reducedFlags); setCapacity(v.capacity); setUnavailable(v.unavailable); markStale(); }}>{p.label}</Button>)}</div>
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-ink-3"><th className="py-1 font-medium">Crew</th><th className="font-medium">Capacity (h)</th><th className="font-medium">Available</th></tr></thead>
              <tbody>{crew.map((c) => (
                <tr key={c.id} className="border-t border-line">
                  <td className="py-1.5 text-ink-2">{c.name}{reducedFlags.includes(c.id) && <Pill tone="attention" className="ml-1.5">reduced load</Pill>}</td>
                  <td><input aria-label={`${c.name} capacity`} type="number" min={0} max={12} step={0.5} className="field !w-20 !py-1" value={capacity[c.id] ?? c.capacity} onChange={(e) => { setCapacity({ ...capacity, [c.id]: Math.max(0, Math.min(12, Number(e.target.value))) }); markStale(); }} /></td>
                  <td><input aria-label={`${c.name} available`} type="checkbox" checked={!unavailable.includes(c.id)} onChange={(e) => { setUnavailable(e.target.checked ? unavailable.filter((x) => x !== c.id) : [...unavailable, c.id]); markStale(); }} /></td>
                </tr>
              ))}</tbody>
            </table>
            <label className="mt-2 flex items-center gap-2 text-sm text-ink-2"><input type="checkbox" checked={optimise} onChange={(e) => { setOptimise(e.target.checked); markStale(); }} />Apply local-search optimisation after greedy assignment</label>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button variant="primary" icon="play" onClick={run} disabled={busy || !tasks.length}>{busy ? 'Planning…' : 'Compute plan'}</Button>
              {stale && result && <span className="flex items-center gap-1 text-xs text-attention"><Icon name="info" size={13} />Inputs changed — recompute to update the board</span>}
            </div>
            {error && <Notice tone="high" className="mt-2">{error}</Notice>}
          </div>
        </div>
      </Card>

      {!result ? (busy ? <div className="skeleton h-64 rounded-2xl" /> : null) : (
        <>
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
            <Card eyebrow="Plan comparison" title="Default · optimiser · your plan">
              <div className="overflow-x-auto">
                <table className="tabular w-full min-w-[420px] text-sm">
                  <caption className="sr-only">Comparison of the default, optimiser and current plans</caption>
                  <thead><tr className="text-left text-xs text-ink-3"><th className="py-1 font-medium">Measure</th><th className="font-medium">Default (greedy)</th><th className="font-medium">Optimiser</th><th className="font-medium">Your plan</th></tr></thead>
                  <tbody>
                    {[
                      { label: 'Peak utilisation', f: (a: Assignment[]) => `${Math.round(peak(a, crew, cap) * 100)}%` },
                      { label: 'Unassigned tasks', f: (a: Assignment[]) => String(a.filter((x) => !x.astronaut_id).length) },
                      { label: 'Conflicts', f: (a: Assignment[]) => String(findConflicts(a, crew, cap, reducedFlags).length) },
                    ].map((row) => (
                      <tr key={row.label} className="border-t border-line">
                        <th scope="row" className="py-2 text-left font-normal text-ink-2">{row.label}</th>
                        <td className="text-ink-3">{row.f(result.base.assignments)}</td><td className="text-ink-2">{row.f(result.plan.assignments)}</td><td className="font-semibold text-ink">{row.f(effective)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-xs text-ink-3">Optimiser: {result.plan.method.replaceAll('_', ' ')} ({result.plan.local_search_moves ?? 0} search moves). Default = same API without optimisation. Values for “your plan” are recomputed in the browser from the same rules.</p>
            </Card>
            <Card eyebrow="Conflicts & recommendations" title={conflicts.length ? `${conflicts.length} conflict${conflicts.length === 1 ? '' : 's'}` : 'No conflicts'}>
              {conflicts.length > 0 ? <ul className="space-y-1.5">{conflicts.map((c) => <li key={c} className="flex gap-2 text-sm text-ink-2"><Icon name="info" size={15} className="mt-0.5 shrink-0 text-attention" />{c}</li>)}</ul>
                : <p className="flex items-center gap-2 text-sm text-good"><Icon name="checkCircle" size={16} />Every task has a qualified, available owner within capacity.</p>}
              {recos.length > 0 && (
                <div className="mt-3 border-t border-line pt-3">
                  <div className="mono-label mb-1.5 text-ink-3">Optimiser recommendation</div>
                  <ul className="space-y-1.5">
                    {recos.map((a) => {
                      const o = result.plan.assignments.find((b) => b.id === a.id)!.astronaut_id;
                      return (
                        <li key={a.id} className="flex items-center justify-between gap-2 text-sm">
                          <span className="text-ink-2">“{a.title}” → <span className="text-ink">{name(o)}</span></span>
                          <Button size="sm" variant="ghost" onClick={() => move(a.id, o)}>Apply</Button>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
            </Card>
          </div>

          <Card eyebrow="Task board" title="Drag a task to another crew member" actions={<span className="text-xs text-ink-3">or use each card’s owner menu (keyboard)</span>}>
            <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-5">
              {cols.map((col) => {
                const items = effective.filter((a) => (a.astronaut_id ?? 'none') === col.id);
                const k = col.member ? cap[col.id] ?? col.member.capacity : 0;
                const load = col.member ? loads[col.id] ?? 0 : items.reduce((s, a) => s + a.hours, 0);
                const over = col.member && load > k;
                return (
                  <div key={col.id} role="group" aria-label={`${col.label}: ${load} h${col.member ? ` of ${k} h` : ''}`}
                    onDragOver={(e) => { e.preventDefault(); setDropCol(col.id); }} onDragLeave={() => setDropCol((c) => (c === col.id ? null : c))} onDrop={onDrop(col.id)}
                    className={cx('flex min-h-48 flex-col rounded-xl border p-2 transition-colors', dropCol === col.id ? 'border-amber bg-amber/10' : 'border-line bg-raised/30', col.member?.id === astronautId && 'ring-1 ring-amber/50')}>
                    <div className="mb-2 flex items-center gap-2">
                      {col.member ? <span className="grid h-7 w-7 place-items-center rounded-full text-[10px] font-bold text-white" style={{ background: CREW_HEX[col.id] }}>{initials(col.label)}</span> : <Icon name="info" size={16} className="text-ink-3" />}
                      <div className="min-w-0 flex-1"><div className="truncate text-sm font-medium text-ink">{col.label}</div>
                        <div className={cx('tabular text-[11px]', over ? 'text-attention' : 'text-ink-3')}>{load} h{col.member ? ` / ${k} h` : ''}{reducedFlags.includes(col.id) ? ' · reduced load' : ''}{k === 0 && col.member ? ' · unavailable' : ''}</div></div>
                    </div>
                    {col.member && <div className="mb-2 h-1.5 overflow-hidden rounded-full bg-line" aria-hidden="true"><div className={cx('h-full rounded-full', over ? 'bg-attention' : 'bg-amber')} style={{ width: `${k ? Math.min(100, (load / k) * 100) : 0}%` }} /></div>}
                    <ul className="flex flex-1 flex-col gap-1.5">
                      {items.map((a) => {
                        const changed = a.id in overrides;
                        const noSkill = col.member && !col.member.skills.includes(a.skill);
                        return (
                          <li key={a.id} draggable onDragStart={(e) => { e.dataTransfer.setData('text/plain', a.id); e.dataTransfer.effectAllowed = 'move'; setDragId(a.id); }} onDragEnd={() => { setDragId(null); setDropCol(null); }}
                            className={cx('cursor-grab rounded-lg border bg-surface p-2 text-sm shadow-sm active:cursor-grabbing', dragId === a.id && 'opacity-50', changed ? 'border-amber' : 'border-line', noSkill && 'border-attention')}>
                            <div className="flex items-start gap-1.5">
                              <Icon name="grip" size={14} className="mt-0.5 shrink-0 text-ink-3" />
                              <div className="min-w-0 flex-1"><div className="text-ink">{a.title}</div><div className="text-[11px] text-ink-3">{a.skill} · {a.hours} h · P{a.priority}{noSkill ? ' · skill missing' : ''}{changed ? ' · moved' : ''}</div></div>
                            </div>
                            <select aria-label={`Owner of ${a.title}`} className="field mt-1.5 min-h-8 !py-1 text-xs" value={a.astronaut_id ?? ''} onChange={(e) => move(a.id, e.target.value || null)}>
                              <option value="">Unassigned</option>
                              {crew.map((c) => <option key={c.id} value={c.id}>{c.name}{c.skills.includes(a.skill) ? '' : ' (no skill)'}</option>)}
                            </select>
                          </li>
                        );
                      })}
                      {!items.length && <li className="flex flex-1 items-center justify-center rounded-lg border border-dashed border-line p-3 text-center text-xs text-ink-3">Drop tasks here</li>}
                    </ul>
                  </div>
                );
              })}
            </div>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
              <span className="text-sm text-ink-2">{changes.length ? `${changes.length} change${changes.length === 1 ? '' : 's'} from the optimiser plan` : 'Board matches the optimiser plan'}{thisDay ? ` · plan for day ${day} confirmed ${new Date(thisDay.at).toLocaleTimeString()}` : ''}</span>
              <div className="flex gap-2">
                <Button variant="ghost" icon="reset" disabled={!changes.length} onClick={() => setOverrides({})}>Undo changes</Button>
                <Button variant="primary" icon="check" onClick={() => setConfirmOpen(true)}>Confirm plan…</Button>
              </div>
            </div>
          </Card>
          <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)} title={`Confirm task plan for ${dayLabel(day)}`} description="Review the changes before the plan is recorded."
            footer={<><Button variant="ghost" onClick={() => setConfirmOpen(false)}>Cancel</Button><Button variant="primary" icon="check" onClick={confirmPlan}>Confirm plan</Button></>}>
            <div className="space-y-3 text-sm">
              {changes.length ? (
                <ul className="space-y-1">{changes.map((a) => <li key={a.id} className="text-ink-2">“{a.title}”: {name(result.plan.assignments.find((b) => b.id === a.id)!.astronaut_id)} → <strong className="text-ink">{name(a.astronaut_id)}</strong></li>)}</ul>
              ) : <p className="text-ink-2">No manual changes – the optimiser plan will be confirmed as is.</p>}
              {conflicts.length > 0 && <Notice tone="attention" title={`${conflicts.length} unresolved conflict${conflicts.length === 1 ? '' : 's'}`}><ul className="list-disc pl-4">{conflicts.map((c) => <li key={c}>{c}</li>)}</ul></Notice>}
              <Notice tone="unknown" title="Stored in this browser only">The API has no endpoint to save a confirmed plan yet (pending contract <code>POST /api/co-orbit/plan/confirm</code>, owner Mission Systems). Confirmation is kept in localStorage on this device.</Notice>
            </div>
          </Dialog>
        </>
      )}
    </div>
  );
}

export function findConflicts(plan: Assignment[], crew: CrewMember[], capacity: Record<string, number>, reduced: string[]): string[] {
  const out: string[] = [];
  const load: Record<string, number> = {};
  for (const a of plan) {
    if (!a.astronaut_id) { out.push(`“${a.title}” has no owner.`); continue; }
    const c = crew.find((x) => x.id === a.astronaut_id);
    if (!c) continue;
    load[c.id] = (load[c.id] ?? 0) + a.hours;
    if (!c.skills.includes(a.skill)) out.push(`${c.name} lacks the ${a.skill} skill for “${a.title}”.`);
    if ((capacity[c.id] ?? c.capacity) === 0) out.push(`${c.name} is unavailable but owns “${a.title}”.`);
  }
  for (const c of crew) {
    const cap = capacity[c.id] ?? c.capacity;
    if ((load[c.id] ?? 0) > cap && cap > 0) out.push(`${c.name} is over capacity (${load[c.id]} h of ${cap} h).`);
    if (reduced.includes(c.id) && (load[c.id] ?? 0) > 2) out.push(`${c.name} has a “reduced load suggested” flag but ${load[c.id]} h assigned.`);
  }
  return out;
}

function RestCalendar({ crew }: { crew: CrewMember[] }) {
  const { api, day, role, dataVersion } = useApp();
  const [span, setSpan] = useState(14);
  const recorded = role === 'flight-surgeon';
  const days = Array.from({ length: span }, (_, i) => day - span + 1 + i).filter((d) => d >= 1);
  // Crew view: planned rest (sleep + personal blocks) from the schedule API. Flight surgeon: recorded sleep from BODY data.
  const res = useResource(`rest-${api.mode}-${day}-${span}-${recorded}-${dataVersion}`, async () => {
    if (recorded) {
      const tls = await Promise.all(crew.map((c) => api.timeline(c.id, day)));
      return crew.map((_, i) => days.map((d) => tls[i].find((r) => r.day === d)?.sleep_hours ?? null));
    }
    const cals = await Promise.all(days.map((d) => api.calendar(d)));
    return crew.map((c) => cals.map((cal) => (cal.blocks[c.id] ?? []).filter((b) => b.kind === 'sleep' || b.kind === 'personal').reduce((s, b) => s + b.end - b.start, 0)));
  });
  return (
    <Card eyebrow="Rest calendar" title={recorded ? `Recorded sleep · last ${span} days` : `Scheduled rest · last ${span} days`} actions={<>
      <label className="flex items-center gap-2 text-sm text-ink-2">Span<select className="field !w-auto !py-1" value={span} onChange={(e) => setSpan(Number(e.target.value))}>{[7, 14, 21, 28].map((n) => <option key={n} value={n}>{n} days</option>)}</select></label>
      <SourceBadge source="simulated" />
    </>}>
      {!recorded && <Notice tone="unknown" className="mb-3">Crew view shows scheduled rest (sleep + personal time) only. Recorded sleep is physiological data and appears in the flight-surgeon role.</Notice>}
      <Async res={res}>{(grid) => (
        <div className="overflow-x-auto">
          <table className="tabular border-separate border-spacing-1 text-xs">
            <caption className="sr-only">{recorded ? 'Recorded sleep hours' : 'Scheduled rest hours'} per astronaut per mission day</caption>
            <thead><tr><th className="text-left font-medium text-ink-3">Crew</th>{days.map((d) => <th key={d} scope="col" className="w-11 font-medium text-ink-3">{d}</th>)}<th className="pl-2 text-left font-medium text-ink-3">Mean</th></tr></thead>
            <tbody>{crew.map((c, i) => {
              const vals = grid[i];
              const known = vals.filter((v): v is number => v != null);
              return (
                <tr key={c.id}>
                  <th scope="row" className="whitespace-nowrap pr-2 text-left font-medium text-ink-2"><span className="mr-1.5 inline-block h-2.5 w-2.5 rounded-full" style={{ background: CREW_HEX[c.id] }} />{c.name.split(' ')[0]}</th>
                  {vals.map((v, j) => {
                    const short = recorded && v != null && v < 6;
                    return (
                      <td key={days[j]} title={`${c.name}, day ${days[j]}: ${v == null ? 'no record' : v.toFixed(1) + ' h'}`}
                        className={cx('h-9 rounded-md text-center', v == null ? 'border border-dashed border-missing text-missing' : short ? 'bg-attention/20 font-semibold text-attention' : 'bg-teal-600/25 text-ink')}>
                        {v == null ? '–' : <>{v.toFixed(1)}{short && <span className="sr-only"> short sleep</span>}</>}
                      </td>
                    );
                  })}
                  <td className="pl-2 text-ink-2">{known.length ? (known.reduce((s, x) => s + x, 0) / known.length).toFixed(1) + ' h' : <MissingValue />}</td>
                </tr>
              );
            })}</tbody>
          </table>
          <ul className="mt-3 flex flex-wrap gap-4 text-xs text-ink-2" aria-label="Legend">
            <li className="flex items-center gap-1.5"><span className="h-3 w-4 rounded-sm bg-teal-600/25" />hours {recorded ? 'slept' : 'of scheduled rest'}</li>
            {recorded && <li className="flex items-center gap-1.5"><span className="h-3 w-4 rounded-sm bg-attention/20" /><strong className="text-attention">bold</strong> = under 6 h (display threshold, not a clinical cut-off)</li>}
            <li className="flex items-center gap-1.5"><span className="h-3 w-4 rounded-sm border border-dashed border-missing" />no record</li>
          </ul>
        </div>
      )}</Async>
    </Card>
  );
}

