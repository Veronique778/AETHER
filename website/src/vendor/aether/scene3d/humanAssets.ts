/**
 * BODY digital-twin assets supplied by the 3D team (web/frontend/public/models/*.glb).
 *
 * Each GLB is fitted to the procedural figure's frame (Y up, +Z front, feet at y = FOOT_Y, height HUMAN_H) so the
 * existing metric anchors, system focus points and inner organ layers line up. Body surfaces are split into
 * regions that carry the BODY system ids (head → nervous, chest centre → cardiovascular, chest sides →
 * respiratory, abdomen → metabolic, limbs → musculoskeletal), which makes picking, highlighting and PHANTOM
 * flags work exactly as with the procedural model. The region mapping is an approximate visual aid, not anatomy.
 */
import { GlbError, parseGlb, vertexNormals, type GlbMesh } from './glb';
import { hex, type Material, type Part } from './geometry';
import { buildHuman } from './models';

export type HumanAssetId = 'procedural' | 'anatom' | 'meza' | 'cosmo11' | 'skeleton';
export type HumanAsset = { id: HumanAssetId; label: string; file?: string; sizeMb?: number; description: string; credit: string };

export const HUMAN_ASSETS: HumanAsset[] = [
  { id: 'procedural', label: 'Schematic', description: 'Procedural stylised figure with schematic organ layers (built-in, instant).', credit: 'AETHER frontend' },
  { id: 'anatom', label: 'Anatomical body', file: 'anatom.glb', sizeMb: 0.9, description: 'Anatomical body surface (anatom.glb) with region-to-system mapping; schematic organs inside in X-ray view.', credit: 'AETHER 3D team' },
  { id: 'meza', label: 'Muscle surface', file: 'meza.glb', sizeMb: 0.9, description: 'Muscle-relief body surface (meza.glb), same topology family as the suit model’s muscle layer.', credit: 'AETHER 3D team' },
  { id: 'cosmo11', label: 'Astronaut + muscles', file: 'cosmo11_lite.glb', sizeMb: 17, description: 'Textured EVA suit with a textured muscle layer inside (cosmo11_lite.glb: identical geometry to cosmo11.glb, textures re-encoded as JPEG – 24 → 17.7 MB). X-ray view shows one translucent astronaut without a duplicate inner model.', credit: 'AETHER 3D team' },
  { id: 'skeleton', label: 'Skeleton', file: 'skeleton.glb', sizeMb: 13.3, description: '144 named bones (skeleton.glb), re-exported without Draco compression for the built-in renderer.', credit: 'AETHER 3D team' },
];

/** Procedural figure frame (see models.ts / buildHuman). */
export const FOOT_Y = -2.98;
export const HUMAN_H = 6.52;

type Region = { id: string; part: string };
function regionOf(x: number, y: number): Region {
  const t = (y - FOOT_Y) / HUMAN_H;
  const ax = Math.abs(x);
  if (t > 0.835) return { id: 'nervous', part: 'head' };
  if (t > 0.5 && ax > 0.78) return { id: 'musculoskeletal', part: 'arm' };
  if (t <= 0.5) return { id: 'musculoskeletal', part: 'leg' };
  if (t > 0.69) return ax < 0.34 ? { id: 'cardiovascular', part: 'chest' } : { id: 'respiratory', part: 'ribcage' };
  return { id: 'metabolic', part: 'abdomen' };
}

type Fitted = { meshes: (GlbMesh & { normals: Float32Array })[] };

/** Scale/translate all meshes so the reference mesh spans the procedural figure's height, centred on x/z. */
function fit(meshes: GlbMesh[], reference: (m: GlbMesh) => boolean): Fitted {
  const ref = meshes.filter(reference);
  const src = ref.length ? ref : meshes;
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (const m of src) for (let k = 0; k < m.positions.length; k += 3) for (let a = 0; a < 3; a++) { lo[a] = Math.min(lo[a], m.positions[k + a]); hi[a] = Math.max(hi[a], m.positions[k + a]); }
  const s = HUMAN_H / Math.max(1e-6, hi[1] - lo[1]);
  const cx = (lo[0] + hi[0]) / 2, cz = (lo[2] + hi[2]) / 2;
  return {
    meshes: meshes.map((m) => {
      const P = new Float32Array(m.positions.length);
      for (let k = 0; k < P.length; k += 3) { P[k] = (m.positions[k] - cx) * s; P[k + 1] = (m.positions[k + 1] - lo[1]) * s + FOOT_Y; P[k + 2] = (m.positions[k + 2] - cz) * s; }
      return { ...m, positions: P, normals: m.normals ?? vertexNormals(P, m.indices) };
    }),
  };
}

