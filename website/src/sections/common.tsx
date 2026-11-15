import { useEffect, useRef, type ReactNode } from 'react';
import { cx } from '../vendor/aether/ui';
import { SOURCES } from '../data/sources';

/** Fades children in when scrolled into view (no-op with reduced motion or without IntersectionObserver). */
export function Reveal({ children, className, as: Tag = 'div' }: { children: ReactNode; className?: string; as?: 'div' | 'section' | 'li' }) {
  const ref = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === 'undefined') { el.classList.add('in'); return; }
    const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } }), { rootMargin: '0px 0px -8% 0px' });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  const props = { ref: (n: HTMLElement | null) => { ref.current = n; }, className: cx('reveal', className) };
  return Tag === 'section' ? <section {...props}>{children}</section> : Tag === 'li' ? <li {...props}>{children}</li> : <div {...props}>{children}</div>;
}

export function SectionHeader({ eyebrow, title, children, id }: { eyebrow: string; title: ReactNode; children?: ReactNode; id: string }) {
  return (
    <header className="mx-auto mb-10 max-w-3xl text-center">
      <p className="mono-label !text-teal-300">{eyebrow}</p>
      <h2 id={`${id}-title`} className="mt-3 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">{title}</h2>
      {children && <p className="mt-4 text-base leading-relaxed text-ink-2">{children}</p>}
    </header>
  );
}

export function Cite({ ids }: { ids: string[] }) {
  return (
    <span className="ml-1 inline-flex flex-wrap gap-1 align-baseline">
      {ids.map((id) => (
        <a key={id} href={SOURCES[id].url} target="_blank" rel="noopener noreferrer" title={SOURCES[id].label}
          className="rounded border border-line-strong/50 px-1 font-mono text-[10px] text-teal-300 hover:border-teal-300">
          {id}
        </a>
      ))}
    </span>
  );
}

export function SyntheticBadge({ className }: { className?: string }) {
  return <span className={cx('inline-flex items-center gap-1 rounded-full border border-attention/60 bg-attention/10 px-2.5 py-0.5 font-mono text-[11px] font-semibold tracking-wide text-attention', className)}>SYNTHETIC DEMO</span>;
}
