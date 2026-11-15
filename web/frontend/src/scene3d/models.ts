/**
 * Procedural placeholder models (v0.4). Part ids follow the GLB node contract in
 * docs/3D_INTEGRATION.md, so the modeller's assets can replace them 1:1.
 */
import type { MetricKey, ZoneId } from '../api/types';
import type { BodySystem } from '../lib/format';
import type { Vec3 } from './engine';
import { alongX, box, capsule, ellipsoid, hex, lathe, merge, rotateX, rotateZ, torus, translate, tube, type Geo, type Material, type Part } from './geometry';

/* ================================================================== spacecraft */
const HULL: Material = { color: hex('#c3cdd6'), shininess: 60 };
const HULL_B: Material = { color: hex('#aebbc7'), shininess: 50 };
const DARK: Material = { color: hex('#3a4654'), shininess: 30 };
const FOIL: Material = { color: hex('#b9925a'), shininess: 90 };
const WINDOW: Material = { color: hex('#0b2232'), emissive: [0.12, 0.42, 0.55], shininess: 120 };
const SOLAR: Material = { color: hex('#173563'), emissive: [0.02, 0.05, 0.12], shininess: 140 };
const RADIATOR: Material = { color: hex('#e2e8ee'), shininess: 20 };

export const SHIP_ZONES: Record<ZoneId, { centre: Vec3; label: Vec3; crewSlots: Vec3[] }> = {
  command: { centre: [8.6, 0, 0], label: [9.0, 2.2, 0], crewSlots: [[7.6, 0.5, 1.45], [9.0, 0.5, 1.45], [8.3, -0.6, 1.45]] },
  medical: { centre: [5.7, 0, 0], label: [5.7, -2.0, 0], crewSlots: [[5.3, 0.3, 1.25], [6.1, 0.3, 1.25]] },
  habitat: { centre: [2.5, 0, 0], label: [2.5, 4.7, 0], crewSlots: [[2.5, 3.3, 1.0], [2.5, -1.2, 3.3], [2.5, -3.3, -0.6], [2.5, 1.2, -3.3]] },
  exercise: { centre: [-0.35, 0, 0], label: [-0.3, -2.0, 0], crewSlots: [[-0.8, 0.3, 1.25], [0.1, 0.3, 1.25]] },
  systems: { centre: [-3.1, 0, 0], label: [-3.4, 2.2, 0], crewSlots: [[-3.5, 0.3, 1.35], [-2.7, 0.3, 1.35]] },
};

const X = (g: Geo) => alongX(g);
const ring = (x: number, r: number, t = 0.035) => translate(alongX(torus(r, t, 72, 8)), [x, 0, 0]);

