// Response shapes transcribed from the supplied BE2 API_EXAMPLES.md; every value here is test-only.
export const be2User = {
  id: '00000000-0000-4000-8000-000000000001',
  login: 'demo_user',
  role: 'astronaut',
  astronaut_id: '00000000-0000-4000-8000-000000000001',
};

export const be2Registration = {
  user: be2User,
  recovery_code: 'TEST_ONLY_RECOVERY_CODE_NOT_A_REAL_CREDENTIAL_0123456789',
};

export const be2Login = {
  user: be2User,
  access_token: 'TEST_ONLY_BEARER_NOT_A_REAL_CREDENTIAL',
  token_type: 'Bearer',
  expires_at: '2026-11-15T08:00:00.000000Z',
  idle_timeout_seconds: 900,
};

export const be2Me = { user: be2User };

export const be2Profile = {
  id: '00000000-0000-4000-8000-000000000001',
  user_id: '00000000-0000-4000-8000-000000000001',
  display_name: 'demo_user',
  language: 'uk',
  created_at: '2026-11-15T08:00:00.000000Z',
};

export const be2Devices = {
  items: [{
    id: 'device-0001',
    astronaut_id: '00000000-0000-4000-8000-000000000001',
    name: 'Research monitor',
    kind: 'ble',
    external_id: null,
    created_at: '2026-11-15T08:00:00.000000Z',
  }],
};

export const be2Signals = {
  contract_status: 'integration_candidate',
  catalog_source: 'be2_measurement_validation',
  items: [
    { signal: 'heart_rate', unit: 'bpm', minimum: 0, maximum: 300 },
    { signal: 'rr_interval', unit: 'ms', minimum: 100, maximum: 5000 },
  ],
};

export const be2Measurement = {
  seq: 1,
  id: 'measurement-0001',
  astronaut_id: '00000000-0000-4000-8000-000000000001',
  mission_id: null,
  device_id: null,
  session_id: null,
  source: 'manual form',
  signal: 'heart_rate',
  value: null,
  unit: 'bpm',
  measured_at: '2026-11-15T08:00:00.000000Z',
  received_at: '2026-11-15T08:00:02.000000Z',
  origin: 'manual',
  quality: 'unverified',
  confidence: null,
  missing: true,
  processing_version: 'raw-1.5',
  metadata: {},
  supersedes_id: null,
};

export const be2Measurements = {
  items: [be2Measurement],
  next_cursor: 1,
};

export const be2Analysis = {
  id: 'analysis-0001',
  astronaut_id: '00000000-0000-4000-8000-000000000001',
  mission_id: null,
  session_id: null,
  model: 'summary-v1',
  processing_version: 'raw-1.5',
  created_at: '2026-11-15T08:00:00.000000Z',
  result: {},
  input_ids: [],
};

export const be2Analyses = {
  items: [be2Analysis],
  next_cursor: null,
};

export const be2Logout = { logged_out: true };

export const be2Recovery = {
  changed: true,
  login_required: true,
  recovery_code: 'TEST_ONLY_ROTATED_RECOVERY_CODE_NOT_A_REAL_SECRET',
};
