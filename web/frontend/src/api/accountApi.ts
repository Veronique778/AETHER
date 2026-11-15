export type AccountRole = 'astronaut' | 'administrator';
export type Language = 'uk' | 'en';

export type UserIdentity = {
  id: string;
  login: string;
  role: AccountRole;
  astronaut_id: string;
};

export type OwnProfile = {
  id: string;
  user_id: string;
  display_name: string;
  language: Language;
  created_at: string;
};

export type PersonalDevice = {
  id: string;
  astronaut_id: string;
  name: string;
  kind: string;
  external_id: string | null;
  created_at: string;
};

export type SignalDefinition = {
  signal: string;
  unit: string;
  minimum: number;
  maximum: number;
};

export type SignalCatalog = {
  contract_status: string;
  catalog_source: string;
  items: SignalDefinition[];
};

export const BE2_SIGNAL_CONTRACT: SignalDefinition[] = [
  { signal: 'heart_rate', unit: 'bpm', minimum: 0, maximum: 300 },
  { signal: 'heart_rate_bpm', unit: 'bpm', minimum: 0, maximum: 300 },
  { signal: 'rr_interval', unit: 'ms', minimum: 100, maximum: 5000 },
  { signal: 'sleep_hours', unit: 'h', minimum: 0, maximum: 24 },
  { signal: 'sleep_duration', unit: 's', minimum: 0, maximum: 86400 },
  { signal: 'fatigue_1_10', unit: 'score', minimum: 1, maximum: 10 },
  { signal: 'reaction_ms', unit: 'ms', minimum: 0, maximum: 10000 },
  { signal: 'activity_minutes', unit: 'min', minimum: 0, maximum: 1440 },
  { signal: 'temperature', unit: 'degC', minimum: -100, maximum: 100 },
  { signal: 'humidity', unit: '%', minimum: 0, maximum: 100 },
  { signal: 'co2', unit: 'ppm', minimum: 0, maximum: 100000 },
  { signal: 'light', unit: 'lux', minimum: 0, maximum: 200000 },
  { signal: 'spo2', unit: '%', minimum: 0, maximum: 100 },
  { signal: 'respiratory_rate', unit: 'breaths/min', minimum: 0, maximum: 120 },
];

export type Measurement = {
  seq: number;
  id: string;
  astronaut_id: string;
  mission_id: string | null;
  device_id: string | null;
  session_id: string | null;
  source: string;
  signal: string;
  value: number | null;
  unit: string;
  measured_at: string | null;
  received_at: string;
  origin: 'real' | 'manual' | 'research' | 'simulated';
  quality: 'unverified' | 'screened' | 'validated' | 'rejected' | 'corrupt' | 'no_contact' | 'connection_lost';
  confidence: number | null;
  missing: boolean;
  processing_version: string;
  written_via?: string;
  metadata: Record<string, unknown>;
  supersedes_id: string | null;
};

export type Analysis = {
  id: string;
  astronaut_id: string;
  mission_id: string | null;
  session_id: string | null;
  model: string;
  processing_version: string;
  created_at: string;
  result: Record<string, unknown>;
  input_ids: string[];
};

export type PersonalSignalSnapshot = {
  items: Measurement[];
  counts: Record<string, { samples: number; usable: number }>;
  source: 'authenticated_personal_sqlite';
  clinical_validation: false;
};

export type Page<T> = {
  items: T[];
  next_cursor: number | null;
};

export type RegistrationInput = {
  login: string;
  password: string;
  display_name: string;
  language?: Language;
};

export type RegistrationResult = {
  user: UserIdentity;
  recovery_code: string;
};

export type LoginResult = {
  user: UserIdentity;
  access_token: string;
  token_type: 'Bearer';
  expires_at: string;
  idle_timeout_seconds: number;
};

export type RecoveryResult = {
  changed: boolean;
  login_required: boolean;
  recovery_code: string;
};

export type ProfileUpdate = {
  display_name?: string;
  language?: Language;
};

export type MeasurementQuery = {
  start?: string;
  end?: string;
  signal?: string;
  session_id?: string;
  after?: number;
  limit?: number;
};

