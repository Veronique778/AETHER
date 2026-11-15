import { useEffect, useState } from 'react';
import { Card, Pill } from '../../ui';

type Group = { token: string; phase: string; count: number; mean: number; median: number };
type Reference = {
  import_id: string; study: string; study_title?: string | null; filename: string; column: string; unit: string;
  organism: string; evidence_label: string; sha256: string; retrieved_at_utc: string; official_url?: string;
  summary: { count: number; mean: number; median: number; minimum: number; maximum: number; timepoints?: { groups: Group[]; subjects_detected: string[] } };
};
type Context = { references: Reference[]; count: number; policy: string };

/**
 * NASA research data beside PHANTOM (AETHER 1.4). Read-only context: the backend lists only verified
 * NASA OSDR downloads of human in vivo clinical/physiological data. Nothing here feeds PHANTOM's
 * baseline, threshold or score.
 */
export function NasaReferenceCard() {
  const [ctx, setCtx] = useState<Context | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    fetch('/api/nasa/reference-context', { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d: Context) => { if (alive) setCtx(d); }, (e: Error) => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, []);
  return (
    <Card eyebrow="NASA research data · context only" title="NASA OSDR human reference data" className="mb-4" id="nasa-reference-context">
      <div data-testid="nasa-reference-context">
        <p className="text-xs text-ink-3">{ctx?.policy ?? 'Only verified NASA OSDR downloads of human in vivo clinical/physiological data appear here. They are not used to calibrate PHANTOM.'}</p>
        {error && <p role="status" className="mt-2 text-xs text-attention">NASA reference context unavailable: {error}</p>}
        {ctx && ctx.count === 0 && <p className="mt-2 text-sm text-ink-2">No eligible NASA import yet. In NASA DATA LAB, import a public human clinical CSV (for example OSD-575, Inspiration4 serum metabolic panel) to show it here.</p>}
        {ctx?.references.map((r) => (
          <div key={r.import_id} className="mt-3 rounded-xl border border-line p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2"><Pill tone="info">NASA research data</Pill><strong>{r.study}</strong><span className="text-ink-3">{r.study_title ?? ''}</span></div>
            <p className="mt-1">{r.column} · n = {r.summary.count} · median {r.summary.median} {r.unit.startsWith('not stated') ? '(unit not stated in file)' : r.unit} · range {r.summary.minimum}–{r.summary.maximum}</p>
            {r.summary.timepoints && <p className="mt-1 text-xs text-ink-2">Timepoints: {r.summary.timepoints.groups.map((g) => `${g.token} (n=${g.count}, median ${g.median})`).join(' · ')}</p>}
            <p className="mt-1 text-xs text-ink-3">{r.organism} · {r.evidence_label} · {r.filename} · SHA-256 {r.sha256.slice(0, 16)}… · retrieved {r.retrieved_at_utc}</p>
            {r.official_url && <a className="text-xs underline" href={r.official_url} target="_blank" rel="noopener noreferrer">Official OSDR study page</a>}
          </div>
        ))}
      </div>
    </Card>
  );
}
