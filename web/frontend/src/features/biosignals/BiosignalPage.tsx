import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { navigate } from '../../lib/router';
import { useHumanModel, readBodyModel } from '../../scene3d/useHumanModel';
import type { Highlight } from '../../scene3d/engine';
import { Viewport } from '../../scene3d/Viewport';
import { HUMAN_ASSETS, type HumanAssetId } from '../../scene3d/humanAssets';
import { Button, Notice } from '../../ui';
import { useAuth } from '../../state/AuthState';
import { useApp } from '../../state/AppState';

/** Legacy local-demo routes. In the AETHER 1.5 release they are isolated on the server (401 without a personal
 * Bearer, 410 legacy_isolated with one) — that was the root cause of the old "Biosignal request failed" message. */
export class LegacyBiosignalError extends Error {
  constructor(message: string, readonly status: number, readonly code: string) { super(message); }
  get isolated() { return this.code === 'legacy_isolated' || this.code === 'unauthenticated' || this.status === 410; }
}

// Always use the desktop's own origin; never send recordings to configured remote APIs.
export async function bioApi<T = any>(path: string, body?: unknown, method?: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch('/api/biosignals' + path, {
      method: method ?? (body === undefined ? 'GET' : 'POST'),
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new LegacyBiosignalError('The local AETHER backend could not be reached (code: network_error).', 0, 'network_error');
  }
  let result: any = null;
  try { result = await response.json(); } catch { result = null; }
  if (!response.ok) {
    const code: string = (result && typeof result.error?.code === 'string' && result.error.code) || (response.status === 401 ? 'unauthenticated' : `http_${response.status}`);
    const isolated = code === 'legacy_isolated' || code === 'unauthenticated' || response.status === 410;
    const text = isolated
      ? `This local demo/research function is isolated from personal accounts in the AETHER 1.5 release (code: ${code}). For Bluetooth recording use Live Mode → BIOSIGNALS after signing in; for a synthetic rehearsal use PHANTOM → SYNTHETIC control.`
      : typeof result?.detail === 'string' ? `${result.detail} (code: ${code})` : `Biosignal request failed (code: ${code}).`;
    throw new LegacyBiosignalError(text, response.status, code);
  }
  return result;
}
type Source = 'synthetic' | 'research' | 'live_sensor' | 'simulated_demo' | 'personal';
const SOURCES: readonly Source[] = ['synthetic', 'research', 'live_sensor', 'simulated_demo', 'personal'];
type StoredSelection = { source: Source; sessionId: string };
function readSelection(): StoredSelection | null {
  try {
    const value: unknown = JSON.parse(localStorage.getItem('aether.biosignal.selection') || 'null');
    if (value === null || typeof value !== 'object') return null;
    const candidate = value as { source?: unknown; sessionId?: unknown };
    return SOURCES.includes(candidate.source as Source) && typeof candidate.sessionId === 'string'
      ? { source: candidate.source as Source, sessionId: candidate.sessionId }
      : null;
  } catch {
    return null;
  }
}
/** Four provenance classes shown everywhere a number appears (AETHER 1.4). */
export const DATA_CLASS: Record<string, { label: string; tone: string }> = {
  research: { label: 'Real terrestrial research recording', tone: 'border-line' },
  live_sensor: { label: 'Real terrestrial wearable measurement', tone: 'border-good' },
  simulated_demo: { label: 'SIMULATED · DEMO MODE', tone: 'border-attention' },
  synthetic: { label: 'Synthetic mission simulation', tone: 'border-line' },
  personal: { label: 'Authenticated personal account data', tone: 'border-good' },
};
type Connector = { id: string; name: string; status: string; data_class: string; access: string; limitations: string; runtime_ready?: boolean; runtime_note?: string };
type Selection = { source: Source; sessionId: string; choose: (source: Source, id?: string) => void };
const Context = createContext<Selection>({ source: 'synthetic', sessionId: '', choose: () => undefined });
export function BiosignalProvider({ children }: { children: ReactNode }) {
  const [selection, setSelection] = useState(readSelection);
  const choose = (source: Source, sessionId = '') => {
    setSelection({ source, sessionId });
    localStorage.setItem('aether.biosignal.selection', JSON.stringify({ source, sessionId }));
  };
  return <Context.Provider value={{ source: selection?.source ?? 'synthetic', sessionId: selection?.sessionId ?? '', choose }}>{children}</Context.Provider>;
}
export const useBiosignal = () => useContext(Context);

/** Live Mode: Live Sensors recordings ARE personal-account data, so BODY/PHANTOM show the personal views for them. */
export function usePersonalView(): boolean {
  const { source } = useBiosignal();
  const { mode } = useApp();
  return source === 'personal' || (mode === 'live' && source === 'live_sensor');
}

export function SourceControl() {
  const { source, choose } = useBiosignal();
  const { status } = useAuth();
  const { mode } = useApp();
  return <div className="mx-4 mb-3 rounded-xl border border-line bg-surface p-3 text-sm lg:mx-8">
    <div className="flex flex-wrap items-center gap-3"><strong>Data origin</strong>
      <select aria-label="Data origin" className="field w-full min-w-0 sm:w-auto" value={source} onChange={e => {
        const selected = e.target.value as Source;
        if ((selected === 'personal' || (mode === 'live' && selected === 'live_sensor')) && status !== 'signed-in') { navigate('/login'); return; }
        choose(selected);
        if (selected === 'personal') navigate('/body');
        else if (selected !== 'synthetic') navigate('/biosignals');
      }}>
        <option value="synthetic">Synthetic Mission Demo · A01–A04</option><option value="research">Research Data · recorded humans</option><option value="live_sensor">Live Sensors · Bluetooth HRS</option><option value="simulated_demo">DEMO MODE · simulated recording</option>
        <option value="personal" disabled={status !== 'signed-in'}>Personal Monitoring · authenticated account</option>
      </select>
      <Button onClick={() => navigate('/biosignals')}>Recordings & sensors</Button>
    </div>
    {source === 'simulated_demo' && <p className="mt-2 text-xs font-semibold text-attention">DEMO MODE: BODY and PHANTOM show a SIMULATED recording.</p>}
    {source === 'personal' && <p className="mt-2 text-xs font-semibold text-good">{status === 'signed-in' ? 'PERSONAL MONITORING: BODY shows your stored measurements; PHANTOM runs personal analysis and saved history; BIOSIGNALS records from a Bluetooth HRS sensor.' : 'PERSONAL MONITORING is selected. Sign in to view account data.'}</p>}
    {mode === 'live' && source === 'live_sensor' && <p className="mt-2 text-xs font-semibold text-good">{status === 'signed-in' ? 'LIVE SENSORS: Bluetooth HRS recordings are stored in your personal account; BODY and PHANTOM show your personal records.' : 'LIVE SENSORS require sign-in; recordings are stored in your personal account.'}</p>}
    {source !== 'synthetic' && source !== 'personal' && !(mode === 'live' && source === 'live_sensor') && <p className="mt-2 text-xs text-ink-3">BODY and PHANTOM use the selected recording. Mission Control, SYMBIOSIS, CO-ORBIT and MISSION LAB retain separately labelled synthetic mission context. No exposure or astronaut identity is assigned to this recording.</p>}
  </div>;
}
function save(text: string, filename: string, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([text], { type })); const a = document.createElement('a'); a.href = url; a.download = filename; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
type Channel = { signal: string; unit: string; total: number; valid: number; missing: number; start: number | null; end: number | null };
type Session = { id: string; source_type: Source; participant: string; source: string; status: string; metadata: Record<string, any>; channels: Channel[] };
type Point = { t: number; low: number; high: number; samples: number; valid: number };
type Window = { start: number; end: number; mean_hr_bpm: number | null; outcome: string; score: number | null; hrv: any };
type Analysis = { windows: Window[]; outcome: string; method: string; threshold: number; available_channels: string[]; missing_channels: string[]; explanation: string; uncertainty: string; baseline_period: (number | null)[]; baseline_hr_bpm: number | null; flag_rate: number | null; [key: string]: unknown };

export function BiosignalPage() {
  const { source, choose, sessionId } = useBiosignal();
  const [path, setPath] = useState(''); const [subjects, setSubjects] = useState<string[]>([]); const [subject, setSubject] = useState('');
  const [confirmed, setConfirmed] = useState(false); const [sessions, setSessions] = useState<any[]>([]); const [busy, setBusy] = useState(''); const [error, setError] = useState('');
  const [devices, setDevices] = useState<any[]>([]); const [sensor, setSensor] = useState<any>(null);
  const [connectors, setConnectors] = useState<Connector[]>([]); const [demoConfirmed, setDemoConfirmed] = useState(false);
  useEffect(() => { fetch('/api/connectors', { cache: 'no-store' }).then(r => r.ok ? r.json() : null).then(d => d && setConnectors(d.connectors)).catch(() => undefined); }, []);
  const { setMode } = useApp();
  const [isolated, setIsolated] = useState(false);
  const refresh = async () => { if (isolated) return; setSessions(await bioApi('/sessions')); setSensor(await bioApi('/sensor/status')); };
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | undefined;
    const fail = (e: unknown) => { if (e instanceof LegacyBiosignalError && e.isolated) { setIsolated(true); if (timer) clearInterval(timer); } else setError((e as Error).message); };
    refresh().then(() => { timer = setInterval(() => refresh().catch(fail), 3000); }).catch(fail);
    return () => { if (timer) clearInterval(timer); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const action = async (label: string, fn: () => Promise<void>) => { setBusy(label); setError(''); try { await fn(); await refresh(); } catch (e) { setError((e as Error).message); } finally { setBusy(''); } };
  const picker = async (folder: boolean) => {
    const host = (window as any).pywebview?.api;
    if (!host) { setError('Native picker is available in the Python desktop window. Enter a local path in this environment.'); return; }
    try { const value = await host.choose_mmash(folder); if (value) { setPath(value); setSubjects([]); setConfirmed(false); } } catch (e) { setError('Native file picker failed: ' + (e as Error).message + '. Enter the local path instead.'); }
  };
  return <div className="space-y-5">
    <h1 className="text-2xl font-semibold">Real Biosignal Intelligence</h1>
    <p className="text-ink-2">Local recordings · source attribution · exploratory analysis · no medical diagnosis</p>
    {source === 'personal' && <Notice tone="unknown" title="Personal Monitoring is separate from local recordings">
      This page manages local research and sensor sessions only. Account measurements are available in BODY; local recordings are not mixed with personal account records.
      <Button className="mt-3" onClick={() => navigate('/body')}>Open Personal BODY history</Button>
    </Notice>}
    {isolated && <Notice tone="unknown" title="DEMO MODE · local legacy recordings are isolated in this release">
      The AETHER 1.5 server keeps the old unauthenticated local-recording and sensor routes isolated from personal accounts, so they are not available here. Physical Bluetooth recording is a personal feature: switch to Live Mode, sign in, and open BIOSIGNALS.
      <div className="mt-3 flex flex-wrap gap-2"><Button variant="primary" onClick={() => { setMode('live'); choose('live_sensor'); navigate('/biosignals'); }}>Open Live Sensors (sign-in)</Button></div>
    </Notice>}
    {error && <div role="alert" className="card border-attention p-4">{error}</div>}
    {busy && <div role="status" className="card p-4"><progress aria-label="Operation in progress" /> {busy} — processing locally; please wait.</div>}
    <section className="card space-y-3 p-5" aria-label="MMASH import">
      <h2 className="text-lg font-semibold">Research Data · Import MMASH</h2>
      <p className="text-sm text-ink-3">Select a downloaded MMASH 1.0.0 folder or ZIP. Original relative recording days are preserved; unknown dates and time zones remain unavailable.</p>
      <div className="flex flex-wrap gap-2"><Button disabled={!!busy} onClick={() => void picker(false)}>Choose ZIP</Button><Button disabled={!!busy} onClick={() => void picker(true)}>Choose folder</Button></div>
      <label className="block">Local MMASH path<input aria-label="Local MMASH path" className="field mt-1 w-full" value={path} onChange={e => { setPath(e.target.value); setSubjects([]); setConfirmed(false); }} placeholder="C:\Datasets\MMASH.zip" /></label>
      <Button disabled={!path || !!busy} onClick={() => void action('Inspecting MMASH', async () => { const r = await bioApi('/mmash/inspect', { path }); setSubjects(r.participants); setSubject(r.participants[0] ?? ''); if (!r.participants.length) throw new Error('No published MMASH participant folders with RR.csv found'); })}>Inspect participants</Button>
      {!!subjects.length && <><label className="block">Participant<select aria-label="MMASH participant" className="field ml-3 w-auto" value={subject} onChange={e => setSubject(e.target.value)}>{subjects.map(s => <option key={s}>{s}</option>)}</select></label>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />I confirm importing these recordings locally and will retain MMASH attribution and comply with its usage terms.</label>
        <Button variant="primary" disabled={!confirmed || !!busy} onClick={() => void action('Importing measurements into SQLite', async () => { const r = await bioApi('/mmash/import', { path, participant: subject, confirmed }); choose('research', r.id); })}>Import selected participant</Button></>}
      <p className="text-xs text-ink-3">Rossi et al. (2020), DOI 10.13026/cerq-fc86 · ODC Attribution 1.0. Recordings stay local. 128 MiB/file; 768 MiB/archive; 2 million records/session. WESAD ingestion is deferred in this release; unsafe pickle files are never loaded.</p>
    </section>
    {!isolated && <section className="card space-y-3 p-5" aria-label="Bluetooth sensors">
      <h2 className="text-lg font-semibold">Live Sensors · Bluetooth Heart Rate Service</h2>
      <p role="status">{sensor?.status ?? 'Sensor disconnected — no live measurements.'}</p>
      <p className="text-sm text-ink-2" data-testid="ble-live">Heart rate: {sensor?.heart_rate ?? '—'} bpm · quality: {sensor?.quality ?? 'unavailable'} · connection: {sensor?.connection ?? 'unknown'} · duration: {sensor?.duration_seconds ?? 0}s · last sample: {sensor?.last_sample_utc ?? 'none'} · reconnects: {sensor?.reconnects ?? 0} · gaps stored as missing: {sensor?.gaps ?? 0} · corrupt packets: {sensor?.corrupt_packets ?? 0}</p>
      {sensor?.error && <p className="text-attention">{sensor.error}</p>}
      <p className="text-xs text-ink-3">BLE Heart Rate Service (0x180D) is verified before live recording. Some compatible monitors do not advertise it; use Scan all nearby if needed. Apple Watch and vendor-specific features are not universally supported. Physical hardware testing remains unverified. If the optional library is missing, run ENABLE_BLE.bat with standard Python 3.13, then restart AETHER.</p>
      <div className="flex flex-wrap gap-2"><Button disabled={!!busy || sensor?.connection === 'connected'} onClick={() => void action('Scanning HRS monitors', async () => { const d = await bioApi('/sensor/scan', { include_unadvertised: false }); setDevices(d); if (!d.length) setError('No HRS-advertising monitors found. You can scan all named devices; compatibility will be checked upon connection.'); })}>Scan HRS monitors</Button>
        <Button disabled={!!busy || sensor?.connection === 'connected'} onClick={() => void action('Scanning named Bluetooth devices', async () => { const d = await bioApi('/sensor/scan', { include_unadvertised: true }); setDevices(d); if (!d.length) setError('No named nearby BLE devices found. Enable Bluetooth and HR broadcast on a compatible device.'); })}>Scan all nearby (verify HRS)</Button>
        <Button disabled={!!busy || sensor?.connection !== 'connected'} onClick={() => void action('Saving and disconnecting', async () => { await bioApi('/sensor/disconnect', {}); })}>Stop, save & disconnect</Button></div>
      {devices.map(d => <div key={d.id} className="flex items-center gap-3"><span>{d.name} · {d.profile}</span><Button disabled={!!busy || sensor?.connection === 'connected'} onClick={() => void action('Connecting sensor', async () => { const r = await bioApi('/sensor/connect', { device_id: d.id }); if (r.connection !== 'connected') throw new Error(r.error); choose('live_sensor', r.session_id); })}>Connect / reconnect</Button></div>)}
    </section>}
    <section className="card space-y-3 p-5" aria-label="DEMO MODE">
      <h2 className="text-lg font-semibold">DEMO MODE · simulated recording</h2>
      <p className="text-sm text-ink-2">For presentations without hardware. Generates a deterministic <strong>simulated</strong> 90-minute heart-rate/RR recording (60-minute resting baseline, then a sustained step and a 3-minute dropout). It is labelled SIMULATED in every view and stored separately from real recordings.</p>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={demoConfirmed} onChange={e => setDemoConfirmed(e.target.checked)} />I understand this recording is simulated and is not a measurement of any person.</label>
      <Button disabled={!demoConfirmed || !!busy} onClick={() => void action('Generating simulated DEMO recording', async () => { const r = await bioApi('/demo/recording', { confirm_simulated: true }); choose('simulated_demo', r.id); })}>Create simulated DEMO recording</Button>
    </section>
    <section className="card space-y-3 p-5" aria-label="Data connectors">
      <h2 className="text-lg font-semibold">Data connectors · honest support status</h2>
      <table className="w-full text-left text-sm"><thead><tr><th>Connector</th><th>Status</th><th>Data class</th><th>Access route / limitation</th></tr></thead>
        <tbody>{connectors.map(c => <tr key={c.id} data-connector={c.id}><td className="pr-2 align-top">{c.name}</td><td className="pr-2 align-top"><span className={c.status === 'unsupported' ? 'text-attention' : ''}>{c.status.replace(/_/g, ' ')}</span>{c.runtime_note ? <div className="text-xs text-ink-3">{c.runtime_note}</div> : null}</td><td className="pr-2 align-top">{c.data_class.replace(/_/g, ' ')}</td><td className="align-top text-xs text-ink-3">{c.access} {c.limitations}</td></tr>)}</tbody></table>
      {!connectors.length && <p className="text-xs text-ink-3">Connector registry unavailable on this backend.</p>}
      <p className="text-xs text-ink-3">“automated tested” = verified with a deterministic mock transport or fixtures. No connector has been verified on physical hardware for this release.</p>
    </section>
    <section className="card space-y-3 p-5"><h2 className="text-lg font-semibold">Local session history</h2>
      <select aria-label="Local session" className="field w-full" value={sessionId} onChange={e => { const s = sessions.find(x => x.id === e.target.value); choose(s?.source_type ?? 'research', e.target.value); }}><option value="">Select a recording</option>{sessions.map(s => <option key={s.id} value={s.id}>{s.participant} · {DATA_CLASS[s.source_type]?.label ?? s.source_type} · {s.status} · {s.created_utc}</option>)}</select>
      <div className="flex gap-2"><Button disabled={!sessionId} onClick={() => navigate('/body')}>Open in BODY</Button><Button disabled={!sessionId} onClick={() => navigate('/phantom')}>Open in PHANTOM</Button><Button onClick={() => { choose('synthetic'); navigate('/mission-lab'); }}>Open synthetic Mission Lab</Button></div>
    </section>
    {sessionId && source !== 'synthetic' && <RecordingView key={sessionId} />}
  </div>;
}

export function RecordingView({ body = false }: { body?: boolean }) {
  const { sessionId, choose } = useBiosignal();
  const [session, setSession] = useState<Session | null>(null); const [signal, setSignal] = useState('heart_rate'); const [points, setPoints] = useState<Point[]>([]);
  const [analysis, setAnalysis] = useState<Analysis | null>(null); const [error, setError] = useState(''); const [busy, setBusy] = useState(false); const [index, setIndex] = useState(0); const [confirmDelete, setConfirmDelete] = useState(false);
  const [asset, setAsset] = useState<HumanAssetId>(readBodyModel); const [xray, setXray] = useState(false); const { model, status: modelStatus } = useHumanModel(asset, xray);
  const load = async () => { const s = await bioApi<Session>('/sessions/' + sessionId); setSession(s); const p = await bioApi<Point[]>('/sessions/' + sessionId + '/points?signal=' + encodeURIComponent(signal)); setPoints(p); setIndex(i => Math.min(i, Math.max(0, p.length - 1))); };
  useEffect(() => { if (!sessionId) return; let active = true; load().catch(e => { if (active) setError(e.message); }); const timer = setInterval(() => load().catch(() => undefined), 5000); return () => { active = false; clearInterval(timer); }; }, [sessionId, signal]);
  const act = async (fn: () => Promise<void>) => { setBusy(true); setError(''); try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  if (!sessionId) return <section className="card p-5"><p>No recording selected. No physiological values are available.</p><Button onClick={() => navigate('/biosignals')}>Import or connect a sensor</Button></section>;
  const current = points[index]; const channel = session?.channels.find(c => c.signal === signal); const window = current && analysis?.windows.find(w => current.t >= w.start && current.t < w.end);
  const highlight: Highlight = window?.outcome === 'flag' && signal === 'heart_rate' ? { cardiovascular: { color: [255, 191, 105] as [number, number, number], amount: 0.4 } } : {};
  return <div className="space-y-4">
    <section className="card space-y-3 p-5"><h1 className="text-xl font-semibold">{session?.participant ?? 'Loading recording…'}</h1>
      <p data-data-class={session?.source_type} className={'inline-block rounded-full border px-3 py-1 text-sm ' + (DATA_CLASS[session?.source_type ?? '']?.tone ?? '')}>{DATA_CLASS[session?.source_type ?? '']?.label ?? 'Loading provenance…'}</p>
      <p>{session?.source_type === 'live_sensor' ? 'Recorded BLE session — connection status is shown in Live Sensors. Gaps from link loss are stored as missing, never filled.' : session?.source_type === 'simulated_demo' ? 'SIMULATED DEMO recording — generated locally; any flag demonstrates the pipeline, not detection performance.' : 'Research data — recorded human measurements.'}</p>
      <p className="text-xs text-ink-3">{session?.source} · session {sessionId} · {session?.status}</p>
      {error && <p role="alert" className="text-attention">{error}</p>}
      <p className="text-sm text-ink-2">No astronaut identity, cabin exposure, organ damage or schedule decision is inferred from this recording.</p>
      <div className="flex flex-wrap gap-2"><Button disabled={busy} onClick={() => void act(async () => setAnalysis(await bioApi('/sessions/' + sessionId + '/analysis', {})))}>Run supported PHANTOM analysis</Button>
        <Button disabled={!analysis} onClick={() => save(JSON.stringify({ session, analysis }, null, 2), 'AETHER-research-summary.json')}>Export research summary</Button>
        <Button disabled={busy} onClick={() => void act(async () => { let offset = 0; const pages: string[] = []; for (;;) { const r = await bioApi('/sessions/' + sessionId + '/csv?offset=' + offset); if (!r.rows) break; pages.push(offset ? r.csv.slice(r.csv.indexOf('\n') + 1) : r.csv); offset = r.next_offset; } save(pages.join(''), 'AETHER-measurements.csv', 'text/csv'); })}>Export CSV</Button>
        <Button onClick={() => setConfirmDelete(v => !v)}>Delete session…</Button></div>
      {confirmDelete && <div className="flex items-center gap-3"><span>Permanently delete this session and all its measurements and analysis?</span><Button disabled={busy} onClick={() => void act(async () => { await bioApi('/sessions/' + sessionId, undefined, 'DELETE'); choose('research'); navigate('/biosignals'); })}>Confirm deletion</Button></div>}
      {busy && <p role="status">Processing local records…</p>}
    </section>
    <section className="card overflow-auto p-5"><h2 className="mb-2 font-semibold">Available modalities & quality</h2><table className="w-full text-left text-sm"><thead><tr><th>Signal</th><th>Unit</th><th>Valid</th><th>Rejected/missing</th><th>Duration</th></tr></thead><tbody>{session?.channels.map(c => <tr key={c.signal}><td>{c.signal}</td><td>{c.unit}</td><td>{c.valid}</td><td>{c.total - c.valid} / {c.missing} missing</td><td>{c.start != null && c.end != null ? ((c.end - c.start) / 3600).toFixed(2) + ' h' : 'unavailable'}</td></tr>)}</tbody></table>
      <p className="mt-3 text-xs text-ink-3">Screening is heuristic. A valid numeric interval is not proof of a valid physiological beat. Unknown channels stay unavailable. RR-derived heart rate and ActiGraph heart rate remain separate.</p>
    </section>
    <section className="card space-y-3 p-5"><label>Signal <select aria-label="Recorded signal" className="field ml-2 w-auto" value={signal} onChange={e => { setSignal(e.target.value); setIndex(0); }}>{session?.channels.map(c => <option key={c.signal} value={c.signal}>{c.signal} · {c.unit}</option>)}</select></label>
      <SignalPlot points={points} unit={channel?.unit ?? ''} />
      {current ? <><input aria-label="Recording time" type="range" min={0} max={Math.max(0, points.length - 1)} value={index} onChange={e => setIndex(Number(e.target.value))} className="w-full" /><p className="tabular">{signal}: {current.low.toFixed(2)}–{current.high.toFixed(2)} {channel?.unit} · {session?.source_type === 'research' ? 'relative second ' + current.t.toFixed(1) : new Date(current.t * 1000).toISOString()} · {window?.outcome ?? 'analysis unavailable'}</p></> : <p>No valid measurements in this channel.</p>}
      <p className="text-xs text-ink-3">Chart shows minimum/maximum per time bucket, without interpolation across missing records. Use CSV for original samples and timestamps.</p>
    </section>
    {body && <section className="card p-3"><div className="flex flex-wrap items-center gap-3"><h2 className="font-semibold">BODY · recorded measurements</h2><select aria-label="Recording 3D model" className="field w-auto" value={asset} onChange={e => setAsset(e.target.value as HumanAssetId)}>{HUMAN_ASSETS.map(a => <option key={a.id} value={a.id}>{a.label}</option>)}</select><label><input type="checkbox" checked={xray} onChange={e => setXray(e.target.checked)} /> X-ray layers</label><span className="text-xs">Model: {modelStatus}</span></div>
      <Viewport model={model} initialCamera={{ yaw: 0.35, pitch: 0.08, dist: 10.5, target: [0, 0.35, 0], fov: 0.72 }} height={520} highlight={highlight} ariaLabel="Original BODY digital twin for recorded physiological signals" />
      <p className="text-sm text-ink-3">Amber cardiovascular highlighting appears only when the selected HR chart time belongs to a flagged analysis window. It indicates a statistical deviation, without organ-health inference.</p>
    </section>}
    {analysis && <section aria-label="Real-signal PHANTOM result" className="card space-y-3 p-5"><h2 className="text-lg font-semibold">PHANTOM adapter · {analysis.outcome}</h2><p>{analysis.method}</p><p>{analysis.explanation}</p><p>Baseline: {analysis.baseline_period.join(' → ')} seconds · HR {analysis.baseline_hr_bpm?.toFixed(2) ?? 'insufficient'} bpm · threshold {analysis.threshold} · flag rate {analysis.flag_rate == null ? 'unavailable' : (100 * analysis.flag_rate).toFixed(2) + '%'}</p><p>Missing: {analysis.missing_channels.join(', ')}</p><p className="text-attention">{analysis.uncertainty}</p><details><summary>All analysis windows, HRV, provenance & limitations</summary><pre className="max-h-96 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(analysis, null, 2)}</pre></details></section>}
    <details className="card p-4"><summary>Original source provenance</summary><pre className="overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(session?.metadata, null, 2)}</pre></details>
  </div>;
}
function SignalPlot({ points, unit }: { points: Point[]; unit: string }) {
  if (!points.length) return <p>No valid samples to plot.</p>;
  const min = Math.min(...points.map(p => p.low)); const max = Math.max(...points.map(p => p.high)); const t0 = points[0].t; const duration = Math.max(1, points[points.length - 1].t - t0);
  const x = (t: number) => 45 + 710 * (t - t0) / duration; const y = (v: number) => 180 - 150 * (v - min) / Math.max(1, max - min);
  return <svg role="img" aria-label={'Recorded signal graph in ' + unit} viewBox="0 0 800 215" className="w-full rounded-lg bg-canvas"><text x="5" y="18" fill="#a9b8ca" fontSize="12">{max.toFixed(1)}</text><text x="5" y="190" fill="#a9b8ca" fontSize="12">{min.toFixed(1)}</text>{points.map((p, i) => <line key={i} x1={x(p.t)} x2={x(p.t)} y1={y(p.low) - 1} y2={y(p.high) + 1} stroke="#00e5ff" strokeWidth="2"><title>{p.t}s: {p.low}–{p.high} {unit}; {p.valid} valid samples</title></line>)}<text x="45" y="207" fill="#a9b8ca" fontSize="12">Elapsed recording: {(duration / 3600).toFixed(2)} h · {unit}</text></svg>;
}
