/**
 * Smooth, indexed geometry builders for the WebGL renderer (and, via `toTris`, the Canvas fallback).
 * Units are metres for the ship and roughly 1 = 50 cm for the human figure. Y is up.
 */
import type { Tri, Vec3 } from './engine';

export type Geo = { p: number[]; n: number[]; i: number[] };
/** Read-only geometry accepted by the renderers: procedural Geo or typed arrays from a GLB asset (optional UVs). */
export type GeoLike = { p: ArrayLike<number>; n: ArrayLike<number>; i: ArrayLike<number>; uv?: ArrayLike<number> | null };
export type Material = {
  color: [number, number, number];          // 0..1 linear-ish RGB
  emissive?: [number, number, number];
  alpha?: number;
  shininess?: number;
  /** Fresnel "x-ray" shell: transparent face-on, visible at silhouettes. */
  xray?: boolean;
  /** Base-colour texture (GLB assets); sampled with geo.uv and multiplied by `color`. */
  texture?: TexImageSource | null;
};
/** A renderable, optionally pickable piece of a model. `id` is the pick target (zone / body system). */
export type Part = { id: string | null; part?: string; layer?: string; geo: GeoLike; mat: Material };

export const hex = (h: string): [number, number, number] => [parseInt(h.slice(1, 3), 16) / 255, parseInt(h.slice(3, 5), 16) / 255, parseInt(h.slice(5, 7), 16) / 255];

const empty = (): Geo => ({ p: [], n: [], i: [] });

/** Area-weighted smooth normals over shared vertices. */
export function computeNormals(g: Geo): Geo {
  const n = new Array<number>(g.p.length).fill(0);
  for (let k = 0; k < g.i.length; k += 3) {
    const [a, b, c] = [g.i[k] * 3, g.i[k + 1] * 3, g.i[k + 2] * 3];
    const ux = g.p[b] - g.p[a], uy = g.p[b + 1] - g.p[a + 1], uz = g.p[b + 2] - g.p[a + 2];
    const vx = g.p[c] - g.p[a], vy = g.p[c + 1] - g.p[a + 1], vz = g.p[c + 2] - g.p[a + 2];
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    for (const v of [a, b, c]) { n[v] += nx; n[v + 1] += ny; n[v + 2] += nz; }
  }
  for (let v = 0; v < n.length; v += 3) {
    const l = Math.hypot(n[v], n[v + 1], n[v + 2]) || 1;
    n[v] /= l; n[v + 1] /= l; n[v + 2] /= l;
  }
  g.n = n;
  return g;
}

/** Surface of revolution around the local Y axis. profile = [[radius, y], …]; radius 0 closes a pole. */
export function lathe(profile: [number, number][], seg = 32): Geo {
  const g = empty();
  for (const [r, y] of profile) for (let s = 0; s < seg; s++) {
    const t = (s / seg) * Math.PI * 2;
    g.p.push(Math.cos(t) * r, y, Math.sin(t) * r);
  }
  for (let j = 0; j < profile.length - 1; j++) for (let s = 0; s < seg; s++) {
    const a = j * seg + s, b = j * seg + ((s + 1) % seg), c = (j + 1) * seg + s, d = (j + 1) * seg + ((s + 1) % seg);
    g.i.push(a, c, b, b, c, d);
  }
  return computeNormals(g);
}

export function ellipsoid(r: Vec3, seg = 28, rings = 18): Geo {
  const prof: [number, number][] = [];
  for (let j = 0; j <= rings; j++) { const ph = (j / rings) * Math.PI; prof.push([Math.sin(ph), -Math.cos(ph)]); }
  const g = lathe(prof, seg);
  for (let k = 0; k < g.p.length; k += 3) { g.p[k] *= r[0]; g.p[k + 1] *= r[1]; g.p[k + 2] *= r[2]; }
  return computeNormals(g);
}

