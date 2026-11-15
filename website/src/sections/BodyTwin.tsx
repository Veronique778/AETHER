/** Lazily loaded chunk: the BODY digital twin (vendored AETHER WebGL2 renderer, Canvas-2D fallback). */
import { useMemo, useState } from 'react';
import { BODY_SYSTEMS, type BodySystem } from '../vendor/aether/lib/format';
import { HUMAN_ASSETS, type HumanAssetId } from '../vendor/aether/scene3d/humanAssets';
import { SYSTEM_FOCUS } from '../vendor/aether/scene3d/models';
import { useHumanModel } from '../vendor/aether/scene3d/useHumanModel';
import { Viewport } from '../vendor/aether/scene3d/Viewport';
import { Icon, InfoTip, cx } from '../vendor/aether/ui';

const ORDER: BodySystem[] = ['cardiovascular', 'respiratory', 'nervous', 'musculoskeletal', 'metabolic'];
const SELECT: [number, number, number] = [0, 229, 255];
const WHY: Record<BodySystem, string> = {
  cardiovascular: 'Long-duration flight changes the cardiovascular system. In AETHER, heart rate from a Bluetooth sensor feeds PHANTOM.',
  respiratory: 'No respiratory measurement in AETHER yet — this layer is a visual reference only.',
  nervous: 'Sleep, reaction time and fatigue are tracked as behavioural-health signals in the synthetic mission.',
  musculoskeletal: 'Unloading causes bone and muscle loss; exercise minutes are the countermeasure signal in the synthetic mission.',
  metabolic: 'Shown for orientation; no metabolic metric is measured.',
};
const ASSETS = HUMAN_ASSETS;

export default function BodyTwin() {
  const [asset, setAsset] = useState<HumanAssetId>('procedural');
  const [xray, setXray] = useState(false);
  const [system, setSystem] = useState<BodySystem>('cardiovascular');
  const [layers, setLayers] = useState<Record<BodySystem, boolean>>({ cardiovascular: true, respiratory: true, nervous: true, musculoskeletal: true, metabolic: true });
  const { model, status, error } = useHumanModel(asset, xray);
  const info = ASSETS.find((a) => a.id === asset)!;
  const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const hidden = useMemo(() => new Set(ORDER.filter((s) => !layers[s] || !xray)), [layers, xray]);
  const highlight = useMemo(() => ({ [system]: { color: SELECT, amount: 0.35 } }), [system]);
  // Same rule as the Windows app BODY fix: Surface dims unchecked regions; X-ray hides their inner layers.
  const dim = useMemo(() => (id: string | null, layer?: string) =>
    layer === 'shell' && id && layers[id as BodySystem] === false ? 0.18 : layer === 'shell' || !id || id === system ? 1 : 0.55, [system, layers]);
  const pick = (s: BodySystem) => setSystem(s);

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
      <div className="always-dark stage relative overflow-hidden rounded-2xl border border-line">
        <Viewport model={model} initialCamera={{ yaw: 0.35, pitch: 0.08, dist: 10.5, target: [0, 0.35, 0], fov: 0.72 }} focus={SYSTEM_FOCUS[system]}
          highlight={highlight} hiddenLayers={hidden} dim={dim} reducedMotion={reduced} height="min(68vh, 560px)"
          onPick={(id) => { if (id && (ORDER as string[]).includes(id)) pick(id as BodySystem); }}
          ariaLabel="3D astronaut digital twin. Drag or use arrow keys to rotate, plus and minus or pinch to zoom. Click a region to select its body system."
          instructions="Drag / arrows rotate · scroll, pinch or ± zoom · click a region" />
        {status === 'loading' && <p role="status" className="absolute left-3 top-3 rounded-lg border border-teal-300/40 bg-canvas/85 px-3 py-1.5 text-xs text-teal-300">Loading {info.file} ({info.sizeMb} MB)…</p>}
        {status === 'error' && <p role="alert" className="absolute left-3 top-3 max-w-xs rounded-lg border border-attention/50 bg-canvas/90 px-3 py-1.5 text-xs text-ink-2">{error} Showing the schematic figure instead.</p>}
      </div>

      <aside className="glass space-y-4 rounded-2xl p-4" aria-label="BODY controls">
        <label className="block text-sm text-ink-2">3D model
          <select className="field mt-1" value={asset} onChange={(e) => setAsset(e.target.value as HumanAssetId)} aria-describedby="model-note">
            {ASSETS.map((a) => <option key={a.id} value={a.id}>{a.label}{a.sizeMb ? ` · ${a.sizeMb} MB download` : ' · instant'}</option>)}
          </select>
        </label>
        <p id="model-note" className="text-[11px] leading-snug text-ink-3">{info.description} {info.credit}.</p>

        <div role="radiogroup" aria-label="Body view" className="grid grid-cols-2 gap-1 rounded-xl border border-line p-1">
          {([['surface', 'Surface', 'body'], ['xray', 'X-ray', 'layers']] as const).map(([v, label, icon]) => (
            <button key={v} type="button" role="radio" aria-checked={(v === 'xray') === xray} onClick={() => setXray(v === 'xray')}
              className={cx('flex items-center justify-center gap-1.5 rounded-lg py-2 text-sm', (v === 'xray') === xray ? 'bg-teal-600 text-ink' : 'text-ink-2 hover:bg-white/5')}>
              <Icon name={icon} size={15} />{label}
            </button>
          ))}
        </div>

        <div>
          <p className="mono-label mb-2">Body systems</p>
          <ul className="space-y-1">
            {ORDER.map((s) => (
              <li key={s} className={cx('flex items-center gap-1 rounded-lg', system === s && 'bg-white/5')}>
                <label className="grid h-9 w-9 shrink-0 cursor-pointer place-items-center" title={`Show ${BODY_SYSTEMS[s].label} layer`}>
                  <input type="checkbox" checked={layers[s]} aria-label={`Show ${BODY_SYSTEMS[s].label} layer`}
                    onChange={(e) => { const checked = e.target.checked; setLayers((prev) => ({ ...prev, [s]: checked })); }} />
                </label>
                <button type="button" onClick={() => pick(s)} aria-pressed={system === s} className="flex min-h-9 flex-1 items-center gap-2 text-left text-sm text-ink">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: BODY_SYSTEMS[s].color }} />{BODY_SYSTEMS[s].label}
                </button>
                <InfoTip text={WHY[s]} label={`About ${BODY_SYSTEMS[s].label}`} />
              </li>
            ))}
          </ul>
        </div>

        <div className="rounded-xl border border-line bg-canvas/60 p-3" aria-live="polite">
          <p className="mono-label">Selected · {BODY_SYSTEMS[system].label}</p>
          <p className="mt-1 text-sm text-ink-2">{BODY_SYSTEMS[system].description}</p>
          <p className="mt-2 text-xs text-ink-3">{WHY[system]}</p>
        </div>
        <p className="text-[11px] text-ink-3">{xray ? 'X-ray: checkboxes show or hide the inner schematic layers.' : 'Surface: unchecked systems dim their approximate body regions.'} Region-to-system mapping is approximate — not a medical visualisation.</p>
      </aside>
    </div>
  );
}