/* ---------------- AETHER 1.5 BLE personal integration (server: app/devices/api.py, contract §3.6) ---------------- */
export type BleDiagnostics = {
  backend: string;
  authenticated_owner: { login: string; astronaut_id: string };
  platform: string;
  frozen_build: boolean;
  ble_dependency_available: boolean;
  bleak_version: string | null;
  ble_dependency_error: string | null;
  radio_available: boolean | null;
  radio_state: 'on' | 'off' | 'no_adapter' | 'unknown';
  radio_access: 'allowed' | 'denied' | 'unknown';
  scan_available: boolean;
  reason_code: string | null;
  reason: string | null;
  supported_protocol: string;
  transport: string;
  radio_data_class: string;
  hardware_verified: false;
  simulated_hrs_available: boolean;
  active_recordings: number;
  compatibility_note: string;
};

export type BleScanItem = {
  hardware_address: string;
  name: string;
  advertised_hrs: boolean;
  rssi: number | null;
  compatibility: 'hrs_advertised' | 'unverified_gatt_check_on_connect';
  registered_device_id: string | null;
};

export type BleScanResult = { found: BleScanItem[]; scanned_at: string; ble_available: boolean; note: string };

export type BleDevice = {
  device_id: string;
  astronaut_id: string;
  name: string;
  kind: string;
  hardware_address: string | null;
  connection: string;
  lifecycle_state: string;
  hardware_verified: false;
  simulated?: boolean;
  data_class?: string;
};

export type BlePhase = 'idle' | 'connecting' | 'connected_awaiting' | 'receiving' | 'no_contact' | 'signal_lost'
  | 'reconnecting' | 'saving' | 'saved' | 'connection_failed' | 'unavailable' | 'revoked';

export type BleStatus = {
  device_id: string;
  connection: string;
  lifecycle_state: string;
  session_id: string | null;
  astronaut_id: string | null;
  last_sample_at: string | null;
  last_sample_age_seconds: number | null;
  heart_rate: number | null;
  stale: boolean;
  quality: string;
  contact_state: 'contact' | 'no_contact' | 'not_reported' | 'unknown';
  rr_available: boolean;
  received_samples: number;
  stored_samples: number;
  pending_rows: number;
  dropped_rows: number;
  reconnect_attempt: number;
  reconnects: number;
  gaps: number;
  corrupt_packets: number;
  no_contact_samples: number;
  storage_failures: number;
  duration_seconds: number;
  hardware_validation: 'unverified';
  error: string | null;
  data_class: string | null;
  simulated: boolean | null;
  hrs_verified: boolean;
  revoked: boolean;
  phase: BlePhase;
  stale_after_seconds: number;
  last_session_id: string | null;
  last_session_status: string | null;
};

export type BleConnectResult = { device_id: string; session_id: string; recording: boolean; connection: string; lifecycle_state: string };
export type BleStopResult = { device_id: string; session_id: string | null; stored_samples: number; pending_rows?: number;
  changed: boolean; session_status?: string };

export type SensorSession = {
  seq: number;
  id: string;
  astronaut_id: string;
  mission_id: string | null;
  device_id: string | null;
  source: string;
  origin: 'real' | 'manual' | 'simulated' | 'research';
  started_at: string;
  ended_at: string | null;
  end_status: string | null;
  metadata: Record<string, unknown>;
};

export type AccountErrorCode =
  | 'network_error'
  | 'invalid_launch_token'
  | 'invalid_credentials'
  | 'invalid_recovery'
  | 'unauthenticated'
  | 'forbidden'
  | 'not_found'
  | 'conflict'
  | 'validation_error'
  | 'rate_limited'
  | 'service_unavailable'
  | 'request_failed';

export class AccountApiError extends Error {
  constructor(
    message: string,
    public readonly status = 0,
    public readonly code: AccountErrorCode = 'request_failed',
    /** Raw server error code (e.g. device_busy, bluetooth_off, device_not_hrs) — never a server message or trace. */
    public readonly serverCode = '',
  ) {
    super(message);
    this.name = 'AccountApiError';
  }
}

