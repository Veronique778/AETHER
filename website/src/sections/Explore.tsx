import { useCallback, useState } from 'react';
import { MODULES, type ModuleInfo } from '../data/modules';
import { Dialog, Icon, cx } from '../vendor/aether/ui';
import { Reveal, SectionHeader } from './common';

function ModuleArt({ id }: { id: string }) {
  // Small looping illustrations (CSS/SVG only), one per module. Decorative.
  const common = 'h-16 w-full';
  if (id === 'phantom' || id === 'biosignals') return (
    <svg viewBox="0 0 200 60" className={common} aria-hidden="true"><path className="ecg" d="M0 34 H60 l6 -12 l6 24 l8 -40 l8 40 l6 -12 H200" fill="none" stroke="#00e5ff" strokeWidth="2" /><line x1="0" x2="200" y1="34" y2="34" stroke="#a875ff" strokeOpacity=".35" strokeDasharray="4 4" /></svg>);
  if (id === 'symbiosis') return (
    <svg viewBox="0 0 200 60" className={common} aria-hidden="true"><circle className="breathe-orb" style={{ ['--breath' as string]: '6s' }} cx="70" cy="30" r="18" fill="#00d6c2" fillOpacity=".25" stroke="#00d6c2" /><circle className="breathe-orb" style={{ ['--breath' as string]: '7s' }} cx="130" cy="30" r="18" fill="#a875ff" fillOpacity=".2" stroke="#a875ff" /><path className="flow-dash" d="M88 30 H112" stroke="#9fc8bc" strokeWidth="2" /></svg>);
  if (id === 'co-orbit') return (
    <svg viewBox="0 0 200 60" className={common} aria-hidden="true">{[0, 1, 2, 3].map((r) => <rect key={r} x={20 + r * 6} y={8 + r * 12} width={60 + ((r * 37) % 90)} height="8" rx="3" fill={['#3987e5', '#199e70', '#9a7ae0', '#d55181'][r]} fillOpacity=".7" />)}</svg>);
  if (id === 'recovery') return (
    <svg viewBox="0 0 200 60" className={common} aria-hidden="true"><circle className="breathe-orb" cx="100" cy="30" r="24" fill="#6fe7ff" fillOpacity=".18" stroke="#6fe7ff" strokeOpacity=".6" /></svg>);
  if (id === 'mission-lab') return (
    <svg viewBox="0 0 200 60" className={common} aria-hidden="true">{[10, 26, 18, 34, 22, 40, 30].map((h, i) => <rect key={i} x={30 + i * 22} y={52 - h} width="12" height={h} rx="2" fill="#6ea2ff" fillOpacity={0.35 + i * 0.08} />)}</svg>);
  return (
    <svg viewBox="0 0 200 60" className={common} aria-hidden="true"><g className="orbit" style={{ transformOrigin: '100px 30px' }}><ellipse cx="100" cy="30" rx="60" ry="16" fill="none" stroke="#6ea2ff" strokeOpacity=".6" /><circle cx="160" cy="30" r="3.5" fill="#00e5ff" /></g><circle cx="100" cy="30" r="10" fill="#0d2234" stroke="#00e5ff" /></svg>);
}

export function Explore() {
  const [open, setOpen] = useState<ModuleInfo | null>(null);
  const close = useCallback(() => setOpen(null), []);
  return (
    <section id="modules" aria-labelledby="modules-title" className="px-4 py-20 sm:px-6">
      <SectionHeader id="modules" eyebrow="05 · Explore AETHER" title="Seven modules, one honest data model">
        Every number in AETHER carries its origin: real sensor, manual, research or synthetic. Open a module to see what it does and what is verified.
      </SectionHeader>
      <ul className="mx-auto grid max-w-7xl gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {MODULES.map((m) => (
          <Reveal as="li" key={m.id}>
            <button type="button" onClick={() => setOpen(m)} aria-haspopup="dialog"
              className="glass interactive group flex h-full w-full flex-col rounded-2xl p-5 text-left">
              <span className="flex items-center gap-3">
                <span className="grid h-10 w-10 place-items-center rounded-xl border border-teal-300/40 bg-teal-300/10 text-teal-300"><Icon name={m.icon} size={19} /></span>
                <span><span className="block font-semibold tracking-wide text-ink">{m.name}</span><span className="block text-xs text-ink-3">{m.tagline}</span></span>
              </span>
              <ModuleArt id={m.id} />
              <span className="mt-auto inline-flex items-center gap-1 text-sm text-teal-300">Details <Icon name="chevronRight" size={14} /></span>
            </button>
          </Reveal>
        ))}
      </ul>
      <Dialog open={!!open} onClose={close} title={open ? `${open.name} · ${open.tagline}` : ''}
        footer={open && (
          <div className="flex flex-wrap justify-end gap-2">
            {open.anchor && <a href={open.anchor} onClick={() => setOpen(null)} className="rounded-xl border border-teal-300/60 px-4 py-2 text-sm text-teal-300 hover:bg-teal-300/10">Try it on this page</a>}
            <button type="button" onClick={() => setOpen(null)} className="rounded-xl border border-line-strong px-4 py-2 text-sm text-ink">Close</button>
          </div>
        )}>
        {open && (
          <div className="space-y-3 text-sm text-ink-2">
            <ModuleArt id={open.id} />
            <p className="text-ink">{open.what}</p>
            <ul className="list-disc space-y-1 pl-5">{open.howItWorks.map((h) => <li key={h}>{h}</li>)}</ul>
            <p className={cx('rounded-lg border border-line bg-canvas/60 p-2.5 text-xs')}><strong className="text-ink">Status: </strong>{open.status}</p>
            <p className="text-xs text-ink-3">{open.demoHere ? `On this website: ${open.demoHere}.` : 'Available in the Windows application only.'}</p>
          </div>
        )}
      </Dialog>
    </section>
  );
}
