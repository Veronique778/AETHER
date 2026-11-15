/**
 * Minimal, dependency-free glTF 2.0 binary (GLB) reader for the AETHER WebGL renderer.
 * Supports: triangle primitives, POSITION / NORMAL / TEXCOORD_0, uint8/16/32 indices (or none), node TRS / matrix
 * hierarchy, baseColorFactor and baseColorTexture (embedded PNG/JPEG). Not supported (reported, never silently
 * ignored): KHR_draco_mesh_compression / EXT_meshopt_compression, skins, morph targets, sparse accessors.
 */
export type GlbMesh = {
  name: string; material: string;
  positions: Float32Array; normals: Float32Array | null; uvs: Float32Array | null; indices: Uint32Array;
  baseColor: [number, number, number, number]; texture: Blob | null;
};
export class GlbError extends Error {
  constructor(public code: 'format' | 'compressed' | 'unsupported' | 'network', message: string) { super(message); this.name = 'GlbError'; }
}

type Json = {
  asset?: { version?: string }; extensionsRequired?: string[]; scene?: number;
  scenes?: { nodes?: number[] }[];
  nodes?: { name?: string; mesh?: number; children?: number[]; matrix?: number[]; translation?: number[]; rotation?: number[]; scale?: number[] }[];
  meshes?: { name?: string; primitives: { attributes: Record<string, number>; indices?: number; material?: number; mode?: number; extensions?: Record<string, unknown> }[] }[];
  accessors?: { bufferView?: number; byteOffset?: number; componentType: number; count: number; type: string; normalized?: boolean; sparse?: unknown }[];
  bufferViews?: { buffer: number; byteOffset?: number; byteLength: number; byteStride?: number }[];
  materials?: { name?: string; pbrMetallicRoughness?: { baseColorFactor?: number[]; baseColorTexture?: { index: number } } }[];
  textures?: { source?: number }[];
  images?: { bufferView?: number; mimeType?: string; uri?: string }[];
};

const COMPONENTS: Record<string, number> = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4, MAT4: 16 };
type M4 = Float64Array;

function mul(a: M4, b: M4): M4 {
  const o = new Float64Array(16);
  for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
    let s = 0;
    for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
    o[c * 4 + r] = s;
  }
  return o;
}
function local(n: NonNullable<Json['nodes']>[number]): M4 {
  if (n.matrix?.length === 16) return Float64Array.from(n.matrix);
  const [x, y, z, w] = n.rotation ?? [0, 0, 0, 1];
  const [sx, sy, sz] = n.scale ?? [1, 1, 1];
  const [tx, ty, tz] = n.translation ?? [0, 0, 0];
  return Float64Array.from([
    (1 - 2 * (y * y + z * z)) * sx, (2 * (x * y + z * w)) * sx, (2 * (x * z - y * w)) * sx, 0,
    (2 * (x * y - z * w)) * sy, (1 - 2 * (x * x + z * z)) * sy, (2 * (y * z + x * w)) * sy, 0,
    (2 * (x * z + y * w)) * sz, (2 * (y * z - x * w)) * sz, (1 - 2 * (x * x + y * y)) * sz, 0,
    tx, ty, tz, 1,
  ]);
}

