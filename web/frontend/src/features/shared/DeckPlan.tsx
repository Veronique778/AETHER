import type { CrewLocation, EnvStatus, ZoneId } from '../../api/types';
import { CREW_HEX, initials } from '../../lib/format';
import { cx } from '../../ui';

export type DeckZone = { id: ZoneId; name: string; status?: EnvStatus; value?: number | null; label?: string };

/** Side-view deck layout (stern → bow). Coordinates in a 1000×300 viewBox. */
const SHAPES: Record<ZoneId, { kind: 'rect' | 'ring' | 'nose'; x: number; y: number; w: number; h: number; slots: [number, number][] }> = {
  systems: { kind: 'rect', x: 30, y: 80, w: 200, h: 140, slots: [[85, 150], [130, 150], [175, 150]] },
  exercise: { kind: 'rect', x: 242, y: 90, w: 156, h: 120, slots: [[285, 150], [320, 150], [355, 150]] },
  habitat: { kind: 'ring', x: 410, y: 20, w: 260, h: 260, slots: [[540, 34], [656, 150], [540, 266], [424, 150]] },
  medical: { kind: 'rect', x: 682, y: 90, w: 126, h: 120, slots: [[725, 150], [765, 150]] },
  command: { kind: 'nose', x: 820, y: 80, w: 170, h: 140, slots: [[865, 150], [905, 150], [945, 150]] },
};
const SHORT: Record<ZoneId, string> = { systems: 'Life support', exercise: 'Exercise', habitat: 'Habitat', medical: 'Medical', command: 'Command' };
const STATUS_FILL: Record<EnvStatus, string> = { nominal: 'rgba(95,211,166,.16)', attention: 'rgba(242,180,90,.20)', high: 'rgba(255,143,128,.24)' };
const STATUS_STROKE: Record<EnvStatus, string> = { nominal: '#5fd3a6', attention: '#f2b45a', high: '#ff8f80' };

/** Sequential cyan scale for metric heat maps (light → saturated as value rises). */
export function heat(t: number) {
  const k = Math.max(0, Math.min(1, t));
  return `rgba(79,209,232,${0.08 + k * 0.5})`;
}

/**
 * Interactive 2D deck plan used as crew map (Mission Control, CO-ORBIT) and environment plan (SYMBIOSIS).
 * Every zone and crew marker is a keyboard-operable button.
 */
