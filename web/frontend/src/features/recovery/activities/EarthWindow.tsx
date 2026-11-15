import { useEffect, useRef, useState } from 'react';
import type { SessionDetails } from '../../../api/types';
import { Button, cx, Segmented, SliderField } from '../../../ui';

type Scene = 'orbit' | 'coast' | 'forest' | 'mountains' | 'aurora';
type TimeOfDay = 'dawn' | 'day' | 'dusk' | 'night';
type Sound = 'off' | 'waves' | 'rain' | 'wind';

const SKY: Record<TimeOfDay, [string, string]> = { dawn: ['#3b4a6b', '#e3b98f'], day: ['#5f93b8', '#cfe3ea'], dusk: ['#2c2f55', '#d98f6f'], night: ['#0b1220', '#1d2b45'] };

/** WebAudio ambience generated locally (no downloaded audio). */
class Ambience {
  private ctx: AudioContext | null = null;
  private nodes: AudioNode[] = [];
  private gain: GainNode | null = null;
  start(kind: Exclude<Sound, 'off'>, volume: number) {
    this.stop();
    const AC = globalThis.AudioContext ?? (globalThis as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AC) return false;
    this.ctx = new AC();
    const ctx = this.ctx;
    const len = ctx.sampleRate * 4;
    const buf = ctx.createBuffer(1, len, ctx.sampleRate);
    const data = buf.getChannelData(0);
    let last = 0;
    for (let i = 0; i < len; i++) { const white = Math.random() * 2 - 1; last = kind === 'rain' ? white : (last + 0.02 * white) / 1.02; data[i] = kind === 'rain' ? white * 0.25 : last * 3.5; }
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.loop = true;
    const filter = ctx.createBiquadFilter();
    filter.type = kind === 'rain' ? 'lowpass' : 'bandpass';
    filter.frequency.value = kind === 'rain' ? 2800 : kind === 'wind' ? 500 : 400;
    this.gain = ctx.createGain();
    this.gain.gain.value = volume;
    const swell = ctx.createGain();
    swell.gain.value = 0.7;
    if (kind !== 'rain') {
      const lfo = ctx.createOscillator();
      lfo.frequency.value = kind === 'waves' ? 0.09 : 0.05;
      const lfoGain = ctx.createGain();
      lfoGain.gain.value = 0.3;
      lfo.connect(lfoGain).connect(swell.gain);
      lfo.start();
      this.nodes.push(lfo);
    }
    src.connect(filter).connect(swell).connect(this.gain).connect(ctx.destination);
    src.start();
    this.nodes.push(src);
    return true;
  }
  setVolume(v: number) { if (this.gain) this.gain.gain.value = v; }
  chime() {
    const AC = globalThis.AudioContext;
    if (!AC) return;
    const ctx = this.ctx ?? new AC();
    [523.25, 659.25].forEach((f, i) => {
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, ctx.currentTime + i * 0.35);
      g.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + i * 0.35 + 0.05);
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + i * 0.35 + 1.6);
      o.connect(g).connect(ctx.destination);
      o.start(ctx.currentTime + i * 0.35);
      o.stop(ctx.currentTime + i * 0.35 + 1.7);
    });
  }
  stop() {
    this.nodes.forEach((n) => { try { (n as AudioScheduledSourceNode).stop(); } catch { /* already stopped */ } });
    this.nodes = [];
    this.ctx?.close().catch(() => undefined);
    this.ctx = null;
    this.gain = null;
  }
}

