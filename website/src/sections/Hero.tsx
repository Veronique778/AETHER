import { useState } from 'react';
import { APP_VERSION, WINDOWS_DOWNLOAD_URL, downloadAvailable } from '../config/download';
import { Icon, cx } from '../vendor/aether/ui';

const LINKS = [['#problem', 'Problem'], ['#body', 'BODY'], ['#phantom', 'PHANTOM'], ['#evidence', 'Evidence'], ['#modules', 'Modules'], ['#download', 'Download']] as const;

export function DownloadButton({ size = 'lg', className, label = 'Download AETHER for Windows' }: { size?: 'sm' | 'lg'; className?: string; label?: string }) {
  const sz = size === 'lg' ? 'px-6 py-3.5 text-base' : 'px-3.5 py-2 text-sm';
  if (!downloadAvailable()) {
    return (
      <span role="status" className={cx('inline-flex items-center gap-2 rounded-xl border border-line-strong/70 bg-raised/60 font-semibold text-ink-2', sz, className)}>
        <Icon name="clock" size={size === 'lg' ? 18 : 15} /> Download coming soon
      </span>
    );
  }
  return (
    <a href={WINDOWS_DOWNLOAD_URL} target="_blank" rel="noopener noreferrer" data-testid="download-link"
      className={cx('cta-primary inline-flex items-center gap-2 rounded-xl font-semibold transition', sz, className)}>
      <Icon name="download" size={size === 'lg' ? 18 : 15} /> {label}
    </a>
  );
}

export function Nav() {
  const [open, setOpen] = useState(false);
  return (
    <nav aria-label="Primary" className="glass fixed inset-x-0 top-0 z-40 !rounded-none !border-x-0 !border-t-0">
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-4 sm:px-6">
        <a href="#top" className="flex items-center gap-2.5" aria-label="AETHER home">
          <Logo />
          <span className="font-semibold tracking-[0.28em] text-ink">AETHER</span>
        </a>
        <ul className="ml-auto hidden items-center gap-1 lg:flex">
          {LINKS.map(([href, label]) => <li key={href}><a href={href} className="rounded-lg px-3 py-2 text-sm text-ink-2 transition hover:bg-white/5 hover:text-ink">{label}</a></li>)}
        </ul>
        <div className="ml-auto hidden sm:block lg:ml-3"><DownloadButton size="sm" label="Download" /></div>
        <button type="button" className="ml-auto grid h-10 w-10 place-items-center rounded-lg border border-line-strong/60 text-ink lg:hidden sm:ml-2"
          aria-expanded={open} aria-controls="mobile-menu" aria-label={open ? 'Close menu' : 'Open menu'} onClick={() => setOpen((v) => !v)}>
          <Icon name={open ? 'x' : 'menu'} size={18} />
        </button>
      </div>
      {open && (
        <ul id="mobile-menu" className="border-t border-line px-4 pb-4 pt-2 lg:hidden">
          {LINKS.map(([href, label]) => <li key={href}><a href={href} onClick={() => setOpen(false)} className="block rounded-lg px-3 py-3 text-ink-2 hover:bg-white/5 hover:text-ink">{label}</a></li>)}
        </ul>
      )}
    </nav>
  );
}

export function Logo({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <defs><linearGradient id="lg" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stopColor="#00e5ff" /><stop offset="1" stopColor="#a875ff" /></linearGradient></defs>
      <circle cx="16" cy="16" r="13" fill="none" stroke="url(#lg)" strokeWidth="1.6" />
      <ellipse cx="16" cy="16" rx="13" ry="5" fill="none" stroke="#6ea2ff" strokeOpacity=".7" strokeWidth="1" transform="rotate(-24 16 16)" />
      <circle cx="16" cy="16" r="3.2" fill="url(#lg)" />
    </svg>
  );
}

