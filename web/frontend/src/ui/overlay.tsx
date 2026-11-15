import { createContext, useCallback as useCb, useContext, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { Icon } from './Icon';

/**
 * Tooltip. Render-prop gives the trigger the id to reference with aria-describedby,
 * so the hint is available to screen readers as well as on hover / focus.
 */
export function Tooltip({ text, children, side = 'top', block = false }: { text: ReactNode; children: (describedBy: string) => ReactNode; side?: 'top' | 'bottom'; block?: boolean }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  return (
    <span className={block ? 'relative flex w-full min-w-0' : 'relative inline-flex'} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
      onKeyDown={(e) => { if (e.key === 'Escape') setOpen(false); }}>
      {children(id)}
      <span id={id} role="tooltip"
        className={`pointer-events-none absolute left-1/2 z-50 w-max max-w-64 -translate-x-1/2 rounded-lg border border-line-strong bg-overlay px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-ink-2 shadow-xl transition-opacity duration-150 ${side === 'top' ? 'bottom-full mb-2' : 'top-full mt-2'} ${open ? 'opacity-100' : 'hidden'}`}>
        {text}
      </span>
    </span>
  );
}

/** Small (i) button that explains a term. */
export function InfoTip({ text, label = 'More information' }: { text: ReactNode; label?: string }) {
  return (
    <Tooltip text={text}>
      {(id) => (
        <button type="button" aria-label={label} aria-describedby={id} className="grid h-7 w-7 place-items-center rounded-full text-ink-3 transition-colors hover:text-teal-300">
          <Icon name="info" size={14} />
        </button>
      )}
    </Tooltip>
  );
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Modal dialog: focus moves in, Tab is trapped, Escape / backdrop closes, focus returns to the opener. */
export function Dialog({ open, onClose, title, description, children, footer, wide }: {
  open: boolean; onClose: () => void; title: string; description?: ReactNode; children?: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descId = useId();
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const el = ref.current;
    (el?.querySelector<HTMLElement>('[data-autofocus]') ?? el?.querySelector<HTMLElement>(FOCUSABLE))?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); onClose(); return; }
      if (e.key !== 'Tab' || !el) return;
      const items = [...el.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); opener?.focus?.(); };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[60] grid place-items-center bg-[rgb(2_5_10/0.72)] p-4 backdrop-blur-sm" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={description ? descId : undefined}
        className={`card max-h-[90vh] w-full overflow-auto p-5 ${wide ? 'max-w-3xl' : 'max-w-lg'}`}>
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <h2 id={titleId} className="text-lg font-semibold text-ink">{title}</h2>
            {description && <p id={descId} className="mt-1 text-sm text-ink-2">{description}</p>}
          </div>
          <button type="button" aria-label="Close dialog" onClick={onClose} className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-ink-3 hover:bg-raised hover:text-ink"><Icon name="x" size={17} /></button>
        </div>
        {children}
        {footer && <div className="mt-5 flex flex-wrap justify-end gap-2 border-t border-line pt-4">{footer}</div>}
      </div>
    </div>
  );
}

/** Loading placeholder shaped like the content it replaces. */
export function Skeleton({ lines = 3, height }: { lines?: number; height?: number }) {
  if (height) return <div className="skeleton" style={{ height }} aria-hidden />;
  return <div className="space-y-2" aria-hidden>{Array.from({ length: lines }, (_, i) => <div key={i} className="skeleton h-3.5" style={{ width: `${92 - i * 14}%` }} />)}</div>;
}

/* ───────────── Toasts ───────────── */

type ToastTone = 'good' | 'info' | 'attention' | 'high';
type ToastItem = { id: number; tone: ToastTone; title: string; body?: string };
const ToastCtx = createContext<(t: Omit<ToastItem, 'id'>) => void>(() => undefined);

/** Polite, auto-dismissing notifications (role=status). Errors stay until dismissed. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const seq = useRef(0);
  const dismiss = useCb((id: number) => setItems((l) => l.filter((x) => x.id !== id)), []);
  const push = useCb((t: Omit<ToastItem, 'id'>) => {
    const id = ++seq.current;
    setItems((l) => [...l.slice(-3), { ...t, id }]);
    if (t.tone !== 'high') setTimeout(() => dismiss(id), 4800);
  }, [dismiss]);
  const tone: Record<ToastTone, { icon: 'checkCircle' | 'info' | 'alert'; cls: string }> = {
    good: { icon: 'checkCircle', cls: 'border-good/60 text-good' }, info: { icon: 'info', cls: 'border-teal-300/60 text-teal-300' },
    attention: { icon: 'info', cls: 'border-attention/60 text-attention' }, high: { icon: 'alert', cls: 'border-high/60 text-high' },
  };
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`pointer-events-auto flex items-start gap-2.5 rounded-xl border bg-overlay/95 p-3 shadow-2xl backdrop-blur page-enter ${tone[t.tone].cls}`}>
            <Icon name={tone[t.tone].icon} size={17} className="mt-0.5 shrink-0" />
            <div className="min-w-0 flex-1"><div className="text-sm font-semibold text-ink">{t.title}</div>{t.body && <div className="mt-0.5 text-xs text-ink-2">{t.body}</div>}</div>
            <button type="button" aria-label="Dismiss notification" onClick={() => dismiss(t.id)} className="grid h-6 w-6 place-items-center rounded text-ink-3 hover:text-ink"><Icon name="x" size={14} /></button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);
