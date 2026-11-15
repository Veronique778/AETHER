/**
 * Minimal WebGL2 renderer for AETHER placeholders.
 * - Blinn-Phong key + fill light, hemispheric ambient, Fresnel rim, depth fog
 * - Opaque pass, then back-to-front transparent pass (x-ray shells, glass)
 * - Highlight tint and dimming per part (selection, status, PHANTOM flags)
 * The camera model is identical to engine.ts so HTML anchors align in both renderers.
 */
import type { Camera } from './engine';
import type { Part } from './geometry';

export type GLHighlight = Record<string, { color: [number, number, number]; amount: number }>; // color 0..255
export type GLRenderOptions = { highlight: GLHighlight; dim: (id: string | null, layer?: string) => number; hiddenLayers?: Set<string> };

const VS = `#version 300 es
in vec3 aPos; in vec3 aNrm; in vec2 aUV;
uniform mat4 uView; uniform mat4 uProj;
out vec3 vN; out vec3 vP; out vec2 vUV;
void main() { vec4 p = uView * vec4(aPos, 1.0); vP = p.xyz; vN = mat3(uView) * aNrm; vUV = aUV; gl_Position = uProj * p; }`;

const FS = `#version 300 es
precision highp float;
in vec3 vN; in vec3 vP; in vec2 vUV; out vec4 o;
uniform sampler2D uTex; uniform float uHasTex;
uniform vec3 uColor; uniform vec3 uEmissive; uniform vec3 uHi; uniform float uHiAmt;
uniform float uAlpha; uniform float uXray; uniform float uShine; uniform float uFogStart; uniform float uDim;
void main() {
  vec3 n = normalize(vN); if (!gl_FrontFacing) n = -n;
  vec3 v = normalize(-vP);
  vec3 L1 = normalize(vec3(-0.45, 0.65, 0.6));
  vec3 L2 = normalize(vec3(0.7, -0.15, 0.45));
  float d1 = max(dot(n, L1), 0.0);
  float d2 = max(dot(n, L2), 0.0) * 0.35;
  float sp = pow(max(dot(n, normalize(L1 + v)), 0.0), uShine) * 0.45;
  vec3 amb = mix(vec3(0.05, 0.06, 0.09), vec3(0.15, 0.19, 0.27), 0.5 + 0.5 * n.y);
  float rim = pow(1.0 - max(dot(n, v), 0.0), 2.4);
  vec3 albedo = uHasTex > 0.5 ? uColor * pow(texture(uTex, vUV).rgb, vec3(1.15)) : uColor;
  vec3 base = mix(albedo, uHi, uHiAmt);
  vec3 col = base * (amb + d1 * vec3(1.0, 0.97, 0.92) + d2 * vec3(0.55, 0.72, 1.0)) + sp + uEmissive
           + rim * mix(vec3(0.10, 0.28, 0.50), uHi, uHiAmt) * (0.45 + uHiAmt);
  float a = uAlpha;
  if (uXray > 0.5) { a = uAlpha * (0.2 + 0.8 * rim); col = mix(col, vec3(0.42, 0.80, 1.0), 0.45); }
  float fog = clamp((-vP.z - uFogStart) / (uFogStart * 1.6), 0.0, 1.0) * 0.55;
  col = mix(col, vec3(0.015, 0.03, 0.06), fog) * uDim;
  o = vec4(pow(max(col, 0.0), vec3(0.85)), a);
}`;

type Buf = { vao: WebGLVertexArrayObject; count: number; part: Part; centroid: [number, number, number]; tex: WebGLTexture | null };

function viewMatrix(c: Camera): Float32Array {
  const cy = Math.cos(c.yaw), sy = Math.sin(c.yaw), cp = Math.cos(c.pitch), sp = Math.sin(c.pitch);
  // camera-space = Rpitch * Ryaw * (p - target), then translate z by -dist (matches engine.toCamera).
  const r00 = cy, r01 = 0, r02 = -sy;
  const r10 = -sp * sy, r11 = cp, r12 = -sp * cy;
  const r20 = cp * sy, r21 = sp, r22 = cp * cy;
  const [tx, ty, tz] = c.target;
  const t0 = -(r00 * tx + r01 * ty + r02 * tz), t1 = -(r10 * tx + r11 * ty + r12 * tz), t2 = -(r20 * tx + r21 * ty + r22 * tz) - c.dist;
  return new Float32Array([r00, r10, r20, 0, r01, r11, r21, 0, r02, r12, r22, 0, t0, t1, t2, 1]);
}

