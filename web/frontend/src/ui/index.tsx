/**
 * AETHER UI kit. Every status is communicated with an icon + word (never colour alone).
 */
import { useId, useRef, useState, type ButtonHTMLAttributes, type KeyboardEvent, type ReactNode } from 'react';
import { setQuery, useRoute } from '../lib/router';
import { ApiError } from '../api/httpClient';
import type { DataSource, EnvStatus, PhantomStatus } from '../api/types';
import { Icon, type IconName } from './Icon';

export { Icon, type IconName };
export { Dialog, InfoTip, Skeleton, ToastProvider, Tooltip, useToast } from './overlay';
import { Skeleton } from './overlay';

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(' ');
}

/* ---------------------------------------------------------------- Buttons */
type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
const VARIANTS: Record<Variant, string> = {
  primary: 'bg-teal-300 text-canvas hover:bg-teal-100 active:brightness-95 font-semibold border border-transparent shadow-[0_6px_18px_-8px_var(--color-teal-300)]',
  secondary: 'bg-raised/80 text-ink border border-line-strong hover:border-teal-300 hover:bg-overlay active:bg-raised',
  ghost: 'bg-transparent text-ink-2 border border-transparent hover:bg-raised hover:text-ink',
  danger: 'bg-transparent text-high border border-high/60 hover:bg-high/10',
};
export function Button({ variant = 'secondary', size = 'md', icon, iconRight, children, className, ...rest }:
  { variant?: Variant; size?: 'sm' | 'md'; icon?: IconName; iconRight?: IconName; children?: ReactNode } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      {...rest}
      className={cx(
        'inline-flex items-center justify-center gap-2 rounded-[10px] transition-[color,background-color,border-color,transform,box-shadow] duration-150 active:translate-y-px disabled:pointer-events-none disabled:opacity-45',
        size === 'sm' ? 'px-2.5 py-1.5 text-[13px]' : 'px-3.5 py-2 text-sm',
        VARIANTS[variant], className,
      )}
    >
      {icon && <Icon name={icon} size={size === 'sm' ? 15 : 17} />}
      {children}
      {iconRight && <Icon name={iconRight} size={size === 'sm' ? 15 : 17} />}
    </button>
  );
}

