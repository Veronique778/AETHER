/**
 * Tiny dependency-free 3D renderer (Canvas 2D, flat-shaded, painter's algorithm).
 * Purpose: an interactive, rotatable placeholder until GLB assets exist. It is
 * intentionally simple – ~2–4k triangles, rendered only when something changes.
 * The React component in Viewport.tsx exposes a renderer-agnostic props contract
 * so this can be replaced by a React Three Fiber implementation (docs/3D_INTEGRATION.md).
 */
export type Vec3 = [number, number, number];
export type RGB = [number, number, number];
export type Tri = { a: Vec3; b: Vec3; c: Vec3; n: Vec3 };
export type Mesh = { id: string | null; part?: string; tris: Tri[]; color: RGB; doubleSided?: boolean; opacity?: number };
export type Camera = { yaw: number; pitch: number; dist: number; target: Vec3; fov: number };

export const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
export const scale = (a: Vec3, s: number): Vec3 => [a[0] * s, a[1] * s, a[2] * s];
export const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
export const norm = (a: Vec3): Vec3 => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };

export function hexToRgb(hex: string): RGB {
  const h = hex.replace('#', '');
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

/** Build a triangle with its normal oriented away from `inside`. */
function tri(a: Vec3, b: Vec3, c: Vec3, inside: Vec3): Tri {
  let n = norm(cross(sub(b, a), sub(c, a)));
  const centroid = scale(add(add(a, b), c), 1 / 3);
  if (dot(n, sub(centroid, inside)) < 0) n = scale(n, -1);
  return { a, b, c, n };
}

/** Frustum / cylinder along the X axis, optionally offset in y/z. */
export function cylinderX(x0: number, x1: number, r0: number, r1: number, seg = 24, caps = true, oy = 0, oz = 0): Tri[] {
  const out: Tri[] = [];
  const ring = (x: number, r: number, i: number): Vec3 => { const t = (i / seg) * Math.PI * 2; return [x, oy + Math.cos(t) * r, oz + Math.sin(t) * r]; };
  for (let i = 0; i < seg; i++) {
    const a = ring(x0, r0, i), b = ring(x0, r0, i + 1), c = ring(x1, r1, i + 1), d = ring(x1, r1, i);
    const inside: Vec3 = [(x0 + x1) / 2, oy, oz];
    out.push(tri(a, b, c, inside), tri(a, c, d, inside));
    if (caps && r0 > 0.001) out.push(tri([x0, oy, oz], b, a, [x0 + 1, oy, oz]));
    if (caps && r1 > 0.001) out.push(tri([x1, oy, oz], d, c, [x1 - 1, oy, oz]));
  }
  return out;
}

export function ellipsoid(c: Vec3, r: Vec3, seg = 18, rings = 10): Tri[] {
  const out: Tri[] = [];
  const p = (i: number, j: number): Vec3 => {
    const th = (i / seg) * Math.PI * 2;
    const ph = (j / rings) * Math.PI;
    return [c[0] + r[0] * Math.sin(ph) * Math.cos(th), c[1] + r[1] * Math.cos(ph), c[2] + r[2] * Math.sin(ph) * Math.sin(th)];
  };
  for (let j = 0; j < rings; j++) {
    for (let i = 0; i < seg; i++) {
      const a = p(i, j), b = p(i + 1, j), cc = p(i + 1, j + 1), d = p(i, j + 1);
      if (j > 0) out.push(tri(a, b, cc, c));
      if (j < rings - 1) out.push(tri(a, cc, d, c));
    }
  }
  return out;
}

/** Torus around the X axis (habitat ring). */
export function torusX(cx: number, R: number, r: number, segR = 36, segr = 10): Tri[] {
  const out: Tri[] = [];
  const p = (i: number, j: number): Vec3 => {
    const u = (i / segR) * Math.PI * 2;
    const v = (j / segr) * Math.PI * 2;
    const rr = R + r * Math.cos(v);
    return [cx + r * Math.sin(v), Math.cos(u) * rr, Math.sin(u) * rr];
  };
  for (let i = 0; i < segR; i++) {
    for (let j = 0; j < segr; j++) {
      const u = ((i + 0.5) / segR) * Math.PI * 2;
      const inside: Vec3 = [cx, Math.cos(u) * R, Math.sin(u) * R];
      const a = p(i, j), b = p(i + 1, j), c = p(i + 1, j + 1), d = p(i, j + 1);
      out.push(tri(a, b, c, inside), tri(a, c, d, inside));
    }
  }
  return out;
}

export function box(c: Vec3, s: Vec3): Tri[] {
  const [hx, hy, hz] = [s[0] / 2, s[1] / 2, s[2] / 2];
  const v = (x: number, y: number, z: number): Vec3 => [c[0] + x * hx, c[1] + y * hy, c[2] + z * hz];
  const faces: Vec3[][] = [
    [v(-1, -1, 1), v(1, -1, 1), v(1, 1, 1), v(-1, 1, 1)], [v(-1, -1, -1), v(-1, 1, -1), v(1, 1, -1), v(1, -1, -1)],
    [v(1, -1, -1), v(1, 1, -1), v(1, 1, 1), v(1, -1, 1)], [v(-1, -1, -1), v(-1, -1, 1), v(-1, 1, 1), v(-1, 1, -1)],
    [v(-1, 1, -1), v(-1, 1, 1), v(1, 1, 1), v(1, 1, -1)], [v(-1, -1, -1), v(1, -1, -1), v(1, -1, 1), v(-1, -1, 1)],
  ];
  return faces.flatMap(([a, b, cc, d]) => [tri(a, b, cc, c), tri(a, cc, d, c)]);
}

/** Apply a vertex transform (e.g. rotate a primitive) and recompute normals around `inside`. */
export function transform(tris: Tri[], fn: (v: Vec3) => Vec3, inside: Vec3): Tri[] {
  return tris.map((t) => tri(fn(t.a), fn(t.b), fn(t.c), inside));
}

/** Rotate around Z by angle (radians) about point p – used to make vertical limbs from X-axis cylinders. */
export const rotZ = (ang: number, p: Vec3 = [0, 0, 0]) => (v: Vec3): Vec3 => {
  const x = v[0] - p[0], y = v[1] - p[1];
  return [p[0] + x * Math.cos(ang) - y * Math.sin(ang), p[1] + x * Math.sin(ang) + y * Math.cos(ang), v[2]];
};

/* ------------------------------------------------------------------ projection */
export function toCamera(p: Vec3, cam: Camera): Vec3 {
  const q = sub(p, cam.target);
  const cy = Math.cos(cam.yaw), sy = Math.sin(cam.yaw);
  const x1 = q[0] * cy - q[2] * sy;
  const z1 = q[0] * sy + q[2] * cy;
  const cp = Math.cos(cam.pitch), sp = Math.sin(cam.pitch);
  const y2 = q[1] * cp - z1 * sp;
  const z2 = q[1] * sp + z1 * cp;
  return [x1, y2, z2];
}

export type Projected = { x: number; y: number; depth: number; visible: boolean };
export function project(p: Vec3, cam: Camera, w: number, h: number): Projected {
  const c = toCamera(p, cam);
  const depth = cam.dist - c[2];
  const f = h / 2 / Math.tan(cam.fov / 2);
  return { x: w / 2 + (f * c[0]) / depth, y: h / 2 - (f * c[1]) / depth, depth, visible: depth > 0.2 };
}

export type Highlight = Record<string, { color: RGB; amount: number }>;
export type ScreenTri = { id: string | null; part?: string; pts: [number, number][]; depth: number };

const LIGHT = norm([-0.45, 0.65, 0.6]);

export function render(ctx: CanvasRenderingContext2D, meshes: Mesh[], cam: Camera, w: number, h: number, highlight: Highlight, dim: (id: string | null) => number): ScreenTri[] {
  const f = h / 2 / Math.tan(cam.fov / 2);
  const list: { pts: [number, number][]; depth: number; fill: string; id: string | null; part?: string }[] = [];
  const camPos: Vec3 = [0, 0, cam.dist];
  for (const m of meshes) {
    const hl = m.id ? highlight[m.id] ?? (m.part ? highlight[m.part] : undefined) : undefined;
    const dimming = dim(m.id);
    for (const t of m.tris) {
      const a = toCamera(t.a, cam), b = toCamera(t.b, cam), c = toCamera(t.c, cam);
      const n = toCamera(add(t.n, cam.target), cam);
      const view = sub(camPos, scale(add(add(a, b), c), 1 / 3));
      if (!m.doubleSided && dot(n, view) <= 0) continue;
      const da = cam.dist - a[2], db = cam.dist - b[2], dc = cam.dist - c[2];
      if (da < 0.2 || db < 0.2 || dc < 0.2) continue;
      const nn = dot(n, view) < 0 ? scale(n, -1) : n;
      const lum = 0.32 + 0.68 * Math.max(0, dot(nn, LIGHT));
      let col: RGB = [m.color[0] * lum, m.color[1] * lum, m.color[2] * lum];
      if (hl) col = [col[0] + (hl.color[0] - col[0]) * hl.amount, col[1] + (hl.color[1] - col[1]) * hl.amount, col[2] + (hl.color[2] - col[2]) * hl.amount];
      if (dimming < 1) col = [col[0] * dimming + 16 * (1 - dimming), col[1] * dimming + 24 * (1 - dimming), col[2] * dimming + 39 * (1 - dimming)];
      const pts: [number, number][] = [[w / 2 + (f * a[0]) / da, h / 2 - (f * a[1]) / da], [w / 2 + (f * b[0]) / db, h / 2 - (f * b[1]) / db], [w / 2 + (f * c[0]) / dc, h / 2 - (f * c[1]) / dc]];
      const alpha = m.opacity ?? 1;
      list.push({ pts, depth: (da + db + dc) / 3, fill: `rgba(${col[0] | 0},${col[1] | 0},${col[2] | 0},${alpha})`, id: m.id, part: m.part });
    }
  }
  list.sort((p, q) => q.depth - p.depth);
  for (const t of list) {
    ctx.beginPath();
    ctx.moveTo(t.pts[0][0], t.pts[0][1]);
    ctx.lineTo(t.pts[1][0], t.pts[1][1]);
    ctx.lineTo(t.pts[2][0], t.pts[2][1]);
    ctx.closePath();
    ctx.fillStyle = t.fill;
    ctx.strokeStyle = t.fill;
    ctx.lineWidth = 0.6;
    ctx.fill();
    ctx.stroke();
  }
  return list.map((t) => ({ id: t.id, part: t.part, pts: t.pts, depth: t.depth }));
}

function inTri(px: number, py: number, [a, b, c]: [number, number][]) {
  const s = (p1: [number, number], p2: [number, number]) => (px - p2[0]) * (p1[1] - p2[1]) - (p1[0] - p2[0]) * (py - p2[1]);
  const d1 = s(a, b), d2 = s(b, c), d3 = s(c, a);
  const neg = d1 < 0 || d2 < 0 || d3 < 0;
  const pos = d1 > 0 || d2 > 0 || d3 > 0;
  return !(neg && pos);
}

/** Front-most triangle under the pointer (drawn last = nearest). */
export function pick(tris: ScreenTri[], x: number, y: number): ScreenTri | null {
  for (let i = tris.length - 1; i >= 0; i--) if (inTri(x, y, tris[i].pts)) return tris[i];
  return null;
}