export function buildShip(): Part[] {
  const parts: Part[] = [];
  const add = (id: ZoneId | null, part: string, geo: Geo, mat: Material) => parts.push({ id, part, geo, mat });

  // Command module – rounded nose, cockpit window band, docking port
  add('command', 'hull', X(lathe([[0, 6.75], [0.82, 6.75], [0.82, 7.15], [1.28, 7.22], [1.3, 8.95], [1.22, 9.45], [1.02, 9.95], [0.7, 10.35], [0.42, 10.55], [0, 10.62]], 56)), HULL);
  add('command', 'window', X(lathe([[1.305, 9.0], [1.29, 9.12], [1.25, 9.3], [1.23, 9.4]], 56)), WINDOW);
  add('command', 'ring', ring(7.3, 1.3), DARK);
  add(null, 'docking', X(lathe([[0.3, 10.55], [0.36, 10.6], [0.36, 10.95], [0.42, 11.0], [0.42, 11.08], [0, 11.08]], 28)), DARK);
  add(null, 'antenna', merge(tube([[8.2, 1.25, 0], [8.2, 2.05, 0]], 0.035, 8), translate(lathe([[0.04, 0], [0.25, 0.06], [0.42, 0.18], [0.5, 0.3]], 28), [8.2, 2.05, 0])), RADIATOR);

  // Medical bay – ribbed cylinder
  add('medical', 'hull', X(lathe([[0.75, 4.25], [0.78, 4.55], [1.05, 4.62], [1.05, 6.72], [0.78, 6.8], [0.75, 6.82]], 48)), HULL_B);
  for (const x of [5.05, 5.65, 6.25]) add('medical', 'rib', ring(x, 1.07), DARK);
  add('medical', 'window', translate(rotateZ(box([0.5, 0.06, 0.28]), 0), [5.65, 1.07, 0]), WINDOW);

  // Habitat – rotating torus, hub, spokes, windows (gold thermal blanket band)
  add('habitat', 'ring', translate(alongX(torus(3.3, 0.62, 96, 22)), [2.5, 0, 0]), HULL);
  add('habitat', 'band', translate(alongX(torusBand()), [2.5, 0, 0]), FOIL);
  add('habitat', 'hub', X(lathe([[0.7, 0.95], [0.98, 1.05], [0.98, 4.05], [0.7, 4.2]], 40)), HULL_B);
  for (let k = 0; k < 4; k++) {
    const a = (k / 4) * Math.PI * 2 + Math.PI / 4;
    add('habitat', 'spoke', tube([[2.5, Math.cos(a) * 0.95, Math.sin(a) * 0.95], [2.5, Math.cos(a) * 2.7, Math.sin(a) * 2.7]], 0.14, 12), DARK);
  }
  const wins: Geo[] = [];
  for (let k = 0; k < 24; k++) {
    const a = (k / 24) * Math.PI * 2;
    wins.push(translate(rotateX(box([0.36, 0.06, 0.22]), a + Math.PI / 2), [2.5, Math.cos(a) * 3.93, Math.sin(a) * 3.93]));
  }
  add('habitat', 'window', merge(...wins), WINDOW);

  // Exercise & recovery module with observation cupola
  add('exercise', 'hull', X(lathe([[0.72, -1.75], [1.04, -1.62], [1.06, 0.82], [0.72, 0.95]], 48)), HULL);
  add('exercise', 'rib', ring(-0.4, 1.08), DARK);
  add('exercise', 'cupola', translate(ellipsoid([0.42, 0.3, 0.42], 28, 12), [-0.4, 1.05, 0]), WINDOW);

  // Life support (ECLSS) + radiators
  add('systems', 'hull', X(lathe([[0.8, -4.75], [1.2, -4.6], [1.22, -1.75], [0.8, -1.62]], 48)), HULL_B);
  for (const x of [-4.1, -3.1, -2.1]) add('systems', 'rib', ring(x, 1.24), DARK);
  for (const z of [1, -1]) {
    add(null, 'radiator', translate(box([2.6, 0.04, 2.3]), [-3.1, 0, z * 2.55]), RADIATOR);
    const stripes: Geo[] = [];
    for (let k = 0; k < 6; k++) stripes.push(translate(box([0.03, 0.05, 2.3]), [-4.25 + k * 0.46, 0.005, z * 2.55]));
    add(null, 'radiator-lines', merge(...stripes), DARK);
    add(null, 'strut', tube([[-3.1, 0, z * 1.2], [-3.1, 0, z * 1.4]], 0.06, 8), DARK);
  }

  // Truss
  const lon: Geo[] = [];
  for (const [y, z] of [[0.3, 0.3], [0.3, -0.3], [-0.3, 0.3], [-0.3, -0.3]] as [number, number][]) lon.push(tube([[-9.3, y, z], [-4.7, y, z]], 0.04, 6));
  for (let k = 0; k < 8; k++) {
    const x0 = -9.3 + k * 0.575, x1 = x0 + 0.575;
    lon.push(tube([[x0, 0.3, 0.3], [x1, -0.3, 0.3]], 0.025, 5), tube([[x0, -0.3, -0.3], [x1, 0.3, -0.3]], 0.025, 5));
  }
  add(null, 'truss', merge(...lon), DARK);

  // Solar wings
  for (const z of [1, -1]) {
    const panels: Geo[] = [];
    for (let k = 0; k < 4; k++) panels.push(translate(box([2.3, 0.03, 1.45]), [-7, 0, z * (1.6 + k * 1.6)]));
    add(null, 'solar', merge(...panels), SOLAR);
    add(null, 'solar-mast', tube([[-7, 0, z * 0.3], [-7, 0, z * 7.0]], 0.05, 8), DARK);
  }

  // Tanks, engine, RCS
  add(null, 'tank', merge(translate(ellipsoid([0.85, 0.75, 0.75], 28, 14), [-8.1, 0.95, 0]), translate(ellipsoid([0.85, 0.75, 0.75], 28, 14), [-8.1, -0.95, 0])), FOIL);
  add(null, 'engine', X(lathe([[0.25, -9.35], [0.42, -9.5], [0.62, -9.9], [0.86, -10.4], [1.06, -10.9], [1.02, -10.92]], 40)), DARK);
  add(null, 'rcs', merge(...[[7.8, 1.3, 0.3], [7.8, -1.3, -0.3], [-4.3, 1.25, 0.4], [-4.3, -1.25, -0.4]].map((p) => translate(box([0.25, 0.18, 0.18]), p as Vec3))), DARK);
  return parts;
}