/* ---------------------------------------------------------------- Cards */
export function Card({ title, eyebrow, actions, children, className, bodyClassName, id }:
  { title?: ReactNode; eyebrow?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClassName?: string; id?: string }) {
  return (
    <section className={cx('card flex min-w-0 flex-col', className)} aria-labelledby={title && id ? `${id}-title` : undefined}>
      {(title || eyebrow || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
          <div className="min-w-0">
            {eyebrow && <div className="eyebrow mb-0.5">{eyebrow}</div>}
            {title && <h2 id={id ? `${id}-title` : undefined} className="text-[15px] font-semibold text-ink">{title}</h2>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cx('min-w-0 flex-1 px-5 pb-5 pt-3', bodyClassName)}>{children}</div>
    </section>
  );
}

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-3xl">
        <div className="eyebrow">{eyebrow}</div>
        <h1 className="mt-1 text-2xl font-semibold text-ink">{title}</h1>
        {description && <p className="mt-1.5 text-ink-2">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/* ---------------------------------------------------------------- Status */
type Tone = 'good' | 'attention' | 'high' | 'unknown' | 'info' | 'analysis';
const TONE: Record<Tone, { cls: string; icon: IconName }> = {
  good: { cls: 'text-good border-good/40 bg-good/10', icon: 'checkCircle' },
  attention: { cls: 'text-attention border-attention/45 bg-attention/10', icon: 'info' },
  high: { cls: 'text-high border-high/45 bg-high/10', icon: 'alert' },
  unknown: { cls: 'text-ink-3 border-line-strong bg-raised', icon: 'info' },
  info: { cls: 'text-teal-300 border-teal-300/40 bg-teal-300/10', icon: 'info' },
  analysis: { cls: 'text-analysis border-analysis/45 bg-analysis/10', icon: 'brain' },
};
export function Pill({ tone, children, icon, className }: { tone: Tone; children: ReactNode; icon?: IconName; className?: string }) {
  const t = TONE[tone];
  return (
    <span className={cx('inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium', t.cls, className)}>
      <Icon name={icon ?? t.icon} size={13} />
      {children}
    </span>
  );
}

export function PhantomPill({ status }: { status: PhantomStatus }) {
  const map: Record<PhantomStatus, [Tone, string]> = { normal: ['good', 'Within personal baseline'], attention: ['attention', 'Review suggested'], insufficient: ['unknown', 'Insufficient data'] };
  const [tone, label] = map[status];
  return <Pill tone={tone}>{label}</Pill>;
}

export function EnvPill({ status }: { status: EnvStatus }) {
  const map: Record<EnvStatus, [Tone, string]> = { nominal: ['good', 'Within reference'], attention: ['attention', 'Above reference'], high: ['high', 'Well above reference'] };
  const [tone, label] = map[status];
  return <Pill tone={tone}>{label}</Pill>;
}

const SOURCE: Record<DataSource, { label: string; title: string; cls: string }> = {
  simulated: { label: 'Synthetic', title: 'Synthetic data generated by the AETHER simulator – not a real person or spacecraft.', cls: 'border-dashed border-ink-3 text-ink-2' },
  manual: { label: 'Manual entry', title: 'Entered by a person through AETHER.', cls: 'border-solid border-teal-300/60 text-teal-300' },
  estimated: { label: 'Model estimate', title: 'Calculated by a model from other data.', cls: 'border-dotted border-sage text-sage' },
  sensor: { label: 'Sensor', title: 'Measured by a connected sensor.', cls: 'border-solid border-good text-good' },
  reference: { label: 'Published source', title: 'Summarised from a published, checked source (see the evidence library) – not AETHER data.', cls: 'border-solid border-blue-300/60 text-blue-300' },
  research_prototype: { label: 'Analysis result', title: 'Output of an experimental, non-validated research algorithm (not a diagnosis).', cls: 'border-dotted border-analysis/70 text-analysis' },
};
/** Data provenance badge – required next to every displayed number group. */
export function SourceBadge({ source, className }: { source: DataSource | null | undefined; className?: string }) {
  const s = SOURCE[source ?? 'simulated'] ?? SOURCE.simulated;
  return (
    <span title={s.title} className={cx('inline-flex items-center gap-1 rounded-md border px-1.5 py-px text-[11px] font-medium uppercase tracking-wide', s.cls, className)}>
      <Icon name="database" size={11} />
      {s.label}
    </span>
  );
}

/* ---------------------------------------------------------------- States */
export function Loading({ label = 'Loading', className }: { label?: string; className?: string }) {
  return (
    <div role="status" aria-live="polite" className={cx('flex min-h-24 flex-col justify-center gap-3 py-3', className)}>
      <Skeleton lines={3} />
      <span className="flex items-center gap-2 text-xs text-ink-3"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-teal-300" />{label}…</span>
    </div>
  );
}

export function ErrorState({ error, onRetry, className }: { error: Error; onRetry?: () => void; className?: string }) {
  const net = error instanceof ApiError && error.isNetwork;
  return (
    <div role="alert" className={cx('flex flex-col items-start gap-2 rounded-xl border border-high/40 bg-high/5 p-4 text-sm', className)}>
      <div className="flex items-center gap-2 font-medium text-high"><Icon name={net ? 'wifiOff' : 'alert'} size={16} />{net ? 'Backend unreachable' : 'Could not load this data'}</div>
      <p className="text-ink-2">{error.message}</p>
      {onRetry && <Button size="sm" icon="reset" onClick={onRetry}>Try again</Button>}
    </div>
  );
}

export function Empty({ title, children, icon = 'info', className }: { title: string; children?: ReactNode; icon?: IconName; className?: string }) {
  return (
    <div className={cx('flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-line-strong p-6 text-center text-sm', className)}>
      <Icon name={icon} size={22} className="text-ink-3" />
      <div className="font-medium text-ink">{title}</div>
      {children && <div className="max-w-md text-ink-3">{children}</div>}
    </div>
  );
}

/** Renders loading / error / content for a Resource-like object. */
export function Async<T>({ res, children, loadingLabel, className }: { res: { data?: T; error?: Error; loading: boolean; reload: () => void }; children: (d: T) => ReactNode; loadingLabel?: string; className?: string }) {
  if (res.error) return <ErrorState error={res.error} onRetry={res.reload} className={className} />;
  if (res.data === undefined) return <Loading label={loadingLabel} className={className} />;
  return <>{children(res.data)}</>;
}

export function Notice({ tone = 'info', title, children, className }: { tone?: Tone; title?: string; children: ReactNode; className?: string }) {
  const t = TONE[tone];
  return (
    <div className={cx('flex gap-2.5 rounded-xl border p-3 text-sm', t.cls.replace(/text-\S+/, ''), className)}>
      <Icon name={t.icon} size={17} className={cx('mt-0.5 shrink-0', t.cls.split(' ')[0])} />
      <div className="text-ink-2">{title && <div className="mb-0.5 font-medium text-ink">{title}</div>}{children}</div>
    </div>
  );
}

/* ---------------------------------------------------------------- Data display */
export function Stat({ label, value, unit, sub, icon, source, emphasis }: { label: string; value: ReactNode; unit?: string; sub?: ReactNode; icon?: IconName; source?: DataSource | null; emphasis?: boolean }) {
  return (
    <div className={cx('min-w-0 rounded-xl border border-line bg-raised/60 p-3', emphasis && 'border-teal-600')}>
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 truncate text-xs font-medium text-ink-3">{icon && <Icon name={icon} size={14} />}{label}</span>
        {source && <SourceBadge source={source} />}
      </div>
      <div className="tabular mt-1 text-2xl font-semibold text-ink">{value}{unit && <span className="ml-1 text-sm font-normal text-ink-3">{unit}</span>}</div>
      {sub && <div className="mt-0.5 text-xs text-ink-3">{sub}</div>}
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange, label, size = 'md' }: { value: T; options: { value: T; label: ReactNode; icon?: IconName }[]; onChange: (v: T) => void; label: string; size?: 'sm' | 'md' }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex flex-wrap gap-1 rounded-xl border border-line bg-canvas/60 p-1">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          onKeyDown={(e) => {
            const i = options.findIndex((x) => x.value === value);
            if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { e.preventDefault(); onChange(options[(i + 1) % options.length].value); }
            if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); onChange(options[(i - 1 + options.length) % options.length].value); }
          }}
          tabIndex={value === o.value ? 0 : -1}
          className={cx('inline-flex items-center gap-1.5 rounded-lg transition-colors', size === 'sm' ? 'min-h-7 px-2 py-1 text-xs' : 'min-h-8 px-3 py-1.5 text-sm',
            value === o.value ? 'bg-teal-600 text-white' : 'text-ink-2 hover:bg-raised hover:text-ink')}
        >
          {o.icon && <Icon name={o.icon} size={14} />}
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function SliderField({ label, value, min, max, step = 1, unit, onChange, format, hint }: { label: string; value: number; min: number; max: number; step?: number; unit?: string; onChange: (v: number) => void; format?: (v: number) => string; hint?: string }) {
  const id = useId();
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={id} className="text-sm text-ink-2">{label}</label>
        <output htmlFor={id} className="tabular text-sm font-semibold text-ink">{format ? format(value) : value}{unit && <span className="ml-0.5 font-normal text-ink-3">{unit}</span>}</output>
      </div>
      <input id={id} type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="mt-1 w-full" aria-describedby={hint ? `${id}-h` : undefined} />
      {hint && <div id={`${id}-h`} className="text-xs text-ink-3">{hint}</div>}
    </div>
  );
}

