import { useState, type FormEvent } from 'react';
import { CAPABILITIES, type HazardGraph, type HazardId, type MissionProfile } from '../../api/types';
import { useResource } from '../../lib/useResource';
import { useApp } from '../../state/AppState';
import { Async, Button, Card, Empty, Notice, Pill, Segmented, SourceBadge } from '../../ui';
import { ModuleHeader } from '../shared/ModuleHeader';

const DEFAULT: MissionProfile = { destination: 'mars', mission_days: 180, crew_size: 4, co2_ppm: 2500, cabin_pressure_mmhg: 760, temperature_c: 22, sleep_hours: 6.5, spe_dose_msv: 0 };
const TYPE_STYLE: Record<string, { dash: string; label: string }> = {
  evidence: { dash: '', label: 'Evidence-supported' }, assumption: { dash: '6 4', label: 'Model assumption' }, hypothesis: { dash: '2 4', label: 'Hypothetical' },
};

/** NASA five hazards, HRP risk mapping, hazard-interaction graph and the offline evidence library (0.9). */
export function SciencePage() {
  const { api, hasCapability, mode } = useApp();
  const enabled = hasCapability(CAPABILITIES.science);
  const [profile, setProfile] = useState<MissionProfile>(DEFAULT);
  const [draft, setDraft] = useState({ mission_days: String(DEFAULT.mission_days), co2_ppm: String(DEFAULT.co2_ppm), spe: '0' });
  const hz = useResource(enabled ? `sci-hz-${mode}` : null, () => api.scienceHazards());
  const ev = useResource(enabled ? `sci-ev-${mode}` : null, () => api.scienceEvidence());
  const gr = useResource(enabled ? `sci-gr-${mode}-${JSON.stringify(profile)}` : null, () => api.scienceGraph(profile));
  const apply = (e?: FormEvent) => {
    e?.preventDefault();
    const clamp = (v: string, lo: number, hi: number, d: number) => { const n = Number(v); return Number.isFinite(n) ? Math.min(hi, Math.max(lo, Math.round(n))) : d; };
    setProfile((p) => ({ ...p, mission_days: clamp(draft.mission_days, 1, 1200, p.mission_days), co2_ppm: clamp(draft.co2_ppm, 300, 20000, p.co2_ppm), spe_dose_msv: clamp(draft.spe, 0, 1000, p.spe_dose_msv) }));
  };
  return (
    <div>
      <ModuleHeader module="/science" title="Scientific core · NASA human-spaceflight hazards"
        description="How AETHER’s modules relate to the NASA Human Research Program hazards and risks, with every claim tied to a source that was checked. Exposure indices rank attention; they are not risk probabilities." />
      {!enabled ? <Empty title="Scientific core needs the AETHER backend" icon="info">Open the desktop app or switch to Live Mode. Demo Mode does not include the evidence library.</Empty> : (
        <div className="space-y-4">
          <Card eyebrow="NASA HRP · 5 hazards of human spaceflight" title="Five Hazards model" actions={<SourceBadge source="reference" />}>
            <Async res={hz} loadingLabel="Loading hazards">{(h) => (
              <ul aria-label="NASA five hazards" className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {h.hazards.map((x) => {
                  const level = gr.data?.exposure[x.id as HazardId];
                  return (
                    <li key={x.id} className="rounded-lg border border-line p-3 text-sm">
                      <div className="flex items-center justify-between gap-2"><span className="font-semibold text-ink">{x.name}</span>
                        {level != null && <Pill tone={level >= 1 ? 'high' : level >= 0.5 ? 'attention' : 'good'}>exposure {level.toFixed(2)}</Pill>}</div>
                      <dl className="mt-2 space-y-1 text-xs text-ink-2">
                        <div><dt className="inline text-ink-3">Inputs: </dt><dd className="inline">{x.inputs.join('; ')}</dd></div>
                        <div><dt className="inline text-ink-3">Body indicators: </dt><dd className="inline">{x.body_indicators.join('; ')}</dd></div>
                        <div><dt className="inline text-ink-3">HRP risks: </dt><dd className="inline">{x.consequences.map((c) => c.replace('Risk of ', '')).join('; ')}</dd></div>
                        <div><dt className="inline text-ink-3">AETHER modules: </dt><dd className="inline">{x.modules.join('; ')}</dd></div>
                        <div><dt className="inline text-ink-3">Index reference: </dt><dd className="inline">{x.reference}</dd></div>
                        <div><dt className="inline text-ink-3">Sources: </dt><dd className="inline">{x.sources.join(', ')}</dd></div>
                      </dl>
                      <p className="mt-2 text-xs text-ink-3">{x.limitations.join(' ')}</p>
                    </li>
                  );
                })}
              </ul>
            )}</Async>
          </Card>

          <Card eyebrow="Scenario-driven · typed edges" title="Hazard interaction graph" actions={<SourceBadge source="estimated" />}>
            <form onSubmit={apply} className="mb-3 flex flex-wrap items-end gap-3 text-sm">
              <Segmented label="Destination" value={profile.destination} onChange={(d) => setProfile((p) => ({ ...p, destination: d }))}
                options={[{ value: 'iss', label: 'ISS' }, { value: 'moon', label: 'Moon' }, { value: 'mars', label: 'Mars' }]} />
              <label className="flex flex-col text-xs text-ink-3">Mission duration<input aria-label="Mission duration" inputMode="numeric" className="mt-1 w-24 rounded border border-line bg-transparent px-2 py-1 text-sm text-ink" value={draft.mission_days} onChange={(e) => setDraft({ ...draft, mission_days: e.target.value })} /></label>
              <label className="flex flex-col text-xs text-ink-3">Cabin CO₂ (ppm)<input aria-label="Cabin CO2" inputMode="numeric" className="mt-1 w-24 rounded border border-line bg-transparent px-2 py-1 text-sm text-ink" value={draft.co2_ppm} onChange={(e) => setDraft({ ...draft, co2_ppm: e.target.value })} /></label>
              <label className="flex flex-col text-xs text-ink-3">SPE dose (mSv, user-set)<input aria-label="SPE dose" inputMode="numeric" className="mt-1 w-24 rounded border border-line bg-transparent px-2 py-1 text-sm text-ink" value={draft.spe} onChange={(e) => setDraft({ ...draft, spe: e.target.value })} /></label>
              <Button type="submit" size="sm" icon="play">Update graph</Button>
            </form>
            <Async res={gr} loadingLabel="Propagating exposures">{(g) => <HazardGraphView g={g} />}</Async>
          </Card>

          <Card eyebrow="NASA HRP · 17 risks" title="HRP risk mapping to AETHER modules" actions={<SourceBadge source="reference" />}>
            <Async res={hz} loadingLabel="Loading risk map">{(h) => (
              <div className="overflow-x-auto">
                <table aria-label="HRP risk mapping" className="w-full min-w-[720px] text-xs">
                  <thead><tr className="text-left text-ink-3"><th className="py-1">HRP risk</th><th>Group</th><th>AETHER signal / module</th><th>Coverage</th><th>Relation</th><th>Sources</th></tr></thead>
                  <tbody>{h.hrp_map.map((r) => (
                    <tr key={r.risk} className="border-t border-line align-top"><td className="py-1 pr-2 text-ink">{r.risk.replace('Risk of ', '')}</td><td>{r.group}</td>
                      <td className="pr-2">{r.aether.length ? r.aether.join('; ') : <span className="text-ink-3">none</span>}</td><td>{r.status}</td>
                      <td><Pill tone={r.relation === 'evidence' ? 'good' : r.relation === 'assumption' ? 'info' : 'unknown'}>{TYPE_STYLE[r.relation].label}</Pill></td><td>{r.sources.join(', ')}</td></tr>))}</tbody>
                </table>
                <p className="mt-2 text-xs text-ink-3">“Evidence-supported” means a library source links the hazard to the risk; it does not mean AETHER measures the risk. Most risks are not measured by AETHER at all.</p>
              </div>
            )}</Async>
          </Card>

          <Card eyebrow={`Offline · checked ${ev.data?.verified_on ?? ''}`} title="Scientific evidence library" actions={<SourceBadge source="reference" />}>
            <Async res={ev} loadingLabel="Loading evidence">{(l) => (
              <div className="overflow-x-auto">
                <table aria-label="Evidence library" className="w-full min-w-[820px] text-xs">
                  <thead><tr className="text-left text-ink-3"><th className="py-1">Source</th><th>Hazards</th><th>Finding (paraphrased)</th><th>Limitation</th><th>Checked</th></tr></thead>
                  <tbody>{l.entries.map((e) => (
                    <tr key={e.id} className="border-t border-line align-top">
                      <td className="w-64 py-1 pr-2"><a className="text-ink underline decoration-line hover:decoration-ink" style={{ display: "inline-block", minHeight: 24, paddingBlock: 3 }} href={e.url} target="_blank" rel="noreferrer">{e.title}</a>
                        <div className="text-ink-3">{e.authors} · {e.year}{e.doi ? ` · doi:${e.doi}` : ''}</div><div className="text-ink-3">{e.kind}</div><div className="break-all text-ink-3 select-all">{e.url}</div></td>
                      <td className="pr-2">{e.hazards.join(', ')}</td><td className="pr-2 text-ink-2">{e.finding}</td><td className="pr-2 text-ink-3">{e.limitation}</td>
                      <td className="text-ink-3">{e.verified_on}<div>{e.verified_via}</div></td></tr>))}</tbody>
                </table>
                {l.unreachable.length > 0 && <Notice tone="attention" title="Sources that could not be checked (not cited)" className="mt-3">
                  <ul className="list-disc pl-5">{l.unreachable.map((u) => <li key={u.url}>{u.url} – {u.reason}</li>)}</ul></Notice>}
              </div>
            )}</Async>
          </Card>
        </div>
      )}
    </div>
  );
}

