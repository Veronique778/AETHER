/**
 * AETHER chart components – dependency-free SVG.
 * Conventions (see docs/DESIGN_SYSTEM.md §Charts): one y-axis, 2px lines, recessive
 * grid, crosshair tooltip + keyboard cursor, legend for ≥2 series, table view, and
 * text in ink tokens (never series colour).
 */
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { cx, Icon } from '../ui';

export function useSize<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => {
      const next = { width: el.clientWidth, height: el.clientHeight };
      setSize((current) => current.width === next.width && current.height === next.height ? current : next);
    };
    update();
    window.addEventListener('resize', update);
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(update);
    ro?.observe(el);
    return () => {
      window.removeEventListener('resize', update);
      ro?.disconnect();
    };
  }, []);
  return [ref, size] as const;
}

export type Pt = { x: number; y: number | null; tag?: string };
export type Series = { id: string; label: string; color: string; points: Pt[]; dashed?: boolean };
export type BandSeries = { id: string; label: string; color: string; points: { x: number; lo: number; hi: number }[] };

function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) { min -= 1; max += 1; }
  const span = max - min;
  const step0 = span / count;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= count) ?? mag * 10;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(Number(v.toFixed(10)));
  return out;
}

export type TimeSeriesProps = {
  series: Series[];
  bands?: BandSeries[];
  refBand?: { lo: number; hi: number; label: string };
  refLines?: { y: number; label: string }[];
  markers?: { x: number; label: string }[];
  height?: number;
  unit?: string;
  xFormat?: (x: number) => string;
  yFormat?: (y: number) => string;
  yDomain?: [number | 'auto', number | 'auto'];
  cursorX?: number | null;
  onCursor?: (x: number | null) => void;
  ariaLabel: string;
  tagLabel?: Record<string, string>;
};