/** Thin raised band across the outer face of the habitat ring (thermal blanket). */
function torusBand(): Geo {
  const g = torus(3.3, 0.632, 96, 18);
  // keep only the outer third of the tube cross-section
  const keep: number[] = [];
  for (let k = 0; k < g.i.length; k += 3) {
    const ok = [g.i[k], g.i[k + 1], g.i[k + 2]].every((v) => Math.hypot(g.p[v * 3], g.p[v * 3 + 2]) > 3.7 && Math.abs(g.p[v * 3 + 1]) < 0.3);
    if (ok) keep.push(g.i[k], g.i[k + 1], g.i[k + 2]);
  }
  return { ...g, i: keep };
}

/* ================================================================== human twin */
const SHELL_COLOR = hex('#8ea6bd');
const HOLO_COLOR = hex('#3ccfff');
const LUNG = hex('#6fe7ff');
const META = hex('#ffbf69');
const CARDIO = hex('#e05265');
const VEIN = hex('#5b84e0');
const NERVE = hex('#ad94ff');
const BONE = hex('#ddd5c2');

/** Hotspot positions for metrics (HTML anchors). */
export const METRIC_ANCHORS: Record<MetricKey, Vec3> = {
  heart_rate_bpm: [0.42, 1.85, 0.5],
  reaction_ms: [0.0, 3.62, 0.25],
  sleep_hours: [-0.62, 3.15, 0.2],
  fatigue_1_10: [0.62, 2.75, 0.25],
  activity_minutes: [0.62, -0.55, 0.3],
};
export const SYSTEM_FOCUS: Record<BodySystem, Vec3> = { cardiovascular: [0, 1.6, 0], respiratory: [0, 1.9, 0], nervous: [0, 2.2, 0], musculoskeletal: [0, 0.2, 0], metabolic: [0, 1.0, 0] };

type Seg = [Vec3, Vec3, number, number];
const L = (s: number): Record<string, Seg> => ({
  upperArm: [[s * 0.84, 2.12, 0], [s * 1.04, 1.05, 0.02], 0.17, 0.14],
  forearm: [[s * 1.04, 1.05, 0.02], [s * 1.14, 0.08, 0.1], 0.135, 0.1],
  thigh: [[s * 0.33, 0.42, 0], [s * 0.37, -1.25, 0.02], 0.26, 0.18],
  calf: [[s * 0.37, -1.25, 0.02], [s * 0.39, -2.72, -0.02], 0.165, 0.11],
});

/**
 * Stylised human figure for BODY.
 * @param xray  render the skin shell as a Fresnel x-ray surface so inner layers are visible
 */