export function torus(R: number, r: number, segR = 64, segr = 16): Geo {
  const g = empty();
  for (let a = 0; a < segR; a++) for (let b = 0; b < segr; b++) {
    const u = (a / segR) * Math.PI * 2, v = (b / segr) * Math.PI * 2;
    const rr = R + r * Math.cos(v);
    g.p.push(Math.cos(u) * rr, r * Math.sin(v), Math.sin(u) * rr);
  }
  for (let a = 0; a < segR; a++) for (let b = 0; b < segr; b++) {
    const i0 = a * segr + b, i1 = ((a + 1) % segR) * segr + b, i2 = a * segr + ((b + 1) % segr), i3 = ((a + 1) % segR) * segr + ((b + 1) % segr);
    g.i.push(i0, i1, i2, i2, i1, i3);
  }
  return computeNormals(g);
}

export function box(s: Vec3): Geo {
  const g = empty();
  const [x, y, z] = [s[0] / 2, s[1] / 2, s[2] / 2];
  const faces: [Vec3, Vec3, Vec3, Vec3][] = [
    [[-x, -y, z], [x, -y, z], [x, y, z], [-x, y, z]], [[x, -y, -z], [-x, -y, -z], [-x, y, -z], [x, y, -z]],
    [[x, -y, z], [x, -y, -z], [x, y, -z], [x, y, z]], [[-x, -y, -z], [-x, -y, z], [-x, y, z], [-x, y, -z]],
    [[-x, y, z], [x, y, z], [x, y, -z], [-x, y, -z]], [[-x, -y, -z], [x, -y, -z], [x, -y, z], [-x, -y, z]],
  ];
  for (const f of faces) {
    const o = g.p.length / 3;
    f.forEach((v) => g.p.push(...v));
    g.i.push(o, o + 1, o + 2, o, o + 2, o + 3);
  }
  return computeNormals(g);
}