function HazardGraphView({ g }: { g: HazardGraph }) {
  const hazards = g.nodes.filter((n) => n.kind === 'hazard');
  const risks = g.nodes.filter((n) => n.kind === 'risk');
  const W = 760, rowH = 26, H = Math.max(hazards.length, risks.length) * rowH + 30;
  const pos: Record<string, { x: number; y: number }> = {};
  hazards.forEach((n, i) => { pos[n.id] = { x: 150, y: 20 + i * ((H - 40) / Math.max(1, hazards.length - 1)) }; });
  risks.forEach((n, i) => { pos[n.id] = { x: 430, y: 18 + i * rowH }; });
  const fill = (l: number) => `color-mix(in srgb, var(--color-amber) ${Math.round(15 + l * 70)}%, transparent)`;
  return (
    <div>
      <div className="overflow-x-auto">
        <svg role="img" aria-label={`Hazard interaction graph – highest levels: ${g.summary}`} viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[640px]">
          {g.edges.filter((e) => pos[e.from] && pos[e.to]).map((e, i) => {
            const a = pos[e.from], b = pos[e.to];
            const same = a.x === b.x;
            const d = same ? `M${a.x + 8},${a.y} C${a.x + 90},${a.y} ${b.x + 90},${b.y} ${b.x + 8},${b.y}` : `M${a.x + 8},${a.y} C${(a.x + b.x) / 2},${a.y} ${(a.x + b.x) / 2},${b.y} ${b.x - 6},${b.y}`;
            return <path key={i} d={d} fill="none" stroke="var(--color-ink-2, #9ab)" strokeWidth={0.8 + e.strength * 2.2} strokeOpacity={0.25 + e.strength * 0.6} strokeDasharray={TYPE_STYLE[e.type].dash}><title>{`${e.from} → ${e.to}: ${TYPE_STYLE[e.type].label}${e.sources.length ? ` (${e.sources.join(', ')})` : ''}${e.note ? ` – ${e.note}` : ''}`}</title></path>;
          })}
          {hazards.map((n) => <g key={n.id}><circle cx={pos[n.id].x} cy={pos[n.id].y} r={9} fill={fill(n.level)} stroke="var(--color-amber)" />
            <text x={pos[n.id].x - 14} y={pos[n.id].y + 4} textAnchor="end" fontSize="11" fill="currentColor">{n.label} · {n.level.toFixed(2)}</text></g>)}
          {risks.map((n) => <g key={n.id}><rect x={pos[n.id].x - 6} y={pos[n.id].y - 7} width={12} height={12} rx={2} fill={fill(n.level)} stroke="var(--color-amber)" />
            <text x={pos[n.id].x + 12} y={pos[n.id].y + 4} fontSize="11" fill="currentColor">{n.label} · {n.level.toFixed(2)}</text></g>)}
        </svg>
      </div>
      <div className="mt-2 flex flex-wrap gap-4 text-xs text-ink-3">
        {Object.entries(TYPE_STYLE).map(([k, v]) => <span key={k} className="flex items-center gap-1"><svg width="28" height="6" aria-hidden="true"><line x1="0" y1="3" x2="28" y2="3" stroke="currentColor" strokeWidth="2" strokeDasharray={v.dash} /></svg>{v.label}: {g.legend[k]}</span>)}
      </div>
      <p className="mt-2 text-xs text-ink-3">Exposure: radiation median {g.exposure_detail.radiation_median_msv} mSv (95th pct {g.exposure_detail.radiation_p95_msv}) · ppCO₂ {g.exposure_detail.pp_co2_mmhg} mmHg · one-way delay {g.exposure_detail.one_way_delay_min} min · gravity {g.exposure_detail.gravity_g} g. {g.note}</p>
    </div>
  );
}