export function NumberField({ label, value, onChange, min, max, step = 'any', unit, error, placeholder }: { label: string; value: string; onChange: (v: string) => void; min?: number; max?: number; step?: number | 'any'; unit?: string; error?: string; placeholder?: string }) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm text-ink-2">{label}{unit && <span className="text-ink-3"> ({unit})</span>}</label>
      <input id={id} inputMode="decimal" type="number" value={value} min={min} max={max} step={step} placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)} className="field" aria-invalid={error ? true : undefined} aria-describedby={error ? `${id}-e` : undefined} />
      {error && <div id={`${id}-e`} className="mt-1 text-xs text-high">{error}</div>}
    </div>
  );
}

export function Disclosure({ summary, children, defaultOpen = false }: { summary: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div className="rounded-xl border border-line">
      <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)} className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm text-ink-2 hover:text-ink">
        <span>{summary}</span>
        <Icon name="chevronDown" size={16} className={cx('transition-transform', open && 'rotate-180')} />
      </button>
      {open && <div id={id} className="border-t border-line px-3 py-3 text-sm text-ink-2">{children}</div>}
    </div>
  );
}

export function Meter({ value, max, label, tone = 'info' }: { value: number; max: number; label: string; tone?: 'info' | 'attention' | 'high' }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : value > 0 ? 100 : 0;
  const color = tone === 'high' ? 'bg-high' : tone === 'attention' ? 'bg-attention' : 'bg-teal-300';
  return (
    <div role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value} className="h-2 w-full overflow-hidden rounded-full bg-canvas">
      <div className={cx('h-full rounded-full', color)} style={{ width: `${pct}%` }} />
    </div>
  );
}