function projMatrix(fov: number, aspect: number, near: number, far: number): Float32Array {
  const f = 1 / Math.tan(fov / 2);
  return new Float32Array([f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) / (near - far), -1, 0, 0, (2 * far * near) / (near - far), 0]);
}

export type GLRenderer = { render: (cam: Camera, w: number, h: number, dpr: number, opts: GLRenderOptions) => void; dispose: () => void };

export function createGLRenderer(canvas: HTMLCanvasElement, parts: Part[]): GLRenderer | null {
  let gl: WebGL2RenderingContext | null = null;
  try { gl = canvas.getContext('webgl2', { antialias: true, alpha: true, premultipliedAlpha: false }); } catch { gl = null; }
  if (!gl) return null;
  const sh = (type: number, src: string) => {
    const s = gl!.createShader(type)!;
    gl!.shaderSource(s, src);
    gl!.compileShader(s);
    if (!gl!.getShaderParameter(s, gl!.COMPILE_STATUS)) throw new Error(gl!.getShaderInfoLog(s) ?? 'shader');
    return s;
  };
  let prog: WebGLProgram;
  try {
    prog = gl.createProgram()!;
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS));
    gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return null;
  } catch { return null; }
  const loc = (n: string) => gl!.getUniformLocation(prog, n);
  const U = { tex: loc('uTex'), hasTex: loc('uHasTex'), view: loc('uView'), proj: loc('uProj'), color: loc('uColor'), emissive: loc('uEmissive'), hi: loc('uHi'), hiAmt: loc('uHiAmt'), alpha: loc('uAlpha'), xray: loc('uXray'), shine: loc('uShine'), fog: loc('uFogStart'), dim: loc('uDim') };
  const aPos = gl.getAttribLocation(prog, 'aPos'), aNrm = gl.getAttribLocation(prog, 'aNrm'), aUV = gl.getAttribLocation(prog, 'aUV');
  const textures = new Map<TexImageSource, WebGLTexture>();
  const textureFor = (img: TexImageSource | null | undefined): WebGLTexture | null => {
    if (!img) return null;
    const hit = textures.get(img);
    if (hit) return hit;
    const t = gl!.createTexture()!;
    gl!.bindTexture(gl!.TEXTURE_2D, t);
    try { gl!.texImage2D(gl!.TEXTURE_2D, 0, gl!.RGBA, gl!.RGBA, gl!.UNSIGNED_BYTE, img); } catch { gl!.deleteTexture(t); return null; }
    gl!.generateMipmap(gl!.TEXTURE_2D);
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_MIN_FILTER, gl!.LINEAR_MIPMAP_LINEAR);
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_MAG_FILTER, gl!.LINEAR);
    textures.set(img, t);
    return t;
  };
  const buffers: Buf[] = parts.map((part) => {
    const vao = gl!.createVertexArray()!;
    gl!.bindVertexArray(vao);
    const pb = gl!.createBuffer(); gl!.bindBuffer(gl!.ARRAY_BUFFER, pb); gl!.bufferData(gl!.ARRAY_BUFFER, new Float32Array(part.geo.p), gl!.STATIC_DRAW);
    gl!.enableVertexAttribArray(aPos); gl!.vertexAttribPointer(aPos, 3, gl!.FLOAT, false, 0, 0);
    const nb = gl!.createBuffer(); gl!.bindBuffer(gl!.ARRAY_BUFFER, nb); gl!.bufferData(gl!.ARRAY_BUFFER, new Float32Array(part.geo.n), gl!.STATIC_DRAW);
    gl!.enableVertexAttribArray(aNrm); gl!.vertexAttribPointer(aNrm, 3, gl!.FLOAT, false, 0, 0);
    const hasUV = !!(part.geo.uv && part.mat.texture);
    if (hasUV) {
      const ub = gl!.createBuffer(); gl!.bindBuffer(gl!.ARRAY_BUFFER, ub); gl!.bufferData(gl!.ARRAY_BUFFER, new Float32Array(part.geo.uv!), gl!.STATIC_DRAW);
      gl!.enableVertexAttribArray(aUV); gl!.vertexAttribPointer(aUV, 2, gl!.FLOAT, false, 0, 0);
    } else if (aUV >= 0) { gl!.disableVertexAttribArray(aUV); gl!.vertexAttrib2f(aUV, 0, 0); }
    const ib = gl!.createBuffer(); gl!.bindBuffer(gl!.ELEMENT_ARRAY_BUFFER, ib); gl!.bufferData(gl!.ELEMENT_ARRAY_BUFFER, part.geo.i instanceof Uint32Array ? part.geo.i : new Uint32Array(part.geo.i), gl!.STATIC_DRAW);
    gl!.bindVertexArray(null);
    let cx = 0, cy = 0, cz = 0;
    const nv = part.geo.p.length / 3 || 1;
    for (let k = 0; k < part.geo.p.length; k += 3) { cx += part.geo.p[k]; cy += part.geo.p[k + 1]; cz += part.geo.p[k + 2]; }
    return { vao, count: part.geo.i.length, part, centroid: [cx / nv, cy / nv, cz / nv], tex: hasUV ? textureFor(part.mat.texture) : null };
  });

  return {
    render(cam, w, h, dpr, opts) {
      const g = gl!;
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
      g.viewport(0, 0, canvas.width, canvas.height);
      g.clearColor(0, 0, 0, 0);
      g.clear(g.COLOR_BUFFER_BIT | g.DEPTH_BUFFER_BIT);
      g.useProgram(prog);
      const view = viewMatrix(cam);
      g.uniformMatrix4fv(U.view, false, view);
      g.uniformMatrix4fv(U.proj, false, projMatrix(cam.fov, w / Math.max(1, h), 0.1, 400));
      g.uniform1f(U.fog, cam.dist * 0.9);
      g.enable(g.DEPTH_TEST);
      g.disable(g.CULL_FACE);
      const visible = buffers.filter((b) => !(b.part.layer && opts.hiddenLayers?.has(b.part.layer)));
      const isXray = (b: Buf) => !!b.part.mat.xray;
      const transparent = (b: Buf) => (b.part.mat.alpha ?? 1) < 0.99 || isXray(b);
      const draw = (b: Buf) => {
        const m = b.part.mat;
        const hl = (b.part.id && opts.highlight[b.part.id]) || (b.part.part && opts.highlight[b.part.part]) || undefined;
        g.uniform3fv(U.color, m.color);
        g.uniform3fv(U.emissive, m.emissive ?? [0, 0, 0]);
        g.uniform3fv(U.hi, hl ? hl.color.map((c) => c / 255) : [0, 0, 0]);
        g.uniform1f(U.hiAmt, hl ? hl.amount : 0);
        g.uniform1f(U.alpha, m.alpha ?? 1);
        g.uniform1f(U.xray, isXray(b) ? 1 : 0);
        g.uniform1f(U.shine, m.shininess ?? 40);
        g.uniform1f(U.dim, opts.dim(b.part.id, b.part.layer));
        g.uniform1f(U.hasTex, b.tex ? 1 : 0);
        if (b.tex) { g.activeTexture(g.TEXTURE0); g.bindTexture(g.TEXTURE_2D, b.tex); g.uniform1i(U.tex, 0); }
        g.bindVertexArray(b.vao);
        g.drawElements(g.TRIANGLES, b.count, g.UNSIGNED_INT, 0);
      };
      g.disable(g.BLEND); g.depthMask(true);
      visible.filter((b) => !transparent(b)).forEach(draw);
      // Transparent: back to front by view-space depth.
      const depth = (b: Buf) => view[2] * b.centroid[0] + view[6] * b.centroid[1] + view[10] * b.centroid[2] + view[14];
      g.enable(g.BLEND); g.blendFunc(g.SRC_ALPHA, g.ONE_MINUS_SRC_ALPHA); g.depthMask(false);
      visible.filter(transparent).sort((a, b) => depth(a) - depth(b)).forEach(draw);
      g.depthMask(true);
      g.bindVertexArray(null);
    },
    dispose() {
      textures.forEach((t) => gl!.deleteTexture(t));
      const ext = gl!.getExtension('WEBGL_lose_context');
      ext?.loseContext();
    },
  };
}