export function EarthWindow({ reducedMotion, onReport }: { reducedMotion: boolean; onReport: (d: SessionDetails) => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [scene, setScene] = useState<Scene>('orbit');
  const wrapRef = useRef<HTMLDivElement>(null);
  const [ghost, setGhost] = useState<{ src: string; on: boolean } | null>(null);
  const [full, setFull] = useState(false);
  const first = useRef(true);
  const [tod, setTod] = useState<TimeOfDay>('dusk');
  const [sound, setSound] = useState<Sound>('off');
  const [volume, setVolume] = useState(0.35);
  const [minutes, setMinutes] = useState(5);
  const [remaining, setRemaining] = useState<number | null>(null);
  const [viewed, setViewed] = useState(0);
  const [completed, setCompleted] = useState(false);
  const [audioError, setAudioError] = useState(false);
  const amb = useRef(new Ambience());

  useEffect(() => () => amb.current.stop(), []);
  useEffect(() => {
    if (sound === 'off') { amb.current.stop(); return; }
    setAudioError(!amb.current.start(sound, volume));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sound]);
  useEffect(() => amb.current.setVolume(volume), [volume]);

  useEffect(() => { const on = () => setFull(document.fullscreenElement === wrapRef.current && !!wrapRef.current); document.addEventListener('fullscreenchange', on); return () => document.removeEventListener('fullscreenchange', on); }, []);
  const toggleFull = () => { if (document.fullscreenElement) void document.exitFullscreen(); else void wrapRef.current?.requestFullscreen?.().catch(() => undefined); };

  useEffect(() => {
    // Smooth scene change: keep a snapshot of the previous view and fade it out over the new one.
    let fadeId: ReturnType<typeof setTimeout> | undefined;
    if (!first.current && !reducedMotion && canvasRef.current) {
      try { const src = canvasRef.current.toDataURL(); setGhost({ src, on: true }); fadeId = setTimeout(() => setGhost((g) => (g ? { ...g, on: false } : g)), 40); } catch { /* tainted canvas – skip fade */ }
    }
    first.current = false;
    let raf = 0;
    const t0 = performance.now();
    const frame = (t: number) => {
      paint(canvasRef.current, scene, tod, reducedMotion ? 0 : (t - t0) / 1000);
      if (!reducedMotion) raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(raf); if (fadeId) clearTimeout(fadeId); };
  }, [scene, tod, reducedMotion]);

  useEffect(() => {
    const id = setInterval(() => {
      setViewed((v) => v + 1);
      setRemaining((r) => {
        if (r == null) return r;
        if (r <= 1) { setCompleted(true); amb.current.chime(); return null; }
        return r - 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => { onReport({ scene, time_of_day: tod, sound, seconds_viewed: viewed, rest_timer_completed: completed }); }, [scene, tod, sound, viewed, completed, onReport]);

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
      <div ref={wrapRef} className={cx('always-dark relative overflow-hidden border border-line bg-black', full ? 'h-screen w-screen' : 'rounded-2xl')}>
        <canvas ref={canvasRef} className={cx('block w-full', full ? 'h-full' : 'h-[400px]')} role="img" aria-label={scene === 'orbit' ? `Earth seen from orbit, ${tod} terminator` : `Earth window: ${scene} at ${tod}`} />
        {ghost && <img src={ghost.src} alt="" aria-hidden="true" onTransitionEnd={() => setGhost(null)} className="pointer-events-none absolute inset-0 h-full w-full transition-opacity duration-[1200ms] ease-out" style={{ opacity: ghost.on ? 1 : 0 }} />}
        <button type="button" onClick={toggleFull} aria-pressed={full} className="absolute bottom-3 right-3 flex items-center gap-1.5 rounded-lg bg-black/45 px-2.5 py-1.5 text-xs text-[#e3d6bd] backdrop-blur hover:bg-black/60 focus-visible:outline-2 focus-visible:outline-[#9cc9ad]">
          {full ? 'Exit full screen (Esc)' : 'View full screen'}
        </button>
        {remaining != null && <div className="absolute right-3 top-3 rounded-lg bg-black/40 px-2.5 py-1 text-sm text-sand tabular" aria-live="off">{Math.floor(remaining / 60)}:{String(remaining % 60).padStart(2, '0')}</div>}
        {completed && <div className="absolute inset-x-0 bottom-4 mx-auto w-fit rounded-xl bg-black/50 px-4 py-2 text-sand" role="status">Rest period complete. Take your time before continuing.</div>}
      </div>
      <div className="space-y-4">
        <div><div className="eyebrow mb-1.5">Landscape</div><Segmented size="sm" label="Landscape" value={scene} onChange={setScene} options={[{ value: 'orbit', label: 'From orbit' }, { value: 'coast', label: 'Coast' }, { value: 'forest', label: 'Forest' }, { value: 'mountains', label: 'Lake' }, { value: 'aurora', label: 'Aurora' }]} /></div>
        <div><div className="eyebrow mb-1.5">Time of day</div><Segmented size="sm" label="Time of day" value={tod} onChange={setTod} options={[{ value: 'dawn', label: 'Dawn' }, { value: 'day', label: 'Day' }, { value: 'dusk', label: 'Dusk' }, { value: 'night', label: 'Night' }]} /></div>
        <div><div className="eyebrow mb-1.5">Ambient sound</div><Segmented size="sm" label="Ambient sound" value={sound} onChange={setSound} options={[{ value: 'off', label: 'Off' }, { value: 'waves', label: 'Waves' }, { value: 'rain', label: 'Rain' }, { value: 'wind', label: 'Wind' }]} />
          {audioError && <p className="mt-1 text-xs text-high">Audio is not available in this browser.</p>}</div>
        {sound !== 'off' && <SliderField label="Volume" value={Math.round(volume * 100)} min={0} max={100} unit="%" onChange={(v) => setVolume(v / 100)} />}
        <div>
          <SliderField label="Rest timer" value={minutes} min={1} max={15} unit=" min" onChange={setMinutes} />
          <div className="mt-2 flex gap-2">
            <Button size="sm" variant="primary" icon="timer" onClick={() => { setRemaining(minutes * 60); setCompleted(false); }}>Start timer</Button>
            {remaining != null && <Button size="sm" icon="x" onClick={() => setRemaining(null)}>Stop</Button>}
          </div>
        </div>
        <p className="text-xs text-ink-3">Scenes are drawn procedurally; sounds are generated noise, not recordings. Motion is limited to slow drift and stops with “Reduce motion”.</p>
      </div>
    </div>
  );
}

function paint(canvas: HTMLCanvasElement | null, scene: Scene, tod: TimeOfDay, t: number) {
  if (!canvas) return;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return;
  const dpr = Math.min(2, devicePixelRatio || 1);
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
  const ctx = canvas.getContext('2d')!;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  if (scene === 'orbit') { paintOrbit(ctx, w, h, tod, t); return; }
  const night = tod === 'night' || scene === 'aurora';
  const [top, bottom] = scene === 'aurora' ? SKY.night : SKY[tod];
  const sky = ctx.createLinearGradient(0, 0, 0, h * 0.7);
  sky.addColorStop(0, top);
  sky.addColorStop(1, bottom);
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, w, h);
  if (night) for (let i = 0; i < 80; i++) { ctx.fillStyle = `rgba(255,255,255,${0.2 + ((i * 13) % 10) / 20})`; ctx.fillRect(((i * 7919) % 1000) / 1000 * w, ((i * 3571) % 1000) / 1000 * h * 0.5, 1.2, 1.2); }
  if (scene === 'aurora') {
    for (let b = 0; b < 3; b++) {
      ctx.beginPath();
      for (let x = 0; x <= w; x += 8) { const y = h * (0.18 + b * 0.06) + Math.sin(x / 90 + t * 0.15 + b) * 18; if (x) ctx.lineTo(x, y); else ctx.moveTo(x, y); }
      ctx.strokeStyle = `rgba(${b === 1 ? '150,210,190' : '120,200,170'},${0.25 - b * 0.05})`;
      ctx.lineWidth = 26 - b * 6;
      ctx.stroke();
    }
  } else {
    const sunY = tod === 'day' ? h * 0.18 : tod === 'night' ? h * 0.15 : h * 0.48;
    ctx.fillStyle = tod === 'night' ? 'rgba(235,235,220,0.85)' : 'rgba(255,236,200,0.85)';
    ctx.beginPath(); ctx.arc(w * 0.72, sunY, tod === 'night' ? 16 : 26, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = tod === 'night' ? 'rgba(200,210,230,0.08)' : 'rgba(255,255,255,0.25)';
    for (let c = 0; c < 4; c++) {
      const cx = (((c * 0.29 + t * 0.004) % 1.3) - 0.15) * w, cy = h * (0.12 + c * 0.06);
      ctx.beginPath(); ctx.ellipse(cx, cy, 70 + c * 10, 14, 0, 0, Math.PI * 2); ctx.fill();
    }
  }
  const shade = (base: number) => (tod === 'night' || scene === 'aurora' ? base * 0.45 : tod === 'day' ? base : base * 0.75);
  const hill = (y0: number, amp: number, freq: number, color: string, phase = 0) => {
    ctx.beginPath(); ctx.moveTo(0, h);
    for (let x = 0; x <= w; x += 6) ctx.lineTo(x, h * y0 + Math.sin(x / freq + phase) * amp + Math.sin(x / (freq * 0.37)) * amp * 0.3);
    ctx.lineTo(w, h); ctx.closePath(); ctx.fillStyle = color; ctx.fill();
  };
  const rgb = (r: number, g: number, b: number) => `rgb(${shade(r) | 0},${shade(g) | 0},${shade(b) | 0})`;
  if (scene === 'coast') {
    ctx.fillStyle = rgb(60, 110, 140); ctx.fillRect(0, h * 0.55, w, h * 0.45);
    for (let k = 0; k < 6; k++) {
      ctx.beginPath();
      for (let x = 0; x <= w; x += 6) { const y = h * (0.6 + k * 0.06) + Math.sin(x / 40 + t * 0.4 + k) * 2.5; if (x) ctx.lineTo(x, y); else ctx.moveTo(x, y); }
      ctx.strokeStyle = 'rgba(255,255,255,0.12)'; ctx.lineWidth = 1.5; ctx.stroke();
    }
    hill(0.86, 10, 120, rgb(200, 180, 140));
  } else if (scene === 'forest') {
    hill(0.55, 25, 160, rgb(70, 100, 85)); hill(0.65, 18, 110, rgb(50, 80, 65), 1);
    for (let i = 0; i < 40; i++) {
      const x = ((i * 977) % 1000) / 1000 * w, base = h * (0.75 + ((i * 31) % 10) / 50), th = 40 + ((i * 53) % 40);
      ctx.fillStyle = rgb(35, 65, 50); ctx.beginPath(); ctx.moveTo(x, base - th); ctx.lineTo(x - 14, base); ctx.lineTo(x + 14, base); ctx.fill();
    }
    hill(0.92, 6, 90, rgb(40, 60, 45));
  } else {
    ctx.fillStyle = rgb(110, 125, 150);
    ctx.beginPath(); ctx.moveTo(0, h * 0.6); [[0.15, 0.3], [0.3, 0.5], [0.45, 0.22], [0.62, 0.48], [0.8, 0.28], [1, 0.55]].forEach(([x, y]) => ctx.lineTo(x * w, y * h)); ctx.lineTo(w, h * 0.6); ctx.fill();
    ctx.fillStyle = scene === 'aurora' ? rgb(40, 70, 90) : rgb(70, 115, 140); ctx.fillRect(0, h * 0.6, w, h * 0.25);
    hill(0.86, 8, 100, rgb(60, 90, 70));
  }
}

/* ───────────── Earth from orbit (procedural, orthographic globe) ───────────── */

function rand(seed: number) { let x = seed; return () => { x = (x * 1664525 + 1013904223) % 4294967296; return x / 4294967296; }; }
type Spot = { lon: number; lat: number; r: number };
const LAND: Spot[] = (() => {
  const rnd = rand(7);
  const centres = [[-100, 45], [-60, -15], [20, 10], [15, 50], [80, 40], [110, 30], [135, -25], [-45, 72], [30, -20], [100, 62]];
  const out: Spot[] = [];
  for (const [clon, clat] of centres) for (let i = 0; i < 150; i++) {
    const a = rnd() * Math.PI * 2, d = Math.pow(rnd(), 0.7) * 26;
    out.push({ lon: (clon + Math.cos(a) * d * 1.4) * Math.PI / 180, lat: Math.max(-80, Math.min(80, clat + Math.sin(a) * d)) * Math.PI / 180, r: 0.018 + rnd() * 0.03 });
  }
  return out;
})();
const CLOUDS: Spot[] = (() => { const rnd = rand(42); return Array.from({ length: 240 }, () => ({ lon: rnd() * Math.PI * 2, lat: (rnd() - 0.5) * 2.4, r: 0.025 + rnd() * 0.05 })); })();
const STARS = (() => { const rnd = rand(3); return Array.from({ length: 140 }, () => [rnd(), rnd(), rnd()]); })();

function paintOrbit(ctx: CanvasRenderingContext2D, w: number, h: number, tod: TimeOfDay, t: number) {
  ctx.fillStyle = '#02040a'; ctx.fillRect(0, 0, w, h);
  for (const [x, y, b] of STARS) { ctx.fillStyle = `rgba(230,236,245,${0.25 + b * 0.55})`; ctx.fillRect(x * w, y * h, b > 0.85 ? 1.6 : 1, b > 0.85 ? 1.6 : 1); }
  const R = Math.min(w, h) * 0.42, cx = w * 0.5, cy = h * 0.54;
  const rot = t * 0.02;
  // Light direction (screen space): day = front lit, dawn/dusk = side lit terminator, night = mostly dark.
  const L = tod === 'day' ? [0.35, -0.35, 0.87] : tod === 'night' ? [-0.2, -0.1, -0.97] : tod === 'dawn' ? [-0.95, -0.15, 0.25] : [0.95, -0.15, 0.25];
  const atm = ctx.createRadialGradient(cx, cy, R * 0.96, cx, cy, R * 1.18);
  atm.addColorStop(0, 'rgba(110,180,255,0.55)'); atm.addColorStop(0.35, 'rgba(90,160,255,0.18)'); atm.addColorStop(1, 'rgba(90,160,255,0)');
  ctx.fillStyle = atm; ctx.beginPath(); ctx.arc(cx, cy, R * 1.18, 0, Math.PI * 2); ctx.fill();
  const ocean = ctx.createRadialGradient(cx - R * 0.3, cy - R * 0.35, R * 0.1, cx, cy, R);
  ocean.addColorStop(0, '#3f93c8'); ocean.addColorStop(1, '#14406b');
  ctx.fillStyle = ocean; ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();
  ctx.save(); ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.clip();
  const project = (s: Spot, spin: number) => {
    const lon = s.lon + spin, cl = Math.cos(s.lat);
    const x = cl * Math.sin(lon), y = -Math.sin(s.lat) * 0.98, z = cl * Math.cos(lon);
    return { x, y, z };
  };
  for (const s of LAND) {
    const p = project(s, rot); if (p.z <= 0.02) continue;
    const lit = Math.max(0, p.x * L[0] + p.y * L[1] + p.z * L[2]);
    ctx.fillStyle = `rgba(${70 + 45 * lit | 0},${98 + 40 * lit | 0},${62 + 22 * lit | 0},${0.75 + 0.25 * p.z})`;
    ctx.beginPath(); ctx.ellipse(cx + p.x * R, cy + p.y * R, s.r * R * (0.35 + 0.65 * p.z), s.r * R * 0.8, 0, 0, Math.PI * 2); ctx.fill();
    if (lit < 0.05 && (s.r * 1000 | 0) % 3 === 0) { ctx.fillStyle = 'rgba(255,214,140,0.7)'; ctx.fillRect(cx + p.x * R, cy + p.y * R, 1.4, 1.4); }
  }
  ctx.filter = 'blur(1.6px)';
  for (const s of CLOUDS) {
    const p = project(s, rot * 1.35 + 0.8); if (p.z <= 0.02) continue;
    ctx.fillStyle = `rgba(255,255,255,${0.1 + 0.2 * p.z})`;
    ctx.beginPath(); ctx.ellipse(cx + p.x * R, cy + p.y * R, s.r * R * 1.6 * (0.3 + 0.7 * p.z), s.r * R * 0.45, 0.2, 0, Math.PI * 2); ctx.fill();
  }
  ctx.filter = 'none';
  // Night side: a soft terminator perpendicular to the light direction.
  const ln = Math.hypot(L[0], L[1]) || 1, dx = L[0] / ln, dy = L[1] / ln;
  const term = ctx.createLinearGradient(cx + dx * R, cy + dy * R, cx - dx * R, cy - dy * R);
  const k = Math.max(0.05, Math.min(0.9, 0.5 + 0.42 * L[2]));
  term.addColorStop(0, 'rgba(2,4,10,0)'); term.addColorStop(Math.max(0, k - 0.12), 'rgba(2,4,10,0)');
  term.addColorStop(Math.min(1, k + 0.1), 'rgba(2,4,10,0.86)'); term.addColorStop(1, 'rgba(2,4,10,0.92)');
  ctx.fillStyle = term; ctx.fillRect(cx - R, cy - R, R * 2, R * 2);
  const spec = ctx.createRadialGradient(cx + L[0] * R * 0.55, cy + L[1] * R * 0.55, 0, cx + L[0] * R * 0.55, cy + L[1] * R * 0.55, R * 0.5);
  spec.addColorStop(0, `rgba(255,255,255,${L[2] > 0 ? 0.12 : 0})`); spec.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = spec; ctx.fillRect(cx - R, cy - R, R * 2, R * 2);
  ctx.restore();
  ctx.strokeStyle = 'rgba(140,200,255,0.55)'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.stroke();
}
