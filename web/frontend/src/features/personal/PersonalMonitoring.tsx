import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AccountApiError,
  BE2_SIGNAL_CONTRACT,
  type Measurement,
  type Page,
  type SignalDefinition,
} from '../../api/accountApi';
import { TimeSeriesChart } from '../../charts';
import { navigate, useRoute } from '../../lib/router';
import { useAuth } from '../../state/AuthState';
import { Button, Loading, Notice, Pill } from '../../ui';
import { chartSeriesForSignal, latestValidMeasurement, personalMeasurementQuery } from './measurementView';
import { PersonalTwin } from './PersonalTwin';
import { PersonalSignalOverview } from './PersonalSignalOverview';
import { usePersonalSnapshot } from './usePersonalSnapshot';

type KeyedResource<T> =
  | { key: string; status: 'loading' }
  | { key: string; status: 'ready'; value: T }
  | { key: string; status: 'error'; message: string };

type SignalResource = {
  key: string;
  status: 'loading' | 'ready' | 'fallback' | 'error';
  items: SignalDefinition[];
  message?: string;
};

function requestError(error: unknown): string {
  return error instanceof Error ? error.message : 'Could not load personal measurements.';
}

function mayUseContractCatalog(error: unknown): boolean {
  return error instanceof AccountApiError
    && (error.status === 0 || error.status === 404 || error.status === 410 || error.status === 503);
}

function utc(value: string | null): string {
  if (!value) return 'Unavailable';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? 'Unavailable' : `${parsed.toISOString().replace('T', ' ').replace('Z', '')} UTC`;
}

function SignInPrompt() {
  return (
    <main className="mx-auto max-w-3xl space-y-4 p-4 sm:p-8">
      <Notice tone="attention" title="Personal Monitoring requires sign-in">
        No demo records are substituted for personal data. Sign in to view measurements belonging to your account.
      </Notice>
      <Button variant="primary" onClick={() => navigate('/login')}>Sign in to AETHER</Button>
    </main>
  );
}

export function PersonalBodyPage() {
  const { status, user } = useAuth();
  if (status === 'checking') return <Loading label="Checking personal session" className="p-8" />;
  if (status !== 'signed-in' || !user) return <SignInPrompt />;
  return <AccountPersonalBody key={user.id} />;
}