export interface AccountApi {
  register(input: RegistrationInput): Promise<RegistrationResult>;
  login(login: string, password: string): Promise<LoginResult>;
  recover(input: { login: string; recovery_code: string; new_password: string }): Promise<RecoveryResult>;
  logout(token: string): Promise<{ logged_out: true }>;
  me(token: string, signal?: AbortSignal): Promise<UserIdentity>;
  profile(token: string, signal?: AbortSignal): Promise<OwnProfile>;
  updateProfile(token: string, update: ProfileUpdate): Promise<OwnProfile>;
  changePassword(token: string, currentPassword: string, newPassword: string): Promise<RecoveryResult>;
  devices(token: string, signal?: AbortSignal): Promise<PersonalDevice[]>;
  signals(token: string, signal?: AbortSignal): Promise<SignalCatalog>;
  measurements(token: string, query?: MeasurementQuery, signal?: AbortSignal): Promise<Page<Measurement>>;
  latestMeasurements(token: string, signal?: AbortSignal): Promise<PersonalSignalSnapshot>;
  analyses(token: string, after?: number, limit?: number, signal?: AbortSignal): Promise<Page<Analysis>>;
  /** Personal science resources (BE3 routes behind the Backend №2 Bearer): PHANTOM analyses and measurement writes. */
  science<T = any>(token: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T>;
  bleDiagnostics(token: string, signal?: AbortSignal): Promise<BleDiagnostics>;
  bleScan(token: string, includeUnadvertised: boolean, timeoutSeconds?: number): Promise<BleScanResult>;
  registerBleDevice(token: string, name: string, hardwareAddress: string): Promise<PersonalDevice>;
  simulatedDevice(token: string): Promise<BleDevice>;
  bleConnect(token: string, deviceId: string, astronautId: string): Promise<BleConnectResult>;
  bleDisconnect(token: string, deviceId: string): Promise<BleStopResult>;
  bleStatus(token: string, deviceId: string, signal?: AbortSignal): Promise<BleStatus>;
  bleActive(token: string, signal?: AbortSignal): Promise<BleStatus[]>;
  deviceSessions(token: string, deviceId: string, signal?: AbortSignal): Promise<Page<SensorSession>>;
}

const DEVICE_ID = /^[a-zA-Z0-9_.:-]{1,80}$/;

type Validator<T> = (value: unknown) => value is T;
type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === 'string';
}

function isNullableString(value: unknown): value is string | null {
  return value === null || isString(value);
}

function isLanguage(value: unknown): value is Language {
  return value === 'uk' || value === 'en';
}

function isUserIdentity(value: unknown): value is UserIdentity {
  if (!isObject(value)) return false;
  return isString(value.id)
    && isString(value.login)
    && (value.role === 'astronaut' || value.role === 'administrator')
    && isString(value.astronaut_id);
}

function isOwnProfile(value: unknown): value is OwnProfile {
  if (!isObject(value)) return false;
  return isString(value.id)
    && isString(value.user_id)
    && isString(value.display_name)
    && isLanguage(value.language)
    && isString(value.created_at);
}

function isDevice(value: unknown): value is PersonalDevice {
  if (!isObject(value)) return false;
  return isString(value.id)
    && isString(value.astronaut_id)
    && isString(value.name)
    && isString(value.kind)
    && isNullableString(value.external_id)
    && isString(value.created_at);
}

function isSignalDefinition(value: unknown): value is SignalDefinition {
  if (!isObject(value)) return false;
  return isString(value.signal)
    && isString(value.unit)
    && typeof value.minimum === 'number'
    && Number.isFinite(value.minimum)
    && typeof value.maximum === 'number'
    && Number.isFinite(value.maximum)
    && value.minimum <= value.maximum;
}

function isSignalCatalog(value: unknown): value is SignalCatalog {
  return isObject(value)
    && isString(value.contract_status)
    && isString(value.catalog_source)
    && Array.isArray(value.items)
    && value.items.every(isSignalDefinition);
}

function isMeasurement(value: unknown): value is Measurement {
  if (!isObject(value)) return false;
  return Number.isInteger(value.seq)
    && isString(value.id)
    && isString(value.astronaut_id)
    && isNullableString(value.mission_id)
    && isNullableString(value.device_id)
    && isNullableString(value.session_id)
    && isString(value.source)
    && isString(value.signal)
    && (value.value === null || (typeof value.value === 'number' && Number.isFinite(value.value)))
    && isString(value.unit)
    && isNullableString(value.measured_at)
    && isString(value.received_at)
    && ['real', 'manual', 'research', 'simulated'].includes(String(value.origin))
    && ['unverified', 'screened', 'validated', 'rejected', 'corrupt', 'no_contact', 'connection_lost'].includes(String(value.quality))
    && (value.confidence === null || (typeof value.confidence === 'number' && Number.isFinite(value.confidence)))
    && typeof value.missing === 'boolean'
    && isString(value.processing_version)
    && isObject(value.metadata)
    && isNullableString(value.supersedes_id);
}