export function DeckPlan({ zones, crew = [], selectedZone, selectedCrew, onZone, onCrew, mode = 'status', range, title, compact }: {
  zones: DeckZone[]; crew?: CrewLocation[]; selectedZone?: ZoneId | null; selectedCrew?: string | null;
  onZone?: (z: ZoneId) => void; onCrew?: (id: string) => void; mode?: 'status' | 'heat'; range?: [number, number]; title: string; compact?: boolean;
}) {
  const fill = (z: DeckZone) => {
    if (mode === 'heat' && z.value != null && range) return heat((z.value - range[0]) / (range[1] - range[0] || 1));
    return z.status ? STATUS_FILL[z.status] : 'rgba(255,255,255,.04)';
  };
  const stroke = (z: DeckZone) => (z.id === selectedZone ? '#4fd1e8' : z.status ? STATUS_STROKE[z.status] : '#56708c');
  const key = (fn: () => void) => (e: { key: string; preventDefault: () => void }) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn(); } };
  const used: Record<string, number> = {};
  return (
    <svg viewBox="0 0 1000 300" className="block h-auto w-full" role="group" aria-label={title}>
      <title>{title}</title>
      {/* spine */}
      <rect x="30" y="143" width="960" height="14" rx="7" fill="rgba(86,112,140,.25)" />
      {zones.map((z) => {
        const s = SHAPES[z.id];
        const sel = z.id === selectedZone;
        const common = { fill: fill(z), stroke: stroke(z), strokeWidth: sel ? 3 : 1.5 };
        return (
          <g key={z.id} role="button" tabIndex={onZone ? 0 : -1} aria-pressed={sel}
            aria-label={`${z.name}${z.label ? `, ${z.label}` : ''}${z.status ? `, ${z.status}` : ''}`}
            onClick={() => onZone?.(z.id)} onKeyDown={key(() => onZone?.(z.id))}
            className={cx('outline-none transition-opacity [&:focus-visible>*:first-child]:stroke-[#c9f3fa]', onZone && 'cursor-pointer hover:opacity-90')}>
            {s.kind === 'rect' && <rect x={s.x} y={s.y} width={s.w} height={s.h} rx="22" {...common} />}
            {s.kind === 'nose' && <path d={`M${s.x} ${s.y + 12} q0 -12 12 -12 h${s.w - 70} q58 0 58 ${s.h / 2} q0 ${s.h / 2} -58 ${s.h / 2} h-${s.w - 70} q-12 0 -12 -12 z`} {...common} />}
            {s.kind === 'ring' && (
              <>
                <circle cx={s.x + s.w / 2} cy={s.y + s.h / 2} r={s.w / 2 - 14} fill="none" stroke={common.stroke} strokeWidth={30} strokeOpacity={0.35} />
                <circle cx={s.x + s.w / 2} cy={s.y + s.h / 2} r={s.w / 2 - 14} fill="none" stroke={fill(z)} strokeWidth={26} />
                <circle cx={s.x + s.w / 2} cy={s.y + s.h / 2} r={s.w / 2 - 14} fill="none" stroke={common.stroke} strokeWidth={sel ? 3 : 1.5} strokeDasharray="2 0" opacity={0.9} />
                <circle cx={s.x + s.w / 2} cy={s.y + s.h / 2} r={64} {...common} />
              </>
            )}
            {!compact && <text x={s.x + s.w / 2 - (s.kind === 'nose' ? 14 : 0)} y={s.kind === 'ring' ? s.y + s.h / 2 - 6 : s.y + 30} textAnchor="middle" fontSize="17" fill="#e6edf5" fontWeight="600">{SHORT[z.id]}</text>}
            {z.label && <text x={s.x + s.w / 2 - (s.kind === 'nose' ? 14 : 0)} y={s.kind === 'ring' ? s.y + s.h / 2 + 18 : s.y + s.h - 16} textAnchor="middle" fontSize="14" fill="#a9b8ca" className="tabular">{z.label}</text>}
          </g>
        );
      })}
      {crew.map((c) => {
        const slotIdx = used[c.zone] ?? 0;
        used[c.zone] = slotIdx + 1;
        const [x, y] = SHAPES[c.zone].slots[slotIdx % SHAPES[c.zone].slots.length];
        const sel = c.id === selectedCrew;
        return (
          <g key={c.id} role="button" tabIndex={onCrew ? 0 : -1} aria-pressed={sel} aria-label={`${c.name}, ${c.activity}${c.reduced_load_suggested ? ', reduced load suggested' : ''}`}
            onClick={(e) => { e.stopPropagation(); onCrew?.(c.id); }} onKeyDown={key(() => onCrew?.(c.id))} className="cursor-pointer outline-none [&:focus-visible>circle:first-child]:stroke-[#c9f3fa]">
            <circle cx={x} cy={y} r={sel ? 21 : 18} fill={CREW_HEX[c.id]} stroke={sel ? '#ffffff' : '#070b14'} strokeWidth={sel ? 3 : 2.5} />
            <text x={x} y={y + 5} textAnchor="middle" fontSize="13" fontWeight="700" fill="#fff">{initials(c.name)}</text>
            {c.reduced_load_suggested && <circle cx={x + 15} cy={y - 14} r={6} fill="#f2b45a" stroke="#070b14" strokeWidth={2} />}
          </g>
        );
      })}
    </svg>
  );
}
