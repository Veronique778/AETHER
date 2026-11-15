import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import {
  AccountApiError,
  BE2_SIGNAL_CONTRACT,
  type Language,
  type Measurement,
  type MeasurementQuery,
  type OwnProfile,
  type Page,
  type PersonalDevice,
  type SignalDefinition,
} from '../../api/accountApi';
import { useApp } from '../../state/AppState';
import { useAuth } from '../../state/AuthState';
import { Button, Empty, Loading, MissingValue, Notice, PageHeader } from '../../ui';

type Resource<T> =
  | { key: string; status: 'loading' }
  | { key: string; status: 'ready'; value: T }
  | { key: string; status: 'error'; message: string };

type SignalResource = {
  key: string;
  status: 'loading' | 'ready' | 'fallback' | 'error';
  items: SignalDefinition[];
  message?: string;
};

function utcDayStart(date: string): string {
  return `${date}T00:00:00.000000Z`;
}

function utcDayEnd(date: string): string {
  return `${date}T23:59:59.999999Z`;
}

function formatUtc(value: string | null): string {
  if (!value) return 'Timestamp unavailable';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Timestamp unavailable' : `${date.toISOString().replace('T', ' ').replace('Z', '')} UTC`;
}

function queryFor(start: string, end: string, signal: string): MeasurementQuery {
  return {
    start: utcDayStart(start),
    end: utcDayEnd(end),
    ...(signal ? { signal } : {}),
    limit: 100,
  };
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Could not load your account data.';
}

function forKey<T>(resource: Resource<T>, key: string): Resource<T> {
  return resource.key === key ? resource : { key, status: 'loading' };
}

function canUseContractSignalFallback(error: unknown): boolean {
  return error instanceof AccountApiError
    && (error.status === 0 || error.status === 404 || error.status === 410 || error.status === 503);
}

