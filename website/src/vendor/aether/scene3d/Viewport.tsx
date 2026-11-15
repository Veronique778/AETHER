import { useCallback, useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react';
import { cx, Icon, Tooltip } from '../ui';
import { project, render as renderCanvas, type Camera, type Highlight, type Mesh, type Vec3 } from './engine';
import { toTris, type Part } from './geometry';
import { createGLRenderer, pixelRay, raycast, type GLRenderer } from './gl';

export type Anchor = { id: string; pos: Vec3; render: (state: { front: boolean }) => ReactNode };

/**
 * Renderer-agnostic 3D viewport contract (see docs/FRONTEND_INTEGRATION.md §3D).
 * Rendering: WebGL2 when available, Canvas-2D fallback otherwise (or with `?renderer=canvas`).
 * Picking: world-space ray cast, identical for both renderers.
 */
export type ViewportProps = {
  model: Part[];
  initialCamera: Camera;
  focus?: Vec3 | null;
  highlight?: Highlight;
  /** Dimming per part: return 0..1 (1 = full brightness). */
  dim?: (id: string | null, layer?: string) => number;
  hiddenLayers?: Set<string>;
  anchors?: Anchor[];
  onPick?: (id: string | null, part?: string) => void;
  onHover?: (id: string | null) => void;
  height?: number | string;
  ariaLabel: string;
  instructions?: string;
  reducedMotion?: boolean;
  className?: string;
  /** Skip see-through parts when picking so inner layers can be clicked. */
  pickThroughTransparent?: boolean;
  minZoom?: number;
  maxZoom?: number;
};

let canvasGeneration = 0;
const forceCanvas = () => /[?&]renderer=canvas/.test(globalThis.location?.hash + globalThis.location?.search);

export function Viewport({ model, initialCamera, focus, highlight = {}, dim, hiddenLayers, anchors = [], onPick, onHover, height = 420, ariaLabel, instructions,
  reducedMotion, className, pickThroughTransparent = true, minZoom = 0.35, maxZoom = 2.2 }: ViewportProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const glRef = useRef<GLRenderer | null>(null);
  const [mode, setMode] = useState<'webgl' | 'canvas' | 'pending'>('pending');
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [cam, setCam] = useState<Camera>(initialCamera);
  const drag = useRef<{ x: number; y: number; moved: boolean; pinch?: number } | null>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const hoverRef = useRef<string | null>(null);
  const helpId = useId();
  // Each model gets its own <canvas>: disposing a renderer loses its WebGL context, so a new renderer must not
  // reuse that canvas (v0.8 fix – previously a model change, e.g. X-ray ↔ surface, fell back to Canvas 2D).
  const generation = useMemo(() => ++canvasGeneration, [model]);
  const dimFn = useCallback((id: string | null, layer?: string) => (dim ? dim(id, layer) : 1), [dim]);
  const fallbackMeshes = useMemo<Mesh[]>(() => (mode === 'canvas'
    ? model.filter((p) => !(p.layer && hiddenLayers?.has(p.layer))).map((p) => ({ id: p.id, part: p.part, tris: toTris(p.geo), doubleSided: true, opacity: p.mat.xray ? 0.18 : p.mat.alpha ?? 1,
      color: p.mat.color.map((c) => Math.round(Math.min(1, c + (p.mat.emissive ? Math.max(...p.mat.emissive) * 0.5 : 0)) * 255)) as [number, number, number] }))
    : []), [mode, model, hiddenLayers]);

  // Create (or recreate) the renderer when the model changes.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (forceCanvas()) { setMode('canvas'); return; }
    const r = createGLRenderer(canvas, model);
    glRef.current = r;
    setMode(r ? 'webgl' : 'canvas');
    const lost = (e: Event) => { e.preventDefault(); glRef.current = null; setMode('canvas'); };
    canvas.addEventListener('webglcontextlost', lost);
    return () => { canvas.removeEventListener('webglcontextlost', lost); r?.dispose(); glRef.current = null; };
  }, [model]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const update = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    update();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!focus) return;
    if (reducedMotion) { setCam((c) => ({ ...c, target: focus })); return; }
    let raf = 0;
    const t0 = performance.now();
    let from: Vec3 | null = null;
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / 480);
      const e = 1 - (1 - k) ** 3;
      setCam((c) => {
        from ??= c.target;
        return { ...c, target: [from[0] + (focus[0] - from[0]) * e, from[1] + (focus[1] - from[1]) * e, from[2] + (focus[2] - from[2]) * e] };
      });
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [focus?.[0], focus?.[1], focus?.[2], reducedMotion]); // eslint-disable-line react-hooks/exhaustive-deps

  // Draw (on demand – no idle loop).
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !size.w || !size.h || mode === 'pending') return;
    const dpr = Math.min(2, globalThis.devicePixelRatio || 1);
    const raf = requestAnimationFrame(() => {
      if (mode === 'webgl' && glRef.current) {
        glRef.current.render(cam, size.w, size.h, dpr, { highlight, dim: dimFn, hiddenLayers });
        return;
      }
      canvas.width = size.w * dpr; canvas.height = size.h * dpr;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, size.w, size.h);
      renderCanvas(ctx, fallbackMeshes, cam, size.w, size.h, highlight, (id) => dimFn(id));
    });
    return () => cancelAnimationFrame(raf);
  }, [cam, size, highlight, dimFn, hiddenLayers, mode, fallbackMeshes]);

  const pickAt = (clientX: number, clientY: number) => {
    const r = canvasRef.current!.getBoundingClientRect();
    const hit = raycast(model, pixelRay(cam, clientX - r.left, clientY - r.top, r.width, r.height),
      (p) => !!(p.layer && hiddenLayers?.has(p.layer)) || (pickThroughTransparent && (!!p.mat.xray || (p.mat.alpha ?? 1) < 0.6)));
    return hit ? { id: hit.part.id, part: hit.part.part } : null;
  };
  const clampPitch = (p: number) => Math.max(-1.35, Math.min(1.35, p));
  const zoom = useCallback((factor: number) => setCam((c) => ({ ...c, dist: Math.max(initialCamera.dist * minZoom, Math.min(initialCamera.dist * maxZoom, c.dist * factor)) })), [initialCamera.dist, minZoom, maxZoom]);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const onWheel = (e: WheelEvent) => { e.preventDefault(); zoom(e.deltaY > 0 ? 1.08 : 1 / 1.08); };
    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', onWheel);
  }, [generation, mode, zoom]);
  const reset = () => setCam(initialCamera);
  const projected = useMemo(() => (size.w ? anchors.map((a) => ({ a, p: project(a.pos, cam, size.w, size.h) })) : []), [anchors, cam, size]);
  const btn = 'grid h-9 w-9 place-items-center rounded-lg border border-[#56708c]/50 bg-[#0c1422]/85 text-[#a9b8ca] backdrop-blur transition-colors hover:border-[#4fd1e8] hover:text-white';

  return (
    <div ref={wrapRef} className={cx('relative w-full overflow-hidden', className)} style={{ height }}>
      <canvas
        key={mode === 'canvas' ? 'c2d' : `gl-${generation}`}
        ref={canvasRef}
        role="application"
        aria-label={ariaLabel}
        aria-describedby={instructions ? helpId : undefined}
        aria-roledescription="3D viewer"
        tabIndex={0}
        className="absolute inset-0 h-full w-full cursor-grab touch-none outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#4fd1e8] active:cursor-grabbing"
        onPointerDown={(e) => {
          pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
          e.currentTarget.setPointerCapture(e.pointerId);
          const pts = [...pointers.current.values()];
          drag.current = { x: e.clientX, y: e.clientY, moved: false, pinch: pts.length === 2 ? Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) : undefined };
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (d && pointers.current.has(e.pointerId)) {
            pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
            const pts = [...pointers.current.values()];
            if (pts.length === 2 && d.pinch) {
              const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
              zoom(d.pinch / dist); d.pinch = dist; d.moved = true; return;
            }
            const dx = e.clientX - d.x, dy = e.clientY - d.y;
            if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
            if (d.moved) { setCam((c) => ({ ...c, yaw: c.yaw + dx * 0.008, pitch: clampPitch(c.pitch + dy * 0.006) })); d.x = e.clientX; d.y = e.clientY; }
            return;
          }
          const hit = pickAt(e.clientX, e.clientY);
          const id = hit?.id ?? null;
          if (id !== hoverRef.current) { hoverRef.current = id; onHover?.(id); e.currentTarget.style.cursor = id ? 'pointer' : ''; }
        }}
        onPointerUp={(e) => {
          pointers.current.delete(e.pointerId);
          const d = drag.current;
          if (pointers.current.size === 0) drag.current = null;
          if (d && !d.moved) { const hit = pickAt(e.clientX, e.clientY); onPick?.(hit?.id ?? null, hit?.part); }
        }}
        onPointerLeave={() => { if (hoverRef.current) { hoverRef.current = null; onHover?.(null); } }}
        onKeyDown={(e) => {
          const k = e.key;
          if (k === 'ArrowLeft') setCam((c) => ({ ...c, yaw: c.yaw - 0.12 }));
          else if (k === 'ArrowRight') setCam((c) => ({ ...c, yaw: c.yaw + 0.12 }));
          else if (k === 'ArrowUp') setCam((c) => ({ ...c, pitch: clampPitch(c.pitch - 0.1) }));
          else if (k === 'ArrowDown') setCam((c) => ({ ...c, pitch: clampPitch(c.pitch + 0.1) }));
          else if (k === '+' || k === '=') zoom(1 / 1.12);
          else if (k === '-' || k === '_') zoom(1.12);
          else if (k === '0') reset();
          else return;
          e.preventDefault();
        }}
      />
      {projected.map(({ a, p }) => p.visible && (
        <div key={a.id} className="pointer-events-none absolute" style={{ left: p.x, top: p.y, transform: 'translate(-50%, -50%)' }}>
          <div className="pointer-events-auto">{a.render({ front: p.depth < cam.dist })}</div>
        </div>
      ))}
      <div className="absolute right-3 top-3 flex flex-col gap-1.5 no-print">
        <Tooltip text="Zoom in (+)">{(id) => <button type="button" aria-label="Zoom in" aria-describedby={id} onClick={() => zoom(1 / 1.15)} className={btn}><Icon name="plus" size={16} /></button>}</Tooltip>
        <Tooltip text="Zoom out (−)">{(id) => <button type="button" aria-label="Zoom out" aria-describedby={id} onClick={() => zoom(1.15)} className={btn}><Icon name="minus" size={16} /></button>}</Tooltip>
        <Tooltip text="Reset view (0)">{(id) => <button type="button" aria-label="Reset view" aria-describedby={id} onClick={reset} className={btn}><Icon name="rotate" size={16} /></button>}</Tooltip>
      </div>
      <div className="pointer-events-none absolute bottom-2 left-3 right-3 flex items-end justify-between gap-3 text-[11px] text-[#8698ae]">
        {instructions ? <p id={helpId}>{instructions}</p> : <span />}
        <span className="mono-label !text-[10px]" title={mode === 'canvas' ? 'WebGL unavailable – Canvas 2D fallback renderer' : 'WebGL 2 renderer'}>{mode === 'webgl' ? 'WebGL' : mode === 'canvas' ? 'Canvas fallback' : ''}</span>
      </div>
    </div>
  );
}
