import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { Icon } from '../vendor/aether/ui';
import { SectionHeader } from './common';

const BodyTwin = lazy(() => import('./BodyTwin'));

function webglLikely(): boolean {
  try {
    const c = document.createElement('canvas');
    return !!(c.getContext('webgl2') || c.getContext('webgl'));
  } catch {
    return false;
  }
}

/** The 3D chunk (≈ renderer + procedural figure) is downloaded only when the section approaches the viewport. */
export function BodySection() {
  const ref = useRef<HTMLDivElement>(null);
  const [mount, setMount] = useState(false);
  const [gl] = useState(() => (typeof document === 'undefined' ? true : webglLikely()));
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === 'undefined') { setMount(true); return; }
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { setMount(true); io.disconnect(); } }, { rootMargin: '400px 0px' });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <section id="body" aria-labelledby="body-title" className="px-4 py-20 sm:px-6">
      <SectionHeader id="body" eyebrow="02 · Interactive BODY" title="A digital twin you can turn, zoom and x-ray">
        The same 3D engine and team models as the Windows application. Rotate, zoom, switch between Surface and X-ray, and
        toggle the five body systems.
      </SectionHeader>
      {/* min-height = rendered twin height, so lazy loading never shifts the sections below (anchor jumps stay exact) */}
      <div ref={ref} className="mx-auto min-h-[1130px] max-w-7xl lg:min-h-[629px]">
        {!gl && (
          <p role="note" className="mb-3 rounded-xl border border-attention/50 bg-attention/10 p-3 text-sm text-ink-2">
            WebGL is not available in this browser, so the twin is drawn with a simpler Canvas renderer. Everything stays interactive.
          </p>
        )}
        {mount ? (
          <Suspense fallback={<Placeholder label="Loading the 3D twin…" />}>
            <BodyTwin />
          </Suspense>
        ) : (
          <Placeholder label="The 3D twin loads when you reach this section." button={() => setMount(true)} />
        )}
      </div>
    </section>
  );
}

function Placeholder({ label, button }: { label: string; button?: () => void }) {
  return (
    <div className="glass grid min-h-[1130px] place-items-center rounded-2xl p-6 text-center lg:min-h-[629px]">
      <div>
        <Icon name="body" size={44} className="mx-auto text-teal-300" />
        <p className="mt-3 text-sm text-ink-2" role="status">{label}</p>
        {button && <button type="button" onClick={button} className="mt-4 rounded-xl border border-line-strong px-4 py-2 text-sm text-ink hover:border-teal-300">Load 3D now</button>}
      </div>
    </div>
  );
}