export function buildHuman(xray: boolean): Part[] {
  const parts: Part[] = [];
  const shell: Material = xray ? { color: HOLO_COLOR, alpha: 0.8, xray: true, shininess: 20 } : { color: SHELL_COLOR, shininess: 24 };
  const add = (id: BodySystem | null, part: string, layer: string, geo: Geo, mat: Material) => parts.push({ id, part, layer, geo, mat });

  // ---- surface shell (picking selects the system that region represents)
  add('nervous', 'head', 'shell', translate(ellipsoid([0.42, 0.52, 0.47], 32, 20), [0, 3.02, 0.02]), shell);
  add('nervous', 'neck', 'shell', capsule([0, 2.3, 0], [0, 2.62, 0.02], 0.17, 0.16), shell);
  const torso = lathe([[0, 0.32], [0.55, 0.36], [0.66, 0.62], [0.62, 1.0], [0.56, 1.28], [0.64, 1.65], [0.77, 2.02], [0.72, 2.28], [0.4, 2.42], [0, 2.46]], 40);
  for (let k = 0; k < torso.p.length; k += 3) torso.p[k + 2] *= 0.6;
  add('cardiovascular', 'torso', 'shell', torso, shell);
  for (const s of [1, -1]) {
    const l = L(s);
    add('musculoskeletal', 'shoulder', 'shell', translate(ellipsoid([0.22, 0.2, 0.2], 20, 12), [s * 0.8, 2.13, 0]), shell);
    add('musculoskeletal', 'arm', 'shell', merge(capsule(...l.upperArm), capsule(...l.forearm)), shell);
    add('musculoskeletal', 'hand', 'shell', translate(ellipsoid([0.09, 0.19, 0.07], 16, 10), [s * 1.17, -0.18, 0.12]), shell);
    add('musculoskeletal', 'leg', 'shell', merge(capsule(...l.thigh), capsule(...l.calf)), shell);
    add('musculoskeletal', 'foot', 'shell', translate(ellipsoid([0.12, 0.08, 0.26], 16, 10), [s * 0.39, -2.9, 0.12]), shell);
  }

  // ---- cardiovascular layer
  add('cardiovascular', 'heart', 'cardiovascular', translate(ellipsoid([0.19, 0.24, 0.17], 24, 14), [0.12, 1.78, 0.1]), { color: CARDIO, emissive: [0.18, 0.03, 0.05], shininess: 70 });
  const arteries: Geo[] = [
    tube([[0.1, 1.95, 0.05], [0.05, 2.18, 0], [-0.12, 2.12, -0.06], [-0.1, 1.6, -0.12], [-0.05, 0.9, -0.12], [0, 0.42, -0.08]], 0.055, 10),
    ...[1, -1].flatMap((s) => {
      const l = L(s);
      return [
        tube([[s * 0.12, 2.12, 0], [s * 0.13, 2.5, 0.02], [s * 0.14, 2.85, 0.05]], 0.03, 8),
        tube([[0, 2.12, -0.02], [s * 0.5, 2.15, 0], l.upperArm[0], l.upperArm[1], l.forearm[1]], 0.03, 8),
        tube([[0, 0.42, -0.08], [s * 0.22, 0.25, 0], l.thigh[0], l.thigh[1], l.calf[1]], 0.04, 8),
      ];
    }),
  ];
  add('cardiovascular', 'arteries', 'cardiovascular', merge(...arteries), { color: CARDIO, emissive: [0.12, 0.02, 0.03], shininess: 60 });
  add('cardiovascular', 'veins', 'cardiovascular', merge(tube([[0.2, 1.7, 0.02], [0.18, 1.1, -0.04], [0.12, 0.42, -0.04]], 0.045, 10),
    ...[1, -1].map((s) => tube([[s * 0.2, 0.3, 0.05], [s * 0.42, -1.2, 0.1], [s * 0.42, -2.6, 0.06]], 0.03, 8))), { color: VEIN, emissive: [0.03, 0.06, 0.14], shininess: 60 });

  // ---- respiratory layer (schematic)
  const lungs: Geo[] = [tube([[0, 2.55, 0.06], [0, 2.3, 0.06], [0, 2.08, 0.04]], 0.05, 10)];
  for (const s of [1, -1]) {
    lungs.push(tube([[0, 2.08, 0.04], [s * 0.18, 1.98, 0.02], [s * 0.28, 1.85, 0]], 0.035, 8));
    lungs.push(translate(ellipsoid([0.22, 0.4, 0.2], 24, 16), [s * 0.3, 1.75, -0.02]));
  }
  add('respiratory', 'lungs', 'respiratory', merge(...lungs), { color: LUNG, emissive: [0.03, 0.1, 0.14], shininess: 55, alpha: 0.85 });

  // ---- metabolic layer (schematic)
  add('metabolic', 'liver', 'metabolic', translate(ellipsoid([0.3, 0.14, 0.18], 22, 12), [-0.18, 1.3, 0.04]), { color: META, emissive: [0.12, 0.07, 0.01], shininess: 45 });
  add('metabolic', 'stomach', 'metabolic', translate(ellipsoid([0.15, 0.12, 0.12], 18, 10), [0.22, 1.22, 0.06]), { color: META, emissive: [0.1, 0.06, 0.01], shininess: 45 });
  const gut: [number, number, number][] = [];
  for (let k = 0; k <= 36; k++) { const a = k * 0.62; gut.push([Math.cos(a) * (0.2 + 0.05 * Math.sin(k)), 1.02 - k * 0.012, 0.08 + Math.sin(a) * 0.06]); }
  add('metabolic', 'intestine', 'metabolic', tube(gut, 0.045, 8), { color: META, emissive: [0.08, 0.05, 0.01], shininess: 40 });

  // ---- nervous layer
  add('nervous', 'brain', 'nervous', translate(ellipsoid([0.32, 0.27, 0.37], 28, 16), [0, 3.1, -0.02]), { color: NERVE, emissive: [0.1, 0.06, 0.2], shininess: 50 });
  const nerves: Geo[] = [tube([[0, 2.86, -0.16], [0, 2.4, -0.22], [0, 1.6, -0.27], [0, 0.9, -0.25], [0, 0.45, -0.2]], 0.045, 10)];
  for (const s of [1, -1]) {
    const l = L(s);
    nerves.push(tube([[0, 2.2, -0.22], [s * 0.6, 2.12, -0.04], l.upperArm[1], l.forearm[1]], 0.02, 6));
    nerves.push(tube([[0, 0.45, -0.2], [s * 0.3, 0.2, -0.08], l.thigh[1], l.calf[1]], 0.025, 6));
  }
  add('nervous', 'nerves', 'nervous', merge(...nerves), { color: NERVE, emissive: [0.08, 0.05, 0.16], shininess: 40 });

  // ---- musculoskeletal layer
  const bones: Geo[] = [];
  for (let k = 0; k < 20; k++) bones.push(translate(box([0.12, 0.07, 0.1]), [0, 0.5 + k * 0.105, -0.3]));
  for (let k = 0; k < 6; k++) {
    const r = torus(0.42 - Math.abs(k - 2.5) * 0.025, 0.022, 40, 6);
    for (let v = 0; v < r.p.length; v += 3) r.p[v + 2] *= 0.62;
    bones.push(translate(rotateX(r, 0.15), [0, 1.4 + k * 0.13, -0.02]));
  }
  bones.push(translate(rotateX(torus(0.38, 0.07, 40, 8), 0.4), [0, 0.5, -0.04]));
  for (const s of [1, -1]) {
    const l = L(s);
    bones.push(tube([l.upperArm[0], l.upperArm[1]], 0.045, 8), tube([l.forearm[0], l.forearm[1]], 0.035, 8),
      tube([l.thigh[0], l.thigh[1]], 0.06, 8), tube([l.calf[0], l.calf[1]], 0.05, 8), tube([[0, 2.25, 0.05], [s * 0.75, 2.2, 0]], 0.03, 6));
  }
  add('musculoskeletal', 'skeleton', 'musculoskeletal', merge(...bones), { color: BONE, shininess: 30 });
  return parts;
}
