/**
 * BIOSIGNALS · Live Sensors (AETHER 1.5 BLE personal integration).
 *
 * Live Mode + signed-in account only. Every call goes through the authenticated account API (Bearer) to the single
 * server-side Device Manager (app/devices) — never to the legacy unauthenticated /api/biosignals/sensor/* routes.
 * Provenance (REAL SENSOR vs SYNTHETIC) is decided by the server from the transport that produced the notifications;
 * this page only displays it. "Connected" is never shown as "receiving data" until notifications arrive.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AccountApiError,
  type BleDiagnostics,
  type BlePhase,
  type BleScanItem,
  type BleStatus,
  type PersonalDevice,
  type SensorSession,
} from '../../api/accountApi';
import { navigate } from '../../lib/router';
import { useAuth } from '../../state/AuthState';
import { Button, Loading, Notice, Pill, cx } from '../../ui';
import { useBiosignal } from '../biosignals/BiosignalPage';
import { BLE_ERROR, bleErrorText } from './bleErrors';

/* ------------------------------------------------------------------ phase presentation */
const PHASE: Record<BlePhase, { label: string; tone: 'good' | 'attention' | 'high' | 'unknown' | 'info'; detail: string }> = {
  idle: { label: 'Not connected', tone: 'unknown', detail: 'No sensor is connected.' },
  connecting: { label: 'Connecting', tone: 'info', detail: 'Opening the Bluetooth link and verifying the Heart Rate Service over GATT…' },
  connected_awaiting: { label: 'Connected, waiting for measurements', tone: 'info', detail: 'The link is open but no heart-rate notification has arrived yet. Nothing is shown as a live value.' },
  receiving: { label: 'Recording', tone: 'good', detail: 'Notifications are arriving and are stored in your personal account.' },
  no_contact: { label: 'Signal lost · no skin contact', tone: 'attention', detail: 'The sensor reports no skin contact. These samples are stored as unusable (no_contact), never as valid values.' },
  signal_lost: { label: 'Signal lost', tone: 'attention', detail: 'No notifications recently. The gap is stored as missing; no value is filled in.' },
  reconnecting: { label: 'Reconnecting', tone: 'attention', detail: 'The Bluetooth link dropped. AETHER reconnects into the same session; the gap is stored as missing.' },
  saving: { label: 'Saving', tone: 'info', detail: 'Flushing pending rows and closing the session…' },
  saved: { label: 'Saved', tone: 'good', detail: 'The recording session is closed and stored in your personal SQLite history.' },
  connection_failed: { label: 'Connection failed', tone: 'high', detail: 'The sensor could not be connected.' },
  unavailable: { label: 'Bluetooth unavailable', tone: 'high', detail: 'The Bluetooth radio is not available.' },
  revoked: { label: 'Stopped · sign-in ended', tone: 'high', detail: 'Your personal session ended, so the recording was stopped and the sensor released.' },
};
const ACTIVE_PHASES: BlePhase[] = ['connecting', 'connected_awaiting', 'receiving', 'no_contact', 'signal_lost', 'reconnecting', 'saving'];

const maskAddress = (a: string | null | undefined) => (!a ? '—' : a.length <= 8 ? a : `${a.slice(0, 2)}…${a.slice(-5)}`);
const utc = (v: string | null | undefined) => (v ? `${v.replace('T', ' ').replace(/\.\d+/, '').replace('Z', '')} UTC` : '—');
const provenanceLabel = (simulated: boolean | null | undefined, origin?: string) =>
  simulated || origin === 'simulated' ? 'SYNTHETIC · simulated HRS' : origin === 'real' || simulated === false ? 'REAL SENSOR · Bluetooth HRS' : 'UNKNOWN';

type Active = { deviceId: string; name: string; simulated: boolean; startedAt: string };
type Saved = { deviceId: string; name: string; simulated: boolean; sessionId: string | null; stored: number; status: string; startedAt: string; endedAt: string; revoked: boolean };
type ScanState = { status: 'idle' | 'scanning' | 'done' | 'error'; mode: 'hrs' | 'all'; items: BleScanItem[]; error?: { text: string; code: string } };