/* ------------------------------------------------------------------ ray picking (renderer independent) */
type V3 = [number, number, number];

/** World-space ray through a canvas pixel for the shared camera model. */
export function pixelRay(cam: Camera, px: number, py: number, w: number, h: number): { o: V3; d: V3 } {
  const f = h / 2 / Math.tan(cam.fov / 2);
  const dc: V3 = [(px - w / 2) / f, -(py - h / 2) / f, -1];
  const cy = Math.cos(cam.yaw), sy = Math.sin(cam.yaw), cp = Math.cos(cam.pitch), sp = Math.sin(cam.pitch);
  // inverse of R = Rpitch * Ryaw  →  Ryaw^T * Rpitch^T
  const inv = (v: V3): V3 => {
    const y1 = cp * v[1] + sp * v[2], z1 = -sp * v[1] + cp * v[2];
    return [cy * v[0] + sy * z1, y1, -sy * v[0] + cy * z1];
  };
  const oc = inv([0, 0, cam.dist]);
  return { o: [oc[0] + cam.target[0], oc[1] + cam.target[1], oc[2] + cam.target[2]], d: inv(dc) };
}

/** Nearest hit among parts (Möller–Trumbore). Parts flagged `skip` (e.g. hidden or see-through layers) are ignored. */
const boxes = new WeakMap<Part['geo'], [number, number, number, number, number, number]>();
function aabb(g: Part['geo']) {
  let b = boxes.get(g);
  if (!b) {
    b = [Infinity, Infinity, Infinity, -Infinity, -Infinity, -Infinity];
    for (let k = 0; k < g.p.length; k += 3) for (let a = 0; a < 3; a++) { const v = g.p[k + a]; if (v < b[a]) b[a] = v; if (v > b[a + 3]) b[a + 3] = v; }
    boxes.set(g, b);
  }
  return b;
}
/** Slab test: does the ray hit the box closer than `limit`? */
function hitsBox(b: number[], o: V3, d: V3, limit: number) {
  let t0 = 0, t1 = limit;
  for (let a = 0; a < 3; a++) {
    if (Math.abs(d[a]) < 1e-12) { if (o[a] < b[a] || o[a] > b[a + 3]) return false; continue; }
    let n = (b[a] - o[a]) / d[a], f = (b[a + 3] - o[a]) / d[a];
    if (n > f) [n, f] = [f, n];
    t0 = Math.max(t0, n); t1 = Math.min(t1, f);
    if (t0 > t1) return false;
  }
  return true;
}