/** Tube along a polyline with parallel-transport frames. radius may vary per point. */
export function tube(path: Vec3[], radius: number | number[], seg = 12): Geo {
  const g = empty();
  const rad = (k: number) => (Array.isArray(radius) ? radius[k] : radius);
  let prevN: Vec3 | null = null;
  for (let k = 0; k < path.length; k++) {
    const a = path[Math.max(0, k - 1)], b = path[Math.min(path.length - 1, k + 1)];
    const t = norm([b[0] - a[0], b[1] - a[1], b[2] - a[2]]);
    let nrm: Vec3;
    if (!prevN) { const up: Vec3 = Math.abs(t[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0]; nrm = norm(cross(cross(t, up), t)); }
    else { const d = dot(prevN, t); nrm = norm([prevN[0] - t[0] * d, prevN[1] - t[1] * d, prevN[2] - t[2] * d]); }
    prevN = nrm;
    const bin = cross(t, nrm);
    for (let s = 0; s < seg; s++) {
      const ang = (s / seg) * Math.PI * 2, c = Math.cos(ang) * rad(k), si = Math.sin(ang) * rad(k);
      g.p.push(path[k][0] + nrm[0] * c + bin[0] * si, path[k][1] + nrm[1] * c + bin[1] * si, path[k][2] + nrm[2] * c + bin[2] * si);
    }
  }
  for (let k = 0; k < path.length - 1; k++) for (let s = 0; s < seg; s++) {
    const a = k * seg + s, b = k * seg + ((s + 1) % seg), c = (k + 1) * seg + s, d = (k + 1) * seg + ((s + 1) % seg);
    g.i.push(a, c, b, b, c, d);
  }
  return computeNormals(g);
}

/** Capsule between two points (limb segment). */
export function capsule(a: Vec3, b: Vec3, r1: number, r2 = r1, seg = 20): Geo {
  const len = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
  const prof: [number, number][] = [];
  const caps = 6;
  for (let j = 0; j <= caps; j++) { const ph = (j / caps) * (Math.PI / 2); prof.push([Math.sin(ph) * r1, -Math.cos(ph) * r1]); }
  for (let j = 0; j <= caps; j++) { const ph = (j / caps) * (Math.PI / 2); prof.push([Math.cos(ph) * r2, len + Math.sin(ph) * r2]); }
  return orient(lathe(prof, seg), a, b);
}

/** Rotate a Y-aligned geometry so local +Y points from a to b, then translate to a. */
export function orient(g: Geo, a: Vec3, b: Vec3): Geo {
  const dir = norm([b[0] - a[0], b[1] - a[1], b[2] - a[2]]);
  const up: Vec3 = [0, 1, 0];
  const axis = cross(up, dir);
  const s = Math.hypot(...axis), c = dot(up, dir);
  const k = s < 1e-6 ? [1, 0, 0] as Vec3 : (axis.map((v) => v / s) as Vec3);
  const ang = s < 1e-6 ? (c > 0 ? 0 : Math.PI) : Math.atan2(s, c);
  return transform(g, (v) => add(rotAxis(v, k, ang), a));
}

export function translate(g: Geo, t: Vec3): Geo { return transform(g, (v) => add(v, t)); }
export function rotateY(g: Geo, ang: number): Geo { return transform(g, (v) => [v[0] * Math.cos(ang) + v[2] * Math.sin(ang), v[1], -v[0] * Math.sin(ang) + v[2] * Math.cos(ang)]); }
export function rotateZ(g: Geo, ang: number): Geo { return transform(g, (v) => [v[0] * Math.cos(ang) - v[1] * Math.sin(ang), v[0] * Math.sin(ang) + v[1] * Math.cos(ang), v[2]]); }
export function rotateX(g: Geo, ang: number): Geo { return transform(g, (v) => [v[0], v[1] * Math.cos(ang) - v[2] * Math.sin(ang), v[1] * Math.sin(ang) + v[2] * Math.cos(ang)]); }
/** Lay a Y-axis geometry along +X (ship modules). */
export const alongX = (g: Geo) => rotateZ(g, -Math.PI / 2);

export function transform(g: Geo, fn: (v: Vec3) => Vec3): Geo {
  const out: Geo = { p: [], n: [], i: [...g.i] };
  for (let k = 0; k < g.p.length; k += 3) out.p.push(...fn([g.p[k], g.p[k + 1], g.p[k + 2]]));
  return computeNormals(out);
}

export function merge(...gs: Geo[]): Geo {
  const out = empty();
  for (const g of gs) {
    const o = out.p.length / 3;
    out.p.push(...g.p); out.n.push(...g.n);
    for (const i of g.i) out.i.push(i + o);
  }
  return out;
}

/** Flat triangles for the Canvas-2D fallback renderer. */
export function toTris(g: GeoLike): Tri[] {
  const out: Tri[] = [];
  for (let k = 0; k < g.i.length; k += 3) {
    const v = (i: number): Vec3 => [g.p[i * 3], g.p[i * 3 + 1], g.p[i * 3 + 2]];
    const a = v(g.i[k]), b = v(g.i[k + 1]), c = v(g.i[k + 2]);
    out.push({ a, b, c, n: norm(cross([b[0] - a[0], b[1] - a[1], b[2] - a[2]], [c[0] - a[0], c[1] - a[1], c[2] - a[2]])) });
  }
  return out;
}

export function triangleCount(parts: Part[]) { return parts.reduce((s, p) => s + p.geo.i.length / 3, 0); }

function add(a: Vec3, b: Vec3): Vec3 { return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]; }
function dot(a: Vec3, b: Vec3) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
function cross(a: Vec3, b: Vec3): Vec3 { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
function norm(a: Vec3): Vec3 { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; }
function rotAxis(v: Vec3, k: Vec3, ang: number): Vec3 {
  const c = Math.cos(ang), s = Math.sin(ang), d = dot(k, v), kv = cross(k, v);
  return [v[0] * c + kv[0] * s + k[0] * d * (1 - c), v[1] * c + kv[1] * s + k[1] * d * (1 - c), v[2] * c + kv[2] * s + k[2] * d * (1 - c)];
}