/* ------------------------------------------------------------------ route entry */
export function LiveSensorsPage() {
  const { status, user } = useAuth();
  if (status === 'checking') return <Loading label="Checking personal session" className="p-8" />;
  if (status !== 'signed-in' || !user) {
    return (
      <main className="mx-auto max-w-3xl space-y-4 p-4 sm:p-8">
        <Notice tone="attention" title="Live Sensors require sign-in">
          Bluetooth recordings are stored in your personal account. Sign in first; no demo data is shown instead.
        </Notice>
        <Button variant="primary" onClick={() => navigate('/login')}>Sign in to AETHER</Button>
      </main>
    );
  }
  return <PersonalLiveSensors key={user.id} />;
}

function PersonalLiveSensors() {
  const { api, token, user } = useAuth();
  const { source, choose } = useBiosignal();
  const [diag, setDiag] = useState<{ status: 'loading' | 'ready' | 'error'; value?: BleDiagnostics; error?: { text: string; code: string } }>({ status: 'loading' });
  const [scan, setScan] = useState<ScanState>({ status: 'idle', mode: 'hrs', items: [] });
  const [devices, setDevices] = useState<PersonalDevice[]>([]);
  const [selected, setSelected] = useState<BleScanItem | null>(null);
  const [active, setActive] = useState<Active | null>(null);
  const [live, setLive] = useState<BleStatus | null>(null);
  const [op, setOp] = useState<'' | 'connecting' | 'stopping'>('');
  const [error, setError] = useState<{ text: string; code: string } | null>(null);
  const [unsupported, setUnsupported] = useState<string | null>(null);
  const [saved, setSaved] = useState<Saved | null>(null);
  const [sessions, setSessions] = useState<Record<string, SensorSession[]>>({});
  const pollFailures = useRef(0);
  const liveRef = useRef<BleStatus | null>(null);
  const opRef = useRef<'' | 'connecting' | 'stopping'>('');
  liveRef.current = live;
  opRef.current = op;

  useEffect(() => { if (source !== 'live_sensor' && source !== 'personal') choose('live_sensor'); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const loadDiagnostics = useCallback(async () => {
    if (!token) return;
    setDiag((d) => ({ ...d, status: 'loading' }));
    try { setDiag({ status: 'ready', value: await api.bleDiagnostics(token) }); } catch (e) { setDiag({ status: 'error', error: bleErrorText(e) }); }
  }, [api, token]);

  const loadDevices = useCallback(async () => {
    if (!token) return [] as PersonalDevice[];
    const items = (await api.devices(token)).filter((d) => d.kind === 'ble');
    setDevices(items);
    const pairs = await Promise.all(items.map(async (d) => [d.id, (await api.deviceSessions(token, d.id).catch(() => ({ items: [] as SensorSession[] }))).items] as const));
    setSessions(Object.fromEntries(pairs));
    return items;
  }, [api, token]);

  // initial load + restore an active recording after a page reload (the server owns the recording, not the page)
  useEffect(() => {
    if (!token) return;
    void loadDiagnostics();
    void loadDevices().then(async (items) => {
      const running = await api.bleActive(token).catch(() => [] as BleStatus[]);
      if (running.length) {
        const s = running[0];
        const d = items.find((x) => x.id === s.device_id);
        setActive({ deviceId: s.device_id, name: d?.name ?? 'HRS monitor', simulated: Boolean(s.simulated), startedAt: new Date(Date.now() - s.duration_seconds * 1000).toISOString() });
        setLive(s);
      }
    }).catch((e) => setError(bleErrorText(e)));
  }, [api, token, loadDiagnostics, loadDevices]);

  const finish = useCallback((status: BleStatus | null, result?: { session_id: string | null; stored_samples: number; session_status?: string }) => {
    const live = liveRef.current;
    setActive((a) => {
      if (a) {
        setSaved({ deviceId: a.deviceId, name: a.name, simulated: a.simulated, sessionId: result?.session_id ?? status?.last_session_id ?? live?.session_id ?? null,
          stored: result?.stored_samples ?? status?.stored_samples ?? live?.stored_samples ?? 0,
          status: result?.session_status ?? status?.last_session_status ?? 'saved', startedAt: a.startedAt, endedAt: new Date().toISOString(),
          revoked: Boolean(status?.revoked) });
      }
      return null;
    });
    setLive(null);
    void loadDevices().catch(() => undefined);
  }, [loadDevices]);

  // status polling while a recording is active (1 s); the server decides stale / gaps / reconnect
  useEffect(() => {
    if (!token || !active) return;
    let stop = false;
    const tick = async () => {
      try {
        const s = await api.bleStatus(token, active.deviceId);
        pollFailures.current = 0;
        if (stop) return;
        if (s.lifecycle_state === 'disconnected' && opRef.current === '') { finish(s); return; }
        setLive(s);
      } catch (e) {
        pollFailures.current += 1;
        if (e instanceof AccountApiError && e.status === 401) { setError(bleErrorText(e)); finish(null); return; }
        if (pollFailures.current >= 5) setError(bleErrorText(e));
      }
    };
    void tick();
    const timer = setInterval(() => void tick(), 1000);
    return () => { stop = true; clearInterval(timer); };
  }, [api, token, active, finish]);

  const runScan = async (mode: 'hrs' | 'all') => {
    if (!token) return;
    setError(null); setUnsupported(null); setSelected(null); setSaved(null);
    setScan({ status: 'scanning', mode, items: [] });
    try {
      const r = await api.bleScan(token, mode === 'all', 7);
      setScan({ status: 'done', mode, items: r.found });
    } catch (e) {
      setScan({ status: 'error', mode, items: [], error: bleErrorText(e) });
      void loadDiagnostics();
    }
  };

  const connectDevice = async (deviceId: string, name: string, simulated: boolean) => {
    if (!token || !user) return;
    setOp('connecting'); setError(null); setUnsupported(null); setSaved(null);
    const startedAt = new Date().toISOString();
    setActive({ deviceId, name, simulated, startedAt });
    setLive(null);
    try {
      await api.bleConnect(token, deviceId, user.astronaut_id);
      choose('live_sensor');
    } catch (e) {
      const err = bleErrorText(e);
      setActive(null);
      setLive(null);
      if (err.code === 'device_not_hrs') setUnsupported(name); else setError(err);
    } finally {
      setOp('');
    }
  };

  const connectSelected = async () => {
    if (!token || !selected) return;
    setError(null);
    let id = selected.registered_device_id ?? devices.find((d) => d.external_id === selected.hardware_address)?.id ?? null;
    if (!id) {
      try {
        id = (await api.registerBleDevice(token, selected.name, selected.hardware_address)).id;
      } catch (e) {
        if (e instanceof AccountApiError && e.status === 409) id = (await loadDevices()).find((d) => d.external_id === selected.hardware_address)?.id ?? null;
        if (!id) { setError(bleErrorText(e)); return; }
      }
      void loadDevices().catch(() => undefined);
    }
    await connectDevice(id, selected.name, false);
  };

  const connectSimulated = async () => {
    if (!token) return;
    setError(null);
    try {
      const dev = await api.simulatedDevice(token);
      await connectDevice(dev.device_id, dev.name, true);
    } catch (e) { setError(bleErrorText(e)); }
  };

  const stopAndSave = async () => {
    if (!token || !active) return;
    setOp('stopping'); setError(null);
    try {
      const r = await api.bleDisconnect(token, active.deviceId);
      finish(live, r);
    } catch (e) { setError(bleErrorText(e)); } finally { setOp(''); }
  };

  const phase: BlePhase = op === 'connecting' ? 'connecting' : op === 'stopping' ? 'saving'
    : active ? (live?.phase ?? 'connecting') : saved ? (saved.revoked ? 'revoked' : 'saved') : 'idle';
  const isActive = Boolean(active) && ACTIVE_PHASES.includes(phase);
  const d = diag.value;
  const btUnavailable = diag.status === 'ready' && d && !d.scan_available;

  const phantomLink = (s: { startedAt: string; endedAt: string; simulated: boolean }) => {
    const f = s.startedAt.slice(0, 19); const t = new Date(Date.parse(s.endedAt) + 60e3).toISOString().slice(0, 19);
    return `/phantom?from=${encodeURIComponent(f)}&to=${encodeURIComponent(t)}&class=${s.simulated ? 'synthetic' : 'real_wearable'}`;
  };

  const allSessions = useMemo(() => devices.flatMap((dev) => (sessions[dev.id] ?? []).map((s) => ({ ...s, deviceName: dev.name })))
    .sort((a, b) => b.started_at.localeCompare(a.started_at)), [devices, sessions]);

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="mono-label text-good">PERSONAL MONITORING · LIVE SENSORS · {user?.login}</p>
          <h1 className="mt-1 text-2xl font-semibold">BIOSIGNALS · Bluetooth Heart Rate Service</h1>
          <p className="mt-2 max-w-3xl text-sm text-ink-2">Scan → Select → Connect → Receiving → Stop &amp; save → History → PHANTOM. Recordings are stored only in your personal account (SQLite). Research prototype, not a medical device.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => { choose('personal'); navigate('/body'); }}>Personal BODY history</Button>
          <Button onClick={() => { choose('personal'); navigate('/phantom'); }}>Personal PHANTOM</Button>
        </div>
      </header>

      <div role="status" aria-live="polite" className="sr-only">{PHASE[phase].label}{unsupported ? ` · unsupported device ${unsupported}` : ''}</div>

      {/* ---------------------------------------------------------------- system state */}
      <section className="card p-4 sm:p-5" aria-label="Bluetooth system state">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold">System state</h2>
          <Button size="sm" variant="ghost" icon="rotate" onClick={() => void loadDiagnostics()}>Re-check</Button>
        </div>
        {diag.status === 'loading' && !d && <Loading label="Checking Bluetooth" />}
        {diag.status === 'error' && <p role="alert" className="text-sm text-high">{diag.error?.text} <span className="text-ink-3">(code: {diag.error?.code})</span></p>}
        {d && (
          <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <div><dt className="text-ink-3">Backend</dt><dd><Pill tone="good" icon="check">connected</Pill></dd></div>
            <div><dt className="text-ink-3">Authenticated owner</dt><dd>{d.authenticated_owner.login}</dd></div>
            <div><dt className="text-ink-3">Bluetooth runtime (bleak/WinRT)</dt><dd><Pill tone={d.ble_dependency_available ? 'good' : 'high'}>{d.ble_dependency_available ? `available${d.bleak_version ? ` · ${d.bleak_version}` : ''}` : 'missing'}</Pill></dd></div>
            <div><dt className="text-ink-3">Bluetooth radio</dt><dd><Pill tone={d.radio_available ? 'good' : d.radio_available === false ? 'high' : 'unknown'}>{d.radio_state === 'unknown' ? 'state unknown' : d.radio_state}</Pill></dd></div>
            <div><dt className="text-ink-3">Radio permission</dt><dd>{d.radio_access}</dd></div>
            <div><dt className="text-ink-3">Scan available</dt><dd><Pill tone={d.scan_available ? 'good' : 'high'}>{d.scan_available ? 'yes' : 'no'}</Pill></dd></div>
            <div><dt className="text-ink-3">Supported protocol</dt><dd className="text-xs">{d.supported_protocol}</dd></div>
            <div><dt className="text-ink-3">Hardware verified</dt><dd><Pill tone="unknown">not verified (hardware_verified=false)</Pill></dd></div>
          </dl>
        )}
        {btUnavailable && (
          <Notice tone="high" title="Bluetooth unavailable" className="mt-3">
            {(d?.reason_code && BLE_ERROR[d.reason_code]) || d?.reason} <span className="text-ink-3">(code: {d?.reason_code ?? 'ble_unavailable'})</span>
            {' '}You can still rehearse the workflow with the clearly labelled SIMULATED strap below.
          </Notice>
        )}
        {d && <p className="mt-3 text-xs text-ink-3">{d.compatibility_note}</p>}
      </section>

      {/* ---------------------------------------------------------------- live panel */}
      {(isActive || saved || phase === 'revoked') && (
        <section className={cx('card space-y-4 p-4 sm:p-5', active?.simulated || saved?.simulated ? 'border-attention' : 'border-good')} aria-label="Live recording">
          <div className="flex flex-wrap items-center gap-2">
            <Pill tone={PHASE[phase].tone}>{PHASE[phase].label}</Pill>
            <Pill tone={(active ?? saved)?.simulated ? 'attention' : 'good'}>{provenanceLabel((active ?? saved)?.simulated ?? live?.simulated)}</Pill>
            <span className="text-sm text-ink-2">{(active ?? saved)?.name}</span>
          </div>
          <p className="text-sm text-ink-2">{PHASE[phase].detail}{phase === 'reconnecting' && live ? ` Attempt ${live.reconnect_attempt}/5.` : ''}</p>
          {live && isActive && (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-xl border border-line p-3">
                  <p className="mono-label">Heart rate</p>
                  <p className="tabular text-3xl font-semibold" aria-label="Current heart rate">{live.heart_rate ?? '—'} <span className="text-base font-normal">bpm</span></p>
                  <p className="text-xs text-ink-3">{live.heart_rate === null ? (live.received_samples === 0 ? 'No measurement received yet' : 'Not current — not displayed as live') : 'Latest notification'}</p>
                </div>
                <div className="rounded-xl border border-line p-3">
                  <p className="mono-label">Signal quality / contact</p>
                  <p className="text-lg font-semibold">{live.quality}</p>
                  <p className="text-xs text-ink-3">contact: {live.contact_state.replace('_', ' ')} · RR intervals: {live.rr_available ? 'present' : 'not provided by sensor'}</p>
                </div>
                <div className="rounded-xl border border-line p-3">
                  <p className="mono-label">Measurement time</p>
                  <p className="text-sm">{utc(live.last_sample_at)}</p>
                  <p className="text-xs text-ink-3">age: {live.last_sample_age_seconds ?? '—'} s · stale after {live.stale_after_seconds} s{live.stale ? ' · STALE' : ''}</p>
                </div>
                <div className="rounded-xl border border-line p-3">
                  <p className="mono-label">Connection</p>
                  <p className="text-sm">{live.connection} · {live.lifecycle_state}</p>
                  <p className="text-xs text-ink-3">GATT HRS verified: {live.hrs_verified ? 'yes' : 'pending'} · duration {live.duration_seconds} s</p>
                </div>
              </div>
              <p className="text-xs text-ink-3">received {live.received_samples} · stored {live.stored_samples} · pending {live.pending_rows} · gaps {live.gaps} · reconnects {live.reconnects} · no-contact {live.no_contact_samples} · corrupt packets {live.corrupt_packets}{live.dropped_rows ? ` · dropped ${live.dropped_rows}` : ''}</p>
              {live.error && <p className="text-sm text-attention">{live.error}</p>}
            </>
          )}
          {isActive && (
            <Button variant="primary" disabled={op !== '' || phase === 'connecting'} onClick={() => void stopAndSave()}>Stop, save &amp; disconnect</Button>
          )}
          {saved && !isActive && (
            <div className="space-y-2">
              <p className="text-sm">Session <span className="break-all font-mono text-xs">{saved.sessionId ?? '—'}</span> · {saved.stored} rows stored · status {saved.status} · {utc(saved.startedAt)} → {utc(saved.endedAt)}</p>
              <p className="text-xs text-ink-3">PHANTOM needs at least 60 minutes of personal baseline in the analysed interval; shorter recordings correctly return “insufficient data”.</p>
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => { choose('personal'); navigate('/body'); }}>Open in BODY history</Button>
                <Button variant="primary" onClick={() => { choose('personal'); navigate(phantomLink(saved)); }}>Analyse in PHANTOM</Button>
              </div>
            </div>
          )}
        </section>
      )}

      {error && <div role="alert" className="card border-attention p-4 text-sm">{error.text} <span className="text-ink-3">(code: {error.code})</span></div>}
      {unsupported && (
        <Notice tone="attention" title="Unsupported device">
          “{unsupported}” connected but does not expose the standard Bluetooth Heart Rate Service (0x180D / Heart Rate Measurement 0x2A37), so nothing was recorded. Many smartwatches only share heart rate through their vendor app; some offer a “broadcast heart rate” mode that does expose HRS.
        </Notice>
      )}

      {/* ---------------------------------------------------------------- scan */}
      <section className="card space-y-3 p-4 sm:p-5" aria-label="Scan for heart-rate sensors" aria-busy={scan.status === 'scanning'}>
        <h2 className="text-lg font-semibold">Physical sensor · scan</h2>
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" icon="bluetooth" disabled={isActive || scan.status === 'scanning' || btUnavailable || diag.status !== 'ready'} onClick={() => void runScan('hrs')}>Scan HRS monitors</Button>
          <Button icon="bluetooth" disabled={isActive || scan.status === 'scanning' || btUnavailable || diag.status !== 'ready'} onClick={() => void runScan('all')}>Scan nearby; verify HRS</Button>
        </div>
        {scan.status === 'scanning' && <Loading label={scan.mode === 'hrs' ? 'Searching for Heart Rate Service advertisements (7 s)' : 'Searching for named Bluetooth devices (7 s)'} />}
        {scan.status === 'error' && <p role="alert" className="text-sm text-high">{scan.error?.text} <span className="text-ink-3">(code: {scan.error?.code})</span></p>}
        {scan.status === 'done' && scan.items.length === 0 && (
          <p role="status" className="rounded-xl border border-line p-3 text-sm text-ink-2">
            {scan.mode === 'hrs' ? 'No Heart Rate Service advertisement found. Wear the strap (moisten the electrodes) or enable “broadcast heart rate” on the watch, then scan again — or use “Scan nearby; verify HRS”.'
              : 'No named Bluetooth device found nearby. Check that Bluetooth is on and the sensor is awake.'}
          </p>
        )}
        {scan.items.length > 0 && (
          <ul className="space-y-2" aria-label="Found devices">
            {scan.items.map((item) => {
              const isSel = selected?.hardware_address === item.hardware_address;
              return (
                <li key={item.hardware_address}>
                  <button type="button" aria-pressed={isSel} onClick={() => { setSelected(item); setUnsupported(null); }}
                    className={cx('flex w-full flex-wrap items-center gap-2 rounded-xl border p-3 text-left text-sm', isSel ? 'border-teal-300 bg-white/5' : 'border-line hover:border-line-strong')}>
                    <span className="font-semibold">{item.name}</span>
                    <span className="font-mono text-xs text-ink-3">id {maskAddress(item.hardware_address)}</span>
                    <Pill tone={item.advertised_hrs ? 'good' : 'unknown'}>{item.advertised_hrs ? 'HRS advertised' : 'HRS not advertised · verified on connect'}</Pill>
                    {item.rssi !== null && <span className="text-xs text-ink-3">{item.rssi} dBm</span>}
                    {item.registered_device_id && <span className="text-xs text-ink-3">registered</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        {selected && !isActive && (
          <div className="rounded-xl border border-teal-300/60 p-3 text-sm">
            <p><strong>{selected.name}</strong> selected. Connecting verifies the GATT Heart Rate Service before anything is recorded. Heart rate (and RR intervals, if the sensor sends them) are stored in <strong>your</strong> account until you press Stop &amp; save.</p>
            <Button className="mt-2" variant="primary" disabled={op !== ''} onClick={() => void connectSelected()}>Connect &amp; start recording</Button>
          </div>
        )}
      </section>

      {/* ---------------------------------------------------------------- simulated */}
      <section className="card space-y-2 border-attention p-4 sm:p-5" aria-label="Test with simulated HRS">
        <h2 className="text-lg font-semibold">Test with simulated HRS · SYNTHETIC</h2>
        <p className="text-sm text-ink-2">For rehearsals without a strap. A server-side simulated strap sends standard 0x2A37 packets through the same decoder, storage and PHANTOM path. Every row is stored as <strong>SYNTHETIC</strong> (origin simulated) — never as REAL SENSOR, and it does not prove that physical Bluetooth works.</p>
        <Button disabled={isActive || op !== '' || !d?.simulated_hrs_available} onClick={() => void connectSimulated()}>Test with simulated HRS</Button>
      </section>

      {/* ---------------------------------------------------------------- history */}
      <section className="card space-y-3 p-4 sm:p-5" aria-label="Recording history">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold">Recording history (personal SQLite)</h2>
          <Button size="sm" variant="ghost" icon="rotate" onClick={() => void loadDevices().catch((e) => setError(bleErrorText(e)))}>Refresh</Button>
        </div>
        {allSessions.length === 0 && <p className="text-sm text-ink-2">No sensor recordings in this account yet.</p>}
        {allSessions.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-xs">
              <thead><tr className="border-b border-line text-ink-3"><th className="p-2">Started (UTC)</th><th className="p-2">Ended</th><th className="p-2">Device</th><th className="p-2">Provenance</th><th className="p-2">Status</th><th className="p-2">Analyse</th></tr></thead>
              <tbody>{allSessions.slice(0, 50).map((s) => (
                <tr key={s.id} className="border-b border-line/60">
                  <td className="whitespace-nowrap p-2">{utc(s.started_at)}</td>
                  <td className="whitespace-nowrap p-2">{s.ended_at ? utc(s.ended_at) : 'open'}</td>
                  <td className="p-2">{s.deviceName}</td>
                  <td className="p-2"><Pill tone={s.origin === 'real' ? 'good' : 'attention'}>{provenanceLabel(null, s.origin)}</Pill></td>
                  <td className="p-2">{s.end_status ?? (s.ended_at ? 'closed' : 'recording')}</td>
                  <td className="p-2">{s.ended_at && (
                    <Button size="sm" onClick={() => { choose('personal'); navigate(phantomLink({ startedAt: s.started_at, endedAt: s.ended_at!, simulated: s.origin !== 'real' })); }}>PHANTOM</Button>
                  )}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