function AccountPersonalBody() {
  const { api, token, user } = useAuth();
  const [refreshIndex, setRefreshIndex] = useState(0);
  const signalSnapshot = usePersonalSnapshot(refreshIndex);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [signal, setSignal] = useState('heart_rate');
  const [historyState, setHistoryState] = useState<KeyedResource<Page<Measurement>>>({ key: '', status: 'loading' });
  const [signalsState, setSignalsState] = useState<SignalResource>({ key: '', status: 'loading', items: [] });
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState('');
  const loadMoreController = useRef<AbortController | null>(null);

  const accountKey = user?.id ?? '';
  const historyKey = useMemo(() => JSON.stringify([accountKey, start, end, refreshIndex]), [accountKey, start, end, refreshIndex]);
  const history: KeyedResource<Page<Measurement>> = historyState.key === historyKey
    ? historyState
    : { key: historyKey, status: 'loading' };
  const signals = signalsState.key === accountKey
    ? signalsState
    : { key: accountKey, status: 'loading' as const, items: [] };

  useEffect(() => {
    if (!token || !user) return;
    const key = historyKey;
    const controller = new AbortController();
    loadMoreController.current?.abort();
    setHistoryState({ key, status: 'loading' });
    setLoadingMore(false);
    setMoreError('');
    if (start && end && start > end) {
      setHistoryState({ key, status: 'error', message: 'Start date must be on or before end date.' });
      return () => controller.abort();
    }

    void api.measurements(token, personalMeasurementQuery(start, end), controller.signal).then((value) => {
      if (!controller.signal.aborted) setHistoryState({ key, status: 'ready', value });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setHistoryState({ key, status: 'error', message: requestError(error) });
    });

    return () => {
      controller.abort();
      loadMoreController.current?.abort();
    };
  }, [api, token, user, historyKey, start, end]);

  useEffect(() => {
    if (!token || !user) return;
    const key = user.id;
    const controller = new AbortController();
    setSignalsState({ key, status: 'loading', items: [] });
    void api.signals(token, controller.signal).then((catalog) => {
      if (!controller.signal.aborted) {
        setSignalsState({
          key,
          status: 'ready',
          items: catalog.items,
          message: catalog.contract_status === 'integration_candidate'
            ? 'The server signal catalog is an integration candidate.'
            : undefined,
        });
      }
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      if (mayUseContractCatalog(error)) {
        setSignalsState({
          key,
          status: 'fallback',
          items: BE2_SIGNAL_CONTRACT,
          message: 'Signal names use the BE2 contract fallback; the server catalog is unavailable.',
        });
      } else {
        setSignalsState({ key, status: 'error', items: [], message: requestError(error) });
      }
    });
    return () => controller.abort();
  }, [api, token, accountKey]);

  const loadMore = async () => {
    if (!token || history.status !== 'ready' || history.value.next_cursor === null || loadingMore) return;
    const key = historyKey;
    const cursor = history.value.next_cursor;
    const controller = new AbortController();
    loadMoreController.current = controller;
    setLoadingMore(true);
    setMoreError('');
    try {
      const next = await api.measurements(token, { ...personalMeasurementQuery(start, end), after: cursor }, controller.signal);
      if (!controller.signal.aborted) {
        setHistoryState((current) => current.key === key && current.status === 'ready'
          ? {
            ...current,
            value: { items: [...current.value.items, ...next.items], next_cursor: next.next_cursor },
          }
          : current);
      }
    } catch (error) {
      if (!controller.signal.aborted) setMoreError(requestError(error));
    } finally {
      if (loadMoreController.current === controller) {
        loadMoreController.current = null;
        setLoadingMore(false);
      }
    }
  };

  const items = history.status === 'ready' ? history.value.items : [];
  const options = useMemo(() => {
    const byName = new Map(signals.items.map((item) => [item.signal, item]));
    for (const item of items) {
      if (!byName.has(item.signal)) byName.set(item.signal, { signal: item.signal, unit: item.unit, minimum: 0, maximum: 0 });
    }
    return [...byName.values()];
  }, [signals.items, items]);
  const series = useMemo(() => chartSeriesForSignal(items, signal), [items, signal]);
  const latest = useMemo(() => latestValidMeasurement(items, signal), [items, signal]);
  const selectedLabel = options.find((item) => item.signal === signal)?.signal ?? signal;

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="mono-label text-good">PERSONAL MONITORING · authenticated account</p>
          <h1 className="mt-1 text-2xl font-semibold">BODY · {user?.login}</h1>
          <p className="mt-2 text-sm text-ink-2">Your BE2 measurement history only. This view does not read synthetic mission data or infer a health state.</p>
        </div>
        <div className="flex flex-wrap gap-2"><Button onClick={() => setRefreshIndex((v) => v + 1)}>Refresh stored data</Button><Button onClick={() => navigate('/profile')}>Account profile</Button></div>
      </header>

      <Notice tone="unknown" title="Personal records, not a live health assessment">
        Values below are historical records returned for this account. The latest timestamp is the latest recorded sample, not a current reading. No individual baseline is computed by this measurement-history view.
      </Notice>

      <section className="card space-y-4 p-4 sm:p-5" aria-label="Personal measurement filters">
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-36 flex-1 text-sm">Start date (UTC)
            <input type="date" aria-label="Personal history start date" className="field mt-1 w-full" value={start} onChange={(event) => setStart(event.target.value)} />
          </label>
          <label className="min-w-36 flex-1 text-sm">End date (UTC, inclusive)
            <input type="date" aria-label="Personal history end date" className="field mt-1 w-full" value={end} onChange={(event) => setEnd(event.target.value)} />
          </label>
          <label className="min-w-48 flex-1 text-sm">Signal
            <select aria-label="Personal signal" className="field mt-1 w-full" value={signal} onChange={(event) => setSignal(event.target.value)}>
              {options.map((item) => <option key={item.signal} value={item.signal}>{item.signal} · {item.unit}</option>)}
            </select>
          </label>
          <Button size="sm" variant="ghost" onClick={() => { setStart(''); setEnd(''); }}>Clear date range</Button>
        </div>
        {signals.message && <p className="text-xs text-ink-3">{signals.message}</p>}
        {signals.status === 'error' && <p role="alert" className="text-sm text-high">{signals.message}</p>}
      </section>

      {latest && (
        <section className="card flex flex-wrap items-center justify-between gap-3 p-4" aria-label="Latest recorded sample">
          <div>
            <p className="mono-label">Latest recorded sample · {selectedLabel}</p>
            <p className="mt-1 tabular text-xl font-semibold">{latest.value} {latest.unit}</p>
            <p className="text-xs text-ink-3">{utc(latest.measured_at)} · origin {latest.origin} · quality {latest.quality}</p>
          </div>
          <Pill tone="unknown">Historical, not current</Pill>
        </section>
      )}

      {signalSnapshot.status === 'error' && <p role="alert" className="rounded-xl border border-attention/40 p-3 text-sm text-attention">Current personal signal snapshot is unavailable: {signalSnapshot.error}. Existing history is shown separately.</p>}
      {signalSnapshot.status === 'ready' && signalSnapshot.data && (
        <><PersonalSignalOverview snapshot={signalSnapshot.data} /><PersonalTwin measurements={signalSnapshot.data.items} /></>
      )}
      {signalSnapshot.status === 'loading' && <Loading label="Loading latest personal signals from SQLite" />}


      <section className="card space-y-4 p-4 sm:p-5" aria-label="Personal signal history chart">
        <div>
          <h2 className="text-lg font-semibold">{selectedLabel} history</h2>
          <p className="text-sm text-ink-3">Each unit is graphed separately. Null, missing, rejected, and unusable-quality samples remain gaps.</p>
        </div>
        {history.status === 'loading' && <Loading label="Loading personal measurements" />}
        {history.status === 'error' && <div role="alert" className="rounded-xl border border-high/40 p-3 text-sm text-high">{history.message}</div>}
        {history.status === 'ready' && items.length === 0 && (
          <p className="rounded-xl border border-line p-4 text-sm text-ink-2">No measurements were returned for this account and date range. This is not a health assessment.</p>
        )}
        {history.status === 'ready' && items.length > 0 && series.length === 0 && (
          <p role="status" className="rounded-xl border border-line p-4 text-sm text-ink-2">Insufficient chart data: matching records have no usable measured timestamp.</p>
        )}
        {history.status === 'ready' && series.map((group) => (
          <div key={group.unit} className="rounded-xl border border-line p-3">
            <p className="mb-2 text-xs text-ink-3">Unit: {group.unit} · origin: {group.origins.join(', ') || 'unavailable'} · quality: {group.qualities.join(', ') || 'unavailable'}</p>
            {group.points.some((point) => point.y !== null)
              ? <TimeSeriesChart
                height={220}
                ariaLabel={`${selectedLabel} personal history in ${group.unit}; origin ${group.origins.join(', ')}; quality ${group.qualities.join(', ')}`}
                series={[{ id: `${selectedLabel}-${group.unit}`, label: `${selectedLabel} · ${group.unit}`, color: 'var(--color-series-1)', points: group.points }]}
                unit={group.unit}
                xFormat={(value) => new Date(value).toLocaleDateString('en', { month: 'short', day: 'numeric', timeZone: 'UTC' })}
              />
              : <p role="status" className="text-sm text-ink-2">Insufficient valid samples for this unit; missing or rejected values are not plotted.</p>}
          </div>
        ))}
      </section>

      <section className="card space-y-3 p-4 sm:p-5" aria-label="Personal measurement records">
        <h2 className="text-lg font-semibold">Measurement records</h2>
        {history.status === 'ready' && items.length > 0 && (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-[1100px] w-full text-left text-xs">
                <thead><tr className="border-b border-line text-ink-3">
                  <th className="p-2">Measured (UTC)</th><th className="p-2">Received (UTC)</th><th className="p-2">Signal</th><th className="p-2">Value</th>
                  <th className="p-2">Missing</th><th className="p-2">Origin</th><th className="p-2">Quality</th><th className="p-2">Source</th><th className="p-2">Device / session</th><th className="p-2">Mission / processing</th>
                </tr></thead>
                <tbody>{items.map((item) => (
                  <tr key={item.id} className="border-b border-line/60">
                    <td className="whitespace-nowrap p-2">{utc(item.measured_at)}</td>
                    <td className="whitespace-nowrap p-2">{utc(item.received_at)}</td>
                    <td className="p-2">{item.signal}</td>
                    <td className="tabular p-2">{item.value === null || item.missing ? '—' : `${item.value} ${item.unit}`}</td><td className="p-2">{item.missing ? 'yes' : 'no'}</td>
                    <td className="p-2">{item.origin}</td><td className="p-2">{item.quality}</td><td className="p-2">{item.source}</td>
                    <td className="p-2">{item.device_id ?? '—'} / {item.session_id ?? '—'}</td>
                    <td className="p-2">{item.mission_id ?? '—'} / {item.processing_version}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
            {moreError && <p role="alert" className="text-sm text-high">{moreError}</p>}
            {history.value.next_cursor !== null && <Button disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? 'Loading…' : 'Load older records'}</Button>}
          </>
        )}
        {history.status === 'loading' && <Loading label="Loading personal measurement records" />}
        {history.status === 'error' && <p className="text-sm text-ink-2">History is unavailable; an error is not shown as an empty history.</p>}
      </section>
    </div>
  );
}

export function PersonalPhantomPage() {
  const { status, user } = useAuth();
  if (status === 'checking') return <Loading label="Checking personal session" className="p-8" />;
  if (status !== 'signed-in' || !user) return <SignInPrompt />;
  return <AccountPersonalPhantom key={user.id} />;
}

type DataClass = 'real_wearable' | 'manual' | 'synthetic' | 'terrestrial_research';
const DATA_CLASS_LABEL: Record<DataClass, string> = {
  real_wearable: 'REAL SENSOR', manual: 'MANUAL', synthetic: 'SYNTHETIC', terrestrial_research: 'TERRESTRIAL RESEARCH',
};
const OUTCOME_LABEL: Record<string, string> = {
  flag: 'Statistical change detected', no_flag: 'No statistical flag', insufficient_data: 'Insufficient data',
};
type PhantomWindow = { start: string; mean_hr_bpm: number | null; outcome: string };
type PhantomExplain = {
  data_label: string;
  baseline: { median_hr_bpm: number; windows_used: number } | null;
  deviation: { window_mean_hr_bpm?: number; difference_from_baseline_bpm?: number; max_robust_z?: number } | null;
  signal_quality: { valid: number; measurements: number; coverage: number | null; excluded: unknown };
  why: string[];
  next_measurement: string;
  limitations: string[];
  validation_status: unknown;
};
type PhantomResult = {
  analysis_id: string;
  outcome: string;
  processing_version: string;
  created_at?: string;
  created_at_utc?: string;
  windows?: PhantomWindow[];
  explain?: PhantomExplain;
};
type PhantomList = { items: PhantomResult[]; next_cursor: string | null };

const isoInput = (ms: number) => new Date(ms).toISOString().slice(0, 19);
function initialRange(query: URLSearchParams): { from: string; to: string; cls: DataClass } {
  const valid = (v: string | null) => (v && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(v) ? v.slice(0, 19) : null);
  const cls = query.get('class');
  return {
    from: valid(query.get('from')) ?? isoInput(Date.now() - 4 * 3600e3),
    to: valid(query.get('to')) ?? isoInput(Date.now()),
    cls: (cls && cls in DATA_CLASS_LABEL ? cls : 'real_wearable') as DataClass,
  };
}

function AccountPersonalPhantom() {
  const { api, token, user } = useAuth();
  const { query } = useRoute();
  const initial = useMemo(() => initialRange(query), []); // eslint-disable-line react-hooks/exhaustive-deps
  const [history, setHistory] = useState<PhantomList | null>(null);
  const [result, setResult] = useState<PhantomResult | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [from, setFrom] = useState(initial.from);
  const [to, setTo] = useState(initial.to);
  const [dataClass, setDataClass] = useState<DataClass>(initial.cls);
  const [manualHr, setManualHr] = useState('70');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    api.science<PhantomList>(token, '/phantom-analyses', undefined, controller.signal).then(setHistory).catch((e: unknown) => {
      if (!controller.signal.aborted) setError(requestError(e));
    });
    return () => controller.abort();
  }, [api, token]);

  async function guarded(fn: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : 'Science request failed.'); } finally { setBusy(false); }
  }

  async function analyse(fromIso: string, toIso: string, cls: DataClass) {
    if (!token || !user) return;
    const value = await api.science<PhantomResult>(token, '/phantom-analyses', {
      astronaut_id: user.astronaut_id, from: fromIso, to: toIso, data_classes: [cls],
    });
    setResult(value);
    setHistory(await api.science<PhantomList>(token, '/phantom-analyses'));
  }

  async function syntheticControl() {
    if (!token) return;
    const t0 = Date.now() - 4 * 3600e3;
    const rows = [];
    for (let i = 0; i < 5400; i++) {
      rows.push({
        idempotency_key: `demo-${t0}-${i}`, source: 'AETHER control SYNTHETIC', signal: 'heart_rate',
        value: 64 + Math.sin(i * 0.2) * 2 + (i >= 3300 ? 15 : 0), unit: 'bpm', measured_at: new Date(t0 + i * 2000).toISOString(),
        origin: 'simulated', quality: 'screened', metadata: { generator: 'release-control-v1', label: 'SYNTHETIC' },
      });
    }
    for (let i = 0; i < rows.length; i += 500) await api.science(token, '/measurements/batch', { measurements: rows.slice(i, i + 500) });
    const f = new Date(t0).toISOString(); const t = new Date(t0 + 180 * 60e3).toISOString();
    setDataClass('synthetic'); setFrom(f.slice(0, 19)); setTo(t.slice(0, 19));
    await analyse(f, t, 'synthetic');
    setNotice('SYNTHETIC control stored in your history. No physical sensor was used.');
  }

  const explain = result?.explain;
  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <header>
        <p className="mono-label text-violet">PERSONAL MONITORING · {user?.login}</p>
        <h1 className="text-2xl font-semibold">PHANTOM · personal analysis</h1>
      </header>
      <Notice tone="unknown" title="Research prototype · not a medical device">
        Frozen personal baseline; 5-minute HR windows; robust z ≥ 3.5. Brief activity can trigger flags. Mathematical and synthetic evidence only; human clinical, hardware and astronaut validation are not established.
      </Notice>
      <section className="card space-y-3 p-5" aria-label="PHANTOM controls">
        <div className="flex flex-wrap gap-3">
          <label>From (UTC)<input className="field block" type="datetime-local" step="1" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
          <label>To (UTC)<input className="field block" type="datetime-local" step="1" value={to} onChange={(e) => setTo(e.target.value)} /></label>
          <label>Source
            <select className="field block" value={dataClass} onChange={(e) => setDataClass(e.target.value as DataClass)}>
              {(Object.keys(DATA_CLASS_LABEL) as DataClass[]).map((k) => <option key={k} value={k}>{DATA_CLASS_LABEL[k]}</option>)}
            </select>
          </label>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button disabled={busy || !from || !to} onClick={() => void guarded(async () => {
            if (from >= to) throw new Error('From must be earlier than To.');
            await analyse(`${from}Z`, `${to}Z`, dataClass);
          })}>Run personal PHANTOM</Button>
          <Button disabled={busy} onClick={() => void guarded(syntheticControl)}>Store & analyse SYNTHETIC control</Button>
          <Button variant="ghost" onClick={() => navigate('/biosignals')}>Record with Live Sensors</Button>
        </div>
        <p className="text-xs text-ink-3">The control writes 180 minutes of labelled synthetic HR to your account. It does not represent live data. REAL SENSOR selects only rows the server stored from Bluetooth HRS notifications.</p>
        <label>Manual heart rate (bpm)<input className="field mx-2" type="number" min="30" max="220" value={manualHr} onChange={(e) => setManualHr(e.target.value)} /></label>
        <Button disabled={busy} onClick={() => void guarded(async () => {
          const v = Number(manualHr);
          if (!token || !Number.isFinite(v) || v < 30 || v > 220) throw new Error('Enter 30–220 bpm.');
          await api.science(token, '/measurements', {
            idempotency_key: crypto.randomUUID(), source: 'Manual entry', signal: 'heart_rate', value: v, unit: 'bpm',
            measured_at: new Date().toISOString(), origin: 'manual', quality: 'unverified',
          });
          setNotice('MANUAL measurement stored; quality unverified. A single measurement is insufficient for PHANTOM.');
        })}>Save manual measurement</Button>
      </section>
      {busy && <Loading label="Processing personal science request" />}
      {error && <p role="alert" className="card p-4 text-high">{error}</p>}
      {notice && <p role="status" className="card p-4">{notice}</p>}
      {result && explain && (
        <section className="card space-y-4 p-5" aria-label="Personal PHANTOM result">
          <Pill tone="unknown">{explain.data_label}</Pill>
          <h2 className="text-xl">{OUTCOME_LABEL[result.outcome] ?? result.outcome}</h2>
          <dl className="grid gap-3 sm:grid-cols-2">
            <div><dt>Signal</dt><dd>Heart rate — bpm</dd></div>
            <div><dt>Baseline</dt><dd>{explain.baseline ? `${explain.baseline.median_hr_bpm} bpm · ${explain.baseline.windows_used} windows` : 'Insufficient data'}</dd></div>
            <div><dt>Most deviant window</dt><dd>{explain.deviation?.window_mean_hr_bpm ?? 'Unavailable'} bpm</dd></div>
            <div><dt>Deviation</dt><dd>{explain.deviation?.difference_from_baseline_bpm ?? 'Unavailable'} bpm · z {explain.deviation?.max_robust_z ?? 'unavailable'}</dd></div>
            <div><dt>Quality</dt><dd>{explain.signal_quality.valid}/{explain.signal_quality.measurements} valid · coverage {explain.signal_quality.coverage ?? 'unavailable'}</dd></div>
            <div><dt>Processing version</dt><dd>{result.processing_version}</dd></div>
            <div><dt>Analysis ID / timestamp</dt><dd className="break-all">{result.analysis_id} · {result.created_at ?? result.created_at_utc ?? 'See stored record'}</dd></div>
          </dl>
          {explain.why.map((line, i) => <p key={i}>{line}</p>)}
          {result.windows && (
            <div className="min-w-0">
              <TimeSeriesChart height={220} unit="bpm" ariaLabel={`${explain.data_label} five-minute mean heart rate; gaps are unusable windows`}
                series={[{ id: 'hr', label: `${explain.data_label} HR window mean`, color: 'var(--color-series-1)',
                  points: result.windows.map((w) => ({ x: Date.parse(w.start), y: w.mean_hr_bpm })) }]}
                refLines={explain.baseline ? [{ y: explain.baseline.median_hr_bpm, label: 'Frozen personal baseline' }] : []}
                xFormat={(v) => new Date(v).toISOString().slice(11, 16)} />
              <p className="text-xs text-ink-3">UTC · gaps are unusable windows. Flagged windows: {result.windows.filter((w) => w.outcome === 'flag').map((w) => w.start.slice(11, 16)).join(', ') || 'none'}.</p>
            </div>
          )}
          <p>{explain.next_measurement}</p>
          <details>
            <summary>Quality exclusions, evidence & limitations</summary>
            <pre className="overflow-auto text-xs">{JSON.stringify(explain.signal_quality.excluded, null, 2)}</pre>
            {explain.limitations.map((line, i) => <p key={i} className="mt-2 text-sm">{line}</p>)}
            <pre className="overflow-auto text-xs">{JSON.stringify(explain.validation_status, null, 2)}</pre>
            <p>Protocol and results: docs/validation/EXPERIMENT_PROTOCOL_BE3_04.md; RESULTS_BE3_04.md. Synthetic results do not measure clinical accuracy.</p>
          </details>
        </section>
      )}
      <section className="card space-y-3 p-5" aria-label="PHANTOM analysis history">
        <h2 className="text-lg">Saved analysis history</h2>
        {!history && !error && <Loading label="Loading analysis history" />}
        {history?.items.length === 0 && <p>No saved PHANTOM analyses.</p>}
        {history?.items.map((item) => (
          <div key={item.analysis_id} className="flex flex-wrap items-center gap-2 border-b border-line py-2">
            <Pill tone="unknown">{item.explain?.data_label ?? 'UNKNOWN / UNVERIFIED'}</Pill>
            <span>{OUTCOME_LABEL[item.outcome] ?? item.outcome} · {item.created_at}</span>
            <Button disabled={busy} onClick={() => void guarded(async () => {
              if (token) setResult(await api.science<PhantomResult>(token, `/phantom-analyses/${item.analysis_id}`));
            })}>Open saved analysis</Button>
          </div>
        ))}
        {history?.next_cursor && <p>Showing the most recent 100 analyses.</p>}
      </section>
    </div>
  );
}