/** Split one mesh into region sub-meshes (compacted vertex buffers). */
function splitRegions(m: Fitted['meshes'][number]) {
  const groups = new Map<string, { region: Region; tris: number[] }>();
  const { positions: P, indices: I } = m;
  for (let k = 0; k < I.length; k += 3) {
    const a = I[k] * 3, b = I[k + 1] * 3, c = I[k + 2] * 3;
    const r = regionOf((P[a] + P[b] + P[c]) / 3, (P[a + 1] + P[b + 1] + P[c + 1]) / 3);
    const key = `${r.id}:${r.part}`;
    let g = groups.get(key);
    if (!g) { g = { region: r, tris: [] }; groups.set(key, g); }
    g.tris.push(k);
  }
  return [...groups.values()].map(({ region, tris }) => {
    const remap = new Map<number, number>();
    const idx = new Uint32Array(tris.length * 3);
    tris.forEach((k, t) => { for (let j = 0; j < 3; j++) { const v = I[k + j]; let n = remap.get(v); if (n == null) { n = remap.size; remap.set(v, n); } idx[t * 3 + j] = n; } });
    const p = new Float32Array(remap.size * 3), n = new Float32Array(remap.size * 3), uv = m.uvs ? new Float32Array(remap.size * 2) : null;
    remap.forEach((nv, ov) => {
      p.set(P.subarray(ov * 3, ov * 3 + 3), nv * 3); n.set(m.normals.subarray(ov * 3, ov * 3 + 3), nv * 3);
      if (uv && m.uvs) uv.set(m.uvs.subarray(ov * 2, ov * 2 + 2), nv * 2);
    });
    return { region, geo: { p, n, i: idx, uv } };
  });
}

async function decodeTexture(blob: Blob | null): Promise<TexImageSource | null> {
  if (!blob || typeof createImageBitmap !== 'function') return null;
  try { return await createImageBitmap(blob); } catch { return null; }
}

const SKIN = hex('#c9d6e2');
const HOLO: [number, number, number] = [0.45, 0.82, 1.0];
/** Inner schematic organs kept inside a GLB body (limb-bound procedural parts are dropped: the GLB pose differs). */
const INNER_KEEP = new Set(['heart', 'lungs', 'liver', 'stomach', 'intestine', 'brain']);

type Loaded = { asset: HumanAssetId; fitted: Fitted; textures: (TexImageSource | null)[] };
const cache = new Map<HumanAssetId, Promise<Loaded>>();

export function loadHumanAsset(id: HumanAssetId, baseUrl = 'models/'): Promise<Loaded> {
  const asset = HUMAN_ASSETS.find((a) => a.id === id);
  if (!asset?.file) return Promise.reject(new GlbError('format', 'No file for this asset'));
  let p = cache.get(id);
  if (!p) {
    p = (async () => {
      let res: Response;
      try { res = await fetch(baseUrl + asset.file); } catch (e) { throw new GlbError('network', `Cannot load ${asset.file}: ${(e as Error).message}`); }
      if (!res.ok) throw new GlbError('network', `Cannot load ${asset.file} (HTTP ${res.status})`);
      const meshes = parseGlb(await res.arrayBuffer());
      const fitted = fit(meshes, (m) => (id === 'cosmo11' ? /muscle/i.test(m.name) : true));
      const textures = await Promise.all(fitted.meshes.map((m) => decodeTexture(m.texture)));
      return { asset: id, fitted, textures };
    })();
    p.catch(() => cache.delete(id));
    cache.set(id, p);
  }
  return p;
}

/** Build renderer parts for a loaded asset in surface or X-ray view. */
export function buildAssetParts(loaded: Loaded, xray: boolean): Part[] {
  const parts: Part[] = [];
  const shellMat = (tex: TexImageSource | null, base: [number, number, number, number]): Material => (xray
    ? { color: HOLO, alpha: 0.8, xray: true, shininess: 20 }
    : { color: tex ? [1, 1, 1] : base[0] > 0.75 && base[1] > 0.75 ? SKIN : [base[0], base[1], base[2]], texture: tex, shininess: 28 });
  loaded.fitted.meshes.forEach((m, k) => {
    const tex = loaded.textures[k];
    const isMuscle = loaded.asset === 'cosmo11' && /muscle/i.test(m.name);
    if (isMuscle) {
      if (!xray) parts.push({ id: 'musculoskeletal', part: 'muscles', layer: 'musculoskeletal', geo: { p: m.positions, n: m.normals, i: m.indices, uv: m.uvs }, mat: { color: [1, 1, 1], texture: tex, shininess: 40 } });
      return;
    }
    for (const r of splitRegions(m)) parts.push({ id: r.region.id, part: r.region.part, layer: 'shell', geo: r.geo, mat: shellMat(tex, m.baseColor) });
  });
  if (xray && loaded.asset !== 'cosmo11') parts.push(...buildHuman(true).filter((p) => p.layer !== 'shell' && p.part && INNER_KEEP.has(p.part)));
  return parts;
}
