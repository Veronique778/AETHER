import { useEffect, useRef, useState } from 'react';
import { CAPABILITIES, type BiofeedbackFrame, type SessionDetails } from '../../../api/types';
import { useApp } from '../../../state/AppState';
import { useLiveHeartRate } from '../../biosignals/useLiveHeartRate';
import { Button, cx, Icon, PendingBackend, Pill, Segmented, SliderField, SourceBadge } from '../../../ui';
import { CoherenceMeter, pacerPhase, type Pace } from '../logic/breathing';

type PlantType = 'fern' | 'flower' | 'moss';
type Plant = { id: number; type: PlantType; x: number; growth: number; lean: number };
type Source = 'pacer' | 'service';
const MAX_PLANTS = 12;
const HUE: Record<PlantType, number> = { fern: 140, flower: 155, moss: 120 };
const START: Plant[] = [0.15, 0.32, 0.5, 0.68, 0.85].map((x, i) => ({ id: i + 1, type: (['fern', 'flower', 'moss'] as const)[i % 3], x, growth: 0.18, lean: ((i * 37) % 7) / 7 - 0.5 }));

/**
 * Zero-G Garden. Biofeedback input is pluggable:
 *  - "pacer": the user's own key/press follows a breathing pacer (behavioural, runs locally);
 *  - "service": frames from the Human Systems biofeedback API (GET /api/recovery/biofeedback).
 * The garden only *displays* a coherence value in [0,1]; it does not compute physiology.
 */