export function parseGlb(buf: ArrayBuffer): GlbMesh[] {
  const dv = new DataView(buf);
  if (buf.byteLength < 20 || dv.getUint32(0, true) !== 0x46546c67) throw new GlbError('format', 'Not a GLB file');
  if (dv.getUint32(4, true) !== 2) throw new GlbError('unsupported', 'Only glTF 2.0 GLB is supported');
  let off = 12; let json: Json | null = null; let bin: Uint8Array | null = null;
  while (off + 8 <= buf.byteLength) {
    const len = dv.getUint32(off, true), type = dv.getUint32(off + 4, true);
    const chunk = new Uint8Array(buf, off + 8, len);
    if (type === 0x4e4f534a) json = JSON.parse(new TextDecoder().decode(chunk)) as Json;
    else if (type === 0x004e4942) bin = chunk;
    off += 8 + len;
  }
  if (!json) throw new GlbError('format', 'GLB has no JSON chunk');
  const req = json.extensionsRequired ?? [];
  if (req.some((e) => /draco|meshopt/i.test(e))) throw new GlbError('compressed', `Compressed geometry (${req.join(', ')}) – re-export without mesh compression`);
  if (req.length) throw new GlbError('unsupported', `Required glTF extensions not supported: ${req.join(', ')}`);
  const J = json;
  const B = bin ?? new Uint8Array(0);

  const read = (index: number): { data: ArrayLike<number>; n: number } => {
    const a = J.accessors![index];
    if (a.sparse) throw new GlbError('unsupported', 'Sparse accessors are not supported');
    const n = COMPONENTS[a.type];
    if (a.bufferView == null) return { data: new Float32Array(a.count * n), n };
    const v = J.bufferViews![a.bufferView];
    const base = B.byteOffset + (v.byteOffset ?? 0) + (a.byteOffset ?? 0);
    const Ctor = ({ 5126: Float32Array, 5125: Uint32Array, 5123: Uint16Array, 5122: Int16Array, 5121: Uint8Array, 5120: Int8Array } as const)[a.componentType as 5126];
    if (!Ctor) throw new GlbError('unsupported', `Component type ${a.componentType}`);
    const size = Ctor.BYTES_PER_ELEMENT;
    const stride = v.byteStride && v.byteStride !== n * size ? v.byteStride : 0;
    if (!stride && base % size === 0) return { data: new Ctor(B.buffer, base, a.count * n), n };
    // interleaved or unaligned: copy element-wise
    const out = new Float32Array(a.count * n);
    const view = new DataView(B.buffer);
    const get = (o: number) => (size === 4 ? (a.componentType === 5126 ? view.getFloat32(o, true) : view.getUint32(o, true)) : size === 2 ? view.getUint16(o, true) : view.getUint8(o));
    for (let i = 0; i < a.count; i++) for (let k = 0; k < n; k++) out[i * n + k] = get(base + i * (stride || n * size) + k * size);
    return { data: out, n };
  };
  const imageBlob = (texIndex: number | undefined): Blob | null => {
    if (texIndex == null) return null;
    const img = J.images?.[J.textures?.[texIndex]?.source ?? -1];
    if (!img || img.bufferView == null) return null;
    const v = J.bufferViews![img.bufferView];
    return new Blob([B.slice(v.byteOffset ?? 0, (v.byteOffset ?? 0) + v.byteLength)], { type: img.mimeType ?? 'image/png' });
  };

  const meshes: GlbMesh[] = [];
  const visit = (ni: number, parent: M4) => {
    const node = J.nodes![ni];
    const m = mul(parent, local(node));
    if (node.mesh != null) {
      const mesh = J.meshes![node.mesh];
      // normal matrix = inverse-transpose of the upper 3x3 (uniform scales in practice → normalise after transform)
      for (const prim of mesh.primitives) {
        if ((prim.mode ?? 4) !== 4) continue;
        if (prim.extensions && Object.keys(prim.extensions).some((e) => /draco|meshopt/i.test(e))) throw new GlbError('compressed', 'Compressed primitive');
        const pos = read(prim.attributes.POSITION);
        const count = pos.data.length / 3;
        const P = new Float32Array(count * 3);
        for (let i = 0; i < count; i++) {
          const x = pos.data[i * 3], y = pos.data[i * 3 + 1], z = pos.data[i * 3 + 2];
          P[i * 3] = m[0] * x + m[4] * y + m[8] * z + m[12];
          P[i * 3 + 1] = m[1] * x + m[5] * y + m[9] * z + m[13];
          P[i * 3 + 2] = m[2] * x + m[6] * y + m[10] * z + m[14];
        }
        let N: Float32Array | null = null;
        if (prim.attributes.NORMAL != null) {
          const nr = read(prim.attributes.NORMAL);
          N = new Float32Array(count * 3);
          for (let i = 0; i < count; i++) {
            const x = nr.data[i * 3], y = nr.data[i * 3 + 1], z = nr.data[i * 3 + 2];
            const a = m[0] * x + m[4] * y + m[8] * z, b = m[1] * x + m[5] * y + m[9] * z, c = m[2] * x + m[6] * y + m[10] * z;
            const l = Math.hypot(a, b, c) || 1;
            N[i * 3] = a / l; N[i * 3 + 1] = b / l; N[i * 3 + 2] = c / l;
          }
        }
        const uv = prim.attributes.TEXCOORD_0 != null ? Float32Array.from(read(prim.attributes.TEXCOORD_0).data) : null;
        const I = prim.indices != null ? Uint32Array.from(read(prim.indices).data) : Uint32Array.from({ length: count }, (_, k) => k);
        const mat = prim.material != null ? J.materials?.[prim.material] : undefined;
        const f = mat?.pbrMetallicRoughness?.baseColorFactor ?? [1, 1, 1, 1];
        meshes.push({ name: node.name ?? mesh.name ?? `mesh${node.mesh}`, material: mat?.name ?? '', positions: P, normals: N, uvs: uv, indices: I,
          baseColor: [f[0], f[1], f[2], f[3] ?? 1], texture: imageBlob(mat?.pbrMetallicRoughness?.baseColorTexture?.index) });
      }
    }
    node.children?.forEach((c) => visit(c, m));
  };
  const identity = Float64Array.from([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
  const roots = J.scenes?.[J.scene ?? 0]?.nodes ?? (J.nodes ?? []).map((_, i) => i);
  roots.forEach((r) => visit(r, identity));
  if (!meshes.length) throw new GlbError('format', 'GLB contains no triangle meshes');
  return meshes;
}

/** Smooth vertex normals for meshes exported without NORMAL. */
export function vertexNormals(P: Float32Array, I: Uint32Array): Float32Array {
  const N = new Float32Array(P.length);
  for (let k = 0; k < I.length; k += 3) {
    const a = I[k] * 3, b = I[k + 1] * 3, c = I[k + 2] * 3;
    const ux = P[b] - P[a], uy = P[b + 1] - P[a + 1], uz = P[b + 2] - P[a + 2];
    const vx = P[c] - P[a], vy = P[c + 1] - P[a + 1], vz = P[c + 2] - P[a + 2];
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    for (const v of [a, b, c]) { N[v] += nx; N[v + 1] += ny; N[v + 2] += nz; }
  }
  for (let v = 0; v < N.length; v += 3) { const l = Math.hypot(N[v], N[v + 1], N[v + 2]) || 1; N[v] /= l; N[v + 1] /= l; N[v + 2] /= l; }
  return N;
}