export function raycast(parts: Part[], ray: { o: V3; d: V3 }, skip: (p: Part) => boolean): { part: Part; t: number } | null {
  let best: { part: Part; t: number } | null = null;
  const { o, d } = ray;
  for (const part of parts) {
    if (skip(part)) continue;
    if (!hitsBox(aabb(part.geo), o, d, best ? best.t : Infinity)) continue;
    const P = part.geo.p, I = part.geo.i;
    for (let k = 0; k < I.length; k += 3) {
      const a = I[k] * 3, b = I[k + 1] * 3, c = I[k + 2] * 3;
      const e1x = P[b] - P[a], e1y = P[b + 1] - P[a + 1], e1z = P[b + 2] - P[a + 2];
      const e2x = P[c] - P[a], e2y = P[c + 1] - P[a + 1], e2z = P[c + 2] - P[a + 2];
      const px = d[1] * e2z - d[2] * e2y, py = d[2] * e2x - d[0] * e2z, pz = d[0] * e2y - d[1] * e2x;
      const det = e1x * px + e1y * py + e1z * pz;
      if (Math.abs(det) < 1e-9) continue;
      const inv = 1 / det;
      const tx = o[0] - P[a], ty = o[1] - P[a + 1], tz = o[2] - P[a + 2];
      const u = (tx * px + ty * py + tz * pz) * inv;
      if (u < 0 || u > 1) continue;
      const qx = ty * e1z - tz * e1y, qy = tz * e1x - tx * e1z, qz = tx * e1y - ty * e1x;
      const v = (d[0] * qx + d[1] * qy + d[2] * qz) * inv;
      if (v < 0 || u + v > 1) continue;
      const t = (e2x * qx + e2y * qy + e2z * qz) * inv;
      if (t > 0.01 && (!best || t < best.t)) best = { part, t };
    }
  }
  return best;
}