function isAnalysis(value: unknown): value is Analysis {
  if (!isObject(value)) return false;
  return isString(value.id)
    && isString(value.astronaut_id)
    && isNullableString(value.mission_id)
    && isNullableString(value.session_id)
    && isString(value.model)
    && isString(value.processing_version)
    && isString(value.created_at)
    && isObject(value.result)
    && Array.isArray(value.input_ids)
    && value.input_ids.every(isString);
}

function isPage<T>(value: unknown, itemValidator: Validator<T>): value is Page<T> {
  if (!isObject(value)) return false;
  return Array.isArray(value.items)
    && value.items.every(itemValidator)
    && (value.next_cursor === null || (Number.isInteger(value.next_cursor) && Number(value.next_cursor) >= 0));
}

function isRegistrationResult(value: unknown): value is RegistrationResult {
  return isObject(value)
    && isUserIdentity(value.user)
    && isString(value.recovery_code)
    && value.recovery_code.length >= 32;
}

function isLoginResult(value: unknown): value is LoginResult {
  if (!isObject(value) || !isUserIdentity(value.user)) return false;
  return isString(value.access_token)
    && value.access_token.length > 0
    && isString(value.token_type)
    && value.token_type.toLowerCase() === 'bearer'
    && isString(value.expires_at)
    && Number.isFinite(Date.parse(value.expires_at))
    && Number.isInteger(value.idle_timeout_seconds)
    && Number(value.idle_timeout_seconds) > 0;
}

function isRecoveryResult(value: unknown): value is RecoveryResult {
  return isObject(value)
    && value.changed === true
    && value.login_required === true
    && isString(value.recovery_code)
    && value.recovery_code.length >= 32;
}

function errorCode(body: unknown, status: number): AccountErrorCode {
  const nested = isObject(body) && isObject(body.error) ? body.error : null;
  const rawCode = nested && typeof nested.code === 'string' ? nested.code : '';
  if (status === 401 && rawCode === 'invalid_credentials') return 'invalid_credentials';
  if (status === 401 && rawCode === 'invalid_recovery') return 'invalid_recovery';
  if (status === 401 && rawCode === 'unauthenticated') return 'unauthenticated';
  if (status === 403) return 'forbidden';
  if (status === 404 || status === 410) return 'not_found';
  if (status === 409) return 'conflict';
  if (status === 422) return 'validation_error';
  if (status === 429) return 'rate_limited';
  if (status === 503) return 'service_unavailable';
  if (status === 401 && isObject(body) && typeof body.detail === 'string' && /aether session token/i.test(body.detail)) {
    return 'invalid_launch_token';
  }
  return 'request_failed';
}

function safeErrorMessage(code: AccountErrorCode, status: number): string {
  switch (code) {
    case 'network_error': return 'The AETHER account service could not be reached. Check the connection and try again.';
    case 'invalid_launch_token': return 'The local AETHER launch check failed. Refresh the application or restart its backend.';
    case 'invalid_credentials': return 'The login or password is incorrect.';
    case 'invalid_recovery': return 'The login or recovery code is incorrect.';
    case 'unauthenticated': return 'Your personal session has expired. Sign in again.';
    case 'forbidden': return 'The server denied access to this resource.';
    case 'not_found': return 'This personal API resource is unavailable.';
    case 'conflict': return 'This request conflicts with existing account data.';
    case 'validation_error': return 'Some fields are invalid. Check the entered values and try again.';
    case 'rate_limited': return 'Too many attempts. Wait a little before trying again.';
    case 'service_unavailable': return 'The account service is temporarily unavailable. Try again later.';
    default: return status ? `The account request failed (HTTP ${status}).` : 'The account request failed.';
  }
}

function validateResponse<T>(value: unknown, validator: Validator<T>, label: string): T {
  if (!validator(value)) throw new AccountApiError(`The account API returned an invalid ${label} response.`);
  return value;
}

function allowsTransport(base: string): boolean {
  try {
    const url = new URL(base);
    if (url.username || url.password || url.search || url.hash) return false;
    return url.protocol === 'https:'
      || (url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname));
  } catch {
    return false;
  }
}

