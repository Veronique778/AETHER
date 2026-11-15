import { useEffect, useMemo, useState } from 'react';
import type { Measurement } from '../../api/accountApi';
import { BODY_SYSTEMS, type BodySystem } from '../../lib/format';
import { navigate } from '../../lib/router';
import { hexToRgb } from '../../scene3d/engine';
import { METRIC_ANCHORS, SYSTEM_FOCUS } from '../../scene3d/models';
import type { Vec3 } from '../../scene3d/engine';
import { latestTwinReadings } from './personalTwinData';
import { HUMAN_ASSETS, type HumanAssetId } from '../../scene3d/humanAssets';
import { Viewport } from '../../scene3d/Viewport';
import { useHumanModel } from '../../scene3d/useHumanModel';
import { useApp } from '../../state/AppState';
import { useAuth } from '../../state/AuthState';
import { Button, Segmented } from '../../ui';

const SYSTEMS: BodySystem[] = ['cardiovascular', 'respiratory', 'nervous', 'musculoskeletal', 'metabolic'];
/** The personal visual layer reads ONLY records fetched from authenticated BE2 SQLite. */
export function PersonalTwin({ measurements }: { measurements: Measurement[] }) {
  const { reducedMotion } = useApp();
  const { api: personalApi, token } = useAuth();
  const [lastAnalysis, setLastAnalysis] = useState<{ outcome: string; created_at?: string; explain?: { data_label?: string } } | null>(null);
  const [originFilter, setOriginFilter] = useState<'all' | 'real' | 'manual' | 'simulated' | 'research'>('all');
  const [asset, setAssetState] = useState<HumanAssetId>(() => {
    try {
      const stored = localStorage.getItem('aether.personalHumanModel') as HumanAssetId | null;
      if (stored && HUMAN_ASSETS.some((model) => model.id === stored)) return stored;
    } catch { /* storage unavailable */ }
    return 'anatom'; // the human model is the default, not an EVA suit
  });
  const [xray, setXray] = useState(false);
  const [selected, setSelected] = useState<BodySystem>('cardiovascular');
  const [layers, setLayers] = useState<Record<BodySystem, boolean>>({
    cardiovascular: true, respiratory: true, nervous: true, musculoskeletal: true, metabolic: true,
  });
  const { model, status, error } = useHumanModel(asset, xray);
  const readings = useMemo(() => latestTwinReadings(measurements.filter((row) => originFilter === 'all' || row.origin === originFilter)), [measurements, originFilter]);
  useEffect(() => {
    if (!token) { setLastAnalysis(null); return; }
    let active = true;
    const controller = new AbortController();
    void personalApi.science<{ items: Array<{ outcome: string; created_at?: string; explain?: { data_label?: string } }> }>(token, '/phantom-analyses', undefined, controller.signal)
      .then((result) => { if (active) setLastAnalysis(result.items[0] ?? null); })
      .catch(() => { if (active) setLastAnalysis(null); });
    return () => { active = false; controller.abort(); };
  }, [personalApi, token]);
  const hidden = useMemo(() => new Set(SYSTEMS.filter((s) => !layers[s] || !xray)), [layers, xray]);
  const highlight = useMemo(() => ({ [selected]: { color: hexToRgb('#00e5ff'), amount: 0.35 } }), [selected]);
  const dim = useMemo(() => (id: string | null, layer?: string) =>
    layer === 'shell' && id && layers[id as BodySystem] === false ? 0.18
      : layer === 'shell' || !id || id === selected ? 1 : 0.55, [layers, selected]);
  const chooseModel = (id: HumanAssetId) => {
    try { localStorage.setItem('aether.personalHumanModel', id); } catch { /* storage unavailable */ }
    setAssetState(id);
  };
  const active = readings.filter((r) => layers[r.signal.system]);
  const anchors: Record<string, Vec3> = {
    rr_interval: [-0.55, 1.45, 0.50],
    spo2: [-0.65, 1.85, 0.50],
    respiratory_rate: [0.75, 2.15, 0.45],
  };
  return (
    <section className="card space-y-4 p-4" aria-label="Personal 3D digital twin with stored measurements">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="mono-label text-good">PERSONAL 3D TWIN · AUTHENTICATED HISTORY</p>
          <h2 className="text-lg font-semibold">Your measurements on the 3D human model</h2>
          <p className="mt-1 text-xs text-ink-3">Markers come from your account's stored records (not current live telemetry). Missing signals are never invented. Body regions are approximate, not anatomical diagnoses.</p>
        </div>
        <Button onClick={() => navigate('/phantom')}>Open personal PHANTOM</Button>
      </header>
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_250px]">
        <div className="always-dark relative min-w-0 overflow-hidden rounded-xl border border-line">
          <Viewport model={model} height={480} reducedMotion={reducedMotion}
            initialCamera={{ yaw: 0.35, pitch: 0.08, dist: 10.5, target: [0, 0.35, 0], fov: 0.72 }}
            focus={SYSTEM_FOCUS[selected]} highlight={highlight} dim={dim} hiddenLayers={hidden}
            onPick={(id) => { if (id && SYSTEMS.includes(id as BodySystem)) setSelected(id as BodySystem); }}
            anchors={active.map((r) => ({
              id: r.signal.key, pos: METRIC_ANCHORS[r.signal.key as keyof typeof METRIC_ANCHORS] ?? anchors[r.signal.key] ?? [0, 1.5, 0.5],
              render: () => <button type="button" onClick={() => setSelected(r.signal.system)}
                aria-label={`${r.signal.label}: ${r.value.toFixed(1)} ${r.signal.unit}, ${r.origin}, stored measurement`}
                className="rounded-full border border-cyan-400/70 bg-[#10283b]/90 px-2 py-1 text-xs text-white shadow-lg">
                {r.signal.label}: {Number(r.value.toFixed(1))} {r.signal.unit}
              </button>,
            }))}
            ariaLabel="Personal digital twin; rotate, zoom and select an approximate body system. Labelled markers show stored personal measurements."
            instructions="Drag / arrows rotate · zoom ± · click system · markers are historical" />
        </div>
        <div className="space-y-3">
          <label className="block text-xs text-ink-2">Data provenance
            <select aria-label="Personal 3D data origin" className="field mt-1 w-full" value={originFilter}
              onChange={(e) => setOriginFilter(e.target.value as typeof originFilter)}>
              <option value="all">All origins (each labelled)</option>
              <option value="real">Real / server-verified where available</option>
              <option value="manual">Manual</option>
              <option value="simulated">Synthetic</option>
              <option value="research">Research</option>
            </select>
          </label>
          <label className="block text-xs text-ink-2">3D human / astronaut model
            <select aria-label="Personal 3D model" className="field mt-1 w-full" value={asset}
              onChange={(e) => chooseModel(e.target.value as HumanAssetId)}>
              {HUMAN_ASSETS.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
            </select>
          </label>
          {status === 'loading' && <p className="text-xs text-ink-3">Loading 3D model…</p>}
          {status === 'error' && <p role="alert" className="text-xs text-attention">Model unavailable: {error}. Using schematic fallback.</p>}
          <Segmented size="sm" label="Personal 3D view" value={xray ? 'xray' : 'surface'} onChange={(v) => setXray(v === 'xray')}
            options={[{ value: 'surface', label: 'Surface' }, { value: 'xray', label: 'X-ray' }]} />
          <fieldset className="space-y-1"><legend className="mono-label">Physiological systems</legend>
            {SYSTEMS.map((s) => <label key={s} className="flex items-center gap-2 rounded-lg px-1 py-1 text-xs">
              <input type="checkbox" checked={layers[s]} aria-label={`Show ${BODY_SYSTEMS[s].label} in personal twin`}
                onChange={(e) => setLayers((prev) => ({ ...prev, [s]: e.target.checked }))} />
              <button type="button" onClick={() => setSelected(s)} className="text-left" aria-pressed={selected === s}>
                <span style={{ color: BODY_SYSTEMS[s].color }}>●</span> {BODY_SYSTEMS[s].label}
              </button>
            </label>)}
          </fieldset>
          <p className="text-xs text-ink-3">{readings.length} supported signal types found in the loaded records. Other systems are visualization layers only.</p>
          <div className="rounded-lg border border-line p-3 text-xs" aria-label="Saved PHANTOM status on personal twin">
            <strong>Last saved PHANTOM analysis</strong>
            <p className="mt-1">{lastAnalysis ? `${lastAnalysis.outcome.toUpperCase()} · ${lastAnalysis.explain?.data_label ?? 'source not specified'}` : 'None found / unavailable'}</p>
            <p className="text-ink-3">Historical statistical analysis, not a current diagnosis. The latest analysis may refer to a different data class or time window.</p>
          </div>
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" aria-label="Personal values mapped to systems">
        {readings.length === 0 && <p className="text-sm text-ink-3">No usable stored measurements yet. Record a real HRS session or add a manual sample in PHANTOM.</p>}
        {readings.map((r) => <div key={r.signal.key} className="rounded-xl border border-line p-3 text-sm">
          <div className="font-semibold">{r.signal.label}: {Number(r.value.toFixed(1))} {r.signal.unit}</div>
          <p className="text-xs text-ink-3">{BODY_SYSTEMS[r.signal.system].label} · {r.provenance} · {r.quality}</p>
          <p className="text-xs text-ink-3">{new Date(r.timestamp).toLocaleString()} · historical, not live</p>
        </div>)}
      </div>
    </section>
  );
}