export function ProfilePage() {
  const { mode } = useApp();
  const { api, token, user, signOut, changePassword, error: authError } = useAuth();
  const [start, setStart] = useState(() => new Date().toISOString().slice(0, 10));
  const [end, setEnd] = useState(() => new Date().toISOString().slice(0, 10));
  const [signal, setSignal] = useState('');
  const [profileState, setProfileState] = useState<Resource<OwnProfile>>({ key: '', status: 'loading' });
  const [devicesState, setDevicesState] = useState<Resource<PersonalDevice[]>>({ key: '', status: 'loading' });
  const [signalsState, setSignalsState] = useState<SignalResource>({ key: '', status: 'loading', items: [] });
  const [measurementsState, setMeasurementsState] = useState<Resource<Page<Measurement>>>({ key: '', status: 'loading' });
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState('');
  const [savingProfile, setSavingProfile] = useState(false);
  const [changingPassword, setChangingPassword] = useState(false);
  const [profileMessage, setProfileMessage] = useState('');
  const [profileSaveError, setProfileSaveError] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const loadMoreController = useRef<AbortController | null>(null);

  const accountKey = user?.id ?? '';
  const historyKey = useMemo(
    () => JSON.stringify([accountKey, start, end, signal]),
    [accountKey, start, end, signal],
  );
  const profile = forKey(profileState, accountKey);
  const devices = forKey(devicesState, accountKey);
  const signals = signalsState.key === accountKey
    ? signalsState
    : { key: accountKey, status: 'loading' as const, items: [] };
  const measurements = forKey(measurementsState, historyKey);

  useEffect(() => {
    document.body.classList.add('aether-account-page');
    return () => document.body.classList.remove('aether-account-page');
  }, []);

  useEffect(() => {
    if (!token || !user) return;
    const key = user.id;
    const controller = new AbortController();
    setProfileState({ key, status: 'loading' });
    setDevicesState({ key, status: 'loading' });
    setSignalsState({ key, status: 'loading', items: [] });
    setProfileMessage('');
    setProfileSaveError('');

    void api.profile(token, controller.signal).then((value) => {
      if (!controller.signal.aborted) setProfileState({ key, status: 'ready', value });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setProfileState({ key, status: 'error', message: errorText(error) });
    });

    void api.devices(token, controller.signal).then((value) => {
      if (!controller.signal.aborted) setDevicesState({ key, status: 'ready', value });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setDevicesState({ key, status: 'error', message: errorText(error) });
    });

    void api.signals(token, controller.signal).then((catalog) => {
      if (controller.signal.aborted) return;
      const message = catalog.contract_status === 'integration_candidate'
        ? 'The server signal catalog is an integration candidate; available filters follow its current response.'
        : undefined;
      setSignalsState({ key, status: 'ready', items: catalog.items, message });
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      if (canUseContractSignalFallback(error)) {
        setSignalsState({
          key,
          status: 'fallback',
          items: BE2_SIGNAL_CONTRACT,
          message: 'The server signal catalog is unavailable. These filters come from the BE2 1.5 measurement contract; an older backend may reject a filter.',
        });
      } else {
        setSignalsState({ key, status: 'error', items: [], message: errorText(error) });
      }
    });

    return () => controller.abort();
  }, [api, token, accountKey]);

  useEffect(() => {
    if (!token || !user) return;
    const key = historyKey;
    const controller = new AbortController();
    setMeasurementsState({ key, status: 'loading' });
    setLoadingMore(false);
    setLoadMoreError('');
    loadMoreController.current?.abort();

    void api.measurements(token, queryFor(start, end, signal), controller.signal).then((value) => {
      if (!controller.signal.aborted) setMeasurementsState({ key, status: 'ready', value });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setMeasurementsState({ key, status: 'error', message: errorText(error) });
    });

    return () => {
      controller.abort();
      loadMoreController.current?.abort();
    };
  }, [api, token, accountKey, start, end, signal, historyKey]);

  const loadMore = async () => {
    if (!token || measurements.status !== 'ready' || measurements.value.next_cursor === null || loadingMore) return;
    const key = historyKey;
    const cursor = measurements.value.next_cursor;
    const controller = new AbortController();
    loadMoreController.current = controller;
    setLoadingMore(true);
    setLoadMoreError('');
    try {
      const next = await api.measurements(token, { ...queryFor(start, end, signal), after: cursor }, controller.signal);
      if (!controller.signal.aborted) {
        setMeasurementsState((current) => current.key === key && current.status === 'ready'
          ? {
            ...current,
            value: {
              items: [...current.value.items, ...next.items],
              next_cursor: next.next_cursor,
            },
          }
          : current);
      }
    } catch (error) {
      if (!controller.signal.aborted) setLoadMoreError(errorText(error));
    } finally {
      if (loadMoreController.current === controller) {
        loadMoreController.current = null;
        setLoadingMore(false);
      }
    }
  };

  const saveProfile = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token || profile.status !== 'ready') return;
    const key = accountKey;
    const form = new FormData(event.currentTarget);
    const language = String(form.get('language') ?? 'uk');
    const update: { display_name: string; language: Language } = {
      display_name: String(form.get('display_name') ?? ''),
      language: language === 'en' ? 'en' : 'uk',
    };
    setSavingProfile(true);
    setProfileSaveError('');
    setProfileMessage('');
    try {
      const value = await api.updateProfile(token, update);
      setProfileState((current) => current.key === key && current.status === 'ready'
        ? { ...current, value }
        : current);
      setProfileMessage('Profile updated.');
    } catch (error) {
      setProfileSaveError(errorText(error));
    } finally {
      setSavingProfile(false);
    }
  };

  const updatePassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const currentPassword = String(form.get('current_password') ?? '');
    const newPassword = String(form.get('new_password') ?? '');
    setChangingPassword(true);
    setPasswordError('');
    try {
      await changePassword(currentPassword, newPassword);
    } catch (error) {
      setPasswordError(errorText(error));
    } finally {
      setChangingPassword(false);
    }
  };

  const signOutNow = async () => {
    try { await signOut(); }
    catch { /* AuthProvider reports when server-side logout could not be confirmed. */ }
  };

  const profileValue = profile.status === 'ready' ? profile.value : null;
  const deviceItems = devices.status === 'ready' ? devices.value : [];
  const measurementPage = measurements.status === 'ready' ? measurements.value : null;
  const missingCount = measurementPage?.items.filter((item) => item.value === null || item.missing).length ?? 0;

  return <div className="mx-auto max-w-4xl space-y-5">
    <PageHeader
      eyebrow="My account"
      title={profileValue?.display_name ?? 'Personal profile'}
      description="Only records returned for your authenticated account are shown."
      actions={<Button variant="danger" onClick={() => void signOutNow()}>Sign out</Button>}
    />
    {mode === 'demo' && <Notice tone="attention">Synthetic Demo Mode has no personal profile or live records.</Notice>}
    <Notice tone="unknown">Account: {user?.login ?? 'Unavailable'} · Server role: {user?.role ?? 'Unavailable'} · role is descriptive; the server authorizes each request.</Notice>
    {authError && <div role="alert" className="card border-high/40 p-4 text-high">{authError}</div>}
    {profileMessage && <div role="status" className="card border-good/40 p-4 text-good">{profileMessage}</div>}

    <section className="card space-y-4 p-5">
      <h2 className="text-lg font-semibold">Profile</h2>
      {profile.status === 'loading' && <Loading label="Loading your profile" />}
      {profile.status === 'error' && <div role="alert" className="text-sm text-high">{profile.message}</div>}
      {profile.status === 'ready' && <>
        {profileSaveError && <div role="alert" className="text-sm text-high">{profileSaveError}</div>}
        <form className="grid gap-3 sm:grid-cols-[1fr_auto]" onSubmit={(event) => void saveProfile(event)}>
          <label className="block text-sm">Display name
            <input key={profile.value.id + profile.value.display_name} className="field mt-1" name="display_name" defaultValue={profile.value.display_name} required minLength={1} maxLength={80} />
          </label>
          <label className="block text-sm">Language
            <select key={profile.value.id + profile.value.language} className="field mt-1" name="language" defaultValue={profile.value.language}>
              <option value="uk">Українська</option>
              <option value="en">English</option>
            </select>
          </label>
          <Button type="submit" variant="primary" disabled={savingProfile}>{savingProfile ? 'Saving…' : 'Save profile'}</Button>
        </form>
        <dl className="grid gap-2 text-sm sm:grid-cols-2">
          <div><dt className="text-ink-3">Profile ID</dt><dd className="break-all">{profile.value.id}</dd></div>
          <div><dt className="text-ink-3">Created (UTC)</dt><dd>{formatUtc(profile.value.created_at)}</dd></div>
        </dl>
      </>}
    </section>

    <section className="card space-y-4 p-5">
      <div>
        <h2 className="text-lg font-semibold">Registered devices</h2>
        <p className="text-sm text-ink-3">BE2 device registry only. It does not expose a BLE connection or live-sensor status.</p>
      </div>
      {devices.status === 'loading' && <Loading label="Loading registered devices" />}
      {devices.status === 'error' && <div role="alert" className="text-sm text-high">{devices.message}</div>}
      {devices.status === 'ready' && (deviceItems.length ? <ul className="divide-y divide-line">{deviceItems.map((device) => (
        <li key={device.id} className="flex flex-wrap justify-between gap-2 py-3">
          <span className="min-w-0 break-words">{device.name} <span className="text-xs text-ink-3">· {device.kind}</span></span>
          <span className="text-xs text-ink-3">Registered {formatUtc(device.created_at)}</span>
        </li>
      ))}</ul> : <Empty title="No registered devices">A successful response contained no devices. BLE connection controls are pending backend integration.</Empty>)}
    </section>

    <section className="card min-w-0 space-y-4 p-5">
      <div>
        <h2 className="text-lg font-semibold">Personal measurement history</h2>
        <p className="text-sm text-ink-3">BE2 records are shown with measured and received timestamps, source, origin, and quality. Missing values remain missing.</p>
      </div>
      {signals.status === 'fallback' && <Notice tone="attention">{signals.message}</Notice>}
      {signals.status === 'ready' && signals.message && <Notice tone="unknown">{signals.message}</Notice>}
      {signals.status === 'error' && <div role="alert" className="text-sm text-high">Signal filters are unavailable: {signals.message}</div>}
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm">Start (UTC)
          <input className="field mt-1" type="date" value={start} max={end} onChange={(event) => setStart(event.target.value)} />
        </label>
        <label className="text-sm">End (UTC, inclusive)
          <input className="field mt-1" type="date" value={end} min={start} onChange={(event) => setEnd(event.target.value)} />
        </label>
        <label className="text-sm">Signal
          <select className="field mt-1" value={signal} disabled={signals.status === 'loading' || signals.status === 'error'} onChange={(event) => setSignal(event.target.value)}>
            <option value="">All signals</option>
            {signals.items.map((item) => <option key={item.signal} value={item.signal}>{item.signal.replace(/_/g, ' ')} · {item.unit}</option>)}
          </select>
        </label>
      </div>
      {measurements.status === 'loading' && <Loading label="Loading personal measurements" />}
      {measurements.status === 'error' && <div role="alert" className="text-sm text-high">{measurements.message}</div>}
      {measurementPage && <>
        {missingCount > 0 && <Notice tone="attention">{missingCount} record(s) have missing or null values. Missing data are not zero and do not imply a healthy result.</Notice>}
        {measurementPage.items.length ? <div className="overflow-x-auto">
          <table className="w-full min-w-[1120px] text-left text-sm">
            <thead><tr className="border-b border-line text-ink-3">
              <th className="py-2">Measured (UTC)</th><th>Received (UTC)</th><th>Signal</th><th>Value</th><th>Source</th><th>Origin</th><th>Quality</th><th>Device</th><th>Session</th><th>Processing</th>
            </tr></thead>
            <tbody>{measurementPage.items.map((row) => {
              const deviceName = row.device_id && devices.status === 'ready'
                ? devices.value.find((device) => device.id === row.device_id)?.name
                : undefined;
              return <tr key={row.id} className="border-b border-line/60">
                <td className="py-2">{formatUtc(row.measured_at)}</td>
                <td>{formatUtc(row.received_at)}</td>
                <td>{row.signal}</td>
                <td>{row.value === null || row.missing ? <MissingValue /> : `${row.value} ${row.unit}`}</td>
                <td>{row.source}</td>
                <td>{row.origin}</td>
                <td>{row.quality}</td>
                <td className="max-w-36 truncate" title={row.device_id ?? undefined}>{deviceName ?? row.device_id ?? '—'}</td>
                <td className="max-w-36 truncate" title={row.session_id ?? undefined}>{row.session_id ?? '—'}</td>
                <td>{row.processing_version}</td>
              </tr>;
            })}</tbody>
          </table>
        </div> : <Empty title="No measurements in this range">This empty state is shown only after a successful history response. Failed requests remain errors, never empty histories.</Empty>}
        {loadMoreError && <div role="alert" className="text-sm text-high">{loadMoreError}</div>}
        {measurementPage.next_cursor !== null && (
          <Button disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? 'Loading…' : 'Load more records'}</Button>
        )}
      </>}
    </section>

    <section className="card space-y-4 p-5">
      <h2 className="text-lg font-semibold">Change password</h2>
      <Notice tone="attention">A successful password change revokes sessions and replaces your recovery code. Save the new code before signing in again.</Notice>
      {passwordError && <div role="alert" className="rounded-xl border border-high/40 bg-high/5 p-3 text-sm text-high">{passwordError}</div>}
      <form className="grid gap-3 sm:grid-cols-2" onSubmit={(event) => void updatePassword(event)}>
        <label className="block text-sm">Current password
          <input className="field mt-1" name="current_password" type="password" autoComplete="current-password" required minLength={1} maxLength={128} />
        </label>
        <label className="block text-sm">New password
          <input className="field mt-1" name="new_password" type="password" autoComplete="new-password" required minLength={12} maxLength={128} />
        </label>
        <Button type="submit" variant="primary" disabled={changingPassword}>{changingPassword ? 'Changing…' : 'Change password'}</Button>
      </form>
    </section>
  </div>;
}