/* ---------------------------------------------------------------- Missing data & pending backend */
/** Explicit "no data" marker – never render a blank or a zero for a missing value. */
export function MissingValue({ label = 'No data', title }: { label?: string; title?: string }) {
  return <span title={title ?? 'No measurement available for this item'} className="inline-flex items-center gap-1 rounded border border-dashed border-missing px-1.5 text-xs font-medium text-missing"><Icon name="minus" size={12} />{label}</span>;
}

/** Shown in Live Mode when the connected backend does not (yet) provide a contract. */
export function PendingBackend({ contract, owner, children }: { contract: string; owner: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-xl border border-dashed border-line-strong p-4 text-sm" role="note">
      <div className="flex items-center gap-2 font-medium text-ink"><Icon name="link" size={16} className="text-ink-3" />Waiting for backend integration</div>
      <p className="text-ink-2">This view is ready but the connected API does not provide <code className="rounded bg-raised px-1">{contract}</code> yet (owner: {owner}). An offline preview is available in Demo Mode.</p>
      {children}
    </div>
  );
}

/* ---------------------------------------------------------------- Tabs (URL-synchronised) */
export type TabDef<T extends string> = { id: T; label: string; icon?: IconName; badge?: ReactNode };

/** Current tab from `?tab=`, falling back to the first tab. */
export function useTab<T extends string>(tabs: readonly TabDef<T>[]): [T, (t: T) => void] {
  const { query } = useRoute();
  const q = query.get('tab') as T | null;
  const current = tabs.some((t) => t.id === q) ? (q as T) : tabs[0].id;
  return [current, (t: T) => setQuery('tab', t === tabs[0].id ? null : t)];
}

export function Tabs<T extends string>({ tabs, value, onChange, label }: { tabs: readonly TabDef<T>[]; value: T; onChange: (t: T) => void; label: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const baseId = useId();
  const onKey = (e: KeyboardEvent, i: number) => {
    let j = i;
    if (e.key === 'ArrowRight') j = (i + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') j = (i - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') j = 0;
    else if (e.key === 'End') j = tabs.length - 1;
    else return;
    e.preventDefault();
    onChange(tabs[j].id);
    refs.current[j]?.focus();
  };
  return (
    <div role="tablist" aria-label={label} className="mb-5 flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((t, i) => (
        <button key={t.id} ref={(el) => { refs.current[i] = el; }} id={`${baseId}-${t.id}`} type="button" role="tab" aria-selected={value === t.id}
          aria-controls="module-tabpanel" tabIndex={value === t.id ? 0 : -1} onClick={() => onChange(t.id)} onKeyDown={(e) => onKey(e, i)}
          className={cx('-mb-px inline-flex min-h-10 shrink-0 items-center gap-2 border-b-2 px-3 text-sm font-medium transition-colors',
            value === t.id ? 'border-teal-300 text-ink' : 'border-transparent text-ink-3 hover:text-ink')}>
          {t.icon && <Icon name={t.icon} size={16} />}
          {t.label}
          {t.badge}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({ children, label }: { children: ReactNode; label: string }) {
  return <div id="module-tabpanel" role="tabpanel" aria-label={label} tabIndex={-1} className="outline-none">{children}</div>;
}