function Telemetry() {
  return (
    <svg viewBox="0 0 400 400" className="h-full w-full" role="img" aria-label="Animated illustration: an astronaut heart-rate trace orbiting a planet">
      <defs>
        <radialGradient id="planet" cx="40%" cy="35%"><stop offset="0" stopColor="#1b3c5c" /><stop offset=".7" stopColor="#081827" /><stop offset="1" stopColor="#030b17" /></radialGradient>
        <linearGradient id="trace" x1="0" x2="1"><stop offset="0" stopColor="#00e5ff" stopOpacity="0" /><stop offset=".5" stopColor="#00e5ff" /><stop offset="1" stopColor="#a875ff" /></linearGradient>
      </defs>
      <g className="orbit slow"><circle cx="200" cy="200" r="182" fill="none" stroke="#4f7290" strokeOpacity=".35" strokeDasharray="2 10" /></g>
      <circle cx="200" cy="200" r="118" fill="url(#planet)" stroke="#15304a" />
      <path d="M95 175 Q200 140 305 175" fill="none" stroke="#00e5ff" strokeOpacity=".18" />
      <path d="M90 225 Q200 260 310 225" fill="none" stroke="#a875ff" strokeOpacity=".16" />
      <g className="orbit">
        <ellipse cx="200" cy="200" rx="165" ry="62" fill="none" stroke="#6ea2ff" strokeOpacity=".45" transform="rotate(-22 200 200)" />
        <circle cx="352" cy="138" r="5" fill="#00e5ff" />
      </g>
      <path className="ecg" d="M40 300 H130 l10 -22 l10 44 l12 -76 l12 76 l8 -22 H260 l10 -16 l10 30 l12 -54 l12 54 l8 -14 H360" fill="none" stroke="url(#trace)" strokeWidth="2.4" strokeLinejoin="round" />
      <text x="40" y="340" fill="#7592a8" fontFamily="JetBrains Mono, monospace" fontSize="11">HR · 5-MIN WINDOWS · PERSONAL BASELINE</text>
    </svg>
  );
}

export function Hero() {
  return (
    <section id="top" className="relative overflow-hidden pt-28 sm:pt-32" aria-labelledby="hero-title">
      <div className="grid-lines pointer-events-none absolute inset-0" aria-hidden="true" />
      <div className="relative mx-auto grid max-w-7xl items-center gap-10 px-4 pb-16 sm:px-6 lg:grid-cols-[1.1fr_.9fr] lg:pb-24">
        <div>
          <p className="mono-label !text-teal-300">AETHER · Adaptive Ecosystem for Human Exploration and Resilience</p>
          <h1 id="hero-title" className="mt-5 text-4xl font-semibold leading-[1.05] tracking-tight sm:text-6xl">
            <span className="text-gradient">The Future of Human Health Beyond Earth</span>
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-ink-2">
            A research prototype for long-duration missions: personal monitoring of physiological change, scientifically grounded
            signal processing with honest data labels, and a 3D human digital twin — built for NASA Space Apps Challenge 2026.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <DownloadButton />
            <a href="#phantom" className="inline-flex items-center gap-2 rounded-xl border border-line-strong px-6 py-3.5 text-base font-semibold text-ink transition hover:border-teal-300 hover:bg-white/5">
              <Icon name="play" size={18} /> Explore Interactive Demo
            </a>
          </div>
          <p className="mt-5 text-xs text-ink-3">Windows 10/11 x64 · version {APP_VERSION} · research prototype, not a medical device · not affiliated with or endorsed by NASA.</p>
        </div>
        <div className="glass relative mx-auto aspect-square w-full max-w-[460px] rounded-[28px] p-4">
          <Telemetry />
          <div className="absolute bottom-5 right-5 rounded-lg border border-line bg-canvas/80 px-3 py-2 text-[11px] text-ink-2">
            <span className="font-mono text-teal-300">illustration</span> · no live data
          </div>
        </div>
      </div>
    </section>
  );
}
