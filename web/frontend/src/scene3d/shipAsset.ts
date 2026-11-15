import type { ZoneId } from '../api/types';
import type { Material, Part } from './geometry';
import { parseGlb, vertexNormals, type GlbMesh } from './glb';
import { SHIP_ZONES } from './models';

const SHIP_FILE = 'models/carablik.glb';
const SHIP_LENGTH = 20;
const ZONE_IDS: ZoneId[] = ['systems', 'exercise', 'habitat', 'medical', 'command'];
let cached: Promise<Part[]> | null = null;

function zoneAt(x: number): ZoneId {
  return ZONE_IDS.reduce((best, id) => (
    Math.abs(SHIP_ZONES[id].centre[0] - x) < Math.abs(SHIP_ZONES[best].centre[0] - x) ? id : best
  ), ZONE_IDS[0]);
}

function splitByZone(mesh: GlbMesh, positions: Float32Array, normals: Float32Array, material: Material): Part[] {
  const triangles = new Map<ZoneId, number[]>();
  for (let k = 0; k < mesh.indices.length; k += 3) {
    const a = mesh.indices[k], b = mesh.indices[k + 1], c = mesh.indices[k + 2];
    const zone = zoneAt((positions[a * 3] + positions[b * 3] + positions[c * 3]) / 3);
    let group = triangles.get(zone);
    if (!group) { group = []; triangles.set(zone, group); }
    group.push(a, b, c);
  }
  return [...triangles].map(([id, vertices]) => {
    const remap = new Map<number, number>();
    const p = new Float32Array(new Set(vertices).size * 3);
    const n = new Float32Array(p.length);
    const uv = mesh.uvs ? new Float32Array((p.length / 3) * 2) : null;
    const indices = new Uint32Array(vertices.length);
    vertices.forEach((old, i) => {
      let next = remap.get(old);
      if (next === undefined) {
        next = remap.size;
        remap.set(old, next);
        p.set(positions.subarray(old * 3, old * 3 + 3), next * 3);
        n.set(normals.subarray(old * 3, old * 3 + 3), next * 3);
        if (uv && mesh.uvs) uv.set(mesh.uvs.subarray(old * 2, old * 2 + 2), next * 2);
      }
      indices[i] = next;
    });
    return { id, part: mesh.name, geo: { p, n, i: indices, uv }, mat: material };
  });
}

async function buildParts(meshes: GlbMesh[]): Promise<Part[]> {
  if (meshes.length === 0) throw new Error(`${SHIP_FILE} contains no triangle meshes`);
  const bounds = [Infinity, Infinity, Infinity, -Infinity, -Infinity, -Infinity];
  for (const mesh of meshes) for (let k = 0; k < mesh.positions.length; k += 3) {
    for (let axis = 0; axis < 3; axis++) {
      bounds[axis] = Math.min(bounds[axis], mesh.positions[k + axis]);
      bounds[axis + 3] = Math.max(bounds[axis + 3], mesh.positions[k + axis]);
    }
  }
  const rotateZToX = bounds[5] - bounds[2] >= bounds[3] - bounds[0];
  const length = rotateZToX ? bounds[5] - bounds[2] : bounds[3] - bounds[0];
  const scale = SHIP_LENGTH / Math.max(length, 1e-6);
  const center: [number, number, number] = [
    (bounds[0] + bounds[3]) / 2,
    (bounds[1] + bounds[4]) / 2,
    (bounds[2] + bounds[5]) / 2,
  ];

  const grouped = await Promise.all(meshes.map(async (mesh) => {
    const positions = new Float32Array(mesh.positions.length);
    const normals = new Float32Array(mesh.positions.length);
    for (let k = 0; k < positions.length; k += 3) {
      positions[k] = (rotateZToX ? mesh.positions[k + 2] - center[2] : mesh.positions[k] - center[0]) * scale;
      positions[k + 1] = (mesh.positions[k + 1] - center[1]) * scale;
      positions[k + 2] = (rotateZToX ? center[0] - mesh.positions[k] : mesh.positions[k + 2] - center[2]) * scale;
      if (mesh.normals) {
        const x = rotateZToX ? mesh.normals[k + 2] : mesh.normals[k];
        const y = mesh.normals[k + 1];
        const z = rotateZToX ? -mesh.normals[k] : mesh.normals[k + 2];
        const magnitude = Math.hypot(x, y, z) || 1;
        normals[k] = x / magnitude; normals[k + 1] = y / magnitude; normals[k + 2] = z / magnitude;
      }
    }
    const fittedNormals = mesh.normals ? normals : vertexNormals(positions, mesh.indices);
    let texture: TexImageSource | null = null;
    if (mesh.texture) {
      if (typeof createImageBitmap !== 'function') throw new Error('This WebView cannot decode embedded GLB textures');
      texture = await createImageBitmap(mesh.texture);
    }
    const material: Material = {
      color: [mesh.baseColor[0], mesh.baseColor[1], mesh.baseColor[2]],
      alpha: mesh.baseColor[3],
      texture,
      shininess: 48,
    };
    return splitByZone(mesh, positions, fittedNormals, material);
  }));
  return grouped.flat();
}

async function load(): Promise<Part[]> {
  const response = await fetch(SHIP_FILE);
  if (!response.ok) throw new Error(`Cannot load ${SHIP_FILE} (HTTP ${response.status})`);
  return buildParts(parseGlb(await response.arrayBuffer()));
}

export function loadShipAsset(): Promise<Part[]> {
  if (!cached) {
    const request = load();
    cached = request;
    void request.catch(() => { if (cached === request) cached = null; });
  }
  return cached;
}
