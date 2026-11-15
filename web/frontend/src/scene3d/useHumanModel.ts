import { useEffect, useMemo, useState } from 'react';
import { buildAssetParts, HUMAN_ASSETS, loadHumanAsset, type HumanAssetId } from './humanAssets';
import { buildHuman } from './models';

const KEY = 'aether.bodyModel';

/** Digital-twin model chosen in BODY (shared with the Mission Control hologram). Default: the astronaut suit GLB. */
export function readBodyModel(): HumanAssetId {
  try {
    const v = localStorage.getItem(KEY) as HumanAssetId | null;
    if (v && HUMAN_ASSETS.some((a) => a.id === v)) return v;
  } catch { /* storage unavailable */ }
  // 0.9: a page opened from disk (file://) cannot fetch GLB files – start with the built-in figure there.
  return typeof location !== 'undefined' && location.protocol === 'file:' ? 'procedural' : 'cosmo11';
}
export function writeBodyModel(id: HumanAssetId) {
  try { localStorage.setItem(KEY, id); } catch { /* storage unavailable */ }
}

/** Selected model as renderer parts: a team GLB asset, or the procedural figure while loading / on error. */
export function useHumanModel(asset: HumanAssetId, xray: boolean) {
  const [loaded, setLoaded] = useState<Awaited<ReturnType<typeof loadHumanAsset>> | null>(null);
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (asset === 'procedural') { setStatus('idle'); setError(null); return; }
    let alive = true;
    setStatus('loading');
    loadHumanAsset(asset).then(
      (l) => { if (alive) { setLoaded(l); setStatus('ready'); setError(null); } },
      (e: Error) => { if (alive) { setStatus('error'); setError(e.message); } },
    );
    return () => { alive = false; };
  }, [asset]);
  const model = useMemo(() => (asset !== 'procedural' && loaded?.asset === asset ? buildAssetParts(loaded, xray) : buildHuman(xray)), [asset, loaded, xray]);
  return { model, status, error, isAsset: asset !== 'procedural' && loaded?.asset === asset };
}