export function createAccountApi(base: string): AccountApi {
  async function request<R>(path: string, token?: string, init?: RequestInit): Promise<R> {
    const isPublicAuth = ['/api/auth/register', '/api/auth/login', '/api/auth/recover'].includes(path);
    if (!isPublicAuth && (!token || !token.trim())) {
      throw new AccountApiError('A valid personal Bearer session is required.', 401, 'unauthenticated');
    }
    if (!allowsTransport(base)) {
      throw new AccountApiError('The account service requires HTTPS outside a local development backend.');
    }

    let response: Response;
    try {
      response = await fetch(`${base}${path}`, {
        ...init,
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...(init?.headers ?? {}),
        },
      });
    } catch (error) {
      if (init?.signal?.aborted) throw error;
      throw new AccountApiError(safeErrorMessage('network_error', 0), 0, 'network_error');
    }

    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    if (!response.ok) {
      const code = errorCode(body, response.status);
      const nested = isObject(body) && isObject(body.error) ? body.error : null;
      const raw = nested && typeof nested.code === 'string' && /^[a-z0-9_]{1,64}$/.test(nested.code) ? nested.code : '';
      throw new AccountApiError(safeErrorMessage(code, response.status), response.status, code, raw);
    }
    return body as R;
  }

  const post = <R>(path: string, body: unknown, token?: string) =>
    request<R>(path, token, { method: 'POST', body: JSON.stringify(body) });

  return {
    register: async (input) => validateResponse(
      await post<unknown>('/api/auth/register', input),
      isRegistrationResult,
      'registration',
    ),
    login: async (login, password) => {
      const value = validateResponse(
        await post<unknown>('/api/auth/login', { login, password }),
        isLoginResult,
        'login',
      );
      return { ...value, token_type: 'Bearer' };
    },
    recover: async (input) => validateResponse(
      await post<unknown>('/api/auth/recover', input),
      isRecoveryResult,
      'recovery',
    ),
    logout: async (token) => {
      const result = await post<unknown>('/api/auth/logout', {}, token);
      if (!isObject(result) || result.logged_out !== true) {
        throw new AccountApiError('The account API returned an invalid logout response.');
      }
      return { logged_out: true };
    },
    me: async (token, signal) => {
      const value = await request<unknown>('/api/auth/me', token, { signal });
      if (!isObject(value)) throw new AccountApiError('The account API returned an invalid identity response.');
      return validateResponse(value.user, isUserIdentity, 'identity');
    },
    profile: async (token, signal) => validateResponse(
      await request<unknown>('/api/profile', token, { signal }),
      isOwnProfile,
      'profile',
    ),
    updateProfile: async (token, update) => {
      if (!Object.keys(update).length || Object.values(update).some((value) => value === undefined || value === null)) {
        throw new AccountApiError('Provide at least one non-empty profile field.', 422, 'validation_error');
      }
      return validateResponse(
        await request<unknown>('/api/profile', token, { method: 'PATCH', body: JSON.stringify(update) }),
        isOwnProfile,
        'profile',
      );
    },
    changePassword: async (token, currentPassword, newPassword) => validateResponse(
      await post<unknown>('/api/auth/change-password', { current_password: currentPassword, new_password: newPassword }, token),
      isRecoveryResult,
      'password change',
    ),
    devices: async (token, signal) => {
      const value = await request<unknown>('/api/devices', token, { signal });
      if (!isObject(value) || !Array.isArray(value.items) || !value.items.every(isDevice)) {
        throw new AccountApiError('The account API returned an invalid devices response.');
      }
      return value.items;
    },
    signals: async (token, signal) => {
      const value = await request<unknown>('/api/signals', token, { signal });
      // BE3 signal registry shape {signals:[{signal, unit, plausible_min, plausible_max}]} (operational since 1.5)
      if (isObject(value) && Array.isArray(value.signals)) {
        const items = value.signals.map((item) => (isObject(item)
          ? { signal: item.signal, unit: item.unit, minimum: item.plausible_min, maximum: item.plausible_max }
          : null));
        return validateResponse({ contract_status: 'operational', catalog_source: 'be3_signal_registry', items }, isSignalCatalog, 'signal catalog');
      }
      return validateResponse(value, isSignalCatalog, 'signal catalog');
    },
    measurements: async (token, query = {}, signal) => {
      const params = new URLSearchParams();
      if (query.start) params.set('start', query.start);
      if (query.end) params.set('end', query.end);
      if (query.signal) params.set('signal', query.signal);
      if (query.session_id) params.set('session_id', query.session_id);
      if (query.after !== undefined) params.set('after', String(query.after));
      if (query.limit !== undefined) params.set('limit', String(query.limit));
      const suffix = params.size ? `?${params.toString()}` : '';
      return validateResponse(
        await request<unknown>(`/api/measurements${suffix}`, token, { signal }),
        (value): value is Page<Measurement> => isPage(value, isMeasurement),
        'measurement history',
      );
    },
    latestMeasurements: async (token, signal) => {
      const value = await request<unknown>('/api/measurements/latest', token, { signal });
      if (!isObject(value) || !Array.isArray(value.items) || !value.items.every(isMeasurement)
        || !isObject(value.counts) || value.source !== 'authenticated_personal_sqlite'
        || value.clinical_validation !== false) {
        throw new AccountApiError('The personal snapshot API returned invalid data.');
      }
      return value as unknown as PersonalSignalSnapshot;
    },
    analyses: async (token, after, limit, signal) => {
      const params = new URLSearchParams();
      if (after !== undefined) params.set('after', String(after));
      if (limit !== undefined) params.set('limit', String(limit));
      const suffix = params.size ? `?${params.toString()}` : '';
      return validateResponse(
        await request<unknown>(`/api/analyses${suffix}`, token, { signal }),
        (value): value is Page<Analysis> => isPage(value, isAnalysis),
        'analysis history',
      );
    },
    science: async (token, path, body, signal) => {
      if (!/^\/(phantom-analyses(?:\/[a-zA-Z0-9_.:-]+)?|measurements(?:\/batch)?)$/.test(path)) {
        throw new AccountApiError('Unsupported personal science resource.');
      }
      return request(`/api${path}`, token, { signal, ...(body === undefined ? {} : { method: 'POST', body: JSON.stringify(body) }) });
    },
    bleDiagnostics: async (token, signal) => {
      const value = await request<unknown>('/api/devices/ble-diagnostics', token, { signal });
      if (!isObject(value) || typeof value.scan_available !== 'boolean' || value.hardware_verified !== false) {
        throw new AccountApiError('The device API returned an invalid diagnostics response.');
      }
      return value as unknown as BleDiagnostics;
    },
    bleScan: async (token, includeUnadvertised, timeoutSeconds = 7) => {
      const value = await post<unknown>('/api/devices/scan', { include_unadvertised: includeUnadvertised, timeout_seconds: timeoutSeconds }, token);
      if (!isObject(value) || !Array.isArray(value.found)) throw new AccountApiError('The device API returned an invalid scan response.');
      return value as unknown as BleScanResult;
    },
    registerBleDevice: async (token, name, hardwareAddress) => validateResponse(
      await post<unknown>('/api/devices', { name: name.slice(0, 80) || 'HRS monitor', kind: 'ble', external_id: hardwareAddress }, token),
      isDevice,
      'device registration',
    ),
    simulatedDevice: async (token) => {
      const value = await post<unknown>('/api/devices/simulated', {}, token);
      if (!isObject(value) || !isString(value.device_id) || value.data_class !== 'synthetic') {
        throw new AccountApiError('The device API returned an invalid simulated-device response.');
      }
      return value as unknown as BleDevice;
    },
    bleConnect: async (token, deviceId, astronautId) => {
      if (!DEVICE_ID.test(deviceId)) throw new AccountApiError('Invalid device identifier.');
      return post<BleConnectResult>(`/api/devices/${deviceId}/connect`, { astronaut_id: astronautId }, token);
    },
    bleDisconnect: async (token, deviceId) => {
      if (!DEVICE_ID.test(deviceId)) throw new AccountApiError('Invalid device identifier.');
      return post<BleStopResult>(`/api/devices/${deviceId}/disconnect`, {}, token);
    },
    bleStatus: async (token, deviceId, signal) => {
      if (!DEVICE_ID.test(deviceId)) throw new AccountApiError('Invalid device identifier.');
      const value = await request<unknown>(`/api/devices/${deviceId}/status`, token, { signal });
      if (!isObject(value) || !isString(value.lifecycle_state)) throw new AccountApiError('The device API returned an invalid status response.');
      return value as unknown as BleStatus;
    },
    bleActive: async (token, signal) => {
      const value = await request<unknown>('/api/devices/active', token, { signal });
      if (!isObject(value) || !Array.isArray(value.items)) throw new AccountApiError('The device API returned an invalid response.');
      return value.items as BleStatus[];
    },
    deviceSessions: async (token, deviceId, signal) => {
      if (!DEVICE_ID.test(deviceId)) throw new AccountApiError('Invalid device identifier.');
      const value = await request<unknown>(`/api/devices/${deviceId}/sessions?limit=100`, token, { signal });
      if (!isObject(value) || !Array.isArray(value.items)) throw new AccountApiError('The device API returned an invalid sessions response.');
      return value as unknown as Page<SensorSession>;
    },
  };
}