export function ZeroGGarden({ reducedMotion, onReport }: { reducedMotion: boolean; onReport: (d: SessionDetails) => void }) {
  const { api, astronautId, hasCapability } = useApp();
  const liveHeart = useLiveHeartRate();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [pace, setPace] = useState<Pace>({ breathsPerMin: 6, inhaleShare: 0.4 });
  const [source, setSource] = useState<Source>('pacer');
  const [mode, setMode] = useState<'breathe' | 'arrange'>('breathe');
  const [running, setRunning] = useState(false);
  const [plants, setPlants] = useState<Plant[]>(START);
  const [selected, setSelected] = useState<number | null>(null);
  const [newType, setNewType] = useState<PlantType>('flower');
  const [frame, setFrame] = useState<BiofeedbackFrame | null>(null);
  const [frameError, setFrameError] = useState<string | null>(null);
  const [view, setView] = useState({ inhale: true, progress: 0, coherence: 0, overall: 0, elapsed: 0 });
  const holding = useRef(false);
  const plantsRef = useRef(plants);
  const meter = useRef(new CoherenceMeter());
  const serviceCoh = useRef<number[]>([]);
  const elapsed = useRef(0);
  const serviceAvailable = hasCapability(CAPABILITIES.biofeedback);
  plantsRef.current = plants;

  useEffect(() => {
    const down = (e: KeyboardEvent) => { if (e.code === 'Space' && running && source === 'pacer' && mode === 'breathe') { e.preventDefault(); holding.current = true; } };
    const up = (e: KeyboardEvent) => { if (e.code === 'Space') holding.current = false; };
    addEventListener('keydown', down);
    addEventListener('keyup', up);
    return () => { removeEventListener('keydown', down); removeEventListener('keyup', up); };
  }, [running, source, mode]);

  // Biofeedback service polling (only while running with the service source).
  useEffect(() => {
    if (!running || source !== 'service' || !serviceAvailable) return;
    let alive = true;
    const poll = () => api.biofeedback(astronautId).then((f) => { if (alive) { setFrame(f); setFrameError(null); if (f.coherence_0_1 != null) serviceCoh.current.push(f.coherence_0_1); } }, (e: Error) => alive && setFrameError(e.message));
    poll();
    const id = setInterval(poll, 2000);
    return () => { alive = false; clearInterval(id); };
  }, [running, source, serviceAvailable, api, astronautId]);

  useEffect(() => { draw(canvasRef.current, plantsRef.current, 0, reducedMotion, view.inhale, view.progress, selected); });

  useEffect(() => {
    if (!running) return;
    let raf = 0;
    let last = performance.now();
    let uiTick = 0;
    const loop = (t: number) => {
      const dt = Math.min(0.1, (t - last) / 1000);
      last = t;
      elapsed.current += dt;
      const cycle = 60 / pace.breathsPerMin;
      const ph = pacerPhase(elapsed.current, pace);
      let coh = 0;
      if (source === 'pacer') { meter.current.sample(holding.current, ph, cycle, pace.inhaleShare); coh = meter.current.current; }
      else coh = frameRef.current?.coherence_0_1 ?? 0;
      const grown = plantsRef.current.map((p) => ({ ...p, growth: Math.min(1, p.growth + dt * 0.02 * coh * (p.type === 'moss' ? 1.3 : 1)) }));
      plantsRef.current = grown;
      draw(canvasRef.current, grown, elapsed.current, reducedMotion, ph.inhale, ph.progress, selected);
      uiTick += dt;
      if (uiTick > 0.25) {
        uiTick = 0;
        setPlants(grown);
        const overall = source === 'pacer' ? meter.current.overall : mean(serviceCoh.current);
        setView({ inhale: ph.inhale, progress: ph.progress, coherence: coh, overall, elapsed: elapsed.current });
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [running, pace, reducedMotion, source, selected]);

  const frameRef = useRef<BiofeedbackFrame | null>(null);
  frameRef.current = frame;

  useEffect(() => {
    const growth = plants.reduce((s, p) => s + p.growth, 0) / Math.max(1, plants.length);
    onReport({ biofeedback_source: source === 'pacer' ? 'paced-breathing input' : `biofeedback service (${frame?.source ?? 'n/a'})`, coherence_pct: Math.round(view.overall * 100),
      breaths_per_min: pace.breathsPerMin, active_seconds: Math.round(elapsed.current), plants: plants.length, garden_growth_pct: Math.round(growth * 100) });
  }, [view.elapsed, view.overall, pace.breathsPerMin, plants, source, frame, onReport]);

  const hold = (v: boolean) => { if (running && source === 'pacer' && mode === 'breathe') holding.current = v; };
  const addPlant = (x?: number) => {
    if (plants.length >= MAX_PLANTS) return;
    const free = x ?? ([0.08, 0.24, 0.41, 0.59, 0.76, 0.92, 0.16, 0.33, 0.5, 0.67, 0.84, 0.03].find((c) => plants.every((p) => Math.abs(p.x - c) > 0.05)) ?? Math.random());
    const id = Math.max(0, ...plants.map((p) => p.id)) + 1;
    setPlants([...plants, { id, type: newType, x: Math.min(0.97, Math.max(0.03, free)), growth: 0.08, lean: (Math.random() - 0.5) * 0.8 }]);
    setSelected(id);
  };
  const move = (dx: number) => setPlants(plants.map((p) => (p.id === selected ? { ...p, x: Math.min(0.97, Math.max(0.03, p.x + dx)) } : p)));
  const sel = plants.find((p) => p.id === selected);

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
      <div>
        <div className="always-dark relative overflow-hidden rounded-2xl border border-line">
          <canvas ref={canvasRef} className={cx('block h-[340px] w-full touch-none select-none', mode === 'arrange' && 'cursor-copy')}
            aria-label={`Zero-G garden with ${plants.length} plants. ${mode === 'arrange' ? 'Click to plant or select.' : 'Plants grow while breathing follows the pacer.'}`}
            onPointerDown={(e) => {
              if (mode === 'arrange') {
                const r = e.currentTarget.getBoundingClientRect();
                const x = (e.clientX - r.left) / r.width;
                const near = plants.find((p) => Math.abs(p.x - x) < 0.035);
                if (near) setSelected(near.id); else addPlant(x);
              } else hold(true);
            }}
            onPointerUp={() => hold(false)} onPointerLeave={() => hold(false)} />
          <div className="pointer-events-none absolute left-4 top-4 rounded-xl bg-[#16211c]/85 px-3 py-2 text-sm" aria-live="polite">
            <div className="text-lg font-semibold text-[#e3d6bd]">{!running ? 'Ready' : source === 'service' ? 'Breathe at your own pace' : view.inhale ? 'Breathe in' : 'Breathe out'}</div>
            {source === 'pacer' && <div className="mt-1 h-1.5 w-40 overflow-hidden rounded-full bg-[#27392f]"><div className="h-full bg-[#a9c5b2]" style={{ width: `${(running ? view.progress : 0) * 100}%` }} /></div>}
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button variant="primary" icon={running ? 'pause' : 'play'} onClick={() => setRunning(!running)}>{running ? 'Pause' : view.elapsed ? 'Resume' : 'Start'}</Button>
          <Segmented label="Garden interaction" value={mode} onChange={setMode} options={[{ value: 'breathe', label: 'Breathe', icon: 'wind' }, { value: 'arrange', label: 'Arrange garden', icon: 'leaf' }]} />
          {mode === 'breathe' && source === 'pacer' && (
            <>
              <Button disabled={!running} onPointerDown={() => hold(true)} onPointerUp={() => hold(false)} onPointerLeave={() => hold(false)} aria-label="Hold while breathing in">Hold while inhaling</Button>
              <span className="text-sm text-ink-3">or hold <kbd className="rounded border border-line-strong px-1">Space</kbd> / press on the garden.</span>
            </>
          )}
        </div>
        {mode === 'arrange' && (
          <div className="mt-3 rounded-xl border border-line p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Segmented size="sm" label="New plant type" value={newType} onChange={setNewType} options={[{ value: 'flower', label: 'Flower' }, { value: 'fern', label: 'Fern' }, { value: 'moss', label: 'Moss' }]} />
              <Button size="sm" icon="plus" disabled={plants.length >= MAX_PLANTS} onClick={() => addPlant()}>Plant ({plants.length}/{MAX_PLANTS})</Button>
              <span className="text-xs text-ink-3">Click the garden to plant, or click a plant to select it.</span>
            </div>
            <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="Plants">
              {plants.map((p, i) => (
                <li key={p.id}><button type="button" aria-pressed={p.id === selected} onClick={() => setSelected(p.id)}
                  className={cx('min-h-8 rounded-lg border px-2 text-xs', p.id === selected ? 'border-teal-300 bg-teal-600/20 text-ink' : 'border-line text-ink-2')}>{i + 1}. {p.type} · {Math.round(p.growth * 100)}%</button></li>
              ))}
            </ul>
            {sel && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Button size="sm" icon="chevronLeft" onClick={() => move(-0.04)}>Move left</Button>
                <Button size="sm" iconRight="chevronRight" onClick={() => move(0.04)}>Move right</Button>
                <Button size="sm" variant="danger" icon="x" onClick={() => { setPlants(plants.filter((p) => p.id !== sel.id)); setSelected(null); }}>Remove</Button>
              </div>
            )}
          </div>
        )}
      </div>
      <div className="space-y-4">
        <div>
          <div className="eyebrow mb-1.5">Biofeedback input</div>
          <Segmented size="sm" label="Biofeedback input" value={source} onChange={setSource} options={[{ value: 'pacer', label: 'My breathing input' }, { value: 'service', label: 'Simulated biofeedback' }]} />
          <p className="mt-1 text-[11px] text-ink-3" data-testid="sensor-status" data-aether-live-rendered="true">Live sensor: <strong className="text-ink-2">{liveHeart.label}</strong>. Standard Bluetooth HRS is available in BIOSIGNALS; sensor HR is displayed only and does not control this garden's coherence score.</p>
        </div>
        {source === 'pacer' ? (
          <>
            <SliderField label="Pace" value={pace.breathsPerMin} min={4} max={8} step={0.5} unit=" breaths/min" onChange={(v) => setPace({ ...pace, breathsPerMin: v })} hint={`${(60 / pace.breathsPerMin).toFixed(1)} s per breath`} />
            <SliderField label="Inhale share" value={Math.round(pace.inhaleShare * 100)} min={30} max={50} step={5} unit="%" onChange={(v) => setPace({ ...pace, inhaleShare: v / 100 })} />
            <p className="text-xs text-ink-3">Pacing match = how closely your input follows the pacer. Behavioural feedback only – no physiological measurement.</p>
          </>
        ) : !serviceAvailable ? (
          <PendingBackend contract="GET /api/recovery/biofeedback" owner="Human Systems" />
        ) : (
          <div className="space-y-2 rounded-xl border border-line p-3 text-sm">
            <div className="flex items-center justify-between"><span className="text-ink-2">Latest frame</span>{frame && <SourceBadge source={frame.source} />}</div>
            {frame?.source === 'simulated' && <p className="rounded border border-attention/45 bg-attention/10 px-2 py-1 text-xs text-attention" role="note">SIMULATED signal generated by the backend – not a measurement from a sensor or from you.</p>}
            {frameError ? <p className="text-high">{frameError}</p> : !frame ? <p className="text-ink-3">{running ? 'Waiting for first frame…' : 'Start to receive frames every 2 s.'}</p> : (
              <dl className="tabular grid grid-cols-2 gap-x-2 gap-y-1 text-ink-2">
                <dt>Coherence</dt><dd className="text-ink">{frame.coherence_0_1 == null ? '—' : Math.round(frame.coherence_0_1 * 100) + '%'}</dd>
                <dt>Breathing</dt><dd className="text-ink">{frame.breathing_rate_bpm ?? '—'} /min</dd>
                <dt>Heart rate</dt><dd className="text-ink">{frame.heart_rate_bpm ?? '—'} bpm</dd>
                <dt>Signal</dt><dd><Pill tone={frame.quality === 'good' ? 'good' : 'attention'}>{frame.quality}</Pill></dd>
              </dl>
            )}
          </div>
        )}
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded-xl border border-line p-2"><div className="text-xs text-ink-3">{source === 'pacer' ? 'Pacing match (recent)' : 'Coherence (service)'}</div><div className="tabular text-xl font-semibold text-calm">{Math.round(view.coherence * 100)}%</div></div>
          <div className="rounded-xl border border-line p-2"><div className="text-xs text-ink-3">Session</div><div className="tabular text-xl font-semibold text-calm">{Math.floor(view.elapsed / 60)}:{String(Math.floor(view.elapsed % 60)).padStart(2, '0')}</div></div>
        </div>
        <p className="flex items-start gap-1.5 text-xs text-ink-3"><Icon name="info" size={13} className="mt-0.5 shrink-0" />Growth speed = coherence value received. The personalisation and signal processing belong to the Human Systems service.</p>
      </div>
    </div>
  );
}

const mean = (v: number[]) => (v.length ? v.reduce((s, x) => s + x, 0) / v.length : 0);

function draw(canvas: HTMLCanvasElement | null, plants: Plant[], t: number, reduced: boolean, inhale: boolean, progress: number, selected: number | null) {
  if (!canvas) return;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return;
  const dpr = Math.min(2, devicePixelRatio || 1);
  if (canvas.width !== w * dpr) { canvas.width = w * dpr; canvas.height = h * dpr; }
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, '#1d2b24');
  g.addColorStop(1, '#27392f');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
  const breath = reduced ? 0.5 : inhale ? progress : 1 - progress;
  ctx.beginPath();
  ctx.arc(w * 0.85, h * 0.26, 22 + breath * 26, 0, Math.PI * 2);
  ctx.fillStyle = 'rgba(227,214,189,0.10)';
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = 'rgba(227,214,189,0.45)';
  ctx.stroke();
  ctx.fillStyle = '#16211c';
  ctx.fillRect(0, h - 34, w, 34);
  ctx.fillStyle = '#3a2e22';
  ctx.fillRect(0, h - 34, w, 6);
  for (const p of plants) {
    const baseX = p.x * w, baseY = h - 34;
    const height = 26 + p.growth * (h - 120) * (p.type === 'moss' ? 0.35 : p.type === 'fern' ? 0.8 : 1);
    const sway = reduced ? 0 : Math.sin(t * 0.6 + p.x * 9) * 6 * p.growth;
    const tipX = baseX + p.lean * 30 * p.growth + sway, tipY = baseY - height;
    const hue = HUE[p.type];
    if (p.id === selected) { ctx.strokeStyle = 'rgba(95,184,192,0.9)'; ctx.lineWidth = 2; ctx.setLineDash([4, 3]); ctx.strokeRect(baseX - 22, tipY - 14, 44, baseY - tipY + 14); ctx.setLineDash([]); }
    if (p.type === 'moss') {
      ctx.fillStyle = `hsl(${hue} 30% 45%)`;
      for (let k = 0; k < 6; k++) { ctx.beginPath(); ctx.arc(baseX + (k - 2.5) * 6, baseY - 4 - (k % 2) * height * 0.4, 6 + p.growth * 6, 0, Math.PI * 2); ctx.fill(); }
      continue;
    }
    ctx.strokeStyle = `hsl(${hue} 30% 55%)`;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(baseX, baseY);
    ctx.quadraticCurveTo(baseX + p.lean * 10, baseY - height * 0.5, tipX, tipY);
    ctx.stroke();
    const leaves = p.type === 'fern' ? 7 : 4;
    const count = Math.round(leaves * Math.min(1, p.growth * 1.4));
    for (let i = 1; i <= count; i++) {
      const k = i / (leaves + 1);
      const lx = baseX + (tipX - baseX) * k, ly = baseY - height * k;
      const side = i % 2 ? 1 : -1;
      ctx.fillStyle = `hsl(${hue} 32% ${48 + i * 2}%)`;
      ctx.beginPath();
      ctx.ellipse(lx + side * 9, ly, (p.type === 'fern' ? 13 : 11) * Math.min(1, p.growth + 0.3), p.type === 'fern' ? 3 : 4.5, side * 0.5, 0, Math.PI * 2);
      ctx.fill();
    }
    if (p.type === 'flower' && p.growth > 0.7) {
      const bloom = (p.growth - 0.7) / 0.3;
      ctx.fillStyle = `rgba(199,182,217,${0.4 + bloom * 0.6})`;
      for (let k = 0; k < 5; k++) { const a = (k / 5) * Math.PI * 2; ctx.beginPath(); ctx.arc(tipX + Math.cos(a) * 6 * bloom, tipY + Math.sin(a) * 6 * bloom, 4 * bloom + 1, 0, Math.PI * 2); ctx.fill(); }
      ctx.fillStyle = '#e3d6bd';
      ctx.beginPath(); ctx.arc(tipX, tipY, 3, 0, Math.PI * 2); ctx.fill();
    }
  }
}