export function TimeSeriesChart({ series, bands = [], refBand, refLines = [], markers = [], height = 220, unit = '', xFormat = (x) => String(x),
  yFormat = (y) => String(Math.round(y * 100) / 100), yDomain = ['auto', 'auto'], cursorX, onCursor, ariaLabel, tagLabel = {} }: TimeSeriesProps) {
  const [wrapRef, { width }] = useSize<HTMLDivElement>();
  const [hoverX, setHoverX] = useState<number | null>(null);
  const M = { t: 12, r: 14, b: 26, l: 46 };
  const W = Math.max(0, width);
  const H = height;

  const xs = useMemo(() => {
    const set = new Set<number>();
    series.forEach((s) => s.points.forEach((p) => set.add(p.x)));
    bands.forEach((b) => b.points.forEach((p) => set.add(p.x)));
    return [...set].sort((a, b) => a - b);
  }, [series, bands]);

  const [y0, y1] = useMemo(() => {
    const vals: number[] = [];
    series.forEach((s) => s.points.forEach((p) => p.y != null && vals.push(p.y)));
    bands.forEach((b) => b.points.forEach((p) => vals.push(p.lo, p.hi)));
    refLines.forEach((r) => vals.push(r.y));
    if (refBand) vals.push(refBand.lo, refBand.hi);
    let lo = Math.min(...vals);
    let hi = Math.max(...vals);
    if (!vals.length) { lo = 0; hi = 1; }
    const pad = (hi - lo || Math.abs(hi) || 1) * 0.08;
    return [yDomain[0] === 'auto' ? lo - pad : yDomain[0], yDomain[1] === 'auto' ? hi + pad : yDomain[1]];
  }, [series, bands, refLines, refBand, yDomain]);

  const xMin = xs[0] ?? 0;
  const xMax = xs[xs.length - 1] ?? 1;
  const sx = (x: number) => M.l + ((x - xMin) / (xMax - xMin || 1)) * (W - M.l - M.r);
  const sy = (y: number) => M.t + (1 - (y - y0) / (y1 - y0 || 1)) * (H - M.t - M.b);
  const yTicks = niceTicks(y0, y1, 4).filter((t) => t >= y0 && t <= y1);
  const xTicks = niceTicks(xMin, xMax, Math.max(2, Math.floor(W / 90))).filter((t) => t >= xMin && t <= xMax && Number.isInteger(t));

  const path = (pts: Pt[]) => {
    let d = '';
    let pen = false;
    for (const p of pts) {
      if (p.y == null) { pen = false; continue; }
      d += `${pen ? 'L' : 'M'}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`;
      pen = true;
    }
    return d;
  };
  const bandPath = (b: BandSeries) => {
    if (!b.points.length) return '';
    const top = b.points.map((p, i) => `${i ? 'L' : 'M'}${sx(p.x).toFixed(1)},${sy(p.hi).toFixed(1)}`).join('');
    const bot = [...b.points].reverse().map((p) => `L${sx(p.x).toFixed(1)},${sy(p.lo).toFixed(1)}`).join('');
    return top + bot + 'Z';
  };

  const active = hoverX ?? cursorX ?? null;
  const setActive = (x: number | null) => { setHoverX(x); onCursor?.(x); };
  const nearest = (px: number) => {
    let best = xs[0];
    for (const x of xs) if (Math.abs(sx(x) - px) < Math.abs(sx(best) - px)) best = x;
    return best;
  };
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (!xs.length) return;
    const i = active == null ? -1 : xs.indexOf(active);
    if (e.key === 'ArrowRight') { e.preventDefault(); setActive(xs[Math.min(xs.length - 1, i + 1)]); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); setActive(xs[Math.max(0, i < 0 ? xs.length - 1 : i - 1)]); }
    else if (e.key === 'Home') { e.preventDefault(); setActive(xs[0]); }
    else if (e.key === 'End') { e.preventDefault(); setActive(xs[xs.length - 1]); }
    else if (e.key === 'Escape') setActive(null);
  };

  const legend = series.length + bands.length >= 2;
  const tipRows = active == null ? [] : [
    ...series.map((s) => { const p = s.points.find((q) => q.x === active); return p && p.y != null ? { color: s.color, label: s.label, value: `${yFormat(p.y)}${unit ? ' ' + unit : ''}`, tag: p.tag ? tagLabel[p.tag] ?? p.tag : undefined } : null; }),
    ...bands.map((b) => { const p = b.points.find((q) => q.x === active); return p ? { color: b.color, label: b.label, value: `${yFormat(p.lo)}–${yFormat(p.hi)}`, tag: undefined } : null; }),
  ].filter((r): r is NonNullable<typeof r> => r != null);
  const tipLeft = active != null && sx(active) > W * 0.6;

  return (
    <div>
      {legend && (
        <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2" aria-label="Legend">
          {bands.map((b) => <li key={b.id} className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-4 rounded-sm" style={{ background: b.color, opacity: 0.35 }} />{b.label}</li>)}
          {series.map((s) => (
            <li key={s.id} className="flex items-center gap-1.5">
              <svg width="18" height="8" aria-hidden><line x1="0" y1="4" x2="18" y2="4" stroke={s.color} strokeWidth="2" strokeDasharray={s.dashed ? '4 3' : undefined} /></svg>
              {s.label}
            </li>
          ))}
        </ul>
      )}
      <div ref={wrapRef} className="relative w-full" style={{ height: H }}>
        {W > 0 && (
          <svg
            width={W}
            height={H}
            role="img"
            aria-label={ariaLabel}
            tabIndex={0}
            onKeyDown={onKey}
            onPointerMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); setActive(nearest(e.clientX - r.left)); }}
            onPointerLeave={() => setActive(null)}
            onBlur={() => setHoverX(null)}
            className="block touch-none select-none outline-none focus-visible:outline-2 focus-visible:outline-teal-300"
          >
            {refBand && <rect x={M.l} width={W - M.l - M.r} y={sy(Math.min(y1, refBand.hi))} height={Math.max(0, sy(Math.max(y0, refBand.lo)) - sy(Math.min(y1, refBand.hi)))} fill="var(--color-teal-300)" opacity={0.06} />}
            {yTicks.map((t) => (
              <g key={t}>
                <line x1={M.l} x2={W - M.r} y1={sy(t)} y2={sy(t)} stroke="var(--color-line)" strokeDasharray="2 4" />
                <text x={M.l - 8} y={sy(t)} dy="0.32em" textAnchor="end" fontSize="11" fill="var(--color-ink-3)" className="tabular">{yFormat(t)}</text>
              </g>
            ))}
            {xTicks.map((t) => <text key={t} x={sx(t)} y={H - 6} textAnchor="middle" fontSize="11" fill="var(--color-ink-3)" className="tabular">{xFormat(t)}</text>)}
            {refLines.map((r) => (
              <g key={r.label}>
                <line x1={M.l} x2={W - M.r} y1={sy(r.y)} y2={sy(r.y)} stroke="var(--color-ink-3)" strokeDasharray="6 4" />
                <text x={W - M.r - 4} y={sy(r.y) - 5} textAnchor="end" fontSize="11" fill="var(--color-ink-2)">{r.label}</text>
              </g>
            ))}
            {markers.map((m) => (
              <g key={m.label + m.x}>
                <line x1={sx(m.x)} x2={sx(m.x)} y1={M.t} y2={H - M.b} stroke="var(--color-line-strong)" />
                <text x={sx(m.x) + 4} y={M.t + 10} fontSize="11" fill="var(--color-ink-3)">{m.label}</text>
              </g>
            ))}
            {bands.map((b) => <path key={b.id} d={bandPath(b)} fill={b.color} opacity={0.22} />)}
            {series.map((s) => <path key={s.id} d={path(s.points)} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" strokeDasharray={s.dashed ? '5 4' : undefined} />)}
            {series.map((s) => s.points.filter((p) => p.tag && p.y != null).map((p) => (
              <rect key={s.id + p.x} x={sx(p.x) - 4.5} y={sy(p.y!) - 4.5} width={9} height={9} transform={`rotate(45 ${sx(p.x)} ${sy(p.y!)})`} fill="var(--color-canvas)" stroke={s.color} strokeWidth={2} />
            )))}
            {active != null && (
              <g pointerEvents="none">
                <line x1={sx(active)} x2={sx(active)} y1={M.t} y2={H - M.b} stroke="var(--color-ink-3)" />
                {series.map((s) => { const p = s.points.find((q) => q.x === active); return p && p.y != null ? <circle key={s.id} cx={sx(active)} cy={sy(p.y)} r={4.5} fill={s.color} stroke="var(--color-surface)" strokeWidth={2} /> : null; })}
              </g>
            )}
          </svg>
        )}
        {active != null && tipRows.length > 0 && (
          <div className="pointer-events-none absolute top-1 z-10 min-w-36 rounded-lg border border-line-strong bg-overlay/95 px-2.5 py-1.5 text-xs shadow-lg"
            style={tipLeft ? { right: W - sx(active) + 10 } : { left: sx(active) + 10 }} aria-live="polite">
            <div className="mb-1 font-medium text-ink">{xFormat(active)}</div>
            {tipRows.map((r) => (
              <div key={r.label} className="flex items-center justify-between gap-3 text-ink-2">
                <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: r.color }} />{r.label}</span>
                <span className="tabular font-medium text-ink">{r.value}{r.tag && <span className="ml-1 text-ink-3">· {r.tag}</span>}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/** Chart wrapper with an accessible data-table toggle. */
export function ChartFrame({ children, table, caption }: { children: ReactNode; table: { columns: string[]; rows: (string | number)[][] }; caption: string }) {
  const [showTable, setShowTable] = useState(false);
  return (
    <div>
      <div className="mb-1 flex justify-end">
        <button type="button" onClick={() => setShowTable(!showTable)} aria-pressed={showTable} className="inline-flex min-h-7 items-center gap-1 rounded-md px-2 text-xs text-ink-3 hover:text-ink">
          <Icon name={showTable ? 'activity' : 'table'} size={13} />{showTable ? 'Chart' : 'Table'}
        </button>
      </div>
      {showTable ? (
        <div className="max-h-72 overflow-auto rounded-lg border border-line">
          <table className="tabular w-full text-left text-xs">
            <caption className="sr-only">{caption}</caption>
            <thead className="sticky top-0 bg-raised text-ink-3"><tr>{table.columns.map((c) => <th key={c} scope="col" className="px-2 py-1.5 font-medium">{c}</th>)}</tr></thead>
            <tbody>{table.rows.map((r, i) => <tr key={i} className="border-t border-line text-ink-2">{r.map((c, j) => <td key={j} className="px-2 py-1">{c}</td>)}</tr>)}</tbody>
          </table>
        </div>
      ) : children}
    </div>
  );
}

export function Sparkline({ values, color = 'var(--color-teal-300)', height = 32, label }: { values: (number | null)[]; color?: string; height?: number; label: string }) {
  const [ref, { width }] = useSize<HTMLDivElement>();
  const v = values.filter((x): x is number => x != null);
  const lo = Math.min(...v);
  const hi = Math.max(...v);
  let d = '';
  values.forEach((y, i) => {
    if (y == null) return;
    const x = (i / Math.max(1, values.length - 1)) * (width - 4) + 2;
    const yy = height - 3 - ((y - lo) / (hi - lo || 1)) * (height - 6);
    d += `${d ? 'L' : 'M'}${x.toFixed(1)},${yy.toFixed(1)}`;
  });
  return (
    <div ref={ref} style={{ height }} className="w-full">
      {width > 0 && <svg width={width} height={height} role="img" aria-label={label}><path d={d} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" /></svg>}
    </div>
  );
}

/** Horizontal comparison bars (HTML, so labels wrap and remain accessible). */
export function BarRows({ rows, max, unit = '', format = (v) => String(v) }: { rows: { label: ReactNode; value: number; color?: string; marker?: number; note?: ReactNode }[]; max: number; unit?: string; format?: (v: number) => string }) {
  return (
    <ul className="space-y-2.5">
      {rows.map((r, i) => (
        <li key={i}>
          <div className="mb-1 flex items-baseline justify-between gap-2 text-sm"><span className="text-ink-2">{r.label}</span><span className="tabular font-medium text-ink">{format(r.value)}{unit}{r.note && <span className="ml-1.5 text-xs font-normal text-ink-3">{r.note}</span>}</span></div>
          <div className="relative h-2.5 rounded-full bg-canvas">
            <div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(100, (r.value / (max || 1)) * 100))}%`, background: r.color ?? 'var(--color-teal-300)' }} />
            {r.marker != null && <div className="absolute -top-1 h-4.5 w-0.5 bg-ink" style={{ left: `${Math.min(100, (r.marker / (max || 1)) * 100)}%` }} title="Capacity" />}
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Diverging colour for a correlation in [-1, 1]: blue ← neutral grey → magenta. */
export function divergingColor(v: number): string {
  const neutral = [58, 74, 92];
  const neg = [57, 135, 229];
  const pos = [213, 81, 129];
  const t = Math.min(1, Math.abs(v));
  const to = v < 0 ? neg : pos;
  const c = neutral.map((n, i) => Math.round(n + (to[i] - n) * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

export function Matrix({ labels, value, onSelect, selected, ariaLabel }: { labels: { key: string; short: string }[]; value: (a: string, b: string) => { v: number | null; n: number }; onSelect?: (a: string, b: string) => void; selected?: [string, string] | null; ariaLabel: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="tabular border-separate border-spacing-0.5 text-xs" aria-label={ariaLabel}>
        <thead>
          <tr><th />{labels.map((l) => <th key={l.key} scope="col" className="px-1 pb-1 text-center font-medium text-ink-3">{l.short}</th>)}</tr>
        </thead>
        <tbody>
          {labels.map((r) => (
            <tr key={r.key}>
              <th scope="row" className="pr-2 text-right font-medium text-ink-3">{r.short}</th>
              {labels.map((c) => {
                const cell = value(r.key, c.key);
                const isSel = selected && selected[0] === r.key && selected[1] === c.key;
                return (
                  <td key={c.key} className="p-0">
                    <button type="button" onClick={() => onSelect?.(r.key, c.key)} disabled={r.key === c.key}
                      aria-label={`${r.short} vs ${c.short}: ${cell.v == null ? 'not computed' : `rho ${cell.v.toFixed(2)}`}, n=${cell.n}`}
                      className={cx('flex h-11 w-14 items-center justify-center rounded-md text-[12px] font-semibold', isSel && 'ring-2 ring-ink', r.key === c.key && 'opacity-40')}
                      style={{ background: cell.v == null ? 'var(--color-raised)' : divergingColor(cell.v), color: cell.v != null && Math.abs(cell.v) > 0.55 ? '#0b1220' : '#e8edf2' }}>
                      {cell.v == null ? '—' : cell.v.toFixed(2)}
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
